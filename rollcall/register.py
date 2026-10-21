"""Registers, excused absences and course summaries. Derived on read from scans, marks and excusals,
never stored, so a late USB import or a correction changes every report consistently.

For each student at each class, the first of these that applies decides:
  1. the lecturer's latest correction for that class (present or absent, with a note)
  2. a scan between the start time minus the "before" grace and the end time plus the "after" grace,
     or, for a class taken live, a scan between the moment it was started and the moment it was ended
  3. an excused absence covering that date, for that course or for every course
  4. otherwise absent

A scan beats an excusal: a student excused for a week who still came is present.

A class taken live is still open until the lecturer ends it. While it is open nobody is absent,
only not yet scanned, and it is counted in no total: an open class with 120 "absent" would drag every
percentage down for the length of a lecture (asked for on 2026-09-22).

Excused classes come out of that student's total by default (setting ``excused_rule`` = excluded),
the rule Canvas Roll Call uses. The alternative, ``present``, counts them as attended.
"""
from __future__ import annotations

import re
import sqlite3
from datetime import date, datetime, timedelta

from . import courses, db, groups, roles

_TIME = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
EXCUSAL_CATEGORIES = ("medical", "official", "bereavement", "other")


class RegisterError(ValueError):
    pass


# A class taken live and not yet ended. Every query that counts classes leaves these out.
OPEN = "(opened_at IS NOT NULL AND closed_at IS NULL)"


def is_open(s) -> bool:
    return bool(s["opened_at"]) and not s["closed_at"]


def current_academic_session(conn: sqlite3.Connection) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM academic_sessions WHERE is_current = 1").fetchone()
    if row is None:
        raise RegisterError("No current academic session is set. Create one first, for example 2026/2027.")
    return row


def _parse_day(value: str, label: str = "Date") -> date:
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise RegisterError(f"{label} must be YYYY-MM-DD.") from exc


def validate_session_fields(day: str, start: str, end: str) -> None:
    _parse_day(day)
    if not (_TIME.match(start or "") and _TIME.match(end or "")):
        raise RegisterError("Times must be HH:MM, 24 hour.")
    if end <= start:
        raise RegisterError("The class must end after it starts.")


# -- who and what an activity log row is about ----------------------------------------------------

# The log is what answers "who changed that, and when", and it answered with row numbers:
# "Corrected a student's attendance: session 5 person 26 present". Nobody can read that, and the
# numbers are this database's own, so they mean nothing beside a paper sheet either. The log is
# append-only, so only rows written from here on read properly (Checklist Design, Audit log:
# affected resource; 2026-09-21).

def _person_label(conn: sqlite3.Connection, person_id: int) -> str:
    row = conn.execute("SELECT matric_no, surname, other_names FROM people WHERE id = ?",
                       (person_id,)).fetchone()
    if row is None:
        return f"person {person_id}"
    name = f"{row['surname']} {row['other_names']}".strip()
    return f"{row['matric_no']} {name}".strip() if row["matric_no"] else name or f"person {person_id}"


def _class_label(conn: sqlite3.Connection, class_session_id: int) -> str:
    row = conn.execute("SELECT s.course_code, s.date, s.start_time, g.name AS group_name FROM class_sessions s"
                       " LEFT JOIN course_groups g ON g.id = s.group_id WHERE s.id = ?",
                       (class_session_id,)).fetchone()
    if row is None:
        return f"class {class_session_id}"
    group = f" {row['group_name']}" if row["group_name"] else ""
    return f"{row['course_code'] or 'a class on no course'}{group} {row['date']} {row['start_time']}"


# -- classes -------------------------------------------------------------------------------------

def create_session(conn: sqlite3.Connection, course_id: int, day: str, start: str, end: str, kind: str,
                   account_id: int | None, title: str | None = None, group_id: int | None = None) -> int:
    validate_session_fields(day, start, end)
    if kind not in ("device", "manual"):
        raise RegisterError("kind must be device or manual")
    course = courses.get_course(conn, course_id)
    group = _group_of_course(conn, course_id, group_id)
    with db.transaction(conn):
        cur = conn.execute(
            "INSERT INTO class_sessions(level_id, academic_session_id, course_id, course_code, title, date,"
            " start_time, end_time, kind, created_by, created_at, group_id)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (course["level_id"], course["academic_session_id"], course_id, course["code"], title, day, start, end,
             kind, account_id, db.now(), group_id),
        )
        db.audit(conn, account_id, "session.create", "class_sessions", cur.lastrowid,
                 f"{course['code']}{' ' + group['name'] if group else ''} {day} {start}-{end} {kind}")
    return int(cur.lastrowid)


def _group_of_course(conn: sqlite3.Connection, course_id: int, group_id: int | None) -> sqlite3.Row | None:
    if group_id is None:
        return None
    group = conn.execute("SELECT * FROM course_groups WHERE id = ?", (group_id,)).fetchone()
    if group is None or group["course_id"] != course_id:
        raise RegisterError("That group is not one of this course's.")
    return group


def scanned_in(conn: sqlite3.Connection, s) -> set[int]:
    """The people with a scan inside a class's window, by person id."""
    start, end = _window(conn, s)
    return {r[0] for r in conn.execute(
        "SELECT DISTINCT p.id FROM punches pu JOIN people p ON CAST(p.device_user_id AS TEXT) = pu.device_user_id"
        " WHERE pu.timestamp BETWEEN ? AND ?", (start, end))}


def assign_course(conn: sqlite3.Connection, class_session_id: int, course_id: int, account_id: int) -> None:
    """Put a class on a course: for a detected class the app could not place, or one placed wrongly.

    For a course with groups, the class goes to the group the scans in it point at, by the same rule a
    class found in the scans is given one (groups.infer_group), and to everybody otherwise.
    """
    s = conn.execute("SELECT * FROM class_sessions WHERE id = ?", (class_session_id,)).fetchone()
    if s is None:
        raise RegisterError("Unknown class.")
    course = courses.get_course(conn, course_id)
    if course["academic_session_id"] != s["academic_session_id"]:
        raise RegisterError("That course belongs to a different academic session.")
    group_id = groups.infer_group(conn, course_id, scanned_in(conn, s), s["date"])
    group = _group_of_course(conn, course_id, group_id)
    with db.transaction(conn):
        conn.execute("UPDATE class_sessions SET course_id = ?, course_code = ?, level_id = ?, group_id = ? WHERE id = ?",
                     (course_id, course["code"], course["level_id"], group_id, class_session_id))
        db.audit(conn, account_id, "session.assign_course", "class_sessions", class_session_id,
                 f"{s['course_code'] or 'no course'} {s['date']} {s['start_time']} to {course['code']}"
                 + (f" {group['name']}" if group else ""))


