"""Run context — which GPU, which experiment, which command.

Everything in this module is best-effort and must NEVER raise: a missing
``nvidia-smi``, an exotic container, or an odd ``sys.argv`` can only make a
field come back ``None``. A context lookup must not be able to break the job
the notifier is attached to.
"""
from __future__ import annotations

import os
import shlex
import subprocess
import sys
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence

from .config import Config, load_config

# Env vars that decide which physical GPUs the process can see. Docker sets the
# NVIDIA_ one via `--gpus`; user code / launchers usually set the CUDA_ one.
_VISIBLE_ENV_VARS = ("CUDA_VISIBLE_DEVICES", "NVIDIA_VISIBLE_DEVICES")

_MAX_COMMAND_CHARS = 600
_NVIDIA_SMI_TIMEOUT = 5.0

# nvidia-smi costs ~100ms; one lookup per process is plenty.
_gpu_probe_cache: Optional[List[str]] = None
_gpu_probe_done = False


# --------------------------------------------------------------------------- #
# GPU
# --------------------------------------------------------------------------- #
def _selected_ids():
    """The device ids this process was given, e.g. ``(['0'], 'CUDA_VISIBLE_DEVICES')``.

    Returns ``(None, None)`` when nothing restricts us — the process sees every
    GPU on the machine.
    """
    for name in _VISIBLE_ENV_VARS:
        raw = os.environ.get(name)
        if raw is None:
            continue
        raw = raw.strip()
        if not raw:
            return [], name          # explicitly empty → no GPU at all
        if raw.lower() in ("all", "none", "void"):
            return (None, None) if raw.lower() == "all" else ([], name)
        return [part.strip() for part in raw.split(",") if part.strip()], name
    return None, None


def _probe_index_table():
    """``{'0': 'NVIDIA RTX A6000', ...}`` straight from nvidia-smi."""
    global _gpu_probe_cache, _gpu_probe_done
    if _gpu_probe_done:
        return _gpu_probe_cache
    _gpu_probe_done = True
    _gpu_probe_cache = None
    try:
        proc = subprocess.run(
            ["nvidia-smi", "--query-gpu=index,name", "--format=csv,noheader"],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=_NVIDIA_SMI_TIMEOUT,
        )
    except Exception:  # not installed, no driver, timeout, ...
        return None
    if proc.returncode != 0:
        return None
    table = {}
    for line in proc.stdout.decode("utf-8", "replace").splitlines():
        index, _, name = line.strip().partition(",")
        if index.strip() and name.strip():
            table[index.strip()] = name.strip()
    _gpu_probe_cache = table or None
    return _gpu_probe_cache


def _probe_torch_names():
    """Names of the devices *this process* can see, in torch's own order.

    Only when torch is already imported AND CUDA is already initialized: we
    never import torch ourselves (slow, side effects) and never trigger CUDA
    init. torch's indices are already remapped by CUDA_VISIBLE_DEVICES, so
    ``names[k]`` is the k-th id in the selection.
    """
    torch = sys.modules.get("torch")
    if torch is None:
        return None
    try:
        if not torch.cuda.is_initialized():  # type: ignore[union-attr]
            return None
        return [
            torch.cuda.get_device_name(i)  # type: ignore[union-attr]
            for i in range(torch.cuda.device_count())  # type: ignore[union-attr]
        ]
    except Exception:
        return None


def _render(pairs) -> str:
    """``[('0', 'NVIDIA RTX A6000')]`` → ``0 (NVIDIA RTX A6000)``."""
    ids = [str(i) for i, _ in pairs]
    names = [name for _, name in pairs]
    if not all(names):
        return ",".join(ids)
    if len(names) > 1 and len(set(names)) == 1:
        return "{} ({} x{})".format(",".join(ids), names[0], len(names))
    return ", ".join("{} ({})".format(i, n) for i, n in pairs)


