"""A course's groups: its students split into A, B, C and D, with a class taken for one group at a time.

Asked for on 2026-09-29: "the lecturer wants to be able to create sub groups from the attendance and
be able to create attendance for those sub groups like eg creating sub group a,b,c,d for 200 level for
a particular course ... and still be able to use the full roster for some courses".

A course with no groups is exactly what it always was. A course with groups can still have classes for
everybody on it (a lecture) as well as classes for one group (a practical). A student is expected at
the classes for everybody and at their own group's, and nothing else: somebody in Group A is not
absent from Group B's practical, and their percentage counts only the classes they were expected at.

A student is in one group of a course at a time, and the membership is dated. Moving somebody from A to
B part of the way through the course keeps the classes they already had with A as A's, rather than
rewriting them as absences from B's classes. Putting somebody in the wrong group and putting it right
is a different thing, and changes the group for the whole of that stretch: the two are asked apart.
"""
from __future__ import annotations

import re
import sqlite3
from collections import Counter

from . import courses, db, names

MAX_GROUPS = 20
ORDERS = ("matric", "surname")
HOW = ("from_today", "wrong_group")

# Whether a membership row covers a day. Two placeholders, both the day.
COVERS = "(gm.since IS NULL OR gm.since <= ?) AND (gm.until IS NULL OR ? < gm.until)"


class GroupError(ValueError):
    pass


def today() -> str:
    return db.now()[:10]


def default_name(n: int) -> str:
    """Group A, Group B ... the way a department's own lists name them."""
    return f"Group {chr(ord('A') + n)}" if n < 26 else f"Group {n + 1}"


def get_group(conn: sqlite3.Connection, group_id: int) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM course_groups WHERE id = ?", (group_id,)).fetchone()
    if row is None:
        raise GroupError("Unknown group.")
    return row


def _of_course(conn: sqlite3.Connection, course_id: int, group_id: int) -> sqlite3.Row:
    group = get_group(conn, group_id)
    if group["course_id"] != course_id:
        raise GroupError("That group belongs to another course.")
    return group


def has_groups(conn: sqlite3.Connection, course_id: int) -> bool:
    return conn.execute("SELECT 1 FROM course_groups WHERE course_id = ? LIMIT 1", (course_id,)).fetchone() is not None


def in_group_on(conn: sqlite3.Connection, group_id: int, day: str) -> set[int]:
    """Everybody in a group on a day, by person id, whether or not they are still on the course."""
    return {r[0] for r in conn.execute(
        f"SELECT person_id FROM course_group_members gm WHERE group_id = ? AND {COVERS}",
        (group_id, day, day))}


def groups_on(conn: sqlite3.Connection, course_id: int, day: str | None = None) -> dict[int, sqlite3.Row]:
    """Each student's group on a day, by person id. A student in no group is not in it."""
    day = day or today()
    return {r["person_id"]: r for r in conn.execute(
        "SELECT gm.person_id, g.id, g.name, g.position FROM course_group_members gm"
        f" JOIN course_groups g ON g.id = gm.group_id WHERE gm.course_id = ? AND {COVERS}",
        (course_id, day, day))}


def class_members(conn: sqlite3.Connection, s) -> list[sqlite3.Row]:
    """The students a class expects: everybody on the course, or its group on the day it was held.

    The one rule for who is on a class's register. The register, the sheet, the percentages and the
    eligibility list all ask it, so none of them can count a group's class differently.
    """
    if not s["course_id"]:
        return []
    everyone = courses.members(conn, s["course_id"])
    group_id = s["group_id"] if "group_id" in s.keys() else None
    if group_id is None:
        return everyone
    ids = in_group_on(conn, group_id, s["date"])
    return [p for p in everyone if p["id"] in ids]


