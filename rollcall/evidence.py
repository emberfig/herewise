"""Evidence for one student, to settle a dispute on the spot.

Everything the app knows that bears on a student's attendance, with where it came from: every scan
(time, device, pulled over the cable or read from a USB file, when it was stored), every class on
each of their courses and why they were counted present, absent or excused, every correction with who
made it and when, and every excused absence including withdrawn ones.
"""
from __future__ import annotations

import sqlite3

from . import db, groups, register


class EvidenceError(ValueError):
    pass


def search(conn: sqlite3.Connection, query: str, limit: int = 25) -> list[dict]:
    q = (query or "").strip()
    if len(q) < 2:
        raise EvidenceError("Type at least 2 characters: part of a name, a matric number or a device ID.")
    from .names import fold

    like = f"%{fold(q)}%"
    rows = conn.execute(
        "SELECT p.id, p.device_user_id, p.matric_no, p.surname, p.other_names, p.active, l.name AS level"
        " FROM people p LEFT JOIN level_memberships m ON m.person_id = p.id"
        " AND m.academic_session_id = (SELECT id FROM academic_sessions WHERE is_current = 1)"
        " LEFT JOIN levels l ON l.id = m.level_id"
        " WHERE p.role = 'student' AND (fold(p.matric_no) LIKE ? OR fold(p.surname || ' ' || p.other_names) LIKE ?"
        " OR CAST(p.device_user_id AS TEXT) = ?)"
        " ORDER BY CAST(p.device_user_id AS TEXT) = ? DESC, p.matric_no = ? DESC, p.surname LIMIT ?",
        (like, like, q, q, q, limit)).fetchall()
    return [dict(r) for r in rows]


