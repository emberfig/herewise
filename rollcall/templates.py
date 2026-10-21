"""The attendance sheet template: S/N, matric number, full name, then a column per week.

Modelled on the lecturer's own sheet (200L_Pharmacy_Attendance.pdf): a title, a COURSE field, twelve
week columns, lecturer's signature, and totals for registered, present and absent.

Every course gets a template as soon as it exists; importing a level's roster creates the level's
first course. The lecturer can change the number of weeks, the start date of any week, and how many
classes each week has. A week with 2 classes has 2 tick boxes. Carry-over students are listed after
the home level's students.

Ticks are derived, never typed in. A class on the course fills the next box in the week it falls in,
in date order. A student's box is ticked when the register for that class says present, so a
fingerprint scan ticks it. An excused absence shows as excused.
"""
from __future__ import annotations

import re
import sqlite3
from datetime import date, timedelta

from . import db, register

DEFAULT_WEEKS = 12
DEFAULT_CLASSES_PER_WEEK = 1
MAX_WEEKS = 52
MAX_CLASSES_PER_WEEK = 7


class TemplateError(ValueError):
    pass


def in_week(s, w: dict) -> bool:
    """Whether a class belongs in a week of the sheet. The one rule, used by the sheet and by the
    code that gives a week another box, so the two can never count a week differently.

    A class the lecturer put in a week is in that week, whatever its date: a course's weeks are its
    own numbering, not the calendar's (asked for on 2026-09-23). Any other class goes by its date.
    """
    if s["week_number"] is not None:
        return s["week_number"] == w["week_number"]
    return bool(w["starts_on"]) and w["starts_on"] <= s["date"] <= w["ends_on"]


# Every class of the course, whoever it was for. The other audiences are a group's id, whose sheet
# holds the classes for everybody and that group's own, or None, the sheet of the students in no
# group, which holds only the classes for everybody (groups.py, 2026-09-29).
ALL = "all"


def _for(s, audience) -> bool:
    return audience == ALL or s["group_id"] is None or s["group_id"] == audience


def week_classes(conn: sqlite3.Connection, course_id: int, week: dict, audience=ALL) -> list[sqlite3.Row]:
    """The classes in one week of a course's sheet, open ones included, cancelled ones not."""
    rows = conn.execute("SELECT * FROM class_sessions WHERE course_id = ? AND cancelled_at IS NULL"
                        " ORDER BY date, start_time", (course_id,)).fetchall()
    return [s for s in rows if in_week(s, week) and _for(s, audience)]


def audiences(conn: sqlite3.Connection, course_id: int) -> list:
    """Whose sheets the course has: None alone for a course without groups, else each group and None."""
    return [r[0] for r in conn.execute("SELECT id FROM course_groups WHERE course_id = ? ORDER BY position, id",
                                       (course_id,))] + [None]


def boxes_needed(conn: sqlite3.Connection, course_id: int, week: dict) -> int:
    """How many boxes a week needs: the most classes one student was expected at in it.

    A box is one student's class. With four groups each having its practical in week 3 and a lecture
    for everybody, week 3 needs two boxes, not five.
    """
    return max(len(week_classes(conn, course_id, week, a)) for a in audiences(conn, course_id))


def default_title(level_number: int) -> str:
    return f"{level_number} LEVEL ATTENDANCE"


def ensure_template(conn: sqlite3.Connection, course_id: int, account_id: int | None = None) -> int:
    row = conn.execute("SELECT id FROM register_templates WHERE course_id = ?", (course_id,)).fetchone()
    if row:
        return row["id"]
    course = conn.execute("SELECT c.*, l.level_number FROM courses c JOIN levels l ON l.id = c.level_id WHERE c.id = ?",
                          (course_id,)).fetchone()
    if course is None:
        raise TemplateError("Unknown course.")
    stamp = db.now()
    own = not conn.in_transaction
    if own:
        conn.execute("BEGIN IMMEDIATE")
    try:
        template_id = conn.execute(
            "INSERT INTO register_templates(course_id, title, week1_start, created_at, updated_at)"
            " VALUES (?, ?, NULL, ?, ?)", (course_id, default_title(course["level_number"]), stamp, stamp)).lastrowid
        for n in range(1, DEFAULT_WEEKS + 1):
            conn.execute("INSERT INTO register_weeks(template_id, week_number, starts_on, classes) VALUES (?, ?, NULL, ?)",
                         (template_id, n, DEFAULT_CLASSES_PER_WEEK))
        db.audit(conn, account_id, "template.create", "register_templates", template_id, course["code"])
        if own:
            conn.execute("COMMIT")
    except BaseException:
        if own:
            conn.execute("ROLLBACK")
        raise
    return int(template_id)


