"""Storing scans. Both input paths (network pull, USB file) end in ``store_punches``, so mixing them
can never duplicate a record: UNIQUE(device_user_id, timestamp, device_id) plus INSERT OR IGNORE.
Scans from IDs nobody recognises are stored anyway (PRD section 10).
"""
from __future__ import annotations

import sqlite3
from datetime import datetime

from . import db, levels
from .device import RawPunch


def _ts(value: datetime) -> str:
    return value.replace(microsecond=0).isoformat()


# Named here rather than built from `source` in the db.audit call: an action name assembled in
# place is invisible to the test that every action has a sentence, and both of these read as
# "punches.import.network: 229 read, 229 new" on screen 38 until 2026-09-21.
AUDIT_ACTIONS = {"network": "punches.import.network", "usb": "punches.import.usb"}


def store_into_batch(conn: sqlite3.Connection, batch_id: int, device_id: int,
                     records: list[RawPunch]) -> int:
    """Add scans to a batch that already exists, and say how many were new. No audit row.

    For a class taken live, which reads the terminal every few seconds while the queue moves. Each
    read going through ``store_punches`` would put a line in the activity log for every student in
    the queue; the class writes one line when it starts and one when it ends instead, with the
    counts, and every scan still names this batch.
    """
    stamp = db.now()
    records = _without_retired(conn, records)[0]
    with db.transaction(conn):
        new = 0
        for r in records:
            new += conn.execute(
                "INSERT OR IGNORE INTO punches(device_user_id, timestamp, device_id, verify_type, punch_state,"
                " import_batch_id, imported_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (str(r.user_id).strip(), _ts(r.timestamp), device_id, r.verify_type, r.punch_state, batch_id,
                 stamp),
            ).rowcount
        if new:
            conn.execute("UPDATE import_batches SET records_read = records_read + ?,"
                         " new_count = coalesce(new_count, 0) + ? WHERE id = ?", (new, new, batch_id))
    return new


def store_punches(conn: sqlite3.Connection, device_id: int, records: list[RawPunch], source: str,
                  account_id: int | None, file_name: str | None = None, archived_path: str | None = None,
                  skipped_count: int = 0, detail: str | None = None) -> dict:
    stamp = db.now()
    read = len(records)
    records, retired = _without_retired(conn, records)
    with db.transaction(conn):
        cur = conn.execute(
            "INSERT INTO import_batches(source, device_id, file_name, archived_path, created_at, records_read,"
            " skipped_count, account_id, detail) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (source, device_id, file_name, archived_path, stamp, read, skipped_count + retired, account_id, detail),
        )
        batch_id = cur.lastrowid
        new = 0
        for r in records:
            inserted = conn.execute(
                "INSERT OR IGNORE INTO punches(device_user_id, timestamp, device_id, verify_type, punch_state,"
                " import_batch_id, imported_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (str(r.user_id).strip(), _ts(r.timestamp), device_id, r.verify_type, r.punch_state, batch_id, stamp),
            ).rowcount
            new += inserted
        times = sorted(_ts(r.timestamp) for r in records)
        first, last = (times[0], times[-1]) if times else (None, None)
        conn.execute(
            "UPDATE import_batches SET new_count = ?, duplicate_count = ?, first_punch_at = ?, last_punch_at = ?"
            " WHERE id = ?",
            (new, len(records) - new, first, last, batch_id),
        )
        db.audit(conn, account_id, AUDIT_ACTIONS[source], "import_batches", batch_id,
                 f"{read} read, {new} new" + (f", {retired} from a deleted roster left out" if retired else ""))
    return {
        "batch_id": batch_id,
        "source": source,
        "records_read": read,
        "new": new,
        "already_known": len(records) - new,
        "skipped": skipped_count,
        "retired": retired,
        "first_punch_at": first,
        "last_punch_at": last,
        "message": _message(read, new, skipped_count, first, last, retired),
    }


def _without_retired(conn: sqlite3.Connection, records: list[RawPunch]) -> tuple[list[RawPunch], int]:
    """Leave out scans from the device IDs of a deleted roster (levels.clear).

    The terminal keeps its own scan log after a roster is deleted, so without this the next pull
    would bring the deleted attendance straight back, as scans from IDs nobody here has.
    """
    ranges = levels.retired_ranges(conn)
    if not ranges:
        return records, 0
    kept = [r for r in records if not levels.is_retired(r.user_id, ranges)]
    return kept, len(records) - len(kept)


def _message(read: int, new: int, skipped: int, first: str | None, last: str | None,
             retired: int = 0) -> str:
    text = f"{read} scans read, {new} new, {read - new - retired} already stored"
    if retired:
        text += f", {retired} from a deleted roster left out"
    if skipped:
        text += f", {skipped} lines skipped"
    if first and last:
        a, b = datetime.fromisoformat(first), datetime.fromisoformat(last)
        span = (f"{a:%d %b %H:%M} to {b:%H:%M}" if a.date() == b.date()
                else f"{a:%d %b %H:%M} to {b:%d %b %H:%M}")
        text += f". {span}"
    return text + "."


def unmatched(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute(
        "SELECT pu.device_user_id, pu.device_id, COUNT(*) AS scans, MIN(pu.timestamp) AS first_scan,"
        " MAX(pu.timestamp) AS last_scan FROM punches pu"
        " LEFT JOIN people p ON CAST(p.device_user_id AS TEXT) = pu.device_user_id"
        " WHERE p.id IS NULL GROUP BY pu.device_user_id, pu.device_id ORDER BY last_scan DESC"
    ).fetchall()
    return [dict(r) for r in rows]
