"""Courses: the unit a register, a sheet, a plan and an eligibility list belong to.

A course has a home level. Every student in that level is on it automatically, including students
imported later. Carry-over students from other levels are added to it explicitly, from a list of
matric numbers, and a carry-over student the app has never seen is created in their own level's ID
block so their device ID still reads correctly.

Removing a student from a course keeps the row with a timestamp and a note, so the history stays.
"""
from __future__ import annotations

import sqlite3

from . import db, names, templates


class CourseError(ValueError):
    pass


def get_course(conn: sqlite3.Connection, course_id: int) -> sqlite3.Row:
    row = conn.execute(
        "SELECT c.*, l.name AS level_name, l.level_number, a.name AS academic_session, a.is_current"
        " FROM courses c JOIN levels l ON l.id = c.level_id JOIN academic_sessions a ON a.id = c.academic_session_id"
        " WHERE c.id = ?", (course_id,)).fetchone()
    if row is None:
        raise CourseError("Unknown course.")
    return row


def list_courses(conn: sqlite3.Connection, academic_session_id: int) -> list[dict]:
    rows = conn.execute(
        "SELECT c.*, l.name AS level_name, l.level_number,"
        " (SELECT COUNT(*) FROM course_enrolments e WHERE e.course_id = c.id AND e.removed_at IS NULL"
        "   AND e.kind = 'level') AS level_students,"
        " (SELECT COUNT(*) FROM course_enrolments e WHERE e.course_id = c.id AND e.removed_at IS NULL"
        "   AND e.kind = 'carry_over') AS carry_over_students,"
        " (SELECT COUNT(*) FROM class_sessions s WHERE s.course_id = c.id AND s.cancelled_at IS NULL"
        "   AND NOT (s.opened_at IS NOT NULL AND s.closed_at IS NULL)) AS classes_held,"
        " (SELECT id FROM register_templates t WHERE t.course_id = c.id) AS template_id"
        " FROM courses c JOIN levels l ON l.id = c.level_id WHERE c.academic_session_id = ?"
        " ORDER BY l.level_number, c.code", (academic_session_id,)).fetchall()
    return [dict(r) for r in rows]


def create_course(conn: sqlite3.Connection, academic_session_id: int, level_id: int, code: str,
                  title: str | None, account_id: int | None) -> int:
    code = (code or "").strip()
    if not code:
        raise CourseError("A course needs a code, for example PCT 201.")
    if conn.execute("SELECT 1 FROM levels WHERE id = ?", (level_id,)).fetchone() is None:
        raise CourseError("Unknown level.")
    own = not conn.in_transaction
    if own:
        conn.execute("BEGIN IMMEDIATE")
    try:
        try:
            course_id = conn.execute(
                "INSERT INTO courses(academic_session_id, level_id, code, title, created_at) VALUES (?, ?, ?, ?, ?)",
                (academic_session_id, level_id, code, (title or "").strip() or None, db.now())).lastrowid
        except sqlite3.IntegrityError as exc:
            raise CourseError(f"A course called {code} already exists this academic session.") from exc
        enrol_level_members(conn, course_id, account_id)
        templates.ensure_template(conn, course_id, account_id)
        db.audit(conn, account_id, "course.create", "courses", course_id, code)
        if own:
            conn.execute("COMMIT")
    except BaseException:
        if own:
            conn.execute("ROLLBACK")
        raise
    return int(course_id)


def update_course(conn: sqlite3.Connection, course_id: int, account_id: int, code: str | None = None,
                  title: str | None = None) -> dict:
    get_course(conn, course_id)
    fields = {}
    if code is not None:
        if not code.strip():
            raise CourseError("A course needs a code.")
        fields["code"] = code.strip()
    if title is not None:
        fields["title"] = title.strip() or None
    if fields:
        try:
            with db.transaction(conn):
                conn.execute(f"UPDATE courses SET {', '.join(f'{k} = ?' for k in fields)} WHERE id = ?",
                             [*fields.values(), course_id])
                db.audit(conn, account_id, "course.update", "courses", course_id, str(fields))
        except sqlite3.IntegrityError as exc:
            raise CourseError(f"A course called {fields.get('code')} already exists this academic session.") from exc
    return dict(get_course(conn, course_id))


