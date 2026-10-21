"""Operations that need both the database and a device."""
from __future__ import annotations

import sqlite3
from typing import Callable

from . import db, jobs
from .device import ADMIN, NORMAL, DeviceBusy, DeviceError, DeviceSnapshot, DeviceTarget, K40
from .punches import store_punches
from .reminders import COUNTED_ADMIN

K40Factory = Callable[[DeviceTarget], K40]


class ServiceError(ValueError):
    pass


def device_row(conn: sqlite3.Connection, device_id: int) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM devices WHERE id = ?", (device_id,)).fetchone()
    if row is None:
        raise ServiceError("Unknown device.")
    return row


def target_for(row: sqlite3.Row) -> DeviceTarget:
    return DeviceTarget(ip=row["ip"], port=row["port"], comm_key=row["comm_key"])


def _check_serial(conn: sqlite3.Connection, row: sqlite3.Row, serial: str) -> None:
    if row["serial"] and serial and row["serial"] != serial:
        raise DeviceError(
            f"The device on the cable is {serial}, but {row['name']} is {row['serial']}.",
            "Plug in the right device, or add this one as a new device.",
            "wrong_device",
        )
    if serial and not row["serial"]:
        clash = conn.execute("SELECT name FROM devices WHERE serial = ? AND id != ?", (serial, row["id"])).fetchone()
        if clash:
            raise DeviceError(f"Serial {serial} already belongs to {clash['name']}.", "", "wrong_device")
        conn.execute("UPDATE devices SET serial = ? WHERE id = ?", (serial, row["id"]))


def _record_snapshot(conn: sqlite3.Connection, device_id: int, snap: DeviceSnapshot) -> None:
    conn.execute(
        "UPDATE devices SET firmware = ?, platform = ?, last_seen_at = ?, user_count = ?, user_capacity = ?,"
        " template_count = ?, template_capacity = ?, record_count = ?, record_capacity = ? WHERE id = ?",
        (snap.firmware, snap.platform, db.now(), snap.users, snap.user_capacity, snap.templates,
         snap.template_capacity, snap.records, snap.record_capacity, device_id),
    )


def _drift_warning(conn: sqlite3.Connection, snap: DeviceSnapshot) -> str | None:
    limit = int(db.get_setting(conn, "clock_drift_warn_seconds"))
    drift = snap.clock_drift_seconds
    if abs(drift) <= limit:
        return None
    direction = "ahead of" if drift > 0 else "behind"
    return (f"The device clock is {abs(drift) // 60} min {abs(drift) % 60} s {direction} this PC. "
            "Every scan is stamped with the device clock, so sync the time.")


def ping(conn: sqlite3.Connection, device_id: int, factory: K40Factory = K40) -> dict:
    """What the chip in the top bar says, and when it was last true.

    The chip used to be set only by a screen that happened to talk to the terminal, so it went on
    saying "Device connected" after the cable came out, on every screen that does not touch the
    device (reported on a second run, 2026-09-22). This is the check behind it: cheap, does not
    disable the terminal, and answers "busy" rather than waiting when something else is using it.
    """
    row = device_row(conn, device_id)
    checked_at = db.now()
    try:
        serial = factory(target_for(row)).ping()
    except DeviceBusy:
        return {"state": "busy", "serial": None, "checked_at": checked_at,
                "detail": "Something else is using the terminal."}
    except DeviceError as exc:
        return {"state": "unreachable", "serial": None, "checked_at": checked_at,
                "detail": exc.message}
    known = row["serial"]
    if known and serial and serial != known:
        return {"state": "wrong", "serial": serial, "checked_at": checked_at,
                "detail": f"This is {serial}. The register was set up with {known}."}
    return {"state": "connected", "serial": serial, "checked_at": checked_at, "detail": ""}


def status(conn: sqlite3.Connection, device_id: int, factory: K40Factory = K40) -> dict:
    row = device_row(conn, device_id)
    snap = factory(target_for(row)).snapshot()
    _check_serial(conn, row, snap.serial)
    _record_snapshot(conn, device_id, snap)
    return {
        "device_id": device_id,
        "serial": snap.serial,
        "firmware": snap.firmware,
        "platform": snap.platform,
        "device_time": snap.device_time.isoformat(),
        "pc_time": snap.pc_time.isoformat(timespec="seconds"),
        "clock_drift_seconds": snap.clock_drift_seconds,
        "clock_warning": _drift_warning(conn, snap),
        "users": {"used": snap.users, "capacity": snap.user_capacity},
        "templates": {"used": snap.templates, "capacity": snap.template_capacity},
        "records": {"used": snap.records, "capacity": snap.record_capacity},
    }


