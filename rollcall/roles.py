"""Roles people can create, name and edit, built from a fixed vocabulary of permissions.

Two halves, and the split is the whole design:

  Permissions are fixed and live in this file. Code enforces them, so no one can invent one: a
  permission that nothing checks is a lie told to whoever ticks it.

  Roles are rows. Anyone with `roles.manage` can create a role, name it what they like, describe it,
  tick the permissions it carries, rename it later and delete it. "Lecturer", "Course rep" and
  "Viewer" are only the three seeded at setup, and two of them can be renamed or deleted like any
  other.

The owner role is the exception. Exactly one role has `is_owner`, it always holds every permission
including ones added by a later version, and it cannot be edited away or deleted. Without it a
database can reach a state where nobody can grant anybody anything, which is unrecoverable without
editing SQLite by hand.
"""
from __future__ import annotations

import sqlite3

from . import db


class RoleError(Exception):
    pass


# key: (group, label, what holding it lets someone do)
PERMISSIONS: dict[str, tuple[str, str, str]] = {
    "register.read": ("Attendance", "See registers",
                      "Open courses, classes, registers, the attendance sheet and the percentages."),
    "register.pull": ("Attendance", "Get attendance from the device",
                      "Pull scans off the terminal and let classes be detected from them."),
    "register.correct": ("Attendance", "Correct attendance",
                         "Mark a student present or absent with a note. The correction is signed with"
                         " the name of whoever applies it."),
    "register.request": ("Attendance", "Ask for a correction",
                         "Raise a correction request for someone whose role allows it to approve"
                         " or reject."),
    "register.approve": ("Attendance", "Approve correction requests",
                         "Approve or reject requests other people raised."),
    "class.manage": ("Attendance", "Create and cancel classes",
                     "Record a class by hand, cancel one with a note, and put a detected class on a course."),
    "excusal.manage": ("Attendance", "Grant excused absences",
                       "Record and withdraw excused absences."),
    "plan.manage": ("Attendance", "Set weeks and the threshold",
                    "Edit the attendance sheet template, the weeks, the classes per week and the"
                    " percentage a student needs."),

    "eligibility.view": ("Eligibility", "See the eligibility list",
                         "See who may and may not sit the examination."),
    "eligibility.export": ("Eligibility", "Export the eligibility list",
                           "Produce the signed PDF or Excel eligibility list."),

    "students.read": ("People", "Search students",
                      "Search for a student and open their attendance evidence."),
    "roster.manage": ("People", "Import and edit the roster",
                      "Import a roster, edit levels, add staff, and remove a student with a note."),
    "courses.manage": ("People", "Manage courses",
                       "Create and edit courses and add or remove carry-over students."),
    "enrollment.run": ("People", "Enrol fingerprints",
                       "Run fingerprint enrolment on the terminal."),

    "device.read": ("Device", "See device status",
                    "See whether the terminal is reachable, its counts, and run the diagnostics."),
    "device.manage": ("Device", "Change the device",
                      "Push users, sync the clock and fingerprints, clear attendance on the terminal,"
                      " unlock the keypad menu and set Super Admins."),

    "accounts.manage": ("Administration", "Manage accounts",
                        "Create accounts, disable them and change which role someone has."),
    "roles.manage": ("Administration", "Manage roles",
                     "Create, rename, edit and delete roles, and choose what each one can do."),
    "settings.manage": ("Administration", "Change settings",
                        "Edit the grace periods, the academic session and the other settings."),
    "audit.read": ("Administration", "Read the audit log",
                   "See the record of who did what."),
    "backup.run": ("Administration", "Take a backup",
                   "Download a copy of the database."),
    # Separate from taking one, because restoring replaces the whole register. Only the owner holds
    # it until somebody ticks it for another role.
    "backup.restore": ("Administration", "Restore from a backup",
                       "Replace the whole register with a backup. The register as it was is kept"
                       " as a copy first, so a restore can be undone."),
}

ALL_PERMISSIONS = frozenset(PERMISSIONS)

GROUPS = ["Attendance", "Eligibility", "People", "Device", "Administration"]

# The three seeded at setup. Only the owner is protected; the other two are ordinary rows that can be
# renamed, re-ticked or deleted.
OWNER_ROLE = "Lecturer"

SEED_ROLES: list[tuple[str, str, bool, list[str]]] = [
    (OWNER_ROLE, "Owns the register. Can do everything, and cannot be edited or deleted.", True, []),
    ("Course rep", "Runs a class on the day: pulls attendance and asks for corrections, but cannot"
                   " apply one.", False,
     ["register.read", "register.pull", "register.request", "class.manage", "students.read",
      "device.read"]),
    ("Viewer", "Reads registers and percentages, changes nothing.", False,
     ["register.read", "students.read"]),
]


def describe() -> list[dict]:
    """The permission vocabulary, grouped, for the role editor screen."""
    out = []
    for group in GROUPS:
        items = [{"key": k, "label": v[1], "help": v[2]} for k, v in PERMISSIONS.items() if v[0] == group]
        out.append({"group": group, "permissions": items})
    return out