def enrol_level_members(conn: sqlite3.Connection, course_id: int, account_id: int | None) -> int:
    """Put every current member of the home level on the course. Students removed by hand stay removed."""
    course = conn.execute("SELECT * FROM courses WHERE id = ?", (course_id,)).fetchone()
    return conn.execute(
        "INSERT OR IGNORE INTO course_enrolments(course_id, person_id, kind, added_at, account_id)"
        " SELECT ?, m.person_id, 'level', ?, ? FROM level_memberships m JOIN people p ON p.id = m.person_id"
        " WHERE m.level_id = ? AND m.academic_session_id = ? AND p.role = 'student'",
        (course_id, db.now(), account_id, course["level_id"], course["academic_session_id"])).rowcount


def on_roster_commit(conn: sqlite3.Connection, level_id: int, academic_session_id: int,
                     account_id: int | None) -> list[int]:
    """Called inside the roster commit: put the new names on every course the level already has.

    It used to make a course named after the level when the level had none, so importing five
    levels made five courses called "200 Level" to "600 Level" that nobody asked for (reported
    2026-09-24). A course is the lecturer's to make, with its real code, and making one puts everybody
    on its level on it (create_course), so nothing is lost by waiting for them to.
    """
    course_ids = [r["id"] for r in conn.execute(
        "SELECT id FROM courses WHERE level_id = ? AND academic_session_id = ? ORDER BY id",
        (level_id, academic_session_id))]
    for course_id in course_ids:
        enrol_level_members(conn, course_id, account_id)
    return course_ids


def members(conn: sqlite3.Connection, course_id: int, include_removed: bool = False) -> list[sqlite3.Row]:
    """Students on the course: home level first, then carry-over, each in device ID order."""
    course = conn.execute("SELECT * FROM courses WHERE id = ?", (course_id,)).fetchone()
    return conn.execute(
        "SELECT p.*, e.kind, e.added_at, e.removed_at, e.removed_note, l.name AS level_name, l.level_number"
        " FROM course_enrolments e JOIN people p ON p.id = e.person_id"
        " LEFT JOIN level_memberships m ON m.person_id = p.id AND m.academic_session_id = ?"
        " LEFT JOIN levels l ON l.id = m.level_id"
        " WHERE e.course_id = ? AND p.role = 'student' AND p.active = 1"
        + ("" if include_removed else " AND e.removed_at IS NULL") +
        " ORDER BY e.kind = 'carry_over', p.device_user_id",
        (course["academic_session_id"], course_id)).fetchall()


def is_member(conn: sqlite3.Connection, course_id: int, person_id: int) -> bool:
    return conn.execute("SELECT 1 FROM course_enrolments WHERE course_id = ? AND person_id = ? AND removed_at IS NULL",
                        (course_id, person_id)).fetchone() is not None


