"""Configuration loading — reads everything from environment variables.

No credential is ever hardcoded or read from a committed file; the only source
of truth is the process environment (export / `docker -e` / a sourced .env).
"""
from __future__ import annotations

import os
from dataclasses import dataclass

ENV_TOKEN = "JOBNOTIFY_TELEGRAM_TOKEN"
ENV_CHAT_ID = "JOBNOTIFY_TELEGRAM_CHAT_ID"
ENV_JOB_NAME = "JOBNOTIFY_JOB_NAME"
ENV_DISABLE = "JOBNOTIFY_DISABLE"
# Run-context knobs (all optional; every one has a safe default).
ENV_EXPERIMENT = "JOBNOTIFY_EXPERIMENT"
ENV_GPU = "JOBNOTIFY_GPU"
ENV_CONTEXT = "JOBNOTIFY_CONTEXT"
ENV_GPU_QUERY = "JOBNOTIFY_GPU_QUERY"
ENV_NOTIFY_START = "JOBNOTIFY_NOTIFY_START"

_TRUTHY = {"1", "true", "yes", "on"}
_FALSY = {"0", "false", "no", "off"}


@dataclass
class Config:
    telegram_token: str | None
    telegram_chat_id: str | None
    default_job_name: str | None
    disabled: bool
    # Defaults are chosen so an existing deployment that sets none of the
    # context env vars keeps working exactly as before, just with richer alerts.
    experiment: str | None = None
    gpu_override: str | None = None
    context_enabled: bool = True
    gpu_query_enabled: bool = True
    notify_start: bool = False

    @property
    def telegram_enabled(self) -> bool:
        return bool(self.telegram_token and self.telegram_chat_id)


def _clean(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    return value or None


def _flag(name: str, default: bool) -> bool:
    raw = (os.environ.get(name) or "").strip().lower()
    if raw in _TRUTHY:
        return True
    if raw in _FALSY:
        return False
    return default


def load_config() -> Config:
    return Config(
        telegram_token=_clean(os.environ.get(ENV_TOKEN)),
        telegram_chat_id=_clean(os.environ.get(ENV_CHAT_ID)),
        default_job_name=_clean(os.environ.get(ENV_JOB_NAME)),
        disabled=_flag(ENV_DISABLE, False),
        experiment=_clean(os.environ.get(ENV_EXPERIMENT)),
        gpu_override=_clean(os.environ.get(ENV_GPU)),
        context_enabled=_flag(ENV_CONTEXT, True),
        gpu_query_enabled=_flag(ENV_GPU_QUERY, True),
        notify_start=_flag(ENV_NOTIFY_START, False),
    )