def unassigned_sessions(conn: sqlite3.Connection) -> list[dict]:
    """Classes Herewise could not place, each with the evidence for every course it might be.

    The evidence is the point of screen 6: how many of the people who actually scanned in this
    window are on each candidate course. Without it the chooser is a guess with four equal options,
    which is what the lecturer came to the screen to avoid.
    """
    rows = conn.execute(
        "SELECT s.*, l.name AS level_name FROM class_sessions s JOIN levels l ON l.id = s.level_id"
        " WHERE s.course_id IS NULL AND s.cancelled_at IS NULL ORDER BY s.date, s.start_time").fetchall()
    result = []
    for s in rows:
        opens, closes = _window(conn, s)
        scanners = [r["device_user_id"] for r in conn.execute(
            "SELECT DISTINCT device_user_id FROM punches WHERE timestamp BETWEEN ? AND ?",
            (opens, closes))]
        candidates = []
        people = None
        for course in conn.execute(
                "SELECT id, code, title FROM courses WHERE level_id = ? AND academic_session_id = ?"
                " ORDER BY code", (s["level_id"], s["academic_session_id"])):
            members = courses.members(conn, course["id"])
            ids = {str(m["device_user_id"]) for m in members}
            matched = sum(1 for scan in scanners if scan in ids)
            # For a course with groups, the group assigning it would give the class, so the choice
            # says "PCT 201, Group B" before it is made rather than after.
            group_name = None
            if groups.has_groups(conn, course["id"]):
                people = scanned_in(conn, s) if people is None else people
                group_id = groups.infer_group(conn, course["id"], people, s["date"])
                if group_id is not None:
                    group_name = groups.get_group(conn, group_id)["name"]
            candidates.append({
                "course_id": course["id"], "code": course["code"], "title": course["title"],
                "students": len(members), "scanners_on_it": matched,
                "percent": round(100 * matched / len(members)) if members else 0,
                "group": group_name,
            })
        # Best evidence first, so the one the figures point at is the one already selected.
        candidates.sort(key=lambda c: (-c["scanners_on_it"], c["code"]))
        result.append({**dict(s), "students": len(scanners),
                       "candidate_course_ids": [c["course_id"] for c in candidates],
                       "candidates": candidates})
    return result


def suggest_window(conn: sqlite3.Connection, course_id: int, day: str) -> dict:
    """The span of scans on a date by students on this course, to create a class from what happened."""
    _parse_day(day)
    row = conn.execute(
        "SELECT MIN(pu.timestamp) AS first, MAX(pu.timestamp) AS last, COUNT(DISTINCT pu.device_user_id) AS students"
        " FROM punches pu JOIN people p ON CAST(p.device_user_id AS TEXT) = pu.device_user_id"
        " JOIN course_enrolments e ON e.person_id = p.id AND e.removed_at IS NULL"
        " WHERE e.course_id = ? AND substr(pu.timestamp, 1, 10) = ?", (course_id, day)).fetchone()
    if not row["first"]:
        raise RegisterError("No scans from students on this course on that date.")
    first = datetime.fromisoformat(row["first"])
    last = datetime.fromisoformat(row["last"])
    end = last + timedelta(minutes=1)
    return {"date": day, "start_time": f"{first:%H:%M}",
            "end_time": f"{end:%H:%M}" if end.date() == first.date() else "23:59",
            "students_scanned": row["students"]}


def cancel_session(conn: sqlite3.Connection, class_session_id: int, note: str, account_id: int) -> None:
    if not (note or "").strip():
        raise RegisterError("Say why the class is cancelled.")
    stamp = db.now()
    with db.transaction(conn):
        # A class still taking attendance stops as well: a class that did not happen is not waiting
        # for anybody. It used to stay open, so the banner went on saying it was taking attendance and
        # the terminal could not start another class until somebody pressed End (2026-09-23).
        updated = conn.execute(
            "UPDATE class_sessions SET cancelled_at = ?, cancel_note = ?,"
            " closed_at = CASE WHEN opened_at IS NOT NULL AND closed_at IS NULL THEN ? ELSE closed_at END,"
            " end_time = CASE WHEN opened_at IS NOT NULL AND closed_at IS NULL THEN ? ELSE end_time END"
            " WHERE id = ? AND cancelled_at IS NULL",
            (stamp, note.strip(), stamp, stamp[11:16], class_session_id),
        ).rowcount
        if not updated:
            raise RegisterError("Unknown class, or it is already cancelled.")
        db.audit(conn, account_id, "session.cancel", "class_sessions", class_session_id, note.strip())


def restore_session(conn: sqlite3.Connection, class_session_id: int, note: str, account_id: int) -> None:
    """Undo a cancellation, so the class counts again.

    Known gap 15, decided 2026-09-21: the route is added rather than Restore being dropped from the
    screen. Cancelling is a judgement made in a hurry, often from a list of similar dates, and until
    now a wrong one could only be undone by editing SQLite. Nothing is lost either way: every scan
    and every correction on a cancelled class is kept, and both the cancel and the restore are in
    the audit log with whoever did them.
    """
    with db.transaction(conn):
        row = conn.execute("SELECT cancelled_at, cancel_note FROM class_sessions WHERE id = ?",
                           (class_session_id,)).fetchone()
        if row is None:
            raise RegisterError("Unknown class.")
        if row["cancelled_at"] is None:
            raise RegisterError("That class is not cancelled.")
        conn.execute("UPDATE class_sessions SET cancelled_at = NULL, cancel_note = NULL WHERE id = ?",
                     (class_session_id,))
        detail = f"was cancelled {row['cancelled_at']}: {row['cancel_note']}"
        if (note or "").strip():
            detail = f"{note.strip()} ({detail})"
        db.audit(conn, account_id, "session.restore", "class_sessions", class_session_id, detail)


# -- excused absences ----------------------------------------------------------------------------