def carry_over_plan(conn: sqlite3.Connection, course_id: int, entries: list[dict]) -> dict:
    """Preview adding students to a course. Each entry: matric_no, and for a new student name and level.

    Changes nothing. Existing students are matched by matric number; unknown ones are created in the
    ID block of the level given for them.
    """
    from . import roster  # imported here: roster imports this module

    course = get_course(conn, course_id)
    device = conn.execute("SELECT * FROM devices ORDER BY is_default DESC, id LIMIT 1").fetchone()
    if device is None:
        raise CourseError("Set up a device first.")
    levels = {str(r["level_number"]): r for r in conn.execute("SELECT * FROM levels")}
    next_ids: dict[int, int] = {}
    seen: set[str] = set()
    planned = []
    for n, entry in enumerate(entries, start=1):
        line = entry.get("_line", n)
        matric = names.matric_or_none(entry.get("matric_no")) or ""
        item = {"line": line, "matric_no": matric, "action": "skip", "issues": []}
        planned.append(item)
        if matric and matric in seen:
            item["issues"].append("duplicate matric number in this list")
            continue
        if matric:
            seen.add(matric)
            person = conn.execute("SELECT * FROM people WHERE matric_no = ?", (matric,)).fetchone()
        else:
            # A direct-entry student has no matric number yet (2026-09-23). Somebody already known
            # without one is found by name, so adding them twice does not make two of them; anybody
            # else is created without one, and the number is added from the sheet when it comes.
            wanted = names.fold(" ".join((entry.get("name") or "").split()))
            if not wanted:
                item["issues"].append("new student: name is missing")
                continue
            if wanted in seen:
                item["issues"].append("the same name twice with no matric number in this list")
                continue
            seen.add(wanted)
            person = conn.execute(
                "SELECT * FROM people WHERE matric_no IS NULL AND role = 'student'"
                " AND fold(surname || ' ' || other_names) = ?", (wanted,)).fetchone()
            if person is None:
                item["issues"].append("direct entry (DE): added without a matric number, which can be "
                                      "added later")
        if person is not None:
            level = conn.execute(
                "SELECT l.* FROM level_memberships m JOIN levels l ON l.id = m.level_id"
                " WHERE m.person_id = ? AND m.academic_session_id = ?",
                (person["id"], course["academic_session_id"])).fetchone()
            enrolment = conn.execute("SELECT * FROM course_enrolments WHERE course_id = ? AND person_id = ?",
                                     (course_id, person["id"])).fetchone()
            item.update(person_id=person["id"], device_user_id=person["device_user_id"],
                        name=f"{person['surname']} {person['other_names']}".strip(),
                        level=level["level_number"] if level else None,
                        kind="level" if level and level["id"] == course["level_id"] else "carry_over")
            if not person["active"]:
                item["issues"].append("this student is deactivated")
            elif enrolment and enrolment["removed_at"] is None:
                item["action"] = "already_on_course"
            else:
                item["action"] = "restore" if enrolment else "enrol"
            if level is None:
                item["issues"].append("no level recorded for this academic session")
            continue

        level_value = str(entry.get("level") or "").strip()
        level = levels.get(level_value)
        parsed = names.split_name(entry.get("name") or "")
        item.update(name=" ".join(x for x in (parsed.surname, parsed.other_names) if x), level=level_value or None,
                    kind="carry_over" if not level or level["id"] != course["level_id"] else "level")
        if not parsed.surname:
            item["issues"].append("new student: name is missing")
            continue
        if level is None:
            item["issues"].append("new student: give their current level, for example 300")
            continue
        if level["id"] not in next_ids:
            next_ids[level["id"]] = roster.next_device_id(conn, level)
        if next_ids[level["id"]] > level["id_block_end"]:
            item["issues"].append(f"no IDs left in the {level['name']} block")
            continue
        item.update(action="create", device_user_id=next_ids[level["id"]], level_id=level["id"],
                    surname=parsed.surname, other_names=parsed.other_names,
                    device_name=names.device_name(parsed.surname, parsed.other_names), source_name=entry.get("name"))
        item["issues"].extend(parsed.warnings)
        next_ids[level["id"]] += 1

    creating = sum(1 for p in planned if p["action"] == "create")
    assigned = conn.execute("SELECT COUNT(*) FROM people WHERE device_id = ? AND active = 1", (device["id"],)).fetchone()[0]
    capacity = device["user_capacity"] or 1000
    errors = []
    if assigned + creating > capacity:
        errors.append(f"Adding {creating} new students would put {assigned + creating} people on {device['name']}, "
                      f"which holds {capacity}.")
    return {
        "course": {"id": course["id"], "code": course["code"], "level": course["level_name"]},
        "entries": planned,
        "enrol": sum(1 for p in planned if p["action"] in ("enrol", "restore")),
        "create": creating,
        "already_on_course": sum(1 for p in planned if p["action"] == "already_on_course"),
        "skipped": sum(1 for p in planned if p["action"] == "skip"),
        "errors": errors,
        "can_commit": not errors and any(p["action"] in ("enrol", "restore", "create") for p in planned),
    }