def list_groups(conn: sqlite3.Connection, course_id: int, day: str | None = None) -> list[dict]:
    """The course's groups in order, with how many students each has today and its classes."""
    day = day or today()
    on_course = {p["id"] for p in courses.members(conn, course_id)}
    current = groups_on(conn, course_id, day)
    counts = Counter(row["id"] for person, row in current.items() if person in on_course)
    rows = conn.execute(
        "SELECT g.*,"
        " (SELECT COUNT(*) FROM class_sessions s WHERE s.group_id = g.id) AS classes,"
        " (SELECT COUNT(*) FROM class_sessions s WHERE s.group_id = g.id AND s.cancelled_at IS NULL"
        "   AND NOT (s.opened_at IS NOT NULL AND s.closed_at IS NULL)) AS held"
        " FROM course_groups g WHERE g.course_id = ? ORDER BY g.position, g.id", (course_id,)).fetchall()
    return [{"id": g["id"], "name": g["name"], "position": g["position"], "students": counts.get(g["id"], 0),
             "classes": g["classes"], "held": g["held"], "can_delete": not g["classes"]} for g in rows]


def ungrouped(conn: sqlite3.Connection, course_id: int, day: str | None = None) -> list[sqlite3.Row]:
    """Students on the course in no group today. Expected only at the classes for everybody."""
    if not has_groups(conn, course_id):
        return []
    current = groups_on(conn, course_id, day)
    return [p for p in courses.members(conn, course_id) if p["id"] not in current]


def _natural(text: str) -> tuple:
    """PHA/23/9 before PHA/23/10, the order a department's list is in."""
    return tuple(int(part) if part.isdigit() else part for part in re.split(r"(\d+)", names.fold(text)))


def _ordered(students: list[sqlite3.Row], order: str) -> list[sqlite3.Row]:
    """The students in the order the groups are cut from.

    The course's own students first and carry-over students after them, the same order as the sheet,
    so a group's matric numbers are one unbroken run of the level's list, which is how a department
    publishes its groups ("Group A: 001 to 040"). A direct-entry student has no matric number to
    sort by and goes after everyone who has one, by name.
    """
    def by_name(p):
        return (names.fold(p["surname"]), names.fold(p["other_names"]))

    def key(p):
        if order == "surname":
            return (p["kind"] == "carry_over", by_name(p))
        return (p["kind"] == "carry_over", p["matric_no"] is None, _natural(p["matric_no"] or ""), by_name(p))
    return sorted(students, key=key)


def _check_name(name: str) -> str:
    name = " ".join((name or "").split())
    if not name:
        raise GroupError("A group needs a name, for example Group A.")
    if len(name) > 40:
        raise GroupError("Keep a group's name to 40 characters. It heads the sheet.")
    return name


def split(conn: sqlite3.Connection, course_id: int, count: int, order: str, account_id: int | None) -> list[dict]:
    """Make the course's groups and share its students out between them.

    Each group is one unbroken run of the students in the order chosen, and the sizes differ by one at
    most. Everybody goes in from the start of the course. Only for a course with no groups: once there
    are groups, students are moved one at a time, so a class already taken for a group never finds
    its register rewritten.
    """
    course = courses.get_course(conn, course_id)
    if has_groups(conn, course_id):
        raise GroupError(f"{course['code']} has groups already. Move students between them, or take "
                         "the groups away first, which is possible while no class has been taken for one.")
    if not isinstance(count, int) or not 2 <= count <= MAX_GROUPS:
        raise GroupError(f"Split the course into 2 to {MAX_GROUPS} groups.")
    if order not in ORDERS:
        raise GroupError("Put the students in matric number order or surname order.")
    students = _ordered(courses.members(conn, course_id), order)
    if len(students) < count:
        raise GroupError(f"{course['code']} has {len(students)} students, too few for {count} groups.")
    base, extra = divmod(len(students), count)
    stamp = db.now()
    with db.transaction(conn):
        start = 0
        for n in range(count):
            size = base + (1 if n < extra else 0)
            group_id = conn.execute(
                "INSERT INTO course_groups(course_id, name, position, created_at) VALUES (?, ?, ?, ?)",
                (course_id, default_name(n), n + 1, stamp)).lastrowid
            conn.executemany(
                "INSERT INTO course_group_members(course_id, group_id, person_id, since, until, added_at,"
                " account_id) VALUES (?, ?, ?, NULL, NULL, ?, ?)",
                [(course_id, group_id, p["id"], stamp, account_id) for p in students[start:start + size]])
            start += size
        db.audit(conn, account_id, "group.split", "courses", course_id,
                 f"{course['code']} into {count} groups of about {base}, by "
                 f"{'matric number' if order == 'matric' else 'surname'}")
    return list_groups(conn, course_id)


