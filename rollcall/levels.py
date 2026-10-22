"""The years a department runs, and the block of device IDs each one owns.

Herewise seeded 100 to 500 and had no way to add a sixth or take away a fifth, so a department whose
years stop at 400, and a course of study that runs to 700, could neither be set up nor tidied up
(found on a first run, 2026-09-21). A level is three things: a number, which is structural; a name,
which anybody can change to whatever the department calls that year; and a block of a thousand
device IDs derived from the number.

**The number decides the IDs, so it is a multiple of 100 from 100 to 900.** Level 200 owns 2001 to
2999, level 700 owns 7001 to 7999, and 1 to 999 is left to staff. That is what keeps a device ID
permanent and unambiguous: a scan carries a number and nothing else, so two levels sharing a block
would make a scan unattributable for ever. A department that calls its years something else renames
the level and leaves the number alone.

**A level is only removable while nothing points at it.** What points at it is read from the
database's own foreign keys rather than a list kept here, so a table added later cannot quietly
orphan a row.
"""
from __future__ import annotations

import sqlite3

from . import db

MIN_LEVEL = 100
MAX_LEVEL = 900
STEP = 100
STAFF_IDS = 999                       # 1 to 999 are staff, so no level may own them


class LevelError(ValueError):
    """A level that cannot be made or removed, with the sentence the person reads."""


