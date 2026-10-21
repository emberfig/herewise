"""A class taken live: Start in the room, the queue scans, End when it is done.

Asked for on 2026-09-22, as the way a lecturer actually takes attendance: bring the terminal and the
laptop, open the course, start taking attendance, let the students scan one by one and watch them
come in as present, and only when the lecturer ends it does everybody who did not scan become
absent. It is untimed, and a level can have more than one class in a week.

The register already worked this way underneath, which is why this is small: attendance is worked
out from the scans inside a class's window, never stored per student. A class taken live is a class
whose window is exactly the minutes it was open (``opened_at`` to ``closed_at``), with no grace, and
while it is open it has no end: nobody in it is absent yet, only not yet scanned, and it is counted in
no total (``register.OPEN``).

The scans come in by asking the terminal how many it holds every couple of seconds, and reading them
only when that number moves, without taking the terminal out of service. Not by listening for the
terminal to announce each scan: on this K40 the real-time events never arrived for anything on its
idle screen (2026-09-22, ``docs/pyzk-notes.md``), and a count that is read is a count that is known.
Ending reads everything once more, so a scan the last refresh missed is still counted.
"""
from __future__ import annotations

import sqlite3
import threading
import time
from datetime import date, timedelta

from . import courses, db, groups, punches, register, services, templates
from .device import DeviceBusy, DeviceError, K40

# How often a class taken live asks the terminal whether anyone has scanned. A student takes a
# couple of seconds at the reader, so this keeps the screen a scan or two behind the queue at most.
REFRESH_SECONDS = 2.0

# What the terminal said last time, per device: when it was asked and how many scans it held.
# In memory on purpose: after a restart the first refresh simply reads everything once.
_seen: dict[int, dict] = {}
_seen_lock = threading.Lock()


class LiveError(ValueError):
    pass


def open_class(conn: sqlite3.Connection) -> sqlite3.Row | None:
    """The class taking attendance now, if any. One terminal, so at most one."""
    return conn.execute(
        "SELECT cs.*, c.code AS code, c.title AS course_title, g.name AS group_name FROM class_sessions cs"
        " LEFT JOIN courses c ON c.id = cs.course_id LEFT JOIN course_groups g ON g.id = cs.group_id"
        " WHERE cs.opened_at IS NOT NULL AND cs.closed_at IS NULL ORDER BY cs.id DESC LIMIT 1").fetchone()


def _default_device(conn: sqlite3.Connection) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM devices ORDER BY is_default DESC, id LIMIT 1").fetchone()
    if row is None:
        raise LiveError("No terminal is set up. Add it under Device first.")
    return row


def _class(conn: sqlite3.Connection, class_id: int) -> sqlite3.Row:
    row = conn.execute("SELECT cs.*, c.code AS code, g.name AS group_name FROM class_sessions cs"
                       " LEFT JOIN courses c ON c.id = cs.course_id LEFT JOIN course_groups g ON g.id = cs.group_id"
                       " WHERE cs.id = ?", (class_id,)).fetchone()
    if row is None:
        raise LiveError("Unknown class.")
    return row


NO_GROUP = "everybody"