def get_template(conn: sqlite3.Connection, template_id: int) -> dict:
    t = conn.execute(
        "SELECT t.*, c.code AS course_code, c.title AS course_title, c.level_id, c.academic_session_id,"
        " l.name AS level_name, l.level_number, a.name AS academic_session"
        " FROM register_templates t JOIN courses c ON c.id = t.course_id JOIN levels l ON l.id = c.level_id"
        " JOIN academic_sessions a ON a.id = c.academic_session_id WHERE t.id = ?", (template_id,)).fetchone()
    if t is None:
        raise TemplateError("Unknown template.")
    weeks = [_week_dict(w) for w in conn.execute(
        "SELECT * FROM register_weeks WHERE template_id = ? ORDER BY week_number", (template_id,))]
    return {**dict(t), "weeks": weeks, "total_classes": sum(w["classes"] for w in weeks)}


def _week_dict(w: sqlite3.Row) -> dict:
    starts = date.fromisoformat(w["starts_on"]) if w["starts_on"] else None
    return {"week_number": w["week_number"], "label": w["label"] or f"WK {w['week_number']}",
            "starts_on": w["starts_on"], "ends_on": (starts + timedelta(days=6)).isoformat() if starts else None,
            "classes": w["classes"]}


def update_template(conn: sqlite3.Connection, template_id: int, account_id: int, title: str | None = None,
                    course_code: str | None = None, week1_start: str | None = None) -> dict:
    """Title and week 1 start live on the template; the course code shown as COURSE lives on the course."""
    current = get_template(conn, template_id)
    fields: dict = {}
    if title is not None:
        if not title.strip():
            raise TemplateError("The title cannot be empty.")
        fields["title"] = title.strip()
    with db.transaction(conn):
        if course_code is not None:
            if not course_code.strip():
                raise TemplateError("The course code cannot be empty.")
            try:
                conn.execute("UPDATE courses SET code = ? WHERE id = ?", (course_code.strip(), current["course_id"]))
            except sqlite3.IntegrityError as exc:
                raise TemplateError(f"A course called {course_code.strip()} already exists this academic session.") from exc
        if week1_start is not None:
            new_start = _parse_date(week1_start, "Week 1 start")
            fields["week1_start"] = new_start.isoformat()
            _shift_weeks(conn, template_id, current, new_start)
        if fields:
            fields["updated_at"] = db.now()
            conn.execute(f"UPDATE register_templates SET {', '.join(f'{k} = ?' for k in fields)} WHERE id = ?",
                         [*fields.values(), template_id])
        db.audit(conn, account_id, "template.update", "register_templates", template_id,
                 str({**fields, "course_code": course_code}))
    return get_template(conn, template_id)


def _shift_weeks(conn: sqlite3.Connection, template_id: int, current: dict, new_start: date) -> None:
    """Moving week 1 moves every week by the same amount, keeping any breaks the lecturer set."""
    old = current["weeks"][0]["starts_on"] if current["weeks"] else None
    if old is None:
        for w in current["weeks"]:
            conn.execute("UPDATE register_weeks SET starts_on = ? WHERE template_id = ? AND week_number = ?",
                         ((new_start + timedelta(days=7 * (w["week_number"] - 1))).isoformat(),
                          template_id, w["week_number"]))
        return
    delta = new_start - date.fromisoformat(old)
    for w in current["weeks"]:
        start = date.fromisoformat(w["starts_on"]) if w["starts_on"] else \
            new_start + timedelta(days=7 * (w["week_number"] - 1)) - delta
        conn.execute("UPDATE register_weeks SET starts_on = ? WHERE template_id = ? AND week_number = ?",
                     ((start + delta).isoformat(), template_id, w["week_number"]))


