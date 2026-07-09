"""jobnotify — send a Telegram alert when a long-running Python job finishes.

Public API:
    notify(text)                 send an arbitrary message now
    notify_scope(job_name)       context manager: alert on success AND failure
    notify_on_finish(job_name)   decorator form of notify_scope

All entry points are safe: a notification failure (bad token, no network,
missing config) never raises into your job — at worst it prints a stderr warning.
If no credentials are configured, everything is a silent no-op.
"""
from __future__ import annotations

import functools
import sys
import time
from contextlib import contextmanager

from . import message as _message
from .backends import build_backends
from .config import load_config

__all__ = ["notify", "notify_scope", "notify_on_finish"]
__version__ = "0.1.0"


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
def notify_scope(job_name=None):
    """Run a block; alert on completion (success or failure). Re-raises errors.

        with notify_scope("train.py"):
            main(...)
    """
    name = _resolve_job_name(job_name)
    start = time.time()
    try:
        yield
    except BaseException as exc:  # noqa: BLE001 - we re-raise below
        end = time.time()
        # `sys.exit(0)` / `sys.exit()` is a normal, successful termination.
        if isinstance(exc, SystemExit) and (exc.code in (0, None)):
            _dispatch(_message.format_success(name, start, end))
        else:
            _dispatch(_message.format_failure(name, start, end, exc))
        raise
    else:
        end = time.time()
        _dispatch(_message.format_success(name, start, end))


def notify_on_finish(job_name=None):
    """Decorator form of :func:`notify_scope`.

        @notify_on_finish("training")
        def main(...): ...
    """

    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            name = job_name or getattr(func, "__name__", "python job")
            with notify_scope(name):
                return func(*args, **kwargs)

        return wrapper

    return decorator
