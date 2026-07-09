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

_TRUTHY = {"1", "true", "yes", "on"}


@dataclass
class Config:
    telegram_token: str | None
    telegram_chat_id: str | None
    default_job_name: str | None
    disabled: bool

    @property
    def telegram_enabled(self) -> bool:
        return bool(self.telegram_token and self.telegram_chat_id)


def _clean(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    return value or None


def load_config() -> Config:
    disable_raw = (os.environ.get(ENV_DISABLE) or "").strip().lower()
    return Config(
        telegram_token=_clean(os.environ.get(ENV_TOKEN)),
        telegram_chat_id=_clean(os.environ.get(ENV_CHAT_ID)),
        default_job_name=_clean(os.environ.get(ENV_JOB_NAME)),
        disabled=disable_raw in _TRUTHY,
    )