def student_evidence(conn: sqlite3.Connection, person_id: int, course_id: int | None = None) -> dict:
    person = conn.execute("SELECT * FROM people WHERE id = ? AND role = 'student'", (person_id,)).fetchone()
    if person is None:
        raise EvidenceError("Unknown student.")

    levels = [dict(r) for r in conn.execute(
        "SELECT a.name AS academic_session, l.name AS level FROM level_memberships m"
        " JOIN academic_sessions a ON a.id = m.academic_session_id JOIN levels l ON l.id = m.level_id"
        " WHERE m.person_id = ? ORDER BY a.name DESC", (person_id,))]
    fingers = [r["finger_index"] for r in conn.execute(
        "SELECT finger_index FROM fingers WHERE person_id = ? ORDER BY finger_index", (person_id,))]

    scans = [dict(r) for r in conn.execute(
        "SELECT pu.timestamp, d.name AS device, d.serial AS device_serial, b.source, b.file_name,"
        " pu.imported_at, pu.verify_type FROM punches pu JOIN devices d ON d.id = pu.device_id"
        " LEFT JOIN import_batches b ON b.id = pu.import_batch_id WHERE pu.device_user_id = ?"
        " ORDER BY pu.timestamp", (str(person["device_user_id"]),))]

    enrolments = conn.execute(
        "SELECT e.*, c.code, c.title, a.name AS academic_session FROM course_enrolments e"
        " JOIN courses c ON c.id = e.course_id JOIN academic_sessions a ON a.id = c.academic_session_id"
        " WHERE e.person_id = ?" + (" AND e.course_id = ?" if course_id else "") +
        " ORDER BY a.name DESC, c.code", (person_id, course_id) if course_id else (person_id,)).fetchall()

    course_records = []
    for e in enrolments:
        classes = []
        for s in conn.execute("SELECT * FROM class_sessions WHERE course_id = ? ORDER BY date, start_time",
                              (e["course_id"],)):
            entry = {"session_id": s["id"], "date": s["date"], "start_time": s["start_time"],
                     "end_time": s["end_time"], "kind": s["kind"], "cancelled": s["cancelled_at"] is not None,
                     "cancel_note": s["cancel_note"]}
            # A class for a group they were not in that day is not theirs, and is left off their
            # timeline: three other groups' practicals a week buried their own classes (seen on the
            # demo register, 2026-09-29). Unless they scanned in it, which is evidence to show.
            theirs = s["group_id"] is None or person_id in groups.in_group_on(conn, s["group_id"], s["date"])
            if not theirs and s["cancelled_at"] is not None:
                continue
            if s["cancelled_at"] is None:
                reg = register.session_register(conn, s["id"])
                mine = next((x for x in reg["students"] if x["person_id"] == person_id), None)
                entry["window"] = reg["window"]
                visiting = next((x for x in reg["others"] if x["person_id"] == person_id), None)
                if mine is None and reg["group"] and visiting is not None:
                    # The scan is shown on the timeline where it fell, so the claim is checkable.
                    entry.update(status="other_group", group=reg["group"]["name"], first_scan=visiting["first_scan"],
                                 reason=f"A class for {reg['group']['name']}, which they were not in that day. "
                                        "They scanned in it; it counts in their own group's class, not here.")
                elif mine is None and reg["group"]:
                    continue
                elif mine is None:
                    entry.update(status="not_on_course", reason="Not on the course at the time this was produced.")
                else:
                    entry.update(status=mine["status"], first_scan=mine["first_scan"], scans=mine["scans"],
                                 reason=_reason(mine, reg["window"]))
            classes.append(entry)
        marks = [dict(r) for r in conn.execute(
            "SELECT am.class_session_id, s.date, am.status, am.note, a.display_name AS by_account, am.created_at"
            " FROM attendance_marks am JOIN class_sessions s ON s.id = am.class_session_id"
            " JOIN accounts a ON a.id = am.account_id WHERE am.person_id = ? AND s.course_id = ? ORDER BY am.id",
            (person_id, e["course_id"]))]
        summary_row = None
        if e["removed_at"] is None:
            summary = register.course_summary(conn, e["course_id"])
            summary_row = next((r for r in summary["students"] if r["person_id"] == person_id), None)
            if summary_row:
                summary_row = {k: summary_row[k] for k in ("attended", "excused", "held", "counted", "percent", "status")}
                summary_row["threshold_percent"] = summary["threshold_percent"]
        course_records.append({
            "course_id": e["course_id"], "code": e["code"], "title": e["title"],
            "academic_session": e["academic_session"], "kind": e["kind"], "added_at": e["added_at"],
            "removed_at": e["removed_at"], "removed_note": e["removed_note"],
            "summary": summary_row, "classes": classes, "corrections": marks,
        })

    return {
        "student": {"person_id": person["id"], "device_user_id": person["device_user_id"],
                    "matric_no": person["matric_no"], "surname": person["surname"],
                    "other_names": person["other_names"], "active": bool(person["active"]),
                    "fingers_enrolled": fingers, "has_keypad_password": person["device_password"] is not None,
                    "keypad_password_reason": person["password_reason"],
                    # Whether the terminal has them, so the record can say so and offer to take
                    # them off it (2026-09-21).
                    "on_device": bool(person["on_device"])},
        "levels": levels,
        "scans": scans,
        "courses": course_records,
        "excusals": register.list_excusals(conn, person_id=person_id),
        "generated_at": db.now(),
    }


def _reason(entry: dict, window: dict) -> str:
    frm, to = window["from"][11:16], window["to"][11:16]
    status = entry["status"]
    if status in ("marked_present", "marked_absent"):
        m = entry["mark"]
        return f"Corrected to {m['status']} by {m['by']} on {m['at'].replace('T', ' ')}: {m['note']}"
    if status == "present":
        return f"Scanned at {entry['first_scan'][11:19]}, inside the class window {frm} to {to}."
    if status == "excused":
        x = entry["excusal"]
        return f"Excused ({x['category']}): {x['note']}"
    if status == "waiting":
        return f"This class is still taking attendance, since {frm}, and there is no scan yet."
    return f"No scan between {frm} and {to}, no correction and no excused absence."