def sync_time(conn: sqlite3.Connection, device_id: int, account_id: int | None, factory: K40Factory = K40) -> dict:
    row = device_row(conn, device_id)
    set_to = factory(target_for(row)).set_time()
    db.audit(conn, account_id, "device.sync_time", "devices", device_id, set_to.isoformat())
    return {"device_time": set_to.isoformat()}


def pull_attendance(conn: sqlite3.Connection, device_id: int, account_id: int | None,
                    factory: K40Factory = K40) -> dict:
    row = device_row(conn, device_id)
    k40 = factory(target_for(row))
    # How many scans there are is not known until they have been read, so this stage has no total
    # and says so: the bar is a barber's pole until the count arrives, then it is a real one.
    jobs.start(f"Reading the scans on {row['name']}", detail="the terminal decides how long this takes")
    try:
        serial, records = k40.read_attendance()
        _check_serial(conn, row, serial)
        jobs.expect(len(records), f"{len(records)} scans read, working out the classes")
        result = store_punches(conn, device_id, records, "network", account_id)
        jobs.at(len(records))
        jobs.finish("done", f"{len(records)} scans read from {row['name']}")
    except Exception:
        jobs.finish("failed", "nothing was stored")
        raise
    conn.execute("UPDATE devices SET last_seen_at = ?, record_count = ? WHERE id = ?",
                 (db.now(), len(records), device_id))
    return result


def _people_for_push(conn: sqlite3.Connection, device_id: int, person_ids: list[int] | None,
                     level_id: int | None, course_id: int | None = None) -> list[sqlite3.Row]:
    if person_ids:
        marks = ",".join("?" * len(person_ids))
        rows = conn.execute(f"SELECT * FROM people WHERE id IN ({marks}) AND active = 1", person_ids).fetchall()
    elif level_id:
        rows = conn.execute(
            "SELECT p.* FROM people p JOIN level_memberships m ON m.person_id = p.id"
            " JOIN academic_sessions a ON a.id = m.academic_session_id AND a.is_current = 1"
            " WHERE m.level_id = ? AND p.active = 1 ORDER BY p.device_user_id", (level_id,)).fetchall()
    elif course_id:
        # Everyone on a course, carry-over students included.
        rows = conn.execute(
            "SELECT p.* FROM people p JOIN course_enrolments e ON e.person_id = p.id"
            " WHERE e.course_id = ? AND e.removed_at IS NULL AND p.active = 1 ORDER BY p.device_user_id",
            (course_id,)).fetchall()
    else:
        raise ServiceError("Choose people, a level or a course to push.")
    wrong = [r["device_user_id"] for r in rows if r["device_id"] != device_id]
    if wrong:
        raise ServiceError(f"{len(wrong)} of these people belong to another device, for example ID {wrong[0]}.")
    return rows