def describe_gpu(override: Optional[str] = None, config: Optional[Config] = None) -> Optional[str]:
    """One-line answer to "which GPU is this running on", e.g. ``0 (NVIDIA RTX A6000)``."""
    try:
        config = config or load_config()
        if override:
            return override
        if config.gpu_override:
            return config.gpu_override

        ids, source = _selected_ids()
        if ids == []:
            return "none (CPU only, {}=empty)".format(source)

        torch_names = _probe_torch_names()
        table = _probe_index_table() if config.gpu_query_enabled else None

        if ids is not None:
            # torch's order matches the selection one-for-one.
            if torch_names and len(torch_names) == len(ids):
                return _render(list(zip(ids, torch_names)))
            if table:
                pairs = [(i, table.get(i)) for i in ids]
                if any(name for _, name in pairs):
                    return _render(pairs)
                # Container case: the ids are host ids, but nvidia-smi inside
                # the container renumbers them. Report what we actually see.
                return "{} [{}={}]".format(
                    _render(sorted(table.items())), source, ",".join(ids)
                )
            return _render([(i, None) for i in ids])

        # Nothing restricts us: report every device on the machine.
        if table:
            return _render(sorted(table.items()))
        if torch_names:
            return _render(list(enumerate(torch_names)))
        return None
    except Exception:  # pragma: no cover - defensive
        return None


# --------------------------------------------------------------------------- #
# command
# --------------------------------------------------------------------------- #
def quote_command(argv: Sequence[str]) -> str:
    """Join ``argv`` into a copy-pasteable shell command."""
    text = " ".join(shlex.quote(str(a)) for a in argv)
    if len(text) > _MAX_COMMAND_CHARS:
        text = text[: _MAX_COMMAND_CHARS - 3] + "..."
    return text


def describe_command(override: Optional[str] = None) -> Optional[str]:
    """The command that launched this process, reconstructed from ``sys.argv``.

    ``python -m poster.train --datasets pku`` comes back as written rather than
    as the absolute path to ``train.py`` that lands in ``sys.argv[0]``.
    """
    if override:
        return override
    try:
        python = os.path.basename(sys.executable) or "python"
        spec = getattr(sys.modules.get("__main__"), "__spec__", None)
        module = getattr(spec, "name", None) if spec is not None else None
        if module:
            # `python -m pkg` reports the module as "pkg.__main__".
            if module.endswith(".__main__"):
                module = module[: -len(".__main__")]
            return quote_command([python, "-m", module] + list(sys.argv[1:]))
        return quote_command([python] + list(sys.argv))
    except Exception:  # pragma: no cover - defensive
        return None


# --------------------------------------------------------------------------- #
# the bundle
# --------------------------------------------------------------------------- #
@dataclass
class RunContext:
    """The "where did this run" block appended to every alert."""

    experiment: Optional[str] = None
    gpu: Optional[str] = None
    command: Optional[str] = None
    extra: Dict[str, str] = field(default_factory=dict)

    def lines(self) -> List[str]:
        out = []
        if self.experiment:
            out.append("experiment: {}".format(self.experiment))
        if self.gpu:
            out.append("gpu: {}".format(self.gpu))
        if self.command:
            out.append("command: {}".format(self.command))
        for key, value in self.extra.items():
            if value:
                out.append("{}: {}".format(key, value))
        return out


def collect(
    experiment: Optional[str] = None,
    gpu: Optional[str] = None,
    command=None,
    extra: Optional[Dict[str, str]] = None,
) -> RunContext:
    """Gather run context, filling in anything the caller did not pass.

    Returns an empty context when ``JOBNOTIFY_CONTEXT=0`` — that restores the
    pre-0.2 message layout for anyone who wants it.
    """
    try:
        config = load_config()
        if not config.context_enabled:
            return RunContext()
        if command is not None and not isinstance(command, str):
            command = quote_command(command)
        return RunContext(
            experiment=experiment or config.experiment,
            gpu=describe_gpu(gpu, config),
            command=describe_command(command),
            extra=dict(extra or {}),
        )
    except Exception:  # pragma: no cover - defensive
        return RunContext()