def start(conn: sqlite3.Connection, course_id: int, account_id: int | None, factory=K40,
          week_number: int | None = None, group_id=None) -> int:
    """Open a class on this course from now, in the week of the sheet the lecturer chose.

    ``week_number`` is the lecturer's answer to "which week is this class for?"; without one, the
    week ``week_choices`` would have suggested. Either way it is stored, so the class stays where
    it was put even if the week dates are changed afterwards.

    ``group_id`` is who the class is for, on a course with groups: one group's id, or NO_GROUP for
    everybody on the course. A course with groups has no default, because the wrong answer marks a
    whole group absent from a class that was never theirs; a course without groups needs none.
    """
    already = open_class(conn)
    if already is not None:
        raise LiveError(f"{already['code'] or 'A class'} is already taking attendance, since "
                        f"{already['opened_at'][11:16]}. End it before starting another.")
    course = courses.get_course(conn, course_id)
    if not courses.members(conn, course_id):
        raise LiveError(f"{course['code']} has no students yet, so there is nobody to take attendance for.")
    group = None
    if groups.has_groups(conn, course_id):
        if group_id is None:
            raise LiveError(f"{course['code']} is split into groups. Say which group this class is for, or "
                            "that it is for everybody on the course.")
        if group_id != NO_GROUP:
            try:
                group = groups.get_group(conn, int(group_id))
            except (groups.GroupError, ValueError):
                raise LiveError("That group is not one of this course's.") from None
            if group["course_id"] != course_id:
                raise LiveError("That group is not one of this course's.")
            if not groups.in_group_on(conn, group["id"], db.now()[:10]) & {p["id"] for p in courses.members(conn, course_id)}:
                raise LiveError(f"{group['name']} has nobody in it, so there is nobody to take attendance for.")
    elif group_id not in (None, NO_GROUP):
        raise LiveError(f"{course['code']} has no groups. Start the class for everybody on it.")
    device = _default_device(conn)
    choices = week_choices(conn, course_id, group_id=group["id"] if group else None)
    if week_number is None:
        week_number = choices["suggested"]
    if week_number == len(choices["weeks"]) + 1 and week_number <= templates.MAX_WEEKS:
        # "A new week" at the end of the list: the lecturer did not know the course would run this
        # long, and the sheet grows by one week following the last.
        t = _template(conn, course_id, account_id)
        templates.set_weeks(conn, t["id"], account_id,
                            [{"classes": w["classes"], "starts_on": w["starts_on"], "label": w["label"]
                              if w["label"] != f"WK {w['week_number']}" else None,
                              "from_week": w["week_number"]} for w in t["weeks"]]
                            + [{"classes": 1, "starts_on": None, "label": None}])
        choices = week_choices(conn, course_id, group_id=group["id"] if group else None)
    if not any(w["week_number"] == week_number for w in choices["weeks"]):
        raise LiveError(f"{course['code']} has weeks 1 to {len(choices['weeks'])} on its sheet. Add "
                        "weeks in Sheet setup to take a class in a later one.")

    # The scans are stamped by the terminal's clock and the class's window by this computer's, so a
    # terminal five minutes slow would put the first five minutes of the queue outside the class.
    # Setting it here also proves the terminal is answering before anybody queues at it.
    synced = services.sync_time(conn, device["id"], account_id, factory)

    # The class opens at the earlier of this computer's clock and the terminal's, read back straight
    # after setting it. Scans carry the terminal's time, so a terminal still a little slow can never
    # put a scan made after Start before the class began (it did, 2026-09-23: the first scan of three
    # classes in a row fell outside them).
    opened = min(db.now(), synced["device_time"][:19])
    with db.transaction(conn):
        batch_id = conn.execute(
            "INSERT INTO import_batches(source, device_id, created_at, account_id, detail)"
            " VALUES ('network', ?, ?, ?, ?)",
            (device["id"], opened, account_id,
             f"{course['code']}{' ' + group['name'] if group else ''} taken live")).lastrowid
        class_id = conn.execute(
            "INSERT INTO class_sessions(level_id, academic_session_id, course_id, course_code, date,"
            " start_time, end_time, kind, created_by, created_at, opened_at, live_batch_id, week_number,"
            " group_id) VALUES (?, ?, ?, ?, ?, ?, ?, 'device', ?, ?, ?, ?, ?, ?)",
            (course["level_id"], course["academic_session_id"], course_id, course["code"], opened[:10],
             opened[11:16], opened[11:16], account_id, opened, opened, batch_id, week_number,
             group["id"] if group else None)).lastrowid
        db.audit(conn, account_id, "session.live_start", "class_sessions", class_id,
                 f"{course['code']}{' ' + group['name'] if group else ''} week {week_number}, "
                 f"{opened[:10]} from {opened[11:16]}")
    # On the sheet from the first scan, in its week, rather than only once it has ended.
    _place_on_sheet(conn, class_id, account_id)
    with _seen_lock:
        _seen.pop(device["id"], None)
    return int(class_id)


def refresh(conn: sqlite3.Connection, class_id: int, factory=K40, force: bool = False) -> dict:
    """Take in any scans the terminal holds that this register does not. Cheap when nothing moved.

    Returns what the terminal said, for the screen: never raises for a terminal that is busy or
    unplugged, because a queue does not stop for a loose cable and the class must stay open.
    """
    s = _class(conn, class_id)
    if not register.is_open(s) and not force:
        return {"state": "closed"}
    device = _default_device(conn)
    now = time.monotonic()
    with _seen_lock:
        last = dict(_seen.get(device["id"], {}))
    if not force and last and now - last["at"] < REFRESH_SECONDS:
        return {"state": "connected", "checked_at": last["stamp"], "new": 0, "records": last["count"]}
    k40 = factory(services.target_for(device))
    new = 0
    try:
        count = k40.record_count()
        if force or count != last.get("count"):
            serial, records = k40.read_attendance(disable=False)
            services._check_serial(conn, device, serial)
            new = punches.store_into_batch(conn, s["live_batch_id"], device["id"], records)
            count = len(records)
    except DeviceBusy as exc:
        return {"state": "busy", "detail": exc.message}
    except DeviceError as exc:
        return {"state": "unreachable", "detail": exc.message, "hint": exc.hint}
    stamp = db.now()
    with _seen_lock:
        _seen[device["id"]] = {"at": now, "count": count, "stamp": stamp}
    conn.execute("UPDATE devices SET last_seen_at = ?, record_count = ? WHERE id = ?",
                 (stamp, count, device["id"]))
    return {"state": "connected", "checked_at": stamp, "new": new, "records": count}


