"""Human-readable message formatting for success / failure alerts."""
from __future__ import annotations

import socket
import time
import traceback as _tb
from typing import List, Optional, Sequence


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


def _header(icon: str, title: str, job_name: str, context: Optional[Sequence[str]]) -> List[str]:
    """Headline + the "where did this run" block (experiment / gpu / command)."""
    return ["{} {}: {}".format(icon, title, job_name),
            "host: {}".format(_hostname())] + list(context or [])


def format_start(
    job_name: str,
    start_ts: float,
    context: Optional[Sequence[str]] = None,
) -> str:
    lines = _header("▶️", "Job started", job_name, context)
    lines.append("start: {}".format(_fmt_time(start_ts)))
    return "\n".join(lines)


def format_success(
    job_name: str,
    start_ts: float,
    end_ts: float,
    context: Optional[Sequence[str]] = None,
) -> str:
    lines = _header("✅", "Job finished", job_name, context)
    lines += [
        "elapsed: {}".format(_human_duration(end_ts - start_ts)),
        "start: {}".format(_fmt_time(start_ts)),
        "end:   {}".format(_fmt_time(end_ts)),
    ]
    return "\n".join(lines)


def format_exit(
    job_name: str,
    start_ts: float,
    end_ts: float,
    returncode: int,
    context: Optional[Sequence[str]] = None,
    output_tail: str = "",
) -> str:
    """Alert for a subprocess that ended — used by the CLI wrapper."""
    ok = returncode == 0
    lines = _header("✅" if ok else "❌",
                    "Job finished" if ok else "Job FAILED",
                    job_name, context)
    lines.append("exit: {}".format(_describe_returncode(returncode)))
    lines += [
        "elapsed: {}".format(_human_duration(end_ts - start_ts)),
        "start: {}".format(_fmt_time(start_ts)),
        "end:   {}".format(_fmt_time(end_ts)),
    ]
    if output_tail:
        lines += ["", "output (tail):", output_tail.rstrip()]
    return "\n".join(lines)


def _describe_returncode(returncode: int) -> str:
    """``-2`` → ``killed by SIGINT (-2)``; a plain code stays a plain code."""
    if returncode >= 0:
        return str(returncode)
    try:
        import signal

        name = signal.Signals(-returncode).name
    except Exception:
        return str(returncode)
    return "killed by {} ({})".format(name, returncode)


def format_failure(
    job_name: str,
    start_ts: float,
    end_ts: float,
    exc: BaseException,
    tb_lines: int = 12,
    context: Optional[Sequence[str]] = None,
) -> str:
    tb_text = "".join(_tb.format_exception(type(exc), exc, exc.__traceback__))
    lines = _header("❌", "Job FAILED", job_name, context)
    lines += [
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