def set_weeks(conn: sqlite3.Connection, template_id: int, account_id: int, weeks: list[dict]) -> dict:
    """Replace the week list. Each item: classes (0 to 7), optional starts_on, optional label, and
    optional from_week, the number the week had before, for a list with weeks removed or added.

    A week with no start date follows the previous week by 7 days (or week 1 start for the first).

    Asked for on 2026-09-23: "lecturers don't know the amount of weeks they have so make weeks
    deletable". A week that holds a class is never removed, because its classes would fall off the
    sheet: it is refused with how many it holds. A class the lecturer put in a week follows that week
    to its new number, so removing week 5 leaves the class that was in week 7 in the same week, now
    called week 6. Without from_week the weeks are matched by number, which is what generating a new
    list means, and the same refusal protects a shorter list.
    """
    t = get_template(conn, template_id)
    if not 1 <= len(weeks) <= MAX_WEEKS:
        raise TemplateError(f"A template has 1 to {MAX_WEEKS} weeks.")
    old = {w["week_number"]: w for w in t["weeks"]}
    if any(w.get("from_week") is not None for w in weeks):
        moves: dict[int, int] = {}
        for n, w in enumerate(weeks, start=1):
            before = w.get("from_week")
            if before is None:
                continue
            if before not in old or before in moves:
                raise TemplateError(f"Week {n} says it was week {before}, which the sheet does not have "
                                    "or which is listed twice. Reload Sheet setup and try again.")
            moves[before] = n
    else:
        moves = {n: n for n in old if n <= len(weeks)}
    for number, week in old.items():
        if number in moves:
            continue
        held = week_classes(conn, t["course_id"], week)
        if held:
            raise TemplateError(
                f"{week['label']} holds {len(held)} {'class' if len(held) == 1 else 'classes'}, so it "
                "cannot be removed: they would fall off the sheet. Move them to another week from the "
                "Classes tab first.")
    rows = []
    previous: date | None = None
    week1 = date.fromisoformat(t["week1_start"]) if t["week1_start"] else None
    for n, w in enumerate(weeks, start=1):
        classes = w.get("classes", DEFAULT_CLASSES_PER_WEEK)
        if not isinstance(classes, int) or not 0 <= classes <= MAX_CLASSES_PER_WEEK:
            raise TemplateError(f"Week {n}: classes must be a whole number from 0 to {MAX_CLASSES_PER_WEEK}.")
        if w.get("starts_on"):
            start = _parse_date(w["starts_on"], f"Week {n} start")
        elif previous is not None:
            start = previous + timedelta(days=7)
        else:
            start = week1
        if start is not None and previous is not None and start < previous + timedelta(days=7):
            raise TemplateError(f"Week {n} starts on {start}, before week {n - 1} has finished.")
        label = (w.get("label") or "").strip() or None
        # "WK 7" is the default a screen showed and sent back, not a name somebody gave the week:
        # kept, it would still say WK 7 after week 5 was removed and it became the sixth week.
        if label and re.fullmatch(r"WK\s*\d+", label, flags=re.IGNORECASE):
            label = None
        rows.append((template_id, n, start.isoformat() if start else None, classes, label))
        previous = start if start is not None else previous
    with db.transaction(conn):
        conn.execute("DELETE FROM register_weeks WHERE template_id = ?", (template_id,))
        conn.executemany("INSERT INTO register_weeks(template_id, week_number, starts_on, classes, label)"
                         " VALUES (?, ?, ?, ?, ?)", rows)
        # Classes put in a week follow it to its new number. One read, then the writes, so a class
        # moved from week 7 to 6 is never mistaken for one that was already in week 6. A cancelled
        # class left pointing at a removed week goes back to being placed by its date.
        for s in conn.execute("SELECT id, week_number FROM class_sessions WHERE course_id = ?"
                              " AND week_number IS NOT NULL", (t["course_id"],)).fetchall():
            if moves.get(s["week_number"]) != s["week_number"]:
                conn.execute("UPDATE class_sessions SET week_number = ? WHERE id = ?",
                             (moves.get(s["week_number"]), s["id"]))
        conn.execute("UPDATE register_templates SET week1_start = ?, updated_at = ? WHERE id = ?",
                     (rows[0][2], db.now(), template_id))
        db.audit(conn, account_id, "template.weeks", "register_templates", template_id,
                 f"{len(rows)} weeks, {sum(r[3] for r in rows)} classes")
    return get_template(conn, template_id)


def generate_weeks(conn: sqlite3.Connection, template_id: int, account_id: int, weeks: int,
                   classes_per_week: int, week1_start: str | None = None) -> dict:
    if week1_start is not None:
        start = _parse_date(week1_start, "Week 1 start")
        with db.transaction(conn):
            conn.execute("UPDATE register_templates SET week1_start = ? WHERE id = ?", (start.isoformat(), template_id))
    if not isinstance(weeks, int) or not 1 <= weeks <= MAX_WEEKS:
        raise TemplateError(f"Weeks must be 1 to {MAX_WEEKS}.")
    return set_weeks(conn, template_id, account_id, [{"classes": classes_per_week} for _ in range(weeks)])


