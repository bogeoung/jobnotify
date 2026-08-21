"""jobnotify — send a Telegram alert when a long-running Python job finishes.

Public API:
    notify(text)                 send an arbitrary message now
    notify_scope(job_name)       context manager: alert on success AND failure
    notify_on_finish(job_name)   decorator form of notify_scope

You get one alert when the job starts and one when it finishes, both carrying
the run context — experiment name, GPU, and the command that launched the
process — so you can tell two runs apart from the phone. Pass
``experiment=`` / ``gpu=`` / ``command=`` to override anything auto-detected,
or set ``JOBNOTIFY_EXPERIMENT`` / ``JOBNOTIFY_GPU`` in the environment.

There is also a CLI wrapper for non-Python commands::

    jobnotify -e kd_pku_cgl -- python -m poster.train --datasets pku

All entry points are safe: a notification failure (bad token, no network,
missing config) never raises into your job — at worst it prints a stderr warning.
If no credentials are configured, everything is a silent no-op.
"""
from __future__ import annotations

import functools
import sys
import time
from contextlib import contextmanager

from . import context as _context
from . import message as _message
from .backends import build_backends
from .config import load_config
from .context import RunContext

__all__ = ["notify", "notify_scope", "notify_on_finish", "RunContext"]
__version__ = "0.2.0"


def _dispatch(text: str) -> None:
    """Send ``text`` through every configured backend. Never raises."""
    try:
        config = load_config()
        if config.disabled:
            return
        backends = build_backends(config)
        if not backends:
            return
        for backend in backends:
            try:
                backend.send(text)
            except Exception as exc:  # pragma: no cover - defensive
                sys.stderr.write(
                    "[jobnotify] backend {} error: {!r}\n".format(backend.name, exc)
                )
    except Exception as exc:  # pragma: no cover - defensive
        sys.stderr.write("[jobnotify] dispatch error: {!r}\n".format(exc))


def notify(text: str) -> None:
    """Send an arbitrary message immediately."""
    _dispatch(str(text))


def _resolve_job_name(job_name):
    if job_name:
        return job_name
    return load_config().default_job_name or "python job"


@contextmanager
def notify_scope(
    job_name=None,
    *,
    experiment=None,
    gpu=None,
    command=None,
    extra=None,
    notify_start=None,
):
    """Run a block; alert on completion (success or failure). Re-raises errors.

        with notify_scope("train.py"):
            main(...)

        with notify_scope("train.py", experiment="kd_pku_cgl"):
            main(...)

    You get two alerts per run: one when the job starts (which GPU, which
    command) and one when it ends (success or failure). Pass
    ``notify_start=False`` — or set ``JOBNOTIFY_NOTIFY_START=0`` — for the
    finish-only behaviour of 0.1.x.

    ``experiment`` / ``gpu`` / ``command`` are only overrides — leave them out
    and they are filled in from the environment and ``sys.argv``.
    """
    name = _resolve_job_name(job_name)
    ctx = _context.collect(
        experiment=experiment, gpu=gpu, command=command, extra=extra
    ).lines()
    start = time.time()
    if notify_start or (notify_start is None and load_config().notify_start):
        _dispatch(_message.format_start(name, start, ctx))
    try:
        yield
    except BaseException as exc:  # noqa: BLE001 - we re-raise below
        end = time.time()
        # `sys.exit(0)` / `sys.exit()` is a normal, successful termination.
        if isinstance(exc, SystemExit) and (exc.code in (0, None)):
            _dispatch(_message.format_success(name, start, end, ctx))
        else:
            _dispatch(_message.format_failure(name, start, end, exc, context=ctx))
        raise
    else:
        end = time.time()
        _dispatch(_message.format_success(name, start, end, ctx))


def notify_on_finish(
    job_name=None,
    *,
    experiment=None,
    gpu=None,
    command=None,
    extra=None,
    notify_start=None,
):
    """Decorator form of :func:`notify_scope`.

        @notify_on_finish("training")
        def main(...): ...
    """

    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            name = job_name or getattr(func, "__name__", "python job")
            with notify_scope(
                name,
                experiment=experiment,
                gpu=gpu,
                command=command,
                extra=extra,
                notify_start=notify_start,
            ):
                return func(*args, **kwargs)

        return wrapper

    return decorator