def end(conn: sqlite3.Connection, class_id: int, account_id: int | None, factory=K40,
        ended_at: str | None = None) -> dict:
    """End the class: one last read, then everyone without a scan in it is absent.

    ``ended_at`` is HH:MM on the class's own day, for a class ended late: somebody who forgot to
    press End until the evening would otherwise count every scan made after the lecture.
    """
    s = _class(conn, class_id)
    if not register.is_open(s):
        raise LiveError("This class is not taking attendance.")
    closing = _closing_time(s, ended_at)

    # Before closing, so a scan made in the last seconds is inside the class it belongs to.
    terminal = refresh(conn, class_id, factory, force=True)

    with db.transaction(conn):
        changed = conn.execute(
            "UPDATE class_sessions SET closed_at = ?, end_time = ? WHERE id = ? AND closed_at IS NULL",
            (closing, closing[11:16], class_id)).rowcount
        if not changed:
            raise LiveError("This class was ended already.")
    result = register.session_register(conn, class_id)
    totals = result["totals"]
    with db.transaction(conn):
        db.audit(conn, account_id, "session.live_end", "class_sessions", class_id,
                 f"{s['code']}{' ' + s['group_name'] if s['group_name'] else ''} {s['date']} "
                 f"{s['start_time']}-{closing[11:16]}: {totals['present']} present, "
                 f"{totals['absent']} absent"
                 + (f", {totals['excused']} excused" if totals["excused"] else ""))
    placed = _place_on_sheet(conn, class_id, account_id)
    return {**result, "terminal": terminal, "sheet": placed}


def _closing_time(s: sqlite3.Row, ended_at: str | None) -> str:
    now = db.now()
    if not ended_at:
        return now
    register.validate_session_fields(s["date"], s["start_time"], ended_at)
    closing = f"{s['date']}T{ended_at}:00"
    if closing < s["opened_at"]:
        raise LiveError(f"The class was started at {s['opened_at'][11:16]}, so it cannot end before that.")
    if closing > now:
        raise LiveError("That time has not come yet. End it now, or give a time that has passed.")
    return closing


def _template(conn: sqlite3.Connection, course_id: int, account_id: int | None) -> dict:
    return templates.get_template(conn, templates.ensure_template(conn, course_id, account_id))


def week_choices(conn: sqlite3.Connection, course_id: int, today: date | None = None,
                 group_id: int | None = None) -> dict:
    """The weeks a class about to start could go in, with the one to suggest.

    Asked for on 2026-09-23: a level can have more than one class in a week, so Herewise asks which
    week each class belongs to rather than deciding from the calendar. Each week says how many
    classes it holds already, so the choice reads "WK 3 has 1 class; this will be its second".

    The suggestion is the week today falls in, when the weeks have dates; otherwise the week after
    the last one that holds a class, which is where the next class of a course usually goes.

    For a group's class a week holds what that group has had in it (the classes for everybody and
    its own); for a class for everybody, what the busiest group has had, which is the box it needs.
    """
    today = today or date.today()
    courses.get_course(conn, course_id)
    t = templates.get_template(conn, templates.ensure_template(conn, course_id))
    weeks = []
    for w in t["weeks"]:
        held = (len(templates.week_classes(conn, course_id, w, group_id)) if group_id is not None
                else templates.boxes_needed(conn, course_id, w))
        weeks.append({"week_number": w["week_number"], "label": w["label"], "starts_on": w["starts_on"],
                      "ends_on": w["ends_on"], "boxes": w["classes"], "held": held,
                      "current": bool(w["starts_on"]) and w["starts_on"] <= today.isoformat() <= w["ends_on"]})
    current = next((w for w in weeks if w["current"]), None)
    if current is not None:
        suggested = current["week_number"]
    else:
        used = [w["week_number"] for w in weeks if w["held"]]
        suggested = min(max(used) + 1, len(weeks)) if used else 1
    return {"weeks": weeks, "suggested": suggested,
            # The number a new week would have, when the sheet can take one more.
            "new_week": len(weeks) + 1 if len(weeks) < templates.MAX_WEEKS else None}