def push_people(conn: sqlite3.Connection, device_id: int, account_id: int | None, person_ids: list[int] | None = None,
                level_id: int | None = None, factory: K40Factory = K40, course_id: int | None = None,
                changes: dict[int, dict] | None = None,
                then: Callable[[sqlite3.Connection], None] | None = None) -> dict:
    """Write people to the device, then record that they are on it.

    ``changes`` maps a person id to column values to send in place of the stored ones. ``then`` saves
    them: it runs inside the transaction that records the push, which only starts once the device has
    accepted the users, so a failed push leaves the database as it was.
    """
    row = device_row(conn, device_id)
    people = _people_for_push(conn, device_id, person_ids, level_id, course_id)
    if not people:
        raise ServiceError("Nobody to push.")
    k40 = factory(target_for(row))

    on_device = {int(u.user_id) for u in k40.read_users() if str(u.user_id).isdigit()}
    snap = k40.snapshot()
    _check_serial(conn, row, snap.serial)
    adding = [p for p in people if p["device_user_id"] not in on_device]
    after = snap.users + len(adding)
    if after > snap.user_capacity:
        raise ServiceError(
            f"The device holds {snap.user_capacity} users and has {snap.users}. Adding {len(adding)} would make "
            f"{after}. Nothing was pushed."
        )

    changes = changes or {}
    sent = [{**dict(p), **changes.get(p["id"], {})} for p in people]
    payload = [{"user_id": p["device_user_id"], "name": p["device_name"], "privilege": p["device_privilege"],
                "password": p["device_password"] or ""} for p in sent]
    jobs.start(f"Sending people to {row['name']}", total=len(payload),
               detail=f"{len(payload)} to write, {len(adding)} of them new")
    try:
        k40.push_users(payload, on_each=jobs.at)
        jobs.finish("done", f"{len(payload)} written to {row['name']}")
    except Exception:
        jobs.finish("failed", "nothing was changed on the terminal")
        raise

    stamp = db.now()
    with db.transaction(conn):
        if then is not None:
            then(conn)
        for p in people:
            conn.execute("UPDATE people SET on_device = 1, pushed_at = ? WHERE id = ?", (stamp, p["id"]))
        db.audit(conn, account_id, "device.push_users", "devices", device_id,
                 f"{len(people)} pushed, {len(adding)} new, admins: "
                 f"{[p['device_user_id'] for p in sent if p['device_privilege'] == ADMIN]}")
    return {"pushed": len(people), "new_on_device": len(adding), "device_users_after": after,
            "capacity": snap.user_capacity}


def sync_fingers(conn: sqlite3.Connection, device_id: int, factory: K40Factory = K40) -> dict:
    """Read users and templates back and update what the app believes is on the device."""
    row = device_row(conn, device_id)
    k40 = factory(target_for(row))
    users = k40.read_users()
    templates = k40.read_templates()
    user_ids = {int(u.user_id) for u in users if str(u.user_id).isdigit()}
    by_user: dict[int, list] = {}
    for t in templates:
        by_user.setdefault(t.user_id, []).append(t)

    stamp = db.now()
    people = conn.execute("SELECT id, device_user_id FROM people WHERE device_id = ?", (device_id,)).fetchall()
    known_ids = {p["device_user_id"] for p in people}
    with db.transaction(conn):
        for p in people:
            conn.execute("UPDATE people SET on_device = ? WHERE id = ?", (1 if p["device_user_id"] in user_ids else 0, p["id"]))
            found = {t.finger_index: t for t in by_user.get(p["device_user_id"], [])}
            if found:
                conn.execute(
                    f"DELETE FROM fingers WHERE person_id = ? AND finger_index NOT IN ({','.join('?' * len(found))})",
                    [p["id"], *found.keys()],
                )
            else:
                conn.execute("DELETE FROM fingers WHERE person_id = ?", (p["id"],))
            for idx, t in found.items():
                conn.execute(
                    "INSERT INTO fingers(person_id, finger_index, template_size, first_seen_at, last_seen_at)"
                    " VALUES (?, ?, ?, ?, ?) ON CONFLICT(person_id, finger_index)"
                    " DO UPDATE SET template_size = excluded.template_size, last_seen_at = excluded.last_seen_at",
                    (p["id"], idx, t.size, stamp, stamp),
                )
    return {
        "device_users": len(users),
        "templates": len(templates),
        "unknown_device_users": sorted(u for u in user_ids if u not in known_ids),
        "missing_from_device": sorted(p["device_user_id"] for p in people if p["device_user_id"] not in user_ids),
    }