def carry_over_commit(conn: sqlite3.Connection, course_id: int, entries: list[dict], account_id: int) -> dict:
    with db.transaction(conn):
        plan = carry_over_plan(conn, course_id, entries)
        if not plan["can_commit"]:
            raise CourseError("; ".join(plan["errors"]) or "Nothing to add.")
        course = get_course(conn, course_id)
        device = conn.execute("SELECT id FROM devices ORDER BY is_default DESC, id LIMIT 1").fetchone()
        stamp = db.now()
        for item in plan["entries"]:
            if item["action"] == "create":
                person_id = conn.execute(
                    "INSERT INTO people(role, device_user_id, device_id, matric_no, surname, other_names, source_name,"
                    " device_name, created_at) VALUES ('student', ?, ?, ?, ?, ?, ?, ?, ?)",
                    # NULL, never "": matric_no is unique, and two empty strings would collide.
                    (item["device_user_id"], device["id"], item["matric_no"] or None, item["surname"], item["other_names"],
                     item["source_name"], item["device_name"], stamp)).lastrowid
                conn.execute("INSERT INTO level_memberships(person_id, academic_session_id, level_id) VALUES (?, ?, ?)",
                             (person_id, course["academic_session_id"], item["level_id"]))
                item["person_id"] = person_id
            elif item["action"] not in ("enrol", "restore"):
                continue
            conn.execute(
                "INSERT INTO course_enrolments(course_id, person_id, kind, added_at, account_id) VALUES (?, ?, ?, ?, ?)"
                " ON CONFLICT(course_id, person_id) DO UPDATE SET removed_at = NULL, removed_note = NULL,"
                " kind = excluded.kind, added_at = excluded.added_at, account_id = excluded.account_id",
                (course_id, item["person_id"], item["kind"], stamp, account_id))
        db.audit(conn, account_id, "course.add_students", "courses", course_id,
                 f"{plan['enrol']} enrolled, {plan['create']} created")
    return {k: v for k, v in plan.items() if k != "entries"} | {
        "added": [{"matric_no": e["matric_no"], "device_user_id": e.get("device_user_id"), "kind": e.get("kind"),
                   "action": e["action"]} for e in plan["entries"] if e["action"] in ("enrol", "restore", "create")]}


def holds(conn: sqlite3.Connection, course_id: int) -> dict[str, int]:
    """What a course has recorded against it, by kind, for deciding whether it can be deleted.

    Its own furniture does not count: the sheet template, the attendance plan, who is on it, and
    classes that recorded nothing all go with the course. What counts is anything that is a record
    of something that happened.
    """
    from . import register            # imported here: register imports this module

    found: dict[str, int] = {}
    classes = conn.execute("SELECT id FROM class_sessions WHERE course_id = ?", (course_id,)).fetchall()
    for row in classes:
        for name, count in register.holds(conn, row["id"]).items():
            found[name] = found.get(name, 0) + count
    excused = conn.execute("SELECT COUNT(*) FROM excusals WHERE course_id = ?", (course_id,)).fetchone()[0]
    if excused:
        found["excusals"] = excused
    return found


def delete_course(conn: sqlite3.Connection, course_id: int, account_id: int | None) -> dict:
    """Delete a course nothing was ever recorded against, and its sheet, plan, roll and empty classes."""
    course = get_course(conn, course_id)
    from . import register                          # imported here: register imports this module

    held = holds(conn, course_id)
    stops = register.blocking(held)
    if stops:
        raise CourseError(
            f"{course['code']} has {register.say_holds(stops)} against it, so it cannot be deleted. "
            "Each one is somebody's signed decision, and the register keeps those for good. Take "
            "the students off it instead and it stops collecting anything new, or start a fresh "
            "academic session if this register was only being tried out.")
    with db.transaction(conn):
        template = conn.execute("SELECT id FROM register_templates WHERE course_id = ?",
                                (course_id,)).fetchone()
        if template is not None:
            conn.execute("DELETE FROM register_weeks WHERE template_id = ?", (template["id"],))
            conn.execute("DELETE FROM register_templates WHERE id = ?", (template["id"],))
        conn.execute("DELETE FROM attendance_plans WHERE course_id = ?", (course_id,))
        conn.execute("DELETE FROM course_enrolments WHERE course_id = ?", (course_id,))
        conn.execute("DELETE FROM class_sessions WHERE course_id = ?", (course_id,))
        conn.execute("DELETE FROM course_group_members WHERE course_id = ?", (course_id,))
        conn.execute("DELETE FROM course_groups WHERE course_id = ?", (course_id,))
        conn.execute("DELETE FROM courses WHERE id = ?", (course_id,))
        db.audit(conn, account_id, "course.delete", "courses", course_id,
                 f"{course['code']}, which had no attendance recorded against it")
    return {"deleted": course["code"]}


def remove_student(conn: sqlite3.Connection, course_id: int, person_id: int, note: str, account_id: int) -> None:
    if not (note or "").strip():
        raise CourseError("Say why this student is being removed from the course.")
    with db.transaction(conn):
        updated = conn.execute(
            "UPDATE course_enrolments SET removed_at = ?, removed_note = ? WHERE course_id = ? AND person_id = ?"
            " AND removed_at IS NULL", (db.now(), note.strip(), course_id, person_id)).rowcount
        if not updated:
            raise CourseError("That student is not on this course.")
        db.audit(conn, account_id, "course.remove_student", "courses", course_id, f"person {person_id}: {note.strip()}")
