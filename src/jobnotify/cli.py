"""``jobnotify`` command-line wrapper.

Runs any command and sends a Telegram alert when it starts and when it ends,
with the experiment name, the GPU it ran on, and the command itself in the
message::

    jobnotify -- python -m poster.train --datasets pku
    jobnotify -e kd_pku_cgl -n "poster KD" -- python -m poster.train --pseudo x.jsonl
    jobnotify --shell 'cd /work && python train.py && python eval.py'

The child's stdout/stderr are passed straight through and its exit code is
propagated, so wrapping a command never changes what you see in the terminal.
"""
from __future__ import annotations

import os
import shutil
import signal
import subprocess
import sys
import time
from collections import deque
from contextlib import contextmanager
from typing import List, Optional, Sequence, Tuple

from . import _dispatch, __version__
from . import context as _context
from . import message as _message
from .config import load_config

USAGE = """\
usage: jobnotify [options] -- COMMAND [ARGS...]
       jobnotify [options] --shell 'SHELL COMMAND'
       jobnotify --test

Run COMMAND and send a Telegram alert when it starts and when it finishes,
including the experiment name, the GPU, and the command itself.

options:
  -n, --name NAME        job label in the alert headline (default: derived
                         from COMMAND, or $JOBNOTIFY_JOB_NAME)
  -e, --experiment NAME  experiment id (default: $JOBNOTIFY_EXPERIMENT)
  -g, --gpu TEXT         override the auto-detected GPU description
      --shell            run the rest as one shell command line
      --no-start         skip the "started" alert (finish alert only)
      --tail N           capture the last N output lines into the alert
                         (default 0 = no capture, output is untouched)
      --no-gpu           skip GPU detection entirely
      --test             send a test alert and exit (checks your credentials)
  -h, --help             show this help
  -V, --version          show the jobnotify version
"""

_VALUE_OPTS = {"-n", "--name", "-e", "--experiment", "-g", "--gpu", "--tail"}


class _Options:
    def __init__(self) -> None:
        self.name: Optional[str] = None
        self.experiment: Optional[str] = None
        self.gpu: Optional[str] = None
        self.shell = False
        self.start: Optional[bool] = None
        self.tail = 0
        self.no_gpu = False
        self.test = False


def _split_argv(argv: Sequence[str]) -> Tuple[List[str], List[str]]:
    """Split our own flags from the wrapped command.

    Everything after ``--`` is the command. Without an explicit ``--`` the
    command starts at the first token that is neither an option nor an option's
    value, so ``jobnotify -e kd python train.py`` also works.
    """
    argv = list(argv)
    if "--" in argv:
        index = argv.index("--")
        return argv[:index], argv[index + 1 :]
    expecting_value = False
    for i, token in enumerate(argv):
        if expecting_value:
            expecting_value = False
            continue
        if token.startswith("-") and token != "-":
            expecting_value = token in _VALUE_OPTS
            continue
        return argv[:i], argv[i:]
    return argv, []


def _parse_options(tokens: Sequence[str]) -> _Options:
    opts = _Options()
    i = 0
    while i < len(tokens):
        token = tokens[i]
        # Accept both `--name X` and `--name=X`.
        if "=" in token and token.startswith("--"):
            token, _, inline = token.partition("=")
        else:
            inline = None

        def value() -> str:
            nonlocal i
            if inline is not None:
                return inline
            i += 1
            if i >= len(tokens):
                raise SystemExit("jobnotify: {} needs a value".format(token))
            return tokens[i]

        if token in ("-n", "--name"):
            opts.name = value()
        elif token in ("-e", "--experiment"):
            opts.experiment = value()
        elif token in ("-g", "--gpu"):
            opts.gpu = value()
        elif token == "--tail":
            try:
                opts.tail = max(0, int(value()))
            except ValueError:
                raise SystemExit("jobnotify: --tail needs an integer")
        elif token == "--shell":
            opts.shell = True
        elif token == "--start":
            opts.start = True
        elif token == "--no-start":
            opts.start = False
        elif token == "--no-gpu":
            opts.no_gpu = True
        elif token == "--test":
            opts.test = True
        elif token in ("-h", "--help"):
            sys.stdout.write(USAGE)
            raise SystemExit(0)
        elif token in ("-V", "--version"):
            sys.stdout.write("jobnotify {}\n".format(__version__))
            raise SystemExit(0)
        else:
            raise SystemExit(
                "jobnotify: unknown option {!r}\n\n{}".format(token, USAGE)
            )
        i += 1
    return opts


def _default_name(command: Sequence[str], shell: bool) -> str:
    """A short headline label derived from the command itself."""
    env_name = load_config().default_job_name
    if env_name:
        return env_name
    if not command:
        return "command"
    if shell:
        text = " ".join(command)
        return text if len(text) <= 60 else text[:57] + "..."
    head = os.path.basename(command[0])
    if len(command) > 2 and command[1] == "-m":
        return "{} -m {}".format(head, command[2])
    if len(command) > 1 and not command[1].startswith("-"):
        return "{} {}".format(head, os.path.basename(command[1]))
    return head