def _parse_date(value: str, label: str) -> date:
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise TemplateError(f"{label} must be a date, YYYY-MM-DD.") from exc


NO_GROUP = "none"


def _view(conn: sqlite3.Connection, course_id: int, group) -> dict:
    """Which students and classes one sheet holds, for a course with groups.

    ``group`` is a group's id, or NO_GROUP for the students in no group, or None for the first group.
    A group's sheet lists everybody who has been in it, a student who moved out included, so the
    classes they had with it stay on its paper; the classes they were not in it for read as not theirs.
    """
    from . import courses, groups  # imported here: courses imports this module

    listed = groups.list_groups(conn, course_id)
    loose = groups.ungrouped(conn, course_id)
    if group is None:
        group = listed[0]["id"] if listed else NO_GROUP
    if group == NO_GROUP:
        chosen, audience, students = None, None, loose
    else:
        try:
            chosen = next(g for g in listed if g["id"] == int(group))
        except (StopIteration, ValueError):
            raise TemplateError("That group is not one of this course's.") from None
        audience = chosen["id"]
        ever = {r[0] for r in conn.execute("SELECT DISTINCT person_id FROM course_group_members WHERE group_id = ?",
                                           (chosen["id"],))}
        students = [p for p in courses.members(conn, course_id) if p["id"] in ever]
    return {"audience": audience, "students": students,
            "group": {"id": chosen["id"], "name": chosen["name"]} if chosen else None,
            "groups": listed, "ungrouped": len(loose)}