def denial(permission: str) -> str:
    label = PERMISSIONS.get(permission, (None, permission, ""))[1]
    return f"Your role does not allow this: {label.lower()}."


# -- reading ---------------------------------------------------------------------------------------

def permissions_for(conn: sqlite3.Connection, account: sqlite3.Row | int) -> frozenset[str]:
    account_id = account if isinstance(account, int) else account["id"]
    row = conn.execute(
        "SELECT r.id, r.is_owner FROM accounts a JOIN roles r ON r.id = a.role_id WHERE a.id = ?",
        (account_id,)).fetchone()
    if row is None:
        return frozenset()
    if row["is_owner"]:
        # Every permission, including any added by a later version. An owner who silently lost a new
        # permission on upgrade would be locked out of a feature with no way to grant it back.
        return ALL_PERMISSIONS
    return frozenset(
        r[0] for r in conn.execute("SELECT permission FROM role_permissions WHERE role_id = ?", (row["id"],))
        if r[0] in ALL_PERMISSIONS)


def has(conn: sqlite3.Connection, account: sqlite3.Row | int, permission: str) -> bool:
    return permission in permissions_for(conn, account)


def require(conn: sqlite3.Connection, account: sqlite3.Row | int, permission: str) -> None:
    if not has(conn, account, permission):
        raise RoleError(denial(permission))


def get_role(conn: sqlite3.Connection, role_id: int) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM roles WHERE id = ?", (role_id,)).fetchone()
    if row is None:
        raise RoleError("Unknown role.")
    return row


def owner_role_id(conn: sqlite3.Connection) -> int:
    row = conn.execute("SELECT id FROM roles WHERE is_owner = 1").fetchone()
    if row is None:
        raise RoleError("This database has no owner role.")
    return int(row["id"])