def block_for(number: int) -> tuple[int, int]:
    """200 owns 2001 to 2999, the same arithmetic the first five levels were seeded with."""
    block = (number // 100) * 1000
    return block + 1, block + 999


def check_number(number: int) -> int:
    if not isinstance(number, int) or isinstance(number, bool):
        raise LevelError("A level is a whole number, such as 600.")
    if number < MIN_LEVEL or number > MAX_LEVEL:
        raise LevelError(f"A level runs from {MIN_LEVEL} to {MAX_LEVEL}. Each one owns a thousand "
                         "device IDs, and the terminal has no room below or above that.")
    if number % STEP:
        raise LevelError("A level goes up in hundreds: 100, 200, 300 and so on. The name is yours "
                         "to change to whatever the department calls that year.")
    return number


def add(conn: sqlite3.Connection, number: int, account_id: int | None, name: str = "") -> dict:
    check_number(number)
    if conn.execute("SELECT 1 FROM levels WHERE level_number = ?", (number,)).fetchone():
        raise LevelError(f"There is already a {number} Level.")
    start, end = block_for(number)
    if start <= STAFF_IDS:
        raise LevelError("That level would take device IDs that belong to staff.")
    clash = conn.execute("SELECT name FROM levels WHERE id_block_start = ?", (start,)).fetchone()
    if clash:
        raise LevelError(f"{clash['name']} already owns device IDs {start} to {end}.")
    label = (name or "").strip() or f"{number} Level"
    with db.transaction(conn):
        cur = conn.execute(
            "INSERT INTO levels(level_number, name, code, id_block_start, id_block_end)"
            " VALUES (?, ?, NULL, ?, ?)", (number, label, start, end))
        db.audit(conn, account_id, "level.create", "levels", cur.lastrowid,
                 f"{label}, device IDs {start} to {end}")
    return dict(conn.execute("SELECT * FROM levels WHERE id = ?", (cur.lastrowid,)).fetchone())


def references(conn: sqlite3.Connection, level_id: int) -> dict[str, int]:
    """Every row in the database that points at this level, by table.

    Read from the schema's own foreign keys, so this cannot fall behind a table added later.
    """
    found: dict[str, int] = {}
    tables = [r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'")]
    for table in tables:
        for key in conn.execute(f"PRAGMA foreign_key_list({table})"):
            if key["table"] != "levels":
                continue
            column = key["from"]
            count = conn.execute(
                f"SELECT COUNT(*) FROM {table} WHERE {column} = ?", (level_id,)).fetchone()[0]
            if count:
                found[table] = found.get(table, 0) + count
    return found


# What a table is called when it is being explained to somebody, rather than to SQLite: one, then
# more than one.
PLAIN = {
    # Plain nouns, because these are read in a list inside a table cell. The nuance that a
    # membership may belong to a past session is in why_not_removable, where there is room.
    "level_memberships": ("student", "students"),
    "courses": ("course", "courses"),
    "class_sessions": ("class", "classes"),
    "roster_imports": ("roster import", "roster imports"),
    "people": ("person", "people"),
}


def plain_name(table: str, count: int) -> str:
    """What a table is called to somebody reading a screen, without the count in front of it."""
    one, many = PLAIN.get(table, (table, table))
    return one if count == 1 else many


def _plain(table: str, count: int) -> str:
    one, many = PLAIN.get(table, (table, table))
    return f"{count} {one if count == 1 else many}"


def why_not_removable(conn: sqlite3.Connection, level_id: int) -> str:
    """The sentence a screen writes under a Remove it cannot offer, or "" when it can.

    The Levels screen used to leave the button out entirely when a level had anything on it, which
    breaks this app's own rule: a control somebody cannot use stays on the screen with the reason
    written on it, never disappears (docs/SCREENS.md). Asked for again on a second run: "I want to
    be able to delete the levels I've added", from a screen that was not offering it (2026-09-22).
    """
    level = conn.execute("SELECT * FROM levels WHERE id = ?", (level_id,)).fetchone()
    if level is None:
        return "Unknown level."
    held = references(conn, level_id)
    if not held:
        return ""
    what = ", ".join(_plain(table, count) for table, count in sorted(held.items()))
    fix = (" Take the import back out from its own screen and the students go with it."
           if "level_memberships" in held or "people" in held else "")
    counted = (" Students are counted for this session and any past one." 
               if "level_memberships" in held else "")
    return (f"{level['name']} still has {what}, so it cannot be removed. A level is only removed "
            f"while nothing points at it, because its device IDs are in the scans for "
            f"good.{counted}{fix}")


def remove(conn: sqlite3.Connection, level_id: int, account_id: int | None) -> dict:
    level = conn.execute("SELECT * FROM levels WHERE id = ?", (level_id,)).fetchone()
    if level is None:
        raise LevelError("Unknown level.")
    # One sentence, written once: the screen shows this under its disabled Remove and the API
    # refuses with the same words, so the two can never drift apart.
    why = why_not_removable(conn, level_id)
    if why:
        raise LevelError(why)
    with db.transaction(conn):
        conn.execute("DELETE FROM levels WHERE id = ?", (level_id,))
        db.audit(conn, account_id, "level.delete", "levels", level_id,
                 f"{level['name']}, which had nothing on it")
    return {"removed": level["name"]}


# -- clearing a level's roster and everything on it ------------------------------------------------
#
# Asked for on 2026-09-23, from a Levels screen whose Remove was disabled with "On it: 1 course, 120
# students and 1 roster import": "set it so that I can delete the roster and when i do it delete a
# roster everything related to that roster will be deleted including the classes and the attendance
# and courses". Taking an import back out is refused once anybody has scanned, so without this there
# was no way to start a level again short of deleting the whole register.
#
# Asked for in the same message: the students' fingerprints come off the terminal too, and nothing
# is deleted while the terminal cannot be reached. So the terminal goes first (services.clear_level)
# and the register follows only once the terminal reads back without them, the order
# remove_from_device already uses.
#
# The level itself stays, empty, so the roster can be imported again. Its device IDs do not come
# back: the terminal keeps its own scan log, so the IDs are retired (table retired_ids). New students
# are numbered after them, and a pull leaves out a scan from one rather than bringing the cleared
# attendance back.

# The triggers that refuse a DELETE on attendance (db.py, SCHEMA and SCHEMA_V5).
DELETE_GUARDS = ("punches_immutable_delete", "marks_immutable_delete", "requests_no_delete",
                 "reopenings_immutable_delete")


def _ids(conn: sqlite3.Connection, sql: str, args: tuple) -> list[int]:
    return [r[0] for r in conn.execute(sql, args)]


def _marks(ids: list[int]) -> str:
    return ",".join("?" * len(ids)) or "NULL"


def _in_block(column: str) -> str:
    """A scan's user ID is text from the terminal: only a whole number can fall in a block."""
    return (f"({column} <> '' AND {column} NOT GLOB '*[^0-9]*'"
            f" AND CAST({column} AS INTEGER) BETWEEN ? AND ?)")


def _level(conn: sqlite3.Connection, level_id: int) -> sqlite3.Row:
    level = conn.execute("SELECT * FROM levels WHERE id = ?", (level_id,)).fetchone()
    if level is None:
        raise LevelError("Unknown level.")
    return level


def _scope(conn: sqlite3.Connection, level: sqlite3.Row) -> dict:
    """Everything that goes when a level is cleared, as lists of ids."""
    lid, start, end = level["id"], level["id_block_start"], level["id_block_end"]
    people = sorted(set(
        _ids(conn, "SELECT person_id FROM level_memberships WHERE level_id = ?", (lid,))
        + _ids(conn, "SELECT id FROM people WHERE roster_import_id IN"
                     " (SELECT id FROM roster_imports WHERE level_id = ?)", (lid,))
        + _ids(conn, "SELECT id FROM people WHERE role = 'student' AND device_user_id BETWEEN ? AND ?",
               (start, end))))
    courses = _ids(conn, "SELECT id FROM courses WHERE level_id = ?", (lid,))
    classes = _ids(conn, f"SELECT id FROM class_sessions WHERE level_id = ? OR course_id IN ({_marks(courses)})",
                   (lid, *courses))
    return {"people": people, "courses": courses, "classes": classes}


def clear_preview(conn: sqlite3.Connection, level_id: int) -> dict:
    """What clearing would delete, counted, for the dialog that asks first."""
    level = _level(conn, level_id)
    s = _scope(conn, level)
    p, c, k = s["people"], s["courses"], s["classes"]

    def count(sql: str, args: tuple) -> int:
        return conn.execute(sql, args).fetchone()[0]

    return {
        "level_id": level_id,
        "name": level["name"],
        "id_block": [level["id_block_start"], level["id_block_end"]],
        "students": len(p),
        "courses": len(c),
        "classes": len(k),
        "scans": count(f"SELECT COUNT(*) FROM punches WHERE {_in_block('device_user_id')}",
                       (level["id_block_start"], level["id_block_end"])),
        "corrections": count(f"SELECT COUNT(*) FROM attendance_marks WHERE class_session_id IN ({_marks(k)})"
                             f" OR person_id IN ({_marks(p)})", (*k, *p)),
        "excusals": count(f"SELECT COUNT(*) FROM excusals WHERE course_id IN ({_marks(c)})"
                          f" OR person_id IN ({_marks(p)})", (*c, *p)),
        "fingerprints": count(f"SELECT COUNT(*) FROM fingers WHERE person_id IN ({_marks(p)})", tuple(p)),
        "on_terminal": count(f"SELECT COUNT(*) FROM people WHERE on_device = 1 AND id IN ({_marks(p)})", tuple(p)),
        "imports": count("SELECT COUNT(*) FROM roster_imports WHERE level_id = ? AND status = 'committed'",
                         (level_id,)),
        "open_class": bool(conn.execute(
            f"SELECT 1 FROM class_sessions WHERE opened_at IS NOT NULL AND closed_at IS NULL"
            f" AND id IN ({_marks(k)})", tuple(k)).fetchone()),
    }


def check_clear(conn: sqlite3.Connection, level_id: int, confirm: str) -> sqlite3.Row:
    """Refuse before the terminal is touched: a wrong name, or a class still taking attendance."""
    level = _level(conn, level_id)
    if " ".join((confirm or "").split()).casefold() != " ".join(level["name"].split()).casefold():
        raise LevelError(f"Type {level['name']} exactly to confirm.")
    if clear_preview(conn, level_id)["open_class"]:
        raise LevelError(f"A class of {level['name']} is taking attendance. End it first, then delete "
                         "the roster.")
    return level


def clear(conn: sqlite3.Connection, level_id: int, account_id: int | None, terminal_note: str = "") -> dict:
    """Delete a level's students, courses, classes and attendance, and retire its device IDs.

    Called only once the terminal has been emptied of the level's block (services.clear_level). The
    level stays, with nothing on it.
    """
    level = _level(conn, level_id)
    counts = clear_preview(conn, level_id)
    s = _scope(conn, level)
    p, c, k = s["people"], s["courses"], s["classes"]
    start, end = level["id_block_start"], level["id_block_end"]
    highest = max(
        conn.execute("SELECT COALESCE(MAX(device_user_id), 0) FROM people WHERE device_user_id BETWEEN ? AND ?",
                     (start, end)).fetchone()[0],
        conn.execute(f"SELECT COALESCE(MAX(CAST(device_user_id AS INTEGER)), 0) FROM punches"
                     f" WHERE {_in_block('device_user_id')}", (start, end)).fetchone()[0])
    templates = _ids(conn, f"SELECT id FROM register_templates WHERE course_id IN ({_marks(c)})", tuple(c))

    with db.transaction(conn):
        run = conn.execute
        # The one place the database's refusal to delete a scan, a correction or a request is lifted,
        # for this transaction only. SQLite's DDL is transactional, so the guards come back on commit
        # and on any failure alike. The activity log keeps its guard and records what went.
        guards = conn.execute(
            f"SELECT name, sql FROM sqlite_master WHERE type = 'trigger' AND name IN ({_marks(DELETE_GUARDS)})",
            DELETE_GUARDS).fetchall()
        for guard in guards:
            run(f"DROP TRIGGER {guard['name']}")
        run(f"DELETE FROM correction_requests WHERE class_session_id IN ({_marks(k)})"
            f" OR person_id IN ({_marks(p)})", (*k, *p))
        run(f"DELETE FROM attendance_marks WHERE class_session_id IN ({_marks(k)})"
            f" OR person_id IN ({_marks(p)})", (*k, *p))
        run(f"DELETE FROM class_reopenings WHERE class_session_id IN ({_marks(k)})", tuple(k))
        run(f"DELETE FROM class_sessions WHERE id IN ({_marks(k)})", tuple(k))
        run(f"DELETE FROM excusals WHERE course_id IN ({_marks(c)}) OR person_id IN ({_marks(p)})", (*c, *p))
        run(f"DELETE FROM course_enrolments WHERE course_id IN ({_marks(c)})"
            f" OR person_id IN ({_marks(p)})", (*c, *p))
        run(f"DELETE FROM course_group_members WHERE course_id IN ({_marks(c)})"
            f" OR person_id IN ({_marks(p)})", (*c, *p))
        run(f"DELETE FROM course_groups WHERE course_id IN ({_marks(c)})", tuple(c))
        run(f"DELETE FROM register_weeks WHERE template_id IN ({_marks(templates)})", tuple(templates))
        run(f"DELETE FROM register_templates WHERE id IN ({_marks(templates)})", tuple(templates))
        run(f"DELETE FROM attendance_plans WHERE course_id IN ({_marks(c)})", tuple(c))
        run(f"DELETE FROM courses WHERE id IN ({_marks(c)})", tuple(c))
        run(f"DELETE FROM fingers WHERE person_id IN ({_marks(p)})", tuple(p))
        run(f"DELETE FROM enrollment_attempts WHERE person_id IN ({_marks(p)})", tuple(p))
        run(f"DELETE FROM level_memberships WHERE level_id = ? OR person_id IN ({_marks(p)})", (level_id, *p))
        run(f"UPDATE accounts SET person_id = NULL WHERE person_id IN ({_marks(p)})", tuple(p))
        run(f"DELETE FROM people WHERE id IN ({_marks(p)})", tuple(p))
        # Anybody left who came in through one of this level's imports belongs to another level
        # now; they keep their record and lose only the pointer to an import that is going.
        run("UPDATE people SET roster_import_id = NULL WHERE roster_import_id IN"
            " (SELECT id FROM roster_imports WHERE level_id = ?)", (level_id,))
        run("DELETE FROM roster_imports WHERE level_id = ?", (level_id,))
        run(f"DELETE FROM punches WHERE {_in_block('device_user_id')}", (start, end))
        for guard in guards:
            run(guard["sql"])
        if highest >= start:
            run("INSERT INTO retired_ids(first_id, last_id, level_name, cleared_at) VALUES (?, ?, ?, ?)"
                " ON CONFLICT(first_id) DO UPDATE SET last_id = max(last_id, excluded.last_id),"
                " level_name = excluded.level_name, cleared_at = excluded.cleared_at",
                (start, highest, level["name"], db.now()))
        db.audit(conn, account_id, "level.clear", "levels", level_id,
                 f"{level['name']}: {counts['students']} students, {counts['courses']} courses, "
                 f"{counts['classes']} classes, {counts['scans']} scans and {counts['corrections']} "
                 f"corrections deleted" + (f"; device IDs {start} to {highest} retired" if highest >= start else "")
                 + (f"; {terminal_note}" if terminal_note else ""))
    return {**{key: value for key, value in counts.items() if key != "open_class"},
            "retired": [start, highest] if highest >= start else None}


def retired_ranges(conn: sqlite3.Connection) -> list[tuple[int, int]]:
    return [(r["first_id"], r["last_id"]) for r in conn.execute("SELECT first_id, last_id FROM retired_ids")]


def highest_retired(conn: sqlite3.Connection, start: int, end: int) -> int:
    """The last retired ID inside a block, or 0, so a new student is numbered after it."""
    return conn.execute("SELECT COALESCE(MAX(last_id), 0) FROM retired_ids WHERE first_id BETWEEN ? AND ?",
                        (start, end)).fetchone()[0]


def is_retired(user_id: object, ranges: list[tuple[int, int]]) -> bool:
    """Whether a scan's user ID belongs to a cleared roster. Only whole numbers can."""
    text = str(user_id).strip()
    if not text.isdigit():
        return False
    number = int(text)
    return any(first <= number <= last for first, last in ranges)
