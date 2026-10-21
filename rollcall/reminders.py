"""Reminders the app raises for the lecturer, starting with Super Admin cover on each device.

* No Super Admin: anyone at the keypad can delete everything. This one can be put off but not
  cancelled, because the risk is to every record on the device.
* One Super Admin: one absence or cut finger locks the menu. The lecturer can choose a second admin,
  be reminded later, or cancel the reminder.

Only people on the terminal count. Someone saved as a Super Admin but never pushed cannot open the
menu, so counting them would turn the reminder that cannot be cancelled into one that can.

A reminder has no stored row while it is active. When its condition clears (a second admin is added),
any stored snooze or cancel is forgotten, so losing that admin later raises the reminder again.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta

from . import db
from .device import ADMIN

FIRST = "first_super_admin"
SECOND = "second_super_admin"


class ReminderError(ValueError):
    pass


# The Super Admins a device actually has: saved as admin, pushed, and still active.
COUNTED_ADMIN = "device_privilege = ? AND on_device = 1 AND active = 1"


def _admins(conn: sqlite3.Connection, device_id: int) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT id, device_user_id, surname, other_names, role FROM people"
        f" WHERE device_id = ? AND {COUNTED_ADMIN} ORDER BY device_user_id",
        (device_id, ADMIN),
    ).fetchall()


def count_admins(conn: sqlite3.Connection, device_id: int) -> int:
    return len(_admins(conn, device_id))


def _definitions(conn: sqlite3.Connection, device: sqlite3.Row) -> dict[str, dict]:
    admins = _admins(conn, device["id"])
    names = [f"{a['surname']} {a['other_names']}".strip() for a in admins]
    found: dict[str, dict] = {}
    if not admins:
        found[f"{FIRST}:{device['id']}"] = {
            "kind": FIRST,
            "title": "Set a Super Admin on the device",
            "message": (f"{device['name']} has no Super Admin, so anyone at the keypad can open the menu and "
                        "delete every user and scan. Choose who should be Super Admin, usually you."),
            "can_cancel": False,
        }
    elif len(admins) == 1:
        found[f"{SECOND}:{device['id']}"] = {
            "kind": SECOND,
            "title": "Choose a second Super Admin",
            "message": (f"{names[0]} is the only Super Admin on {device['name']}. If they are away or cannot "
                        "scan, nobody can open the device menu. Choose a second person you trust."),
            "can_cancel": True,
        }
    return found


def pending(conn: sqlite3.Connection) -> list[dict]:
    now = datetime.now()
    stored = {r["key"]: r for r in conn.execute("SELECT * FROM reminders")}
    result, live_keys = [], set()
    for device in conn.execute("SELECT * FROM devices ORDER BY id").fetchall():
        for key, reminder in _definitions(conn, device).items():
            live_keys.add(key)
            state = stored.get(key)
            if state is not None:
                if state["status"] == "dismissed" and reminder["can_cancel"]:
                    continue
                if state["status"] == "snoozed" and state["snoozed_until"] and \
                        datetime.fromisoformat(state["snoozed_until"]) > now:
                    continue
            result.append({"key": key, "device_id": device["id"], **reminder,
                           "actions": ["choose"] + ["remind_later"] + (["cancel"] if reminder["can_cancel"] else [])})

    # Forget snoozes and cancels for conditions that have cleared.
    cleared = [k for k in stored if k.split(":")[0] in (FIRST, SECOND) and k not in live_keys]
    for key in cleared:
        conn.execute("DELETE FROM reminders WHERE key = ?", (key,))
    return result


def _current(conn: sqlite3.Connection, key: str) -> dict:
    for device in conn.execute("SELECT * FROM devices").fetchall():
        definitions = _definitions(conn, device)
        if key in definitions:
            return definitions[key]
    raise ReminderError("That reminder is not active.")


# How long Remind me later puts a reminder off, fixed since 2026-09-23 (db.SCHEMA_V12).
SNOOZE_DAYS = 7


def remind_later(conn: sqlite3.Connection, key: str, days: int | None, account_id: int) -> dict:
    _current(conn, key)
    days = int(days if days is not None else SNOOZE_DAYS)
    if not 1 <= days <= 90:
        raise ReminderError("Remind again in 1 to 90 days.")
    until = (datetime.now() + timedelta(days=days)).isoformat(timespec="seconds")
    with db.transaction(conn):
        conn.execute(
            "INSERT INTO reminders(key, status, snoozed_until, account_id, updated_at) VALUES (?, 'snoozed', ?, ?, ?)"
            " ON CONFLICT(key) DO UPDATE SET status = 'snoozed', snoozed_until = excluded.snoozed_until,"
            " account_id = excluded.account_id, updated_at = excluded.updated_at",
            (key, until, account_id, db.now()),
        )
        db.audit(conn, account_id, "reminder.remind_later", detail=f"{key} until {until}")
    return {"key": key, "remind_after": until}


def cancel(conn: sqlite3.Connection, key: str, account_id: int) -> dict:
    reminder = _current(conn, key)
    if not reminder["can_cancel"]:
        raise ReminderError("This reminder cannot be cancelled while the device has no Super Admin. "
                            "Choose remind me later instead.")
    with db.transaction(conn):
        conn.execute(
            "INSERT INTO reminders(key, status, snoozed_until, account_id, updated_at) VALUES (?, 'dismissed', NULL, ?, ?)"
            " ON CONFLICT(key) DO UPDATE SET status = 'dismissed', snoozed_until = NULL,"
            " account_id = excluded.account_id, updated_at = excluded.updated_at",
            (key, account_id, db.now()),
        )
        db.audit(conn, account_id, "reminder.cancel", detail=key)
    return {"key": key, "cancelled": True}


def restore(conn: sqlite3.Connection, key: str, account_id: int) -> dict:
    """Undo a cancel or snooze so the reminder shows again straight away."""
    with db.transaction(conn):
        removed = conn.execute("DELETE FROM reminders WHERE key = ?", (key,)).rowcount
        if removed:
            db.audit(conn, account_id, "reminder.restore", detail=key)
    return {"key": key, "restored": bool(removed)}


def admin_candidates(conn: sqlite3.Connection, device_id: int) -> dict:
    """Everyone on this device the lecturer could make Super Admin, staff first."""
    rows = conn.execute(
        "SELECT p.id, p.role, p.device_user_id, p.matric_no, p.surname, p.other_names, p.device_privilege,"
        " p.device_password IS NOT NULL AS has_password, p.on_device,"
        " (SELECT COUNT(*) FROM fingers f WHERE f.person_id = p.id) AS fingers"
        " FROM people p WHERE p.device_id = ? AND p.active = 1"
        " ORDER BY p.role = 'student', p.device_user_id",
        (device_id,),
    ).fetchall()
    people = []
    for r in rows:
        item = dict(r)
        saved_admin = item.pop("device_privilege") == ADMIN
        item["is_super_admin"] = saved_admin and bool(item["on_device"])
        # Saved as Super Admin but not yet on the terminal, so not counted until pushed.
        item["awaiting_push"] = saved_admin and not item["on_device"]
        item["has_password"] = bool(item["has_password"])
        if item["role"] == "student":
            item["warning"] = ("A student Super Admin can open the device menu, delete scans on the device and "
                               "enrol fingers for other people.")
        people.append(item)
    return {"device_id": device_id, "current_admins": sum(1 for p in people if p["is_super_admin"]),
            "people": people}