def clear_device_attendance(conn: sqlite3.Connection, device_id: int, account_id: int, confirm_serial: str,
                            factory: K40Factory = K40) -> dict:
    """Clear punches on the device only after proving every one of them is stored here."""
    row = device_row(conn, device_id)
    k40 = factory(target_for(row))
    serial, records = k40.read_attendance()
    _check_serial(conn, row, serial)
    if confirm_serial.strip() != serial:
        raise ServiceError("Type the device serial number exactly to confirm.")
    stored = store_punches(conn, device_id, records, "network", account_id, detail="pull before clear")
    # Scans from a deleted roster's device IDs are left out of every pull on purpose (levels.clear): the
    # person deleting the roster asked for its attendance to go. They are accounted for, not missing.
    # Counted as missing, they stopped the terminal ever being cleared again: "15 scans could not be
    # confirmed as stored" on the owner's K40 on 2026-09-23, every one of them from the deleted
    # dummy 200 Level.
    from . import levels
    retired = levels.retired_ranges(conn)
    deleted = 0
    missing = 0
    for r in records:
        if levels.is_retired(r.user_id, retired):
            deleted += 1
            continue
        exists = conn.execute(
            "SELECT 1 FROM punches WHERE device_user_id = ? AND timestamp = ? AND device_id = ?",
            (str(r.user_id).strip(), r.timestamp.replace(microsecond=0).isoformat(), device_id),
        ).fetchone()
        missing += 0 if exists else 1
    if missing:
        raise ServiceError(f"{missing} scans could not be confirmed as stored. The device was not cleared.")
    # A scan could land between the read and the clear, so the device checks its own count first.
    if not k40.clear_attendance_if_count(len(records)):
        raise ServiceError("New scans arrived while clearing. Nothing was cleared; try again.")
    with db.transaction(conn):
        db.audit(conn, account_id, "device.clear_attendance", "devices", device_id,
                 f"{len(records) - deleted} scans confirmed stored, then cleared"
                 + (f", with {deleted} from a deleted roster, not kept" if deleted else ""))
    return {"cleared": len(records), "from_deleted_roster": deleted, "pull": stored}


def remove_from_device(conn: sqlite3.Connection, device_id: int, person_id: int, account_id: int,
                       factory: K40Factory = K40) -> dict:
    """Take one person off the terminal, keeping their record and their scans here.

    For somebody who has left, or who was sent to the terminal by mistake. The terminal is changed
    first and the register follows: `on_device` goes to 0 and their fingerprints are forgotten,
    because the templates they name are gone.
    """
    row = device_row(conn, device_id)
    person = conn.execute("SELECT * FROM people WHERE id = ?", (person_id,)).fetchone()
    if person is None:
        raise ServiceError("Unknown person.")
    factory(target_for(row)).remove_person(person["device_user_id"])
    name = f"{person['surname']} {person['other_names']}".strip()
    with db.transaction(conn):
        conn.execute("UPDATE people SET on_device = 0 WHERE id = ?", (person_id,))
        conn.execute("DELETE FROM fingers WHERE person_id = ?", (person_id,))
        db.audit(conn, account_id, "device.remove_person", "people", person_id,
                 f"{person['matric_no'] or ''} {name}, device ID {person['device_user_id']}".strip())
    return {"person_id": person_id, "on_device": False}


def empty_device_people(conn: sqlite3.Connection, device_id: int, account_id: int,
                        confirm_serial: str, factory: K40Factory = K40) -> dict:
    """Take everybody and every fingerprint off the terminal, leaving the scans on it alone.

    The serial has to be typed, as it does for clearing the scans, because this is the other thing
    on this screen that cannot be undone from the app: every student has to be sent again and every
    finger enrolled again.
    """
    row = device_row(conn, device_id)
    k40 = factory(target_for(row))
    serial = k40.read_serial()
    _check_serial(conn, row, serial)
    if confirm_serial.strip() != serial:
        raise ServiceError("Type the device serial number exactly to confirm.")
    jobs.start(f"Emptying {row['name']}", detail="reading who is on it")
    try:
        done = k40.empty_people(
            on_start=lambda total: jobs.expect(total, f"{total} people to take off"),
            on_each=jobs.at)
        jobs.finish("done", f"{done['removed']} people and their fingerprints taken off")
    except Exception:
        jobs.finish("failed", "the terminal was left as it was found")
        raise
    if done["left"]:
        raise ServiceError(f"{done['left']} people are still on the terminal. Nothing else was changed.")
    with db.transaction(conn):
        conn.execute("UPDATE people SET on_device = 0")
        conn.execute("DELETE FROM fingers")
        db.audit(conn, account_id, "device.empty", "devices", device_id,
                 f"{done['removed']} people and their fingerprints taken off the terminal")
    return done