def add_excusal(conn: sqlite3.Connection, person_id: int, date_from: str, date_to: str, category: str, note: str,
                account_id: int, course_id: int | None = None) -> int:
    start, end = _parse_day(date_from, "From date"), _parse_day(date_to, "To date")
    if end < start:
        raise RegisterError("The excused period must end on or after the day it starts.")
    if category not in EXCUSAL_CATEGORIES:
        raise RegisterError(f"Category must be one of: {', '.join(EXCUSAL_CATEGORIES)}.")
    if not (note or "").strip():
        raise RegisterError("Record the reason, for example the medical report reference.")
    person = conn.execute("SELECT * FROM people WHERE id = ? AND role = 'student'", (person_id,)).fetchone()
    if person is None:
        raise RegisterError("Unknown student.")
    roles.refuse_self(conn, account_id, person_id, "grant an excused absence")
    if course_id is not None:
        courses.get_course(conn, course_id)
    with db.transaction(conn):
        cur = conn.execute(
            "INSERT INTO excusals(person_id, course_id, date_from, date_to, category, note, account_id, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (person_id, course_id, start.isoformat(), end.isoformat(), category, note.strip(), account_id, db.now()))
        where = courses.get_course(conn, course_id)["code"] if course_id is not None else "every course"
        db.audit(conn, account_id, "excusal.create", "excusals", cur.lastrowid,
                 f"{_person_label(conn, person_id)}, {start} to {end}, {category}, {where}")
    return int(cur.lastrowid)


def revoke_excusal(conn: sqlite3.Connection, excusal_id: int, note: str, account_id: int) -> None:
    if not (note or "").strip():
        raise RegisterError("Say why the excused absence is being withdrawn.")
    with db.transaction(conn):
        updated = conn.execute(
            "UPDATE excusals SET revoked_at = ?, revoked_by = ?, revoke_note = ? WHERE id = ? AND revoked_at IS NULL",
            (db.now(), account_id, note.strip(), excusal_id)).rowcount
        if not updated:
            raise RegisterError("Unknown or already withdrawn excused absence.")
        db.audit(conn, account_id, "excusal.revoke", "excusals", excusal_id, note.strip())


def list_excusals(conn: sqlite3.Connection, person_id: int | None = None, course_id: int | None = None) -> list[dict]:
    query = ("SELECT x.*, a.display_name AS recorded_by, c.code AS course_code, p.matric_no, p.surname, p.other_names"
             " FROM excusals x JOIN accounts a ON a.id = x.account_id JOIN people p ON p.id = x.person_id"
             " LEFT JOIN courses c ON c.id = x.course_id WHERE 1 = 1")
    params: list = []
    if person_id is not None:
        query += " AND x.person_id = ?"
        params.append(person_id)
    if course_id is not None:
        query += " AND (x.course_id = ? OR x.course_id IS NULL)"
        params.append(course_id)
    return [dict(r) for r in conn.execute(query + " ORDER BY x.date_from DESC, x.id DESC", params)]


# -- registers -----------------------------------------------------------------------------------

# Fixed since 2026-09-23, when they left the Settings screen (db.SCHEMA_V12). They only matter for a
# class found in the scans read off the terminal later; a class taken live counts exactly the minutes
# it was open.
GRACE_BEFORE_MINUTES = 15
GRACE_AFTER_MINUTES = 30
# Fewer students than this scanning together is a test, not a class; a quiet stretch this long is
# where one class ended and the next began.
DETECT_MIN_STUDENTS = 5
DETECT_GAP_MINUTES = 90


def _window(conn: sqlite3.Connection, s: sqlite3.Row) -> tuple[str, str]:
    if s["opened_at"]:
        # Exactly the minutes the lecturer had it open, with no grace. The grace exists to guess
        # where a class began and ended from a timetable; a class started and ended by hand needs
        # no guess, and a grace would count a scan made for the class before it in the same room.
        return s["opened_at"], s["closed_at"] or db.now()
    before, after = GRACE_BEFORE_MINUTES, GRACE_AFTER_MINUTES
    start = datetime.fromisoformat(f"{s['date']}T{s['start_time']}:00") - timedelta(minutes=before)
    end = datetime.fromisoformat(f"{s['date']}T{s['end_time']}:00") + timedelta(minutes=after)
    return start.isoformat(), end.isoformat()


def window_for(conn: sqlite3.Connection, s: sqlite3.Row) -> tuple[str, str]:
    """A class's window with the grace either side, the same one the register counts scans in."""
    return _window(conn, s)


# What can never be deleted, and what is only counted. This is the same line the database itself
# draws: attendance_marks, correction_requests, punches and the audit log all carry triggers that
# refuse a DELETE outright, and nothing else does.
#
# A scan is one of those, and it is also never tied to a class row: attendance is worked out from
# the times, so a class is a window over the scans rather than a container of them. Deleting a
# class or a course therefore deletes no scan at all. Saying "9 scans against it, attendance that
# has been recorded is never deleted" implied that it would, and left somebody with a course they
# could not be rid of for a reason that was not true (reported 2026-09-22).
#
# So scans are stated, not a refusal. What refuses is a decision somebody signed: a correction, a
# correction request, an excused absence. Those are the register's word that a person decided
# something, and they outlive the structure around them.
SIGNED = ("corrections", "correction_requests", "excusals")


def blocking(held: dict[str, int]) -> dict[str, int]:
    """The part of what a thing holds that stops it being deleted: the signed decisions."""
    return {key: count for key, count in held.items() if key in SIGNED}


def holds(conn: sqlite3.Connection, class_session_id: int) -> dict[str, int]:
    """What a class has recorded against it, by kind: scans in its window, and signed decisions."""
    s = conn.execute("SELECT * FROM class_sessions WHERE id = ?", (class_session_id,)).fetchone()
    if s is None:
        raise RegisterError("Unknown class.")
    start, end = _window(conn, s)
    found: dict[str, int] = {}
    scans = conn.execute(
        "SELECT COUNT(*) FROM punches WHERE timestamp >= ? AND timestamp <= ?", (start, end)
    ).fetchone()[0]
    if scans:
        found["scans"] = scans
    for table, key in (("attendance_marks", "corrections"),
                       ("correction_requests", "correction_requests")):
        count = conn.execute(
            f"SELECT COUNT(*) FROM {table} WHERE class_session_id = ?", (class_session_id,)
        ).fetchone()[0]
        if count:
            found[key] = count
    return found


# What each key is called to somebody reading it, singular and plural. The keys themselves stay
# stable so a course can add up what its classes hold: naming them per class first put "1
# correction" and "2 corrections" in two different buckets on a real screen (2026-09-22).
HOLD_NAMES = {
    "scans": ("scan", "scans"),
    "corrections": ("correction", "corrections"),
    "correction_requests": ("correction request", "correction requests"),
    "excusals": ("excused absence", "excused absences"),
}


def name_holds(held: dict[str, int]) -> dict[str, int]:
    """The same counts, keyed by the words a screen writes, each right for its own count."""
    named: dict[str, int] = {}
    for key, count in sorted(held.items()):
        one, many = HOLD_NAMES.get(key, (key, key))
        named[one if count == 1 else many] = count
    return named


def say_holds(held: dict[str, int]) -> str:
    """"221 scans, 1 correction request", for a sentence explaining a refusal."""
    return ", ".join(f"{count} {name}" for name, count in name_holds(held).items())


def delete_session(conn: sqlite3.Connection, class_session_id: int, account_id: int | None) -> dict:
    """Delete a class that recorded nothing. Refuses one that did, naming what it holds."""
    s = conn.execute("SELECT * FROM class_sessions WHERE id = ?", (class_session_id,)).fetchone()
    if s is None:
        raise RegisterError("Unknown class.")
    held = holds(conn, class_session_id)
    stops = blocking(held)
    if stops:
        raise RegisterError(
            f"This class has {say_holds(stops)} against it, so it stays. A correction is somebody's "
            "signed decision and the register keeps it for good. Cancelling the class takes it out "
            "of every total and leaves that record where it is, which is what a register is for.")
    when = f"{s['date']} {s['start_time']} to {s['end_time']}"
    with db.transaction(conn):
        conn.execute("DELETE FROM class_sessions WHERE id = ?", (class_session_id,))
        db.audit(conn, account_id, "class.delete", "class_sessions", class_session_id,
                 f"{s['course_code'] or 'a class'} on {when}, which had nothing recorded against it")
    return {"deleted": when}


def session_register(conn: sqlite3.Connection, class_session_id: int) -> dict:
    s = conn.execute(
        "SELECT cs.*, l.name AS level_name, c.code AS course_code, g.name AS group_name FROM class_sessions cs"
        " JOIN levels l ON l.id = cs.level_id LEFT JOIN courses c ON c.id = cs.course_id"
        " LEFT JOIN course_groups g ON g.id = cs.group_id WHERE cs.id = ?",
        (class_session_id,),
    ).fetchone()
    if s is None:
        raise RegisterError("Unknown class.")
    window_start, window_end = _window(conn, s)
    # Everybody on the course, or only the class's group on the day it was held (groups.py).
    members = groups.class_members(conn, s)
    still_open = is_open(s)

    scans = {
        r["device_user_id"]: r for r in conn.execute(
            "SELECT device_user_id, MIN(timestamp) AS first_scan, MAX(timestamp) AS last_scan, COUNT(*) AS scans"
            " FROM punches WHERE timestamp BETWEEN ? AND ? GROUP BY device_user_id",
            (window_start, window_end),
        )
    }
    marks: dict[int, sqlite3.Row] = {}
    for m in conn.execute(
        "SELECT am.*, a.display_name AS marked_by FROM attendance_marks am JOIN accounts a ON a.id = am.account_id"
        " WHERE am.class_session_id = ? ORDER BY am.id", (class_session_id,)
    ):
        marks[m["person_id"]] = m
    excused: dict[int, sqlite3.Row] = {}
    for x in conn.execute(
        "SELECT * FROM excusals WHERE revoked_at IS NULL AND date_from <= ? AND date_to >= ?"
        " AND (course_id IS NULL OR course_id = ?) ORDER BY id", (s["date"], s["date"], s["course_id"])
    ):
        excused[x["person_id"]] = x

    students = []
    for p in members:
        scan = scans.get(str(p["device_user_id"]))
        mark = marks.get(p["id"])
        excusal = excused.get(p["id"])
        if mark is not None:
            present = mark["status"] == "present"
            status = "marked_present" if present else "marked_absent"
        elif scan is not None:
            present, status = True, "present"
        elif excusal is not None:
            present, status = False, "excused"
        elif still_open:
            # Absent is decided when the lecturer ends the class, not before.
            present, status = False, "waiting"
        else:
            present, status = False, "absent"
        students.append({
            "person_id": p["id"],
            "device_user_id": p["device_user_id"],
            "matric_no": p["matric_no"],
            "surname": p["surname"],
            "other_names": p["other_names"],
            "kind": p["kind"],
            "level": p["level_number"],
            "present": present,
            "excused": status == "excused",
            "status": status,
            "first_scan": scan["first_scan"] if scan else None,
            "scans": scan["scans"] if scan else 0,
            "mark": ({"status": mark["status"], "note": mark["note"], "by": mark["marked_by"],
                      "at": mark["created_at"]} if mark else None),
            "excusal": ({"id": excusal["id"], "category": excusal["category"], "note": excusal["note"]}
                        if excusal is not None and status == "excused" else None),
        })

    # A class for one group: the course's other students who scanned in it anyway, a student at the
    # wrong group's practical. Listed, never counted: they are expected at their own group's class,
    # and a correction there is what counts it. Without the list the scan was simply invisible.
    others = []
    if s["group_id"] is not None and s["course_id"]:
        expected = {p["id"] for p in members}
        where = groups.groups_on(conn, s["course_id"], s["date"])
        for p in courses.members(conn, s["course_id"]):
            scan = scans.get(str(p["device_user_id"]))
            if p["id"] in expected or scan is None:
                continue
            others.append({"person_id": p["id"], "device_user_id": p["device_user_id"],
                           "matric_no": p["matric_no"], "surname": p["surname"],
                           "other_names": p["other_names"], "first_scan": scan["first_scan"],
                           "group": where[p["id"]]["name"] if p["id"] in where else None})

    total = len(students)
    present_count = sum(1 for x in students if x["present"])
    excused_count = sum(1 for x in students if x["excused"])
    waiting_count = sum(1 for x in students if x["status"] == "waiting")
    counted = total - excused_count
    return {
        "session": dict(s),
        "group": {"id": s["group_id"], "name": s["group_name"]} if s["group_id"] is not None else None,
        "others": others,
        "open": still_open,
        "unassigned": s["course_id"] is None,
        "window": {"from": window_start, "to": window_end},
        "totals": {"students": total, "present": present_count, "excused": excused_count,
                   "waiting": waiting_count,
                   "absent": total - present_count - excused_count - waiting_count,
                   "percent": round(100 * present_count / counted) if counted else 0},
        "students": students,
    }


def _check_mark(conn: sqlite3.Connection, class_session_id: int, person_id: int, status: str,
                note: str, account_id: int) -> None:
    if status not in ("present", "absent"):
        raise RegisterError("status must be present or absent. Use an excused absence for a valid reason.")
    if not (note or "").strip():
        raise RegisterError("A note is required for every correction.")
    s = conn.execute("SELECT * FROM class_sessions WHERE id = ?", (class_session_id,)).fetchone()
    if s is None:
        raise RegisterError("Unknown class.")
    if s["course_id"] is None:
        raise RegisterError("Put this class on a course first.")
    _check_expected(conn, s, person_id)
    roles.refuse_self(conn, account_id, person_id, "correct attendance")


def _check_expected(conn: sqlite3.Connection, s: sqlite3.Row, person_id: int) -> None:
    """Refuse a mark for somebody the class does not expect: off the course, or in another group."""
    if not courses.is_member(conn, s["course_id"], person_id):
        raise RegisterError("That student is not on this course.")
    if s["group_id"] is not None and person_id not in {p["id"] for p in groups.class_members(conn, s)}:
        group = conn.execute("SELECT name FROM course_groups WHERE id = ?", (s["group_id"],)).fetchone()
        raise RegisterError(
            f"That student was not in {group['name']} on {s['date']}, so this class is not theirs. Correct "
            "their own group's class instead, with a note that they came to this one.")


def _write_mark(conn: sqlite3.Connection, class_session_id: int, person_id: int, status: str,
                note: str, account_id: int) -> int:
    """Insert one correction. A transaction must already be open, so that approving a request and
    recording its decision either both happen or neither does."""
    cur = conn.execute(
        "INSERT INTO attendance_marks(class_session_id, person_id, status, note, account_id, created_at)"
        " VALUES (?, ?, ?, ?, ?, ?)",
        (class_session_id, person_id, status, note.strip(), account_id, db.now()),
    )
    db.audit(conn, account_id, "attendance.mark", "attendance_marks", cur.lastrowid,
             f"{_person_label(conn, person_id)} marked {status} in "
             f"{_class_label(conn, class_session_id)}: {note.strip()}")
    return int(cur.lastrowid)


def add_mark(conn: sqlite3.Connection, class_session_id: int, person_id: int, status: str, note: str,
             account_id: int) -> int:
    _check_mark(conn, class_session_id, person_id, status, note, account_id)
    with db.transaction(conn):
        return _write_mark(conn, class_session_id, person_id, status, note, account_id)


# -- correction requests -------------------------------------------------------------------------
#
# Someone who runs a class but may not correct it asks here, and whoever holds `register.approve`
# decides. The request is evidence in its own right: it is append-only, it records who asked and who
# decided, and approving it produces an ordinary mark signed by the approver, not by the requester.

def request_correction(conn: sqlite3.Connection, class_session_id: int, person_id: int, status: str,
                       note: str, account_id: int) -> int:
    if status not in ("present", "absent"):
        raise RegisterError("status must be present or absent. Use an excused absence for a valid reason.")
    if not (note or "").strip():
        raise RegisterError("Say why the correction is needed.")
    s = conn.execute("SELECT * FROM class_sessions WHERE id = ?", (class_session_id,)).fetchone()
    if s is None:
        raise RegisterError("Unknown class.")
    if s["course_id"] is None:
        raise RegisterError("Put this class on a course first.")
    _check_expected(conn, s, person_id)
    roles.refuse_self(conn, account_id, person_id, "ask for a correction")
    open_already = conn.execute(
        "SELECT id FROM correction_requests WHERE class_session_id = ? AND person_id = ? AND state = 'pending'",
        (class_session_id, person_id)).fetchone()
    if open_already is not None:
        raise RegisterError("There is already a request waiting for that student in this class.")
    with db.transaction(conn):
        cur = conn.execute(
            "INSERT INTO correction_requests(class_session_id, person_id, status, note, requested_by,"
            " requested_at) VALUES (?, ?, ?, ?, ?, ?)",
            (class_session_id, person_id, status, note.strip(), account_id, db.now()))
        db.audit(conn, account_id, "correction.request", "correction_requests", cur.lastrowid,
                 f"{_person_label(conn, person_id)} to be marked {status} in "
                 f"{_class_label(conn, class_session_id)}: {note.strip()}")
    return int(cur.lastrowid)


def list_requests(conn: sqlite3.Connection, state: str | None = None, course_id: int | None = None,
                  requested_by: int | None = None) -> list[dict]:
    query = ("SELECT q.*, p.matric_no, p.surname, p.other_names, cs.date, cs.start_time, cs.end_time,"
             " cs.course_id, cs.cancelled_at, c.code AS course_code, c.title AS course_title,"
             " ra.display_name AS requested_by_name, rr.name AS requested_by_role,"
             " da.display_name AS decided_by_name"
             " FROM correction_requests q"
             " JOIN people p ON p.id = q.person_id"
             " JOIN class_sessions cs ON cs.id = q.class_session_id"
             " LEFT JOIN courses c ON c.id = cs.course_id"
             " JOIN accounts ra ON ra.id = q.requested_by"
             " LEFT JOIN roles rr ON rr.id = ra.role_id"
             " LEFT JOIN accounts da ON da.id = q.decided_by WHERE 1 = 1")
    params: list = []
    if state is not None:
        query += " AND q.state = ?"
        params.append(state)
    if course_id is not None:
        query += " AND cs.course_id = ?"
        params.append(course_id)
    if requested_by is not None:
        query += " AND q.requested_by = ?"
        params.append(requested_by)
    rows = [dict(r) for r in conn.execute(query + " ORDER BY q.state = 'pending' DESC, q.id DESC", params)]

    # What the box says now, so the screen can draw "absent to present" rather than only the ask.
    # Read from session_register, cached per class, rather than worked out again here: two answers
    # to "what is this box" would eventually disagree, and this is the one an approver acts on.
    cache: dict[int, dict] = {}
    for row in rows:
        session_id = row["class_session_id"]
        if session_id not in cache:
            cache[session_id] = {s["person_id"]: s["status"]
                                 for s in session_register(conn, session_id)["students"]}
        row["current_status"] = cache[session_id].get(row["person_id"], "absent")
    return rows


def decide_request(conn: sqlite3.Connection, request_id: int, approve: bool, note: str,
                   account_id: int) -> dict:
    row = conn.execute("SELECT * FROM correction_requests WHERE id = ?", (request_id,)).fetchone()
    if row is None:
        raise RegisterError("Unknown correction request.")
    if row["state"] != "pending":
        raise RegisterError(f"That request was already {row['state']}.")
    if row["requested_by"] == account_id:
        raise RegisterError("You cannot decide your own request. Ask someone else.")
    if not approve and not (note or "").strip():
        raise RegisterError("Say why the request is being rejected.")
    applied_note = f"{row['note'].strip()} (requested, approved)"
    if approve:
        # Checked before the transaction opens, and it refuses a decider correcting their own record.
        _check_mark(conn, row["class_session_id"], row["person_id"], row["status"], applied_note, account_id)
    mark_id = None
    with db.transaction(conn):
        if approve:
            mark_id = _write_mark(conn, row["class_session_id"], row["person_id"], row["status"],
                                  applied_note, account_id)
        conn.execute(
            "UPDATE correction_requests SET state = ?, decided_by = ?, decided_at = ?, decision_note = ?,"
            " mark_id = ? WHERE id = ?",
            ("approved" if approve else "rejected", account_id, db.now(), (note or "").strip() or None,
             mark_id, request_id))
        db.audit(conn, account_id, "correction.decide", "correction_requests", request_id,
                 f"{'approved' if approve else 'rejected'}, {_person_label(conn, row['person_id'])} in "
                 f"{_class_label(conn, row['class_session_id'])}"
                 + (f": {note.strip()}" if (note or "").strip() else ""))
    return {"request_id": request_id, "state": "approved" if approve else "rejected", "mark_id": mark_id}


# -- plans and summaries -------------------------------------------------------------------------

PLAN_LIMITS = {"weeks": (1, 52), "classes_per_week": (1, 20), "total_classes": (1, 1000),
               "threshold_percent": (1, 100)}


def _check_plan_values(values: dict) -> None:
    for key, value in values.items():
        if value is None:
            continue
        low, high = PLAN_LIMITS[key]
        if not isinstance(value, int) or not low <= value <= high:
            raise RegisterError(f"{key.replace('_', ' ')} must be a whole number from {low} to {high}.")


def get_plan(conn: sqlite3.Connection, course_id: int) -> dict:
    row = conn.execute("SELECT * FROM attendance_plans WHERE course_id = ?", (course_id,)).fetchone()
    saved = {k: (row[k] if row else None) for k in PLAN_LIMITS}
    return {"saved": saved, "updated_at": row["updated_at"] if row else None}


def save_plan(conn: sqlite3.Connection, course_id: int, account_id: int, weeks: int | None,
              classes_per_week: int | None, total_classes: int | None, threshold_percent: int | None) -> dict:
    values = {"weeks": weeks, "classes_per_week": classes_per_week, "total_classes": total_classes,
              "threshold_percent": threshold_percent}
    _check_plan_values(values)
    if (weeks is None) != (classes_per_week is None):
        raise RegisterError("Give both the number of weeks and classes per week, or neither.")
    courses.get_course(conn, course_id)
    with db.transaction(conn):
        conn.execute(
            "INSERT INTO attendance_plans(course_id, weeks, classes_per_week, total_classes, threshold_percent,"
            " account_id, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)"
            " ON CONFLICT(course_id) DO UPDATE SET weeks = excluded.weeks,"
            " classes_per_week = excluded.classes_per_week, total_classes = excluded.total_classes,"
            " threshold_percent = excluded.threshold_percent, account_id = excluded.account_id,"
            " updated_at = excluded.updated_at",
            (course_id, weeks, classes_per_week, total_classes, threshold_percent, account_id, db.now()),
        )
        db.audit(conn, account_id, "attendance_plan.save", "courses", course_id, str(values))
    return get_plan(conn, course_id)


def _effective_plan(conn: sqlite3.Connection, course_id: int, overrides: dict) -> dict:
    """Overrides (a what-if from the screen) beat the saved plan, which beats the template and settings."""
    _check_plan_values(overrides)
    saved = get_plan(conn, course_id)["saved"]
    pick = {k: overrides[k] if overrides.get(k) is not None else saved[k] for k in PLAN_LIMITS}

    if pick["threshold_percent"] is not None:
        threshold, threshold_source = pick["threshold_percent"], "plan"
    else:
        threshold, threshold_source = int(db.get_setting(conn, "attendance_threshold_percent")), "setting"

    if pick["total_classes"] is not None:
        planned, planned_source = pick["total_classes"], "total_classes"
    elif pick["weeks"] is not None and pick["classes_per_week"] is not None:
        planned, planned_source = pick["weeks"] * pick["classes_per_week"], "weeks_x_classes"
    else:
        # No explicit figure: the attendance sheet template's class boxes are the plan.
        row = conn.execute(
            "SELECT SUM(w.classes) AS total FROM register_templates t JOIN register_weeks w ON w.template_id = t.id"
            " WHERE t.course_id = ?", (course_id,)).fetchone()
        if row and row["total"]:
            planned, planned_source = int(row["total"]), "template"
        else:
            planned, planned_source = None, None
    return {**pick, "threshold_percent": threshold, "threshold_source": threshold_source,
            "planned_classes": planned, "planned_source": planned_source,
            "excused_rule": db.get_setting(conn, "excused_rule"),
            "uses_overrides": any(v is not None for v in overrides.values())}


def _classes_needed(threshold: int, total: int) -> int:
    """Smallest whole number of classes that reaches threshold percent of total, with no float rounding."""
    return -(-threshold * total // 100)


def course_summary(conn: sqlite3.Connection, course_id: int, date_from: str | None = None,
                   date_to: str | None = None, threshold_percent: int | None = None, weeks: int | None = None,
                   classes_per_week: int | None = None, total_classes: int | None = None) -> dict:
    """Attendance percentage for every student on the course, against the lecturer's pass mark.

    With a planned number of classes it also says how many more classes each student needs, how many
    they can still miss, and who can no longer reach it. Excused classes follow ``excused_rule``.
    """
    if (weeks is None) != (classes_per_week is None):
        raise RegisterError("Give both the number of weeks and classes per week, or neither.")
    course = courses.get_course(conn, course_id)
    plan = _effective_plan(conn, course_id, {
        "weeks": weeks, "classes_per_week": classes_per_week, "total_classes": total_classes,
        "threshold_percent": threshold_percent})
    threshold = plan["threshold_percent"]
    exclude_excused = plan["excused_rule"] != "present"

    query = f"SELECT id FROM class_sessions WHERE course_id = ? AND cancelled_at IS NULL AND NOT {OPEN}"
    params: list = [course_id]
    if date_from:
        query += " AND date >= ?"
        params.append(date_from)
    if date_to:
        query += " AND date <= ?"
        params.append(date_to)
    session_ids = [r["id"] for r in conn.execute(query + " ORDER BY date, start_time", params)]

    # Each student is counted against the classes they were expected at: every class for a course
    # without groups, and for one with groups the classes for everybody and their own group's
    # (groups.class_members). So "held" is per student, and a class is held for whoever is on its
    # register. For a course without groups it is the same number on every row, as it always was.
    grouped = groups.has_groups(conn, course_id)
    group_now = groups.groups_on(conn, course_id) if grouped else {}
    per_student: dict[int, dict] = {}
    for p in courses.members(conn, course_id):
        per_student[p["id"]] = {"person_id": p["id"], "device_user_id": p["device_user_id"],
                                "matric_no": p["matric_no"], "surname": p["surname"],
                                "other_names": p["other_names"], "kind": p["kind"], "level": p["level_number"],
                                "group": group_now[p["id"]]["name"] if p["id"] in group_now else None,
                                "attended": 0, "excused": 0, "held": 0}
    for sid in session_ids:
        for st in session_register(conn, sid)["students"]:
            row = per_student.get(st["person_id"])
            if row is None:
                continue
            row["held"] += 1
            row["attended"] += 1 if st["present"] else 0
            row["excused"] += 1 if st["excused"] else 0
    # The course's own figure: the classes a student has been expected at, at most. For a course
    # with groups, a count of every class would add four groups' practicals together and set it
    # against a plan written for one student.
    held = (max((r["held"] for r in per_student.values()), default=len(session_ids)) if grouped
            else len(session_ids))

    planned = plan["planned_classes"]
    warnings = []
    if planned is not None and held > planned:
        warnings.append(f"{held} classes have been held, more than the {planned} planned. "
                        f"Percentages use {held} until the plan is updated.")
    total_all = max(planned, held) if planned is not None else None
    remaining = (total_all - held) if total_all is not None else None

    students = list(per_student.values())
    for row in students:
        attended, excused = row["attended"], row["excused"]
        mine = row["held"]
        mine_total = max(planned, mine) if planned is not None else None
        mine_remaining = (mine_total - mine) if mine_total is not None else None
        credit = attended if exclude_excused else attended + excused
        counted = mine - excused if exclude_excused else mine
        row["counted"] = counted
        # The student's own classes still to come, for "needs 3 more of the 5 left": on a course with
        # groups a student whose group has had fewer classes has more left than the course figure.
        row["classes_remaining"] = mine_remaining
        row["missed"] = mine - attended - excused
        row["percent"] = round(100 * credit / counted, 1) if counted else 0.0
        if mine and counted == 0:
            row.update(percent_of_plan=None, classes_needed=None, more_needed=None, can_still_miss=None,
                       best_possible_percent=None, status="all_excused")
        elif mine_total is None:
            row.update(percent_of_plan=None, classes_needed=None, more_needed=None, can_still_miss=None,
                       best_possible_percent=None)
            row["status"] = "no_classes_yet" if not mine else ("on_track" if row["percent"] >= threshold else "below")
        else:
            total_s = mine_total - excused if exclude_excused else mine_total
            required = _classes_needed(threshold, total_s) if total_s > 0 else 0
            more = max(required - credit, 0)
            reachable = credit + mine_remaining >= required
            row["percent_of_plan"] = round(100 * credit / total_s, 1) if total_s else 0.0
            row["classes_needed"] = required
            row["more_needed"] = more
            row["can_still_miss"] = mine_remaining - more if reachable else 0
            row["best_possible_percent"] = round(100 * (credit + mine_remaining) / total_s, 1) if total_s else 0.0
            if mine and credit >= required:
                row["status"] = "met"
            elif not reachable:
                row["status"] = "cannot_reach"
            elif mine and row["percent"] < threshold:
                row["status"] = "at_risk"
            else:
                row["status"] = "on_track"
        row["below_threshold"] = row["status"] in ("below", "at_risk", "cannot_reach")

    counts: dict[str, int] = {}
    for row in students:
        counts[row["status"]] = counts.get(row["status"], 0) + 1
    scored = [r["percent"] for r in students if r["counted"]]
    return {
        "course": {"id": course["id"], "code": course["code"], "title": course["title"],
                   "level": course["level_name"], "academic_session": course["academic_session"]},
        "course_id": course_id,
        "date_from": date_from,
        "date_to": date_to,
        "plan": plan,
        "sessions_held": held,
        "grouped": grouped,
        "planned_classes": planned,
        "classes_remaining": remaining,
        "classes_needed_to_pass": _classes_needed(threshold, total_all) if total_all else None,
        "threshold_percent": threshold,
        "below_threshold": sum(1 for r in students if r["below_threshold"]),
        "status_counts": counts,
        "class_average_percent": round(sum(scored) / len(scored), 1) if scored and held else 0.0,
        "warnings": warnings,
        "students": students,
        "generated_at": db.now(),
    }


# -- detecting classes from scans ----------------------------------------------------------------

def detect_sessions(conn: sqlite3.Connection, account_id: int | None = None) -> list[dict]:
    """Create a class wherever enough students of one level scanned close together, so ticks appear
    on the sheet without the lecturer creating each class.

    A burst is scans from students of one level on one day with no gap longer than
    ``DETECT_GAP_MINUTES``, with at least ``DETECT_MIN_STUDENTS`` different students.
    Bursts are handled largest first. A burst is skipped when it overlaps a class (including a
    cancelled one) whose course has most of the burst's students on it, so carry-over students scanning
    in someone else's class do not create a class of their own, and a cancel is never undone.

    A new class goes to the course that has the most of the burst's students, if at least half of them
    are on it and no other course ties. Otherwise it is created without a course for the lecturer to
    place: two courses for the same level share the same students, and only a timetable could tell them
    apart.
    """
    academic = conn.execute("SELECT * FROM academic_sessions WHERE is_current = 1").fetchone()
    if academic is None:
        return []
    min_students = DETECT_MIN_STUDENTS
    gap = timedelta(minutes=DETECT_GAP_MINUTES)

    scans = conn.execute(
        "SELECT m.level_id, p.id AS person_id, pu.device_user_id, pu.timestamp FROM punches pu"
        " JOIN people p ON CAST(p.device_user_id AS TEXT) = pu.device_user_id AND p.role = 'student'"
        " JOIN level_memberships m ON m.person_id = p.id AND m.academic_session_id = ?"
        " ORDER BY m.level_id, pu.timestamp", (academic["id"],)).fetchall()

    bursts: list[tuple[int, list[sqlite3.Row]]] = []
    for scan in scans:
        ts = datetime.fromisoformat(scan["timestamp"])
        if bursts:
            level_id, rows = bursts[-1]
            last = datetime.fromisoformat(rows[-1]["timestamp"])
            if level_id == scan["level_id"] and ts.date() == last.date() and ts - last <= gap:
                rows.append(scan)
                continue
        bursts.append((scan["level_id"], [scan]))
    bursts = [(lvl, rows) for lvl, rows in bursts if len({r["person_id"] for r in rows}) >= min_students]
    bursts.sort(key=lambda b: len({r["person_id"] for r in b[1]}), reverse=True)

    enrolled: dict[int, set[int]] = {}
    for e in conn.execute("SELECT e.course_id, e.person_id FROM course_enrolments e JOIN courses c ON c.id = e.course_id"
                          " WHERE e.removed_at IS NULL AND c.academic_session_id = ?", (academic["id"],)):
        enrolled.setdefault(e["course_id"], set()).add(e["person_id"])

    created = []
    for level_id, rows in bursts:
        people = {r["person_id"] for r in rows}
        first = datetime.fromisoformat(rows[0]["timestamp"])
        last = datetime.fromisoformat(rows[-1]["timestamp"])
        day = first.date().isoformat()

        covered = False
        # The day before as well: a class that runs over midnight is dated the day it began, and
        # its scans after midnight the day after (found at 00:15 on 2026-09-23, by a test that
        # started a class 70 minutes earlier).
        yesterday = (first.date() - timedelta(days=1)).isoformat()
        for s in conn.execute("SELECT * FROM class_sessions WHERE date BETWEEN ? AND ?"
                              " AND academic_session_id = ?", (yesterday, day, academic["id"])):
            # The class's own window, which for a class taken live runs to now while it is open. A
            # window rebuilt here from the times would end half an hour after an open class began,
            # and a pull during a long lecture would make a second class of its later scans.
            start, end = (datetime.fromisoformat(x) for x in _window(conn, s))
            if not (start <= last and first <= end):
                continue
            if s["course_id"] is None:
                on_it = s["level_id"] == level_id
            elif s["group_id"] is not None:
                # A group's class covers the scans of its own group, not the next group's practical
                # held straight after it in the same room.
                expected = {p["id"] for p in groups.class_members(conn, s)}
                on_it = len(people & expected) * 2 >= len(people)
            else:
                on_it = len(people & enrolled.get(s["course_id"], set())) * 2 >= len(people)
            if on_it:
                covered = True
                break
        if covered:
            continue

        ranked = sorted(((len(people & members), cid) for cid, members in enrolled.items()), reverse=True)
        course_id = None
        if ranked and ranked[0][0] * 2 >= len(people) and (len(ranked) == 1 or ranked[1][0] < ranked[0][0]):
            course_id = ranked[0][1]
        home_level = level_id
        course_code = None
        group_id = None
        if course_id is not None:
            course = conn.execute("SELECT * FROM courses WHERE id = ?", (course_id,)).fetchone()
            home_level, course_code = course["level_id"], course["code"]
            group_id = groups.infer_group(conn, course_id, people, day)

        end_time = last + timedelta(minutes=1)
        start_text = f"{first:%H:%M}"
        end_text = f"{end_time:%H:%M}" if end_time.date() == first.date() else "23:59"
        if end_text <= start_text:
            end_text = "23:59"
        title = "Detected from scans" if course_id else "Detected from scans: choose the course"
        with db.transaction(conn):
            cur = conn.execute(
                "INSERT INTO class_sessions(level_id, academic_session_id, course_id, course_code, title, date,"
                " start_time, end_time, kind, created_by, created_at, group_id)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'device', NULL, ?, ?)",
                (home_level, academic["id"], course_id, course_code, title, day, start_text, end_text, db.now(),
                 group_id),
            )
            db.audit(conn, account_id, "session.detect", "class_sessions", cur.lastrowid,
                     f"{day} {start_text}-{end_text}, {len(people)} students, course={course_id}"
                     + (f", group={group_id}" if group_id is not None else ""))
        created.append({"id": cur.lastrowid, "course_id": course_id, "level_id": home_level, "date": day,
                        "start_time": start_text, "end_time": end_text, "students": len(people),
                        "needs_course": course_id is None, "group_id": group_id})
    return created


# -- the headline figures a course card shows ----------------------------------------------------

def course_figures(conn: sqlite3.Connection, course_id: int) -> dict:
    """The four numbers on a course card (screen 10) and in a course header (screen 11).

    Taken from ``course_summary`` rather than from a cheaper aggregate on purpose: two averages
    worked out two different ways would disagree on two screens, and the one on the card is the one
    a lecturer would quote.
    """
    summary = course_summary(conn, course_id)
    last = conn.execute(
        "SELECT id, date, start_time FROM class_sessions WHERE course_id = ? AND cancelled_at IS NULL"
        f" AND NOT {OPEN} AND date <= ? ORDER BY date DESC, start_time DESC LIMIT 1",
        (course_id, db.now()[:10])).fetchone()
    last_class = None
    if last is not None:
        totals = session_register(conn, last["id"])["totals"]
        last_class = {"session_id": last["id"], "date": last["date"], "start_time": last["start_time"],
                      "present": totals["present"], "registered": totals["students"]}
    cancelled = conn.execute(
        "SELECT COUNT(*) FROM class_sessions WHERE course_id = ? AND cancelled_at IS NOT NULL",
        (course_id,)).fetchone()[0]
    unassigned = conn.execute(
        "SELECT COUNT(*) FROM class_sessions s JOIN levels l ON l.id = s.level_id"
        " WHERE s.course_id IS NULL AND s.cancelled_at IS NULL AND l.id ="
        " (SELECT level_id FROM courses WHERE id = ?)", (course_id,)).fetchone()[0]
    # Every class held on the course, whoever it was for: what the Classes tab lists. For a course
    # with groups it is more than classes_held, which is the most one student was expected at.
    taken = conn.execute(
        f"SELECT COUNT(*) FROM class_sessions WHERE course_id = ? AND cancelled_at IS NULL AND NOT {OPEN}",
        (course_id,)).fetchone()[0]
    return {
        "classes_held": summary["sessions_held"],
        "classes_taken": taken,
        "planned_classes": summary["planned_classes"],
        "cancelled_classes": cancelled,
        "unassigned_classes": unassigned,
        "average_percent": summary["class_average_percent"],
        "threshold_percent": summary["threshold_percent"],
        "below_threshold": summary["below_threshold"],
        "cannot_reach": summary["status_counts"].get("cannot_reach", 0),
        "can_still_reach": summary["below_threshold"] - summary["status_counts"].get("cannot_reach", 0),
        "last_class": last_class,
        "warnings": summary["warnings"],
    }


# -- one box on the sheet, for the correction drawer ---------------------------------------------

def cell(conn: sqlite3.Connection, class_session_id: int, person_id: int) -> dict:
    """Everything the correction drawer shows for one student in one class (screen 8).

    One call rather than four, and the history is every mark ever written for this box, oldest
    first, because attendance_marks is append-only and the drawer shows what happened, not only
    what is true now.
    """
    s = conn.execute(
        "SELECT cs.*, c.code AS course_code, c.title AS course_title FROM class_sessions cs"
        " LEFT JOIN courses c ON c.id = cs.course_id WHERE cs.id = ?", (class_session_id,)).fetchone()
    if s is None:
        raise RegisterError("Unknown class.")
    entry = next((x for x in session_register(conn, class_session_id)["students"]
                  if x["person_id"] == person_id), None)
    if entry is None:
        raise RegisterError("That student is not on this course.")

    history = [
        {"status": m["status"], "note": m["note"], "by": m["display_name"], "at": m["created_at"]}
        for m in conn.execute(
            "SELECT am.*, a.display_name FROM attendance_marks am"
            " JOIN accounts a ON a.id = am.account_id"
            " WHERE am.class_session_id = ? AND am.person_id = ? ORDER BY am.id",
            (class_session_id, person_id))
    ]
    pending = [
        {"id": r["id"], "status": r["status"], "note": r["note"], "by": r["requested_by_name"],
         "at": r["requested_at"]}
        for r in conn.execute(
            "SELECT cr.*, a.display_name AS requested_by_name FROM correction_requests cr"
            " JOIN accounts a ON a.id = cr.requested_by"
            " WHERE cr.class_session_id = ? AND cr.person_id = ? AND cr.state = 'pending'"
            " ORDER BY cr.id", (class_session_id, person_id))
    ]
    window_start, window_end = _window(conn, s)
    return {
        "session": {"id": s["id"], "course_id": s["course_id"], "course_code": s["course_code"],
                    "course_title": s["course_title"], "date": s["date"],
                    "start_time": s["start_time"], "end_time": s["end_time"],
                    "cancelled_at": s["cancelled_at"], "cancel_note": s["cancel_note"]},
        "window": {"from": window_start, "to": window_end},
        "student": {"person_id": person_id, "device_user_id": entry["device_user_id"],
                    "matric_no": entry["matric_no"], "surname": entry["surname"],
                    "other_names": entry["other_names"],
                    "full_name": f"{entry['surname']} {entry['other_names']}".strip(),
                    "kind": entry["kind"], "level": entry["level"]},
        "status": entry["status"],
        "first_scan": entry["first_scan"],
        "scans": entry["scans"],
        "excusal": entry["excusal"],
        "history": history,
        "pending_requests": pending,
    }
