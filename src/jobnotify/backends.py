"""Notification backends.

Only Telegram is implemented today. ``Backend`` is the extension point: add a
new subclass (Discord, Slack, ...) and register it in ``build_backends`` to
support more channels without touching the public API.
"""
from __future__ import annotations

from typing import List

from . import _http
from .config import Config

# Telegram rejects messages longer than 4096 characters.
_TELEGRAM_MAX = 4096


class Backend:
    name = "base"

    def send(self, text: str) -> bool:  # pragma: no cover - abstract
        raise NotImplementedError


class TelegramBackend(Backend):
    name = "telegram"
    _API = "https://api.telegram.org/bot{token}/sendMessage"

    def __init__(self, token: str, chat_id: str) -> None:
        self._token = token
        self._chat_id = chat_id

    def send(self, text: str) -> bool:
        if len(text) > _TELEGRAM_MAX:
            text = text[: _TELEGRAM_MAX - 4] + "\n..."
        url = self._API.format(token=self._token)
        payload = {
            "chat_id": self._chat_id,
            # Plain text (no parse_mode): tracebacks contain <, >, & and would
            # break HTML/Markdown parsing.
            "text": text,
            "disable_web_page_preview": True,
        }
        return _http.post_json(url, payload)


def build_backends(config: Config) -> List[Backend]:
    """Return every backend that is fully configured via the environment."""
    backends: List[Backend] = []
    if config.telegram_enabled:
        # telegram_enabled guarantees both fields are non-None.
        backends.append(TelegramBackend(config.telegram_token, config.telegram_chat_id))  # type: ignore[arg-type]
    return backends
