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
def _visible_devices() -> Optional[str]:
    """Return the raw CUDA/NVIDIA visible-device spec, if one is set."""
    for name in _VISIBLE_ENV_VARS:
        raw = os.environ.get(name)
        if raw is None:
            continue
        raw = raw.strip()
        # An explicitly empty value means "no GPU", which is worth reporting.
        return "{}={}".format(name, raw if raw else "(empty → CPU only)")
    return None


def _probe_nvidia_smi() -> Optional[List[str]]:
    """``['0: NVIDIA RTX A6000', ...]`` for every GPU visible to this process."""
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
    devices = []
    for line in proc.stdout.decode("utf-8", "replace").splitlines():
        line = line.strip()
        if not line:
            continue
        index, _, name = line.partition(",")
        devices.append("{}: {}".format(index.strip(), name.strip()))
    return devices or None


def _probe_torch() -> Optional[List[str]]:
    """Same list via torch — only if torch is already imported AND initialized.

    We never import torch ourselves (it is slow and has side effects), and we
    never trigger CUDA init: this is a free read when the job is already using
    the GPU, and a no-op otherwise.
    """
    torch = sys.modules.get("torch")
    if torch is None:
        return None
    try:
        if not torch.cuda.is_initialized():  # type: ignore[union-attr]
            return None
        return [
            "{}: {}".format(i, torch.cuda.get_device_name(i))  # type: ignore[union-attr]
            for i in range(torch.cuda.device_count())  # type: ignore[union-attr]
        ]
    except Exception:
        return None


def _probe_devices(allow_query: bool) -> Optional[List[str]]:
    global _gpu_probe_cache, _gpu_probe_done
    devices = _probe_torch()
    if devices:
        return devices
    if not allow_query:
        return None
    if not _gpu_probe_done:
        _gpu_probe_cache = _probe_nvidia_smi()
        _gpu_probe_done = True
    return _gpu_probe_cache


def describe_gpu(override: Optional[str] = None, config: Optional[Config] = None) -> Optional[str]:
    """One-line GPU description, e.g.::

        CUDA_VISIBLE_DEVICES=1 | 0: NVIDIA RTX A6000
    """
    try:
        config = config or load_config()
        if override:
            return override
        if config.gpu_override:
            return config.gpu_override

        parts = []
        visible = _visible_devices()
        if visible:
            parts.append(visible)
        devices = _probe_devices(allow_query=config.gpu_query_enabled)
        if devices:
            parts.append(", ".join(devices))
        return " | ".join(parts) if parts else None
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