def _empty_block_everywhere(conn: sqlite3.Connection, level: sqlite3.Row, factory: K40Factory) -> str:
    """Take a level's block of IDs off every terminal, or raise and change nothing here.

    Asked for on 2026-09-23: deleting a level takes its fingerprints off the terminal, and is not
    allowed while the terminal cannot be reached. Every terminal is emptied before the register is
    touched, so a cable pulled half way leaves the register whole and the button can be pressed again.
    """
    start, end = level["id_block_start"], level["id_block_end"]
    notes = []
    for row in conn.execute("SELECT * FROM devices ORDER BY id").fetchall():
        k40 = factory(target_for(row))
        jobs.start(f"Taking {level['name']} off {row['name']}", detail="reading who is on it")
        try:
            removed = k40.remove_block(
                start, end,
                on_start=lambda total: jobs.expect(total, f"{total} students to take off"),
                on_each=jobs.at)
            jobs.finish("done", f"{removed} students and their fingerprints taken off")
        except DeviceError as error:
            jobs.finish("failed", "nothing was deleted from the register")
            if isinstance(error, DeviceBusy) or error.code == "user_not_deleted":
                raise
            raise DeviceError(
                f"{row['name']} did not answer, so nothing was deleted. {error.message}",
                "Deleting a level takes its students' fingerprints off the terminal as well, so the "
                "terminal has to be switched on and connected. Check it answers on the Device "
                "screen, then try again.",
                error.code) from error
        except Exception:
            jobs.finish("failed", "nothing was deleted from the register")
            raise
        notes.append(f"{removed} {'student' if removed == 1 else 'students'} taken off {row['name']}")
    return ", ".join(notes)


def clear_level(conn: sqlite3.Connection, level_id: int, confirm: str, account_id: int | None,
                factory: K40Factory = K40) -> dict:
    """Delete a level's roster and everything on it: the terminal first, then the register."""
    from . import backups, levels
    level = levels.check_clear(conn, level_id, confirm)
    note = _empty_block_everywhere(conn, level, factory)
    # A copy of the register as it was, because nothing in the app can bring this back.
    backup = backups.take(conn, "before-deleting-a-roster")
    result = levels.clear(conn, level_id, account_id, terminal_note=note)
    return {**result, "terminal": note, "backup": backup.name if backup else None}


def remove_level(conn: sqlite3.Connection, level_id: int, account_id: int | None,
                 factory: K40Factory = K40) -> dict:
    """Remove an empty level, after taking anybody in its block off the terminal."""
    from . import levels
    level = conn.execute("SELECT * FROM levels WHERE id = ?", (level_id,)).fetchone()
    if level is None:
        raise levels.LevelError("Unknown level.")
    why = levels.why_not_removable(conn, level_id)
    if why:
        raise levels.LevelError(why)
    _empty_block_everywhere(conn, level, factory)
    return levels.remove(conn, level_id, account_id)


# What a restart usually takes, for the bar. Measured on the K40 on 2026-09-22: 35 seconds twice,
# from the command to the terminal answering again. The wait itself allows up to two minutes.
RESTART_SECONDS = 45


def restart_device(conn: sqlite3.Connection, device_id: int, account_id: int | None,
                   factory: K40Factory = K40, **timing) -> dict:
    """Restart the terminal from here and wait for it to answer again.

    For a terminal that answers the enrol command with OK and never asks for a finger. On
    2026-09-22 this K40 did that for over an hour and nothing sent to it changed it; a restart did,
    and it came back in 35 seconds still holding its user. Nothing on the terminal is lost: people,
    fingerprints and scans all live in its flash.
    """
    row = device_row(conn, device_id)
    jobs.start(f"Restarting {row['name']}", total=RESTART_SECONDS,
               detail="its screen goes dark and comes back, usually in about 35 seconds")
    try:
        took = factory(target_for(row)).restart(
            on_wait=lambda gone: jobs.at(min(int(gone), RESTART_SECONDS - 1)), **timing)
        jobs.finish("done", f"{row['name']} is back after {int(took)} seconds")
    except Exception:
        jobs.finish("failed", "the terminal did not answer again in time")
        raise
    db.audit(conn, account_id, "device.restart", "devices", device_id,
             f"back after {int(took)} seconds")
    return {"back_after_seconds": int(took)}


