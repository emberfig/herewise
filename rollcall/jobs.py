"""What a long operation is doing right now, so a screen can draw a bar instead of a spinner.

Asked for on a second run: "there should also be a progress bar for when something is happening
like scanning or emptying the terminal so that a user knows how long to wait", and a plain
statement when it is done (2026-09-22). Sending a level to the terminal takes about thirty seconds
and emptying it about the same, and until now the only sign was a button that said "Sending".

**One slot, because there is only ever one.** Every route that touches the terminal already passes
through ``ensure_device_free()``, so two of these can never run at once. That means no job ids, no
registry and nothing to clean up: a screen asks what is happening and gets the answer or nothing.

**The count is real or it is absent.** ``total`` is only set where the work is a known number of
steps, which is people being written or taken off. A pull does not know how many records it will
read until it has read them, so it reports what it is doing and no bar. A bar that moves without
knowing what it is measuring is worse than no bar: it says "this much is left" and does not know.
"""
from __future__ import annotations

import threading
from typing import Any

from . import db

_lock = threading.Lock()
_current: dict[str, Any] | None = None


def start(what: str, total: int | None = None, detail: str = "") -> None:
    """Begin reporting. ``total`` only when the number of steps is known in advance."""
    global _current
    with _lock:
        _current = {"what": what, "detail": detail, "done": 0, "total": total,
                    "started_at": db.now(), "state": "running", "outcome": None}


def step(done: int = 1, detail: str | None = None) -> None:
    with _lock:
        if _current is None or _current["state"] != "running":
            return
        _current["done"] += done
        if detail is not None:
            _current["detail"] = detail


def at(done: int, detail: str | None = None) -> None:
    """Set the count rather than adding to it: the device reports a running number, not a delta."""
    with _lock:
        if _current is None or _current["state"] != "running":
            return
        _current["done"] = done
        if detail is not None:
            _current["detail"] = detail


def expect(total: int, detail: str | None = None) -> None:
    """Learn the total part way through, for work that has to look before it knows how much."""
    with _lock:
        if _current is None or _current["state"] != "running":
            return
        _current["total"] = total
        if detail is not None:
            _current["detail"] = detail


def say(detail: str) -> None:
    """Change what it says it is doing, without moving the count."""
    step(0, detail)


def finish(outcome: str = "done", detail: str = "") -> None:
    global _current
    with _lock:
        if _current is None:
            return
        _current.update(state="finished", outcome=outcome, finished_at=db.now())
        if detail:
            _current["detail"] = detail


def clear() -> None:
    global _current
    with _lock:
        _current = None


def current() -> dict | None:
    """A copy, so a caller reading it cannot be changed under its feet mid-render."""
    with _lock:
        return dict(_current) if _current else None