def add_group(conn: sqlite3.Connection, course_id: int, name: str | None, account_id: int | None) -> dict:
    course = courses.get_course(conn, course_id)
    taken = conn.execute("SELECT COUNT(*), COALESCE(MAX(position), 0) FROM course_groups WHERE course_id = ?",
                         (course_id,)).fetchone()
    if taken[0] >= MAX_GROUPS:
        raise GroupError(f"A course can have {MAX_GROUPS} groups at most.")
    if name is None or not name.strip():
        existing = {r[0].casefold() for r in conn.execute("SELECT name FROM course_groups WHERE course_id = ?",
                                                          (course_id,))}
        name = next(default_name(n) for n in range(taken[0], 26 + MAX_GROUPS)
                    if default_name(n).casefold() not in existing)
    name = _check_name(name)
    try:
        with db.transaction(conn):
            group_id = conn.execute(
                "INSERT INTO course_groups(course_id, name, position, created_at) VALUES (?, ?, ?, ?)",
                (course_id, name, taken[1] + 1, db.now())).lastrowid
            db.audit(conn, account_id, "group.create", "course_groups", group_id, f"{course['code']} {name}")
    except sqlite3.IntegrityError as exc:
        raise GroupError(f"{course['code']} already has a group called {name}.") from exc
    return next(g for g in list_groups(conn, course_id) if g["id"] == group_id)


def rename_group(conn: sqlite3.Connection, group_id: int, name: str, account_id: int | None) -> dict:
    group = get_group(conn, group_id)
    course = courses.get_course(conn, group["course_id"])
    name = _check_name(name)
    try:
        with db.transaction(conn):
            conn.execute("UPDATE course_groups SET name = ? WHERE id = ?", (name, group_id))
            db.audit(conn, account_id, "group.rename", "course_groups", group_id,
                     f"{course['code']} {group['name']} to {name}")
    except sqlite3.IntegrityError as exc:
        raise GroupError(f"{course['code']} already has a group called {name}.") from exc
    return next(g for g in list_groups(conn, group["course_id"]) if g["id"] == group_id)


def delete_group(conn: sqlite3.Connection, group_id: int, account_id: int | None) -> dict:
    """Take a group away, while no class has been taken for it. Its students are in no group after."""
    group = get_group(conn, group_id)
    course = courses.get_course(conn, group["course_id"])
    classes = conn.execute("SELECT COUNT(*) FROM class_sessions WHERE group_id = ?", (group_id,)).fetchone()[0]
    if classes:
        raise GroupError(
            f"{group['name']} has {classes} {'class' if classes == 1 else 'classes'}, so it stays: they are "
            "its register. A class for it that was started by mistake can be deleted or given to "
            "another group from the Classes tab first.")
    with db.transaction(conn):
        moved = conn.execute("SELECT COUNT(*) FROM course_group_members WHERE group_id = ? AND until IS NULL",
                             (group_id,)).fetchone()[0]
        conn.execute("DELETE FROM course_group_members WHERE group_id = ?", (group_id,))
        conn.execute("DELETE FROM course_groups WHERE id = ?", (group_id,))
        db.audit(conn, account_id, "group.delete", "course_groups", group_id,
                 f"{course['code']} {group['name']}, {moved} students left in no group")
    return {"deleted": group["name"], "ungrouped": moved}


def clear_groups(conn: sqlite3.Connection, course_id: int, account_id: int | None) -> dict:
    """Take every group away, to split the course again. Only while no class has been for a group."""
    course = courses.get_course(conn, course_id)
    classes = conn.execute(
        "SELECT COUNT(*) FROM class_sessions s JOIN course_groups g ON g.id = s.group_id WHERE g.course_id = ?",
        (course_id,)).fetchone()[0]
    if classes:
        raise GroupError(
            f"{classes} {'class has' if classes == 1 else 'classes have'} been taken for {course['code']}'s "
            "groups, so the groups stay: those classes are their registers. Move students one at a time "
            "instead.")
    with db.transaction(conn):
        count = conn.execute("SELECT COUNT(*) FROM course_groups WHERE course_id = ?", (course_id,)).fetchone()[0]
        conn.execute("DELETE FROM course_group_members WHERE course_id = ?", (course_id,))
        conn.execute("DELETE FROM course_groups WHERE course_id = ?", (course_id,))
        db.audit(conn, account_id, "group.clear", "courses", course_id, f"{course['code']}, {count} groups")
    return {"removed": count}