def _place_on_sheet(conn: sqlite3.Connection, class_id: int, account_id: int | None) -> dict:
    """Make sure the class has a box on the sheet, in its week. Run at Start and at End.

    A level can have more than one class in a week, and a week has as many boxes as it was set up
    with. A class the week has no box for was left off the sheet with a warning; a class the
    lecturer is taking in the room belongs on it, so the week gains a box. And a course whose week 1
    was never set would place no class by its date, so the first class taken sets week 1: to the
    Monday of this week for a class in week 1, and that many weeks earlier for a class the lecturer
    put in week 4. Sheet setup can still change it.
    """
    s = _class(conn, class_id)
    t = _template(conn, s["course_id"], account_id)
    said = {}
    day = date.fromisoformat(s["date"])
    if not t["week1_start"]:
        monday = day - timedelta(days=day.weekday()) - timedelta(weeks=(s["week_number"] or 1) - 1)
        templates.update_template(conn, t["id"], account_id, week1_start=monday.isoformat())
        t = _template(conn, s["course_id"], account_id)
        said["week1_set"] = monday.isoformat()
    week = next((w for w in t["weeks"] if templates.in_week(s, w)), None)
    if week is None:
        said["outside"] = True
        return said
    # The open class counts here: it is the one that needs the box. Its position is among the
    # classes the same students have had, which for a group's class is its own group's sheet.
    here = [c["id"] for c in templates.week_classes(
        conn, s["course_id"], week, s["group_id"] if s["group_id"] is not None else templates.ALL)]
    held = templates.boxes_needed(conn, s["course_id"], week)
    said["week"] = week["label"]
    said["position"] = here.index(class_id) + 1 if class_id in here else len(here)
    if held > week["classes"] and week["classes"] < templates.MAX_CLASSES_PER_WEEK:
        with db.transaction(conn):
            conn.execute("UPDATE register_weeks SET classes = ? WHERE template_id = ? AND week_number = ?",
                         (held, t["id"], week["week_number"]))
            db.audit(conn, account_id, "template.weeks", "register_templates", t["id"],
                     f"{week['label']} now has {held} classes, for a class taken live on {s['date']}")
        said["week_classes"] = held
    return said


def sheet_week(conn: sqlite3.Connection, s: sqlite3.Row) -> dict | None:
    """The week of its course's sheet a class sits in, by the same rule the sheet uses."""
    if not s["course_id"]:
        return None
    t = _template(conn, s["course_id"], None)
    week = next((w for w in t["weeks"] if templates.in_week(s, w)), None)
    if week is None:
        return None
    return {"week_number": week["week_number"], "label": week["label"], "starts_on": week["starts_on"]}


def move_to_week(conn: sqlite3.Connection, class_id: int, week_number: int, account_id: int | None) -> dict:
    """Put a class in another week of its course's sheet: the way back from choosing the wrong one.

    Without it a class started in the wrong week stayed there, and deleting it to start again is
    refused once it holds a correction. The scans are untouched; only where the class sits changes.
    """
    s = _class(conn, class_id)
    if not s["course_id"]:
        raise LiveError("This class is not on a course yet, so it is on no sheet. Assign it first.")
    choices = week_choices(conn, s["course_id"], group_id=s["group_id"])
    week = next((w for w in choices["weeks"] if w["week_number"] == week_number), None)
    if week is None:
        raise LiveError(f"{s['code']} has weeks 1 to {len(choices['weeks'])} on its sheet.")
    before = sheet_week(conn, s)
    with db.transaction(conn):
        conn.execute("UPDATE class_sessions SET week_number = ? WHERE id = ?", (week_number, class_id))
        db.audit(conn, account_id, "session.week", "class_sessions", class_id,
                 f"{s['code']} {s['date']} {s['start_time']}: "
                 f"{before['label'] if before else 'not on the sheet'} to {week['label']}")
    return _place_on_sheet(conn, class_id, account_id)


def status(conn: sqlite3.Connection) -> dict:
    """What any screen needs to say a class is taking attendance, without touching the terminal."""
    s = open_class(conn)
    if s is None:
        return {"open": None}
    totals = register.session_register(conn, s["id"])["totals"]
    t = _template(conn, s["course_id"], None)
    week = next((w for w in t["weeks"] if templates.in_week(s, w)), None)
    audience = s["group_id"] if s["group_id"] is not None else templates.ALL
    here = [c["id"] for c in templates.week_classes(conn, s["course_id"], week, audience)] if week else []
    return {"open": {"class_id": s["id"], "course_id": s["course_id"], "code": s["code"],
                     "group": s["group_name"], "group_id": s["group_id"],
                     "opened_at": s["opened_at"], "present": totals["present"],
                     "students": totals["students"],
                     "week": week["label"] if week else None,
                     "position": here.index(s["id"]) + 1 if s["id"] in here else None,
                     "of": len(here) or None}}