def forget_fingers(conn: sqlite3.Connection, account_id: int, level_id: int | None = None) -> dict:
    """Forget the fingerprints this register has recorded. Does not touch the terminal.

    For when the terminal was emptied from its own menu, or reset by somebody else, and the register
    is left claiming fingerprints that are no longer on it. Emptying the terminal from Herewise
    already does this as part of the same action; this is the other half, for when Herewise was not
    the one that did it.

    It removes a record, not a fingerprint: the templates live on the terminal and nowhere else, so
    if they are still on it, Check what is on it puts these rows straight back. That is the point.
    """
    where, params = "", []
    if level_id is not None:
        level = conn.execute("SELECT name FROM levels WHERE id = ?", (level_id,)).fetchone()
        if level is None:
            raise ServiceError("Unknown level.")
        where = (" WHERE person_id IN (SELECT m.person_id FROM level_memberships m"
                 " JOIN academic_sessions a ON a.id = m.academic_session_id AND a.is_current = 1"
                 " WHERE m.level_id = ?)")
        params = [level_id]
    count = conn.execute(f"SELECT COUNT(*) FROM fingers{where}", params).fetchone()[0]
    whose = f"{level['name']}" if level_id is not None else "every level"
    with db.transaction(conn):
        conn.execute(f"DELETE FROM fingers{where}", params)
        db.audit(conn, account_id, "finger.forget", "devices", None,
                 f"{count} fingerprint records for {whose}, which does not touch the terminal")
    return {"forgotten": count, "whose": whose}


def unlock_menu(conn: sqlite3.Connection, device_id: int, account_id: int, confirm_serial: str,
                factory: K40Factory = K40) -> dict:
    row = device_row(conn, device_id)

    def before(serial: str) -> None:
        _check_serial(conn, row, serial)
        if confirm_serial.strip() != serial:
            raise ServiceError("Type the device serial number exactly to confirm.")

    demoted = factory(target_for(row)).demote_all_admins(before=before)
    # Only after the terminal has done it, so the database never claims an unlock that did not happen.
    # Keypad passwords stay, so choosing the same person again needs no new one.
    with db.transaction(conn):
        for user_id in demoted:
            if user_id.isdigit():
                conn.execute("UPDATE people SET device_privilege = ? WHERE device_id = ? AND device_user_id = ?",
                             (NORMAL, device_id, int(user_id)))
        db.audit(conn, account_id, "device.unlock_menu", "devices", device_id, f"demoted {demoted}")
    return {"demoted_user_ids": demoted,
            "note": "The keypad menu is open to anyone until a Super Admin is pushed again."}


def set_fallback_password(conn: sqlite3.Connection, person_id: int, password: str, reason: str,
                          account_id: int, factory: K40Factory = K40) -> dict:
    password = (password or "").strip()
    if not (password.isdigit() and 1 <= len(password) <= 8):
        raise ServiceError("The keypad password must be 1 to 8 digits.")
    if not (reason or "").strip():
        raise ServiceError("Record why this student needs a password instead of a fingerprint.")
    person = conn.execute("SELECT * FROM people WHERE id = ?", (person_id,)).fetchone()
    if person is None:
        raise ServiceError("Unknown person.")

    # Saved only once the device has the password, or the student would count as enrolled without it.
    def save(c: sqlite3.Connection) -> None:
        c.execute("UPDATE people SET device_password = ?, password_reason = ? WHERE id = ?",
                  (password, reason.strip(), person_id))
        db.audit(c, account_id, "person.fallback_password", "people", person_id, reason.strip())

    push = push_people(conn, person["device_id"], account_id, person_ids=[person_id], factory=factory,
                       changes={person_id: {"device_password": password}}, then=save)
    return {"person_id": person_id, "pushed": push["pushed"]}


def roles_summary(conn: sqlite3.Connection, device_id: int) -> dict:
    admins = conn.execute(
        "SELECT id, device_user_id, surname, other_names, device_password IS NOT NULL AS has_password,"
        " (SELECT COUNT(*) FROM fingers f WHERE f.person_id = people.id) AS fingers"
        f" FROM people WHERE device_id = ? AND {COUNTED_ADMIN}", (device_id, ADMIN)).fetchall()
    warnings = []
    if not admins:
        warnings.append("No Super Admin is set. Anyone at the device can open the menu and delete all data.")
    elif len(admins) == 1:
        warnings.append("Only one Super Admin. Add a second so one absence or injury cannot lock the menu.")
    for a in admins:
        if not a["has_password"]:
            warnings.append(f"Admin {a['device_user_id']} has no keypad password.")
        if a["fingers"] < 2:
            count = a["fingers"]
            has = "no fingers" if count == 0 else "one finger" if count == 1 else f"{count} fingers"
            warnings.append(f"Admin {a['device_user_id']} has {has} enrolled, and needs two.")
    return {"admins": [dict(a) for a in admins], "warnings": warnings, "normal_value": NORMAL, "admin_value": ADMIN}