def _current(conn: sqlite3.Connection, course_id: int, person_id: int) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT gm.*, g.name FROM course_group_members gm JOIN course_groups g ON g.id = gm.group_id"
        " WHERE gm.course_id = ? AND gm.person_id = ? AND gm.until IS NULL", (course_id, person_id)).fetchone()


def classes_with_group(conn: sqlite3.Connection, course_id: int, person_id: int) -> int:
    """How many classes of their present group the student has been expected at so far.

    Nothing to keep means nothing to ask: a move before any class for the group changes no register,
    so it simply puts them in the new group from the start of the stretch.
    """
    current = _current(conn, course_id, person_id)
    if current is None:
        return 0
    return conn.execute(
        "SELECT COUNT(*) FROM class_sessions WHERE group_id = ? AND cancelled_at IS NULL AND date <= ?"
        " AND (? IS NULL OR date >= ?)",
        (current["group_id"], today(), current["since"], current["since"])).fetchone()[0]


def move(conn: sqlite3.Connection, course_id: int, person_id: int, group_id: int | None, how: str,
         account_id: int | None, day: str | None = None) -> dict:
    """Put a student in a group, move them to another, or take them out of groups.

    ``how`` says what the lecturer means. "from_today": they are changing group, so the classes they
    already had with the old one stay with it and the new group's classes count for them from today.
    "wrong_group": they were in the wrong group, so the group changes for the whole of that stretch
    and their classes so far become the new group's. When the old group has held no class for them
    yet the two are the same, and it is done the second way, so no empty stretch is left behind.
    """
    day = day or today()
    if how not in HOW:
        raise GroupError("Say whether they are changing group from today or were in the wrong group.")
    course = courses.get_course(conn, course_id)
    if not courses.is_member(conn, course_id, person_id):
        raise GroupError(f"That student is not on {course['code']}.")
    target = _of_course(conn, course_id, group_id) if group_id is not None else None
    current = _current(conn, course_id, person_id)
    if current is None and target is None:
        raise GroupError("They are in no group already.")
    if current is not None and target is not None and current["group_id"] == target["id"]:
        raise GroupError(f"They are in {target['name']} already.")
    history = classes_with_group(conn, course_id, person_id)
    stamp = db.now()
    with db.transaction(conn):
        if current is None:
            # In a group before, and taken out: back in from today, so the stretch in no group stays.
            before = conn.execute("SELECT 1 FROM course_group_members WHERE course_id = ? AND person_id = ?",
                                  (course_id, person_id)).fetchone()
            conn.execute("INSERT INTO course_group_members(course_id, group_id, person_id, since, until, added_at,"
                         " account_id) VALUES (?, ?, ?, ?, NULL, ?, ?)",
                         (course_id, target["id"], person_id, day if before else None, stamp, account_id))
        elif how == "wrong_group" or not history:
            if target is None:
                conn.execute("DELETE FROM course_group_members WHERE id = ?", (current["id"],))
            else:
                conn.execute("UPDATE course_group_members SET group_id = ?, added_at = ?, account_id = ? WHERE id = ?",
                             (target["id"], stamp, account_id, current["id"]))
        else:
            if current["since"] is not None and current["since"] >= day:
                conn.execute("DELETE FROM course_group_members WHERE id = ?", (current["id"],))
            else:
                conn.execute("UPDATE course_group_members SET until = ? WHERE id = ?", (day, current["id"]))
            if target is not None:
                conn.execute("INSERT INTO course_group_members(course_id, group_id, person_id, since, until,"
                             " added_at, account_id) VALUES (?, ?, ?, ?, NULL, ?, ?)",
                             (course_id, target["id"], person_id, day, stamp, account_id))
        who = conn.execute("SELECT surname, other_names, matric_no FROM people WHERE id = ?", (person_id,)).fetchone()
        label = f"{names.matric_text(who['matric_no'])} {who['surname']} {who['other_names']}".strip()
        where = target["name"] if target else "no group"
        was = current["name"] if current else "no group"
        kept = history and how == "from_today" and current is not None
        db.audit(conn, account_id, "group.move", "courses", course_id,
                 f"{course['code']}: {label}, {was} to {where}"
                 + (f" from {day}, their {history} {was} classes kept" if kept
                    else ", as if from the start" if current is not None and history else ""))
    return {"person_id": person_id, "group": where, "was": was, "kept_classes": history if kept else 0}


