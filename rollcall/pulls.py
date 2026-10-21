"""What one pull brought in, with the reasoning behind every class it inferred (screen 5).

Class detection is an automated guess a person must be able to check, so this is the "Footprints"
requirement from `docs/UI-RESOURCES.md`: a detected class shows the scans it was inferred from, the
gap that ended it and the student count that triggered it. Screens 5 and 6 asserted the class and
hid the reasoning.

Every gap here is computed from the two bursts it sits between. The mockup wrote one by hand and
got it wrong by three hours (`docs/DESIGN-DEVIATIONS.md`, screen 5).
"""
from __future__ import annotations

import sqlite3
from datetime import datetime

from . import register


def _bucket_minutes(times: list[str], minutes: int = 5) -> list[dict]:
    """Scans per bucket across a burst, so the page draws a strip rather than placing marks by eye."""
    if not times:
        return []
    start = datetime.fromisoformat(times[0])
    buckets: dict[int, int] = {}
    for value in times:
        offset = int((datetime.fromisoformat(value) - start).total_seconds() // (minutes * 60))
        buckets[offset] = buckets.get(offset, 0) + 1
    width = max(buckets) + 1
    return [{"at": (start.timestamp() + i * minutes * 60), "minute": i * minutes,
             "scans": buckets.get(i, 0)} for i in range(width)]


def batch(conn: sqlite3.Connection, batch_id: int) -> dict:
    """Screen 5's whole contract: what was read, which classes came out of it, and why."""
    row = conn.execute(
        "SELECT b.*, a.display_name, d.name AS device_name, d.serial FROM import_batches b"
        " LEFT JOIN accounts a ON a.id = b.account_id LEFT JOIN devices d ON d.id = b.device_id"
        " WHERE b.id = ?", (batch_id,)).fetchone()
    if row is None:
        raise ValueError("Unknown pull.")

    scans = conn.execute(
        "SELECT p.device_user_id, p.timestamp, pe.id AS person_id, pe.surname, pe.other_names,"
        " pe.matric_no FROM punches p"
        " LEFT JOIN people pe ON CAST(pe.device_user_id AS TEXT) = p.device_user_id"
        " WHERE p.import_batch_id = ? ORDER BY p.timestamp", (batch_id,)).fetchall()

    # The classes this pull's scans landed in, which is the honest definition: a class belongs to
    # this result if at least one scan read here falls inside its window, grace included. Matching
    # on "created after the batch" instead put ten unrelated classes on the screen, because a
    # timestamp in seconds cannot tell two things apart that happened in the same second.
    days = sorted({r["timestamp"][:10] for r in scans})
    sessions = conn.execute(
        "SELECT s.*, c.code AS course_code, c.title AS course_title, l.name AS level_name"
        " FROM class_sessions s LEFT JOIN courses c ON c.id = s.course_id"
        " JOIN levels l ON l.id = s.level_id"
        f" WHERE s.cancelled_at IS NULL AND s.date IN ({','.join('?' * len(days))})"
        " ORDER BY s.date, s.start_time", days).fetchall() if days else []

    classes = []
    for s in sessions:
        opens, closes = register.window_for(conn, s)
        window = [r["timestamp"] for r in scans if opens <= r["timestamp"] <= closes]
        if not window:
            continue
        classes.append({
            "session_id": s["id"],
            "course_id": s["course_id"],
            "course_code": s["course_code"],
            "course_title": s["course_title"],
            "level_name": s["level_name"],
            "date": s["date"],
            "start_time": s["start_time"],
            "end_time": s["end_time"],
            "needs_course": s["course_id"] is None,
            "scans": len(window),
            "students": len({r["device_user_id"] for r in scans if opens <= r["timestamp"] <= closes}),
            "first_scan": window[0],
            "last_scan": window[-1],
            "strip": _bucket_minutes(window),
        })

    # The gap before each class, worked out from the two it sits between, never written by hand.
    # Two overlapping classes give a negative gap, which is not a gap: there is nothing to say.
    for index, item in enumerate(classes):
        previous = classes[index - 1] if index else None
        gap = None
        if previous and previous["date"] == item["date"]:
            minutes = round((datetime.fromisoformat(item["first_scan"])
                             - datetime.fromisoformat(previous["last_scan"])).total_seconds() / 60)
            gap = minutes if minutes > 0 else None
        item["gap_minutes_before"] = gap

    unknown = sorted({r["device_user_id"] for r in scans if r["person_id"] is None})
    return {
        "batch_id": row["id"],
        "source": row["source"],
        "at": row["created_at"],
        "by": row["display_name"],
        "device": {"name": row["device_name"], "serial": row["serial"]},
        "records_read": row["records_read"],
        "new_count": row["new_count"],
        "duplicate_count": row["duplicate_count"],
        "first_punch_at": row["first_punch_at"],
        "last_punch_at": row["last_punch_at"],
        "classes": classes,
        "unknown_device_ids": unknown,
        "settings": {
            "min_students": register.DETECT_MIN_STUDENTS,
            "gap_minutes": register.DETECT_GAP_MINUTES,
            "detection_on": True,
        },
    }


def latest(conn: sqlite3.Connection) -> dict | None:
    row = conn.execute("SELECT id FROM import_batches ORDER BY id DESC LIMIT 1").fetchone()
    return batch(conn, row["id"]) if row else None
