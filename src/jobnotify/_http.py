"""Tiny HTTP helper built on the standard library only.

Design rule: this must NEVER raise. A failed notification must not be able to
crash the training job it is attached to — on any error we write a warning to
stderr and return False.
"""
from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.request
from typing import Any, Dict


def post_json(
    url: str,
    payload: Dict[str, Any],
    *,
    timeout: float = 10.0,
    retries: int = 2,
    retry_delay: float = 2.0,
) -> bool:
    """POST ``payload`` as JSON. Returns True on 2xx, False otherwise. Never raises."""
    data = json.dumps(payload).encode("utf-8")
    last_err = "unknown error"

    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(
                url,
                data=data,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                status = getattr(resp, "status", resp.getcode())
                if 200 <= status < 300:
                    return True
                last_err = "HTTP {}".format(status)
        except urllib.error.HTTPError as exc:
            body = ""
            try:
                body = exc.read().decode("utf-8", "replace")[:300]
            except Exception:
                pass
            last_err = "HTTP {}: {}".format(exc.code, body)
            # Client errors (except rate-limit) won't succeed on retry.
            if 400 <= exc.code < 500 and exc.code != 429:
                break
        except Exception as exc:  # URLError, timeout, DNS, etc.
            last_err = repr(exc)

        if attempt < retries:
            time.sleep(retry_delay)

    sys.stderr.write("[jobnotify] notification failed: {}\n".format(last_err))
    return False
