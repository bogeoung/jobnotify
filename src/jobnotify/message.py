"""Human-readable message formatting for success / failure alerts."""
from __future__ import annotations

import socket
import time
import traceback as _tb


def _human_duration(seconds: float) -> str:
    seconds = int(round(seconds))
    if seconds < 60:
        return "{}s".format(seconds)
    minutes, sec = divmod(seconds, 60)
    if minutes < 60:
        return "{}m {}s".format(minutes, sec)
    hours, minutes = divmod(minutes, 60)
    if hours < 24:
        return "{}h {}m {}s".format(hours, minutes, sec)
    days, hours = divmod(hours, 24)
    return "{}d {}h {}m".format(days, hours, minutes)


def _fmt_time(epoch: float) -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(epoch))


def _hostname() -> str:
    try:
        return socket.gethostname()
    except Exception:
        return "unknown-host"


def format_success(job_name: str, start_ts: float, end_ts: float) -> str:
    lines = [
        "✅ Job finished: {}".format(job_name),
        "host: {}".format(_hostname()),
        "elapsed: {}".format(_human_duration(end_ts - start_ts)),
        "start: {}".format(_fmt_time(start_ts)),
        "end:   {}".format(_fmt_time(end_ts)),
    ]
    return "\n".join(lines)


def format_failure(
    job_name: str,
    start_ts: float,
    end_ts: float,
    exc: BaseException,
    tb_lines: int = 12,
) -> str:
    tb_text = "".join(_tb.format_exception(type(exc), exc, exc.__traceback__))
    lines = [
        "❌ Job FAILED: {}".format(job_name),
        "host: {}".format(_hostname()),
        "elapsed: {}".format(_human_duration(end_ts - start_ts)),
        "error: {}: {}".format(type(exc).__name__, exc),
        "start: {}".format(_fmt_time(start_ts)),
        "end:   {}".format(_fmt_time(end_ts)),
        "",
        "traceback (tail):",
        _tail(tb_text, tb_lines),
    ]
    return "\n".join(lines)


def _tail(text: str, n_lines: int) -> str:
    lines = text.rstrip().splitlines()
    if len(lines) <= n_lines:
        return "\n".join(lines)
    return "\n".join(["...(truncated)..."] + lines[-n_lines:])