def _find(conn: sqlite3.Connection, course_id: int, text: str) -> sqlite3.Row | None:
    """A student on the course, by matric number, or by name for somebody with none (DE)."""
    matric = names.matric_or_none(text)
    members = courses.members(conn, course_id)
    if matric:
        wanted = names.fold(matric)
        found = next((p for p in members if p["matric_no"] and names.fold(p["matric_no"]) == wanted), None)
        if found is not None:
            return found
    wanted = names.fold(" ".join(text.split()))
    return next((p for p in members if names.fold(f"{p['surname']} {p['other_names']}".strip()) == wanted), None)


def list_plan(conn: sqlite3.Connection, course_id: int, group_id: int, lines: list[str]) -> dict:
    """What pasting a list into a group would do, one line at a time. Changes nothing.

    A department often hands out its own group lists. Each line is a matric number, or a name for a
    student with none; a line can also start with a serial number and carry the name after the
    number, the way a copied list does, and only the number is read.
    """
    course = courses.get_course(conn, course_id)
    target = _of_course(conn, course_id, group_id)
    current = groups_on(conn, course_id)
    seen: set[int] = set()
    entries = []
    for n, raw in enumerate(lines, start=1):
        text = " ".join(str(raw or "").split())
        if not text:
            continue
        # "12, PHA/23/0041, OKAFOR Emeka" or "12 PHA/23/0041 OKAFOR Emeka": the matric number is the
        # token with a digit and a slash or several digits in it; anything else is a name.
        parts = [p.strip() for p in re.split(r"[,\t;]", text) if p.strip()]
        if len(parts) == 1:
            parts = text.split(" ")
        numbers = [p for p in parts if re.search(r"\d", p) and (("/" in p) or len(re.sub(r"\D", "", p)) >= 4)]
        key = numbers[0] if numbers else text
        person = _find(conn, course_id, key)
        item = {"line": n, "text": text}
        entries.append(item)
        if person is None:
            item.update(action="not_found", note=f"Not on {course['code']}.")
            continue
        item.update(person_id=person["id"], matric_no=person["matric_no"],
                    name=f"{person['surname']} {person['other_names']}".strip())
        if person["id"] in seen:
            item.update(action="duplicate", note="Twice in this list.")
            continue
        seen.add(person["id"])
        now = current.get(person["id"])
        if now is not None and now["id"] == target["id"]:
            item.update(action="already", note=f"In {target['name']} already.")
        elif now is not None:
            kept = classes_with_group(conn, course_id, person["id"])
            item.update(action="move", from_group=now["name"], kept_classes=kept,
                        note=(f"Moves from {now['name']}; their {kept} {now['name']} "
                              f"{'class stays' if kept == 1 else 'classes stay'} with it." if kept
                              else f"Moves from {now['name']}."))
        else:
            item.update(action="join", note=f"Joins {target['name']}.")
    counts = Counter(e["action"] for e in entries)
    return {"group": {"id": target["id"], "name": target["name"]}, "entries": entries,
            "join": counts["join"], "move": counts["move"], "already": counts["already"],
            "not_found": counts["not_found"], "duplicate": counts["duplicate"],
            "can_commit": bool(counts["join"] or counts["move"])}