def grid(conn: sqlite3.Connection, template_id: int, today: date | None = None, group=None) -> dict:
    """The sheet as data: every student, every week, every class box, ticked from the registers.

    A course with groups has one sheet per group (``group``, see ``_view``), each holding the classes
    for everybody and that group's own. A box is one student's class, so a group's sheet is the paper
    that group's students are marked on.
    """
    from . import courses  # imported here: courses imports this module

    today = today or date.today()
    t = get_template(conn, template_id)
    warnings: list[str] = []
    exclude_excused = db.get_setting(conn, "excused_rule") != "present"

    view = None
    if len(audiences(conn, t["course_id"])) > 1:
        view = _view(conn, t["course_id"], group)
        students, audience = view["students"], view["audience"]
    else:
        students, audience = courses.members(conn, t["course_id"]), ALL
    sessions = [s for s in conn.execute(
        "SELECT * FROM class_sessions WHERE course_id = ? AND cancelled_at IS NULL ORDER BY date, start_time",
        (t["course_id"],)).fetchall() if _for(s, audience)]
    names = {r[0]: r[1] for r in conn.execute("SELECT id, name FROM course_groups WHERE course_id = ?",
                                              (t["course_id"],))}

    if any(w["starts_on"] is None for w in t["weeks"]):
        warnings.append("Set the week 1 start date so classes can be placed in their weeks and ticked.")

    placed: set[int] = set()
    columns = []
    for w in t["weeks"]:
        these = [s for s in sessions if in_week(s, w)]
        placed.update(s["id"] for s in these)
        if len(these) > w["classes"]:
            extra = ", ".join(f"{s['date']} {s['start_time']}" for s in these[w["classes"]:])
            warnings.append(f"{w['label']} has {len(these)} classes but the template allows {w['classes']}. "
                            f"Not on the sheet: {extra}. Add a class to that week or cancel the extra class.")
        past = w["ends_on"] is not None and date.fromisoformat(w["ends_on"]) < today
        slots = []
        for i in range(w["classes"]):
            s = these[i] if i < len(these) else None
            # Held, not held and upcoming belong to the box, not to a student: stated once here so a
            # screen never has to read it off the first row, which an empty course does not have.
            # A class taken live and not yet ended is "open": its ticks show as students scan, and
            # nobody in it is absent until the lecturer ends it.
            state = (("open" if register.is_open(s) else "held") if s
                     else ("not_held" if past else "upcoming"))
            slots.append({"slot": i + 1, "session_id": s["id"] if s else None, "state": state,
                          "date": s["date"] if s else None, "start_time": s["start_time"] if s else None,
                          "kind": s["kind"] if s else None,
                          # Whose class it was: a group's name, or None for everybody on the course.
                          "group": names.get(s["group_id"]) if s else None})
        current = w["starts_on"] is not None and w["starts_on"] <= today.isoformat() <= w["ends_on"]
        columns.append({**w, "current": current, "slots": slots})

    outside = [s for s in sessions if s["id"] not in placed]
    if outside and (all(w["starts_on"] for w in t["weeks"]) or any(s["week_number"] for s in outside)):
        warnings.append(f"{len(outside)} class(es) fall outside the template weeks, first on {outside[0]['date']}.")

    registers: dict[int, dict[int, dict]] = {}
    for col in columns:
        for slot in col["slots"]:
            if slot["session_id"] is not None:
                reg = register.session_register(conn, slot["session_id"])
                registers[slot["session_id"]] = {s["person_id"]: s for s in reg["students"]}

    rows = []
    for serial, p in enumerate(students, start=1):
        cells, attended, held, excused = [], 0, 0, 0
        for col in columns:
            for slot in col["slots"]:
                if slot["session_id"] is None:
                    cells.append({"week": col["week_number"], "slot": slot["slot"], "state": slot["state"]})
                    continue
                entry = registers[slot["session_id"]].get(p["id"])
                if entry is None:
                    # Not on this class's register: in another group that day, having moved. Not
                    # absent, and not counted either way.
                    cells.append({"week": col["week_number"], "slot": slot["slot"], "state": "elsewhere",
                                  "ticked": False, "first_scan": None, "excusal_category": None})
                    continue
                state = entry["status"]
                present = bool(entry["present"])
                if slot["state"] == "open":
                    # Shown, never counted: an open class moves no student's percentage.
                    cells.append({"week": col["week_number"], "slot": slot["slot"],
                                  "state": "present" if present else "waiting", "ticked": present,
                                  "open": True, "first_scan": entry["first_scan"] if entry else None,
                                  "excusal_category": None})
                    continue
                held += 1
                attended += 1 if present else 0
                excused += 1 if state == "excused" else 0
                excusal = entry["excusal"] if entry else None
                cells.append({"week": col["week_number"], "slot": slot["slot"], "state": state, "ticked": present,
                              "first_scan": entry["first_scan"] if entry else None,
                              "excusal_category": excusal["category"] if excusal else None})
        counted = held - excused if exclude_excused else held
        credit = attended if exclude_excused else attended + excused
        rows.append({"sn": serial, "person_id": p["id"], "device_user_id": p["device_user_id"],
                     "matric_no": p["matric_no"], "full_name": f"{p['surname']} {p['other_names']}".strip(),
                     "surname": p["surname"], "other_names": p["other_names"],
                     "kind": p["kind"], "level": p["level_number"],
                     "attended": attended, "excused": excused, "held": held,
                     "percent": round(100 * credit / counted, 1) if counted else 0.0, "cells": cells})

    # Each class's figures from the rows on this sheet, so a lecture for everybody shows Group A's
    # present and absent on Group A's sheet rather than the whole course's. For a course without
    # groups the rows are the register, and the figures are the register's own.
    for c, (col, slot) in enumerate((col, slot) for col in columns for slot in col["slots"]):
        if slot["session_id"] is None:
            continue
        mine = [r["cells"][c]["state"] for r in rows]
        slot["present"] = sum(1 for x in mine if x in ("present", "marked_present"))
        slot["excused"] = sum(1 for x in mine if x == "excused")
        slot["absent"] = sum(1 for x in mine if x in ("absent", "marked_absent"))

    grouping = {}
    if view is not None:
        grouping = {"group": view["group"], "groups": view["groups"], "ungrouped": view["ungrouped"]}
    return {**grouping, "template": {k: v for k, v in t.items() if k != "weeks"}, "weeks": columns,
            "total_registered": len(rows), "carry_over": sum(1 for r in rows if r["kind"] == "carry_over"),
            "classes_held": sum(1 for c in columns for s in c["slots"] if s["state"] == "held"),
            "class_open": any(s["state"] == "open" for c in columns for s in c["slots"]),
            # The same planned figure the course header quotes, so one screen never says "7 of 12"
            # above the sheet and "7 of 13" beside it (seen 2026-09-23, after a week gained a box
            # for a second class while the course had a saved plan of 12).
            "planned_classes": register._effective_plan(conn, t["course_id"], {})["planned_classes"],
            "warnings": warnings, "students": rows, "generated_at": db.now()}