def _shell_argv(command: Sequence[str]) -> List[str]:
    shell = os.environ.get("SHELL") or shutil.which("bash") or "/bin/sh"
    return [shell, "-c", " ".join(command)]


def _run(argv: List[str], tail: int) -> Tuple[int, str]:
    """Run the child, returning ``(returncode, captured_tail)``.

    With ``tail == 0`` the child inherits our stdio untouched — important for
    progress bars and anything that checks for a tty.
    """
    if tail <= 0:
        proc = subprocess.Popen(argv)
        with _forwarding_signals(proc):
            return _wait(proc), ""

    proc = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    buffer: deque = deque(maxlen=tail)
    assert proc.stdout is not None
    with _forwarding_signals(proc):
        try:
            for raw in proc.stdout:
                line = raw.decode("utf-8", "replace")
                sys.stdout.write(line)
                sys.stdout.flush()
                buffer.append(line.rstrip("\n"))
        except KeyboardInterrupt:
            pass
        return _wait(proc), "\n".join(buffer)


@contextmanager
def _forwarding_signals(proc: "subprocess.Popen"):
    """Pass ``kill`` / ``docker stop`` on to the child instead of dying first.

    Without this the wrapper would exit on SIGTERM while the job kept running
    unsupervised. SIGINT is the exception: a terminal Ctrl-C already reaches
    the whole foreground process group, so forwarding the first one would
    double-deliver — we forward from the second Ctrl-C on, which doubles as
    the usual "I really mean it" escalation.
    """
    seen_interrupt = [False]

    def handler(signum, _frame):
        if signum == signal.SIGINT and not seen_interrupt[0]:
            seen_interrupt[0] = True
            return
        try:
            proc.send_signal(signum)
        except Exception:  # already reaped
            pass

    previous = {}
    for signum in (signal.SIGINT, signal.SIGTERM, getattr(signal, "SIGHUP", None)):
        if signum is None:
            continue
        try:
            previous[signum] = signal.signal(signum, handler)
        except (ValueError, OSError, AttributeError):
            # Not the main thread, or the platform lacks the signal.
            pass
    try:
        yield
    finally:
        for signum, old in previous.items():
            try:
                signal.signal(signum, old)
            except Exception:  # pragma: no cover - defensive
                pass


def _wait(proc: "subprocess.Popen") -> int:
    """Wait for the child; a stray Ctrl-C must not skip the notification."""
    while True:
        try:
            return proc.wait()
        except KeyboardInterrupt:
            continue


def main(argv: Optional[Sequence[str]] = None) -> int:
    tokens, command = _split_argv(sys.argv[1:] if argv is None else argv)
    opts = _parse_options(tokens)

    if opts.no_gpu:
        os.environ["JOBNOTIFY_GPU_QUERY"] = "0"

    if opts.test:
        ctx = _context.collect(experiment=opts.experiment, gpu=opts.gpu,
                               command=command or None)
        config = load_config()
        if not config.telegram_enabled:
            sys.stderr.write(
                "jobnotify: no credentials — set JOBNOTIFY_TELEGRAM_TOKEN and "
                "JOBNOTIFY_TELEGRAM_CHAT_ID.\n"
            )
            return 1
        _dispatch("\n".join(
            _message._header("🔔", "jobnotify test", "credentials OK", ctx.lines())
        ))
        sys.stderr.write("jobnotify: test alert sent.\n")
        return 0

    if not command:
        sys.stderr.write(USAGE)
        return 2

    child_argv = _shell_argv(command) if opts.shell else list(command)
    name = opts.name or _default_name(command, opts.shell)
    ctx = _context.collect(
        experiment=opts.experiment,
        gpu=opts.gpu,
        # Report the command the user typed, not the `bash -c` wrapper.
        # A --shell command line is already shell syntax, so don't re-quote it.
        command=" ".join(command) if opts.shell else _context.quote_command(command),
    ).lines()

    start = time.time()
    want_start = opts.start if opts.start is not None else load_config().notify_start
    if want_start:
        _dispatch(_message.format_start(name, start, ctx))

    try:
        returncode, tail_text = _run(child_argv, opts.tail)
    except OSError as exc:
        end = time.time()
        _dispatch(_message.format_failure(name, start, end, exc, context=ctx))
        sys.stderr.write("jobnotify: could not run command: {}\n".format(exc))
        return 127

    end = time.time()
    _dispatch(_message.format_exit(name, start, end, returncode, ctx, tail_text))
    # Mirror the shell's convention for signal deaths (128 + signal number).
    return returncode if returncode >= 0 else 128 - returncode


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