def list_commit(conn: sqlite3.Connection, course_id: int, group_id: int, lines: list[str],
                account_id: int | None) -> dict:
    plan = list_plan(conn, course_id, group_id, lines)
    if not plan["can_commit"]:
        raise GroupError("Nobody in that list would join or move. Check the matric numbers.")
    for e in plan["entries"]:
        if e["action"] in ("join", "move"):
            move(conn, course_id, e["person_id"], group_id, "from_today", account_id)
    return {k: v for k, v in plan.items() if k != "entries"}


def share_out(conn: sqlite3.Connection, course_id: int, account_id: int | None) -> dict:
    """Put every student in no group into the smallest group, one at a time, in the sheet's order.

    For students who joined the course after it was split: a late carry-over student, or a roster
    imported again. They go in from today if they were ever in a group, otherwise from the start.
    """
    groups = list_groups(conn, course_id)
    if not groups:
        raise GroupError("This course has no groups to share students out between.")
    waiting = ungrouped(conn, course_id)
    if not waiting:
        return {"placed": 0}
    sizes = {g["id"]: g["students"] for g in groups}
    order = {g["id"]: g["position"] for g in groups}
    for p in waiting:
        smallest = min(sizes, key=lambda gid: (sizes[gid], order[gid]))
        move(conn, course_id, p["id"], smallest, "from_today", account_id)
        sizes[smallest] += 1
    return {"placed": len(waiting)}


def infer_group(conn: sqlite3.Connection, course_id: int, person_ids: set[int], day: str) -> int | None:
    """The group a class found in the scans was for, or None for everybody on the course.

    A group when at least three quarters of the course's students who scanned were in that one group
    that day. A lecture for everybody spreads across every group (a quarter each, with four), and a
    practical for Group A is nearly all Group A. Anything in between is left as a class for everybody,
    which marks nobody absent from a class that was not theirs, and the Classes tab can change it.
    """
    if not has_groups(conn, course_id):
        return None
    on_course = {p["id"] for p in courses.members(conn, course_id)}
    scanned = person_ids & on_course
    if not scanned:
        return None
    current = groups_on(conn, course_id, day)
    counts = Counter(current[p]["id"] for p in scanned if p in current)
    if not counts:
        return None
    best, n = counts.most_common(1)[0]
    return best if n * 4 >= len(scanned) * 3 else None


def set_class_group(conn: sqlite3.Connection, class_id: int, group_id: int | None, account_id: int | None) -> dict:
    """Say which group a class was for, or that it was for everybody on the course.

    Refused when somebody corrected in the class would no longer be on its register: a correction is
    a signed decision, and it would be left belonging to nobody's box.
    """
    s = conn.execute("SELECT * FROM class_sessions WHERE id = ?", (class_id,)).fetchone()
    if s is None:
        raise GroupError("Unknown class.")
    if not s["course_id"]:
        raise GroupError("Put this class on a course first.")
    target = _of_course(conn, s["course_id"], group_id) if group_id is not None else None
    if s["group_id"] == group_id:
        return {"class_id": class_id, "group": target["name"] if target else None}
    expected = {p["id"] for p in class_members(conn, {**dict(s), "group_id": group_id})}
    signed = {r[0] for r in conn.execute(
        "SELECT person_id FROM attendance_marks WHERE class_session_id = ?"
        " UNION SELECT person_id FROM correction_requests WHERE class_session_id = ?", (class_id, class_id))}
    stranded = signed - expected
    where = target["name"] if target else "everybody on the course"
    if stranded:
        raise GroupError(
            f"{len(stranded)} {'student' if len(stranded) == 1 else 'students'} corrected in this class "
            f"{'is' if len(stranded) == 1 else 'are'} not in {where}, so it stays as it is. A correction is a "
            "signed decision and would be left on nobody's register.")
    before = conn.execute("SELECT name FROM course_groups WHERE id = ?", (s["group_id"],)).fetchone() \
        if s["group_id"] else None
    with db.transaction(conn):
        conn.execute("UPDATE class_sessions SET group_id = ? WHERE id = ?", (group_id, class_id))
        db.audit(conn, account_id, "session.group", "class_sessions", class_id,
                 f"{s['course_code'] or 'a class'} {s['date']} {s['start_time']}: "
                 f"{before['name'] if before else 'everybody'} to {target['name'] if target else 'everybody'}")
    return {"class_id": class_id, "group": target["name"] if target else None}
