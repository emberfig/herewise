"""What happened today and what is waiting, in one shape (screen 4).

Assembled here rather than on the page, because the component guide is firm about it: a screen
renders the contract and never works out a status or a count for itself. Six round trips and a
present count per class would also be slow on the machine this runs on.
"""
from __future__ import annotations

import sqlite3
from datetime import date, datetime

from . import db, register


def _last_pull(conn: sqlite3.Connection) -> dict | None:
    row = conn.execute(
        "SELECT b.*, a.display_name FROM import_batches b LEFT JOIN accounts a ON a.id = b.account_id"
        " ORDER BY b.id DESC LIMIT 1").fetchone()
    if row is None:
        return None
    return {"at": row["created_at"], "source": row["source"], "records_read": row["records_read"],
            "new_count": row["new_count"], "by": row["display_name"],
            "last_punch_at": row["last_punch_at"]}


def now() -> datetime:
    """The clock, in one place, so a test can hold it still. A class is upcoming, running or over
    depending on the minute it is read, and a test that depends on the hour it runs at is a test
    that fails on its own one evening."""
    return datetime.now()


def _class_state(day: str, start: str, end: str, present: int, cancelled: str | None) -> str:
    if cancelled:
        return "cancelled"
    moment = now()
    begins = datetime.fromisoformat(f"{day}T{start}:00")
    ends = datetime.fromisoformat(f"{day}T{end}:00")
    if moment < begins:
        return "upcoming"
    if moment <= ends:
        return "running"
    return "complete" if present else "no_scans"


def today(conn: sqlite3.Connection, day: str | None = None) -> dict:
    day = day or date.today().isoformat()
    # Columns are named one at a time: `cs.*` also carries a `course_code`, and a duplicate name in
    # one row hands back whichever came first, which is the stale one on the class rather than the
    # course's own.
    rows = conn.execute(
        "SELECT cs.id, cs.course_id, cs.title, cs.date, cs.start_time, cs.end_time, cs.kind,"
        " cs.cancelled_at, cs.cancel_note, cs.opened_at, cs.closed_at,"
        " c.code AS course_code, c.title AS course_title, g.name AS group_name"
        " FROM class_sessions cs LEFT JOIN courses c ON c.id = cs.course_id"
        " LEFT JOIN course_groups g ON g.id = cs.group_id"
        " WHERE cs.date = ? ORDER BY cs.start_time", (day,)).fetchall()

    classes = []
    for row in rows:
        counts = register.session_register(conn, row["id"])["totals"]
        classes.append({
            "session_id": row["id"],
            "course_id": row["course_id"],
            "course_code": row["course_code"],
            "course_title": row["course_title"],
            "group": row["group_name"],
            "title": row["title"],
            "start_time": row["start_time"],
            "end_time": row["end_time"],
            "kind": row["kind"],
            "cancel_note": row["cancel_note"],
            "present": counts["present"],
            "registered": counts["students"],
            "excused": counts["excused"],
            # A class taken live has no end time until it is ended, so the clock cannot say.
            "state": ("taking" if register.is_open(row)
                      else _class_state(day, row["start_time"], row["end_time"], counts["present"],
                                        row["cancelled_at"])),
        })

    unassigned = len(register.unassigned_sessions(conn))
    pending = len(register.list_requests(conn, state="pending"))
    academic = conn.execute("SELECT * FROM academic_sessions WHERE is_current = 1").fetchone()
    return {
        "date": day,
        "academic_session": academic["name"] if academic else None,
        "last_pull": _last_pull(conn),
        "classes": classes,
        "waiting": {"unassigned_classes": unassigned, "correction_requests": pending},
        "courses": conn.execute("SELECT COUNT(*) FROM courses").fetchone()[0],
        "students": conn.execute("SELECT COUNT(*) FROM people WHERE role = 'student' AND active = 1")
                        .fetchone()[0],
        "device_clock_limit_seconds": int(db.get_setting(conn, "clock_drift_warn_seconds")),
    }


def rail_footer(conn: sqlite3.Connection) -> dict:
    """What the rail's footer shows: how many students this session holds, and where.

    It used to name only the level with the most students and give that level's count, so a
    department with five levels imported saw one of them and a number that was not the total. It
    also said "No students yet" when the real answer was that no session had been made current,
    which is a different problem with a different fix (reported on a first run, 2026-09-22).
    """
    current = conn.execute("SELECT id FROM academic_sessions WHERE is_current = 1").fetchone()
    if current is None:
        return {"session": False, "levels": 0, "level": None, "students": 0}
    rows = conn.execute(
        "SELECT l.name, COUNT(*) AS students FROM level_memberships m"
        " JOIN people p ON p.id = m.person_id AND p.active = 1"
        " JOIN levels l ON l.id = m.level_id"
        " WHERE m.academic_session_id = ?"
        " GROUP BY l.id ORDER BY COUNT(*) DESC", (current["id"],)).fetchall()
    return {"session": True, "levels": len(rows),
            "level": rows[0]["name"] if len(rows) == 1 else None,
            "students": sum(r["students"] for r in rows)}