def list_roles(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute(
        "SELECT r.*, (SELECT COUNT(*) FROM accounts a WHERE a.role_id = r.id) AS account_count,"
        " (SELECT COUNT(*) FROM accounts a WHERE a.role_id = r.id AND a.disabled = 0) AS enabled_count"
        " FROM roles r ORDER BY r.is_owner DESC, r.name COLLATE NOCASE").fetchall()
    out = []
    for row in rows:
        item = dict(row)
        item["is_owner"] = bool(row["is_owner"])
        item["built_in"] = bool(row["built_in"])
        item["permissions"] = sorted(permissions_of_role(conn, row))
        out.append(item)
    return out


def permissions_of_role(conn: sqlite3.Connection, role: sqlite3.Row | int) -> frozenset[str]:
    if isinstance(role, int):
        role = get_role(conn, role)
    if role["is_owner"]:
        return ALL_PERMISSIONS
    return frozenset(
        r[0] for r in conn.execute("SELECT permission FROM role_permissions WHERE role_id = ?", (role["id"],))
        if r[0] in ALL_PERMISSIONS)


# -- writing ---------------------------------------------------------------------------------------

def _clean_name(name: str) -> str:
    name = (name or "").strip()
    if not name:
        raise RoleError("Give the role a name.")
    if len(name) > 40:
        raise RoleError("A role name must be 40 characters or fewer.")
    return name


def _clean_permissions(permissions) -> list[str]:
    wanted = [p.strip() for p in (permissions or [])]
    unknown = [p for p in wanted if p not in ALL_PERMISSIONS]
    if unknown:
        raise RoleError(f"Not a permission this app has: {', '.join(sorted(set(unknown)))}.")
    return sorted(set(wanted))


def create_role(conn: sqlite3.Connection, name: str, description: str, permissions, account_id: int) -> int:
    name = _clean_name(name)
    wanted = _clean_permissions(permissions)
    with db.transaction(conn):
        try:
            cur = conn.execute(
                "INSERT INTO roles(name, description, is_owner, built_in, created_at, updated_at)"
                " VALUES (?, ?, 0, 0, ?, ?)",
                (name, (description or "").strip(), db.now(), db.now()))
        except sqlite3.IntegrityError:
            raise RoleError(f"There is already a role called {name}.")
        role_id = int(cur.lastrowid)
        conn.executemany("INSERT INTO role_permissions(role_id, permission) VALUES (?, ?)",
                         [(role_id, p) for p in wanted])
        db.audit(conn, account_id, "role.create", "roles", role_id,
                 f"{name} with {len(wanted)} permission(s)")
    return role_id


def update_role(conn: sqlite3.Connection, role_id: int, account_id: int, name: str | None = None,
                description: str | None = None, permissions=None) -> None:
    role = get_role(conn, role_id)
    if role["is_owner"] and permissions is not None:
        raise RoleError(f"{role['name']} owns the register and always has every permission. Give"
                        " someone a different role instead of taking permissions off this one.")
    new_name = role["name"] if name is None else _clean_name(name)
    new_description = role["description"] if description is None else (description or "").strip()
    detail = []
    if new_name != role["name"]:
        detail.append(f"renamed from {role['name']} to {new_name}")
    with db.transaction(conn):
        try:
            conn.execute("UPDATE roles SET name = ?, description = ?, updated_at = ? WHERE id = ?",
                         (new_name, new_description, db.now(), role_id))
        except sqlite3.IntegrityError:
            raise RoleError(f"There is already a role called {new_name}.")
        if permissions is not None:
            wanted = _clean_permissions(permissions)
            before = permissions_of_role(conn, role)
            conn.execute("DELETE FROM role_permissions WHERE role_id = ?", (role_id,))
            conn.executemany("INSERT INTO role_permissions(role_id, permission) VALUES (?, ?)",
                             [(role_id, p) for p in wanted])
            added = sorted(set(wanted) - before)
            removed = sorted(before - set(wanted))
            if added:
                detail.append("added " + ", ".join(added))
            if removed:
                detail.append("removed " + ", ".join(removed))
        db.audit(conn, account_id, "role.update", "roles", role_id, "; ".join(detail) or "no change")


def delete_role(conn: sqlite3.Connection, role_id: int, account_id: int) -> None:
    role = get_role(conn, role_id)
    if role["is_owner"]:
        raise RoleError(f"{role['name']} owns the register and cannot be deleted.")
    used = conn.execute("SELECT COUNT(*) FROM accounts WHERE role_id = ?", (role_id,)).fetchone()[0]
    if used:
        raise RoleError(f"{used} account(s) still have the {role['name']} role. Move them to another"
                        " role first.")
    with db.transaction(conn):
        conn.execute("DELETE FROM role_permissions WHERE role_id = ?", (role_id,))
        conn.execute("DELETE FROM roles WHERE id = ?", (role_id,))
        db.audit(conn, account_id, "role.delete", "roles", role_id, role["name"])


def assign_role(conn: sqlite3.Connection, target_account_id: int, role_id: int, account_id: int) -> None:
    role = get_role(conn, role_id)
    target = conn.execute("SELECT * FROM accounts WHERE id = ?", (target_account_id,)).fetchone()
    if target is None:
        raise RoleError("Unknown account.")
    if target["role_id"] != role_id:
        assert_owner_survives(conn, losing_account_id=target_account_id, new_role_id=role_id)
    with db.transaction(conn):
        conn.execute("UPDATE accounts SET role_id = ? WHERE id = ?", (role_id, target_account_id))
        db.audit(conn, account_id, "account.role", "accounts", target_account_id,
                 f"{target['username']} is now {role['name']}")


# -- the two invariants ----------------------------------------------------------------------------

def assert_owner_survives(conn: sqlite3.Connection, losing_account_id: int,
                          new_role_id: int | None = None) -> None:
    """Refuse to leave the database with no enabled account holding the owner role.

    Called before changing someone's role and before disabling them. Without this, demoting or
    disabling the last lecturer locks everyone out of accounts and roles for good, and the only way
    back is editing the SQLite file by hand.
    """
    owner_id = owner_role_id(conn)
    if new_role_id == owner_id:
        return
    remaining = conn.execute(
        "SELECT COUNT(*) FROM accounts WHERE role_id = ? AND disabled = 0 AND id <> ?",
        (owner_id, losing_account_id)).fetchone()[0]
    if remaining == 0:
        name = conn.execute("SELECT name FROM roles WHERE id = ?", (owner_id,)).fetchone()["name"]
        raise RoleError(f"This is the last enabled {name}. Give someone else that role first,"
                        " otherwise nobody can manage accounts or roles again.")


def refuse_self(conn: sqlite3.Connection, account_id: int, person_id: int, what: str) -> None:
    """Refuse an action by an account on the student record it belongs to.

    A course representative is on the register. Whatever permissions a role carries, someone marking
    their own attendance empties the correction trail of its meaning, so this is checked separately
    from permissions and cannot be granted away.
    """
    row = conn.execute("SELECT person_id, display_name FROM accounts WHERE id = ?", (account_id,)).fetchone()
    if row is None or row["person_id"] is None:
        return
    if int(row["person_id"]) == int(person_id):
        raise RoleError(f"You cannot {what} for yourself. Ask someone else to do it.")


def link_person(conn: sqlite3.Connection, target_account_id: int, person_id: int | None,
                account_id: int) -> None:
    """Tie an account to the student it belongs to, which is what makes `refuse_self` work."""
    if person_id is not None:
        person = conn.execute("SELECT id, surname, other_names FROM people WHERE id = ?", (person_id,)).fetchone()
        if person is None:
            raise RoleError("Unknown person.")
        clash = conn.execute("SELECT username FROM accounts WHERE person_id = ? AND id <> ?",
                             (person_id, target_account_id)).fetchone()
        if clash is not None:
            raise RoleError(f"{clash['username']} is already linked to that person.")
    with db.transaction(conn):
        conn.execute("UPDATE accounts SET person_id = ? WHERE id = ?", (person_id, target_account_id))
        db.audit(conn, account_id, "account.person", "accounts", target_account_id,
                 f"linked to person {person_id}" if person_id else "unlinked from a person")
