"""Restoring the register from a backup (known gap 14).

A backup is the whole register in one SQLite file, so restoring one replaces the whole register. It
is the most destructive thing Herewise can do, so it goes in two steps and nothing changes until the
second:

1. **Look.** The file is copied into the data folder and opened read-only. It must be a SQLite file,
   undamaged (`integrity_check`), a Herewise register (its tables are there), from this version of
   Herewise or an older one, and it must hold at least one enabled owner account, because restoring
   a register nobody can sign in to would lock everyone out for good. The screen shows what the
   backup holds beside what the register holds now.

2. **Replace**, with the password of the account doing it. The register as it is now is copied to
   `backups/before-restore-<when>.db` first, which is never pruned and can itself be restored, so a
   restore can always be undone. The backup is then written into the live database through SQLite's
   backup API, in one step. That is one transaction on the live file, so a failure half way leaves
   the register as it was; and it goes through SQLite rather than round it, so the write-ahead log
   beside the live file can never be left describing a different database, which copying a file
   over it could do.

Afterwards the schema is brought up to date, every signed-in session ends (the accounts are the
backup's now, with the passwords they had then), and the restore is written into the restored
register's own activity log, naming who did it and where the register as it was is kept.
"""
from __future__ import annotations

import re
import secrets
import shutil
import sqlite3
import time
from datetime import datetime
from pathlib import Path

from . import db

HEADER = b"SQLite format 3\x00"
STAGING = "restore-staging"
STAGE_LIFETIME_SECONDS = 3600
TOKEN = re.compile(r"^[0-9a-f]{32}$")
BEFORE_PREFIX = "before-restore-"

# Tables every Herewise register has had since the first schema (courses arrived in schema 4, so it
# is not one of them). Anything without these is some other database, however valid.
REQUIRED = {"accounts", "people", "punches", "class_sessions", "attendance_marks", "audit_log",
            "levels", "settings", "academic_sessions"}


class RestoreError(Exception):
    """A backup that cannot be restored, with the sentence the person reads."""


# -- staging ----------------------------------------------------------------------------------

def staging_folder(data_folder: Path) -> Path:
    place = data_folder / STAGING
    place.mkdir(parents=True, exist_ok=True)
    # A file looked at and never restored is thrown away after an hour, so the folder never keeps a
    # second copy of somebody's register, keypad passwords and all, for longer than it is needed.
    cutoff = time.time() - STAGE_LIFETIME_SECONDS
    for old in [*place.glob("*.db"), *place.glob("*.label")]:
        if old.stat().st_mtime < cutoff:
            old.unlink(missing_ok=True)
    return place


def _label(place: Path, token: str, label: str) -> None:
    # What the activity log will call the file, kept here rather than trusted from the browser.
    (place / f"{token}.label").write_text(label, encoding="utf-8")


def stage_upload(data_folder: Path, source, filename: str) -> str:
    """Copy an uploaded file into the staging folder and return the token that names it."""
    token = secrets.token_hex(16)
    place = staging_folder(data_folder)
    with (place / f"{token}.db").open("wb") as out:
        shutil.copyfileobj(source, out, length=1 << 20)
    _label(place, token, f"the file {Path(filename or 'backup.db').name}")
    return token


def stage_copy(data_folder: Path, backups_folder: Path, name: str) -> str:
    """Stage one of the copies in backups/. Only a plain file name from that folder is accepted."""
    if Path(name).name != name or "\\" in name or not name.endswith(".db"):
        raise RestoreError("That is not one of the copies on this computer.")
    source = backups_folder / name
    if not source.is_file():
        raise RestoreError("That copy is not on this computer any more.")
    token = secrets.token_hex(16)
    place = staging_folder(data_folder)
    shutil.copy2(source, place / f"{token}.db")
    _label(place, token, f"the copy {name}")
    return token


def staged(data_folder: Path, token: str) -> Path:
    path = data_folder / STAGING / f"{token}.db"
    if not TOKEN.match(token or "") or not path.is_file():
        raise RestoreError("That backup is no longer waiting to be restored. Choose it again.")
    return path


def label_of(data_folder: Path, token: str) -> str:
    path = data_folder / STAGING / f"{token}.label"
    return path.read_text(encoding="utf-8") if TOKEN.match(token or "") and path.is_file() else "a backup"


def discard(data_folder: Path, token: str) -> None:
    if TOKEN.match(token or ""):
        for suffix in (".db", ".label"):
            (data_folder / STAGING / f"{token}{suffix}").unlink(missing_ok=True)


# -- looking ----------------------------------------------------------------------------------

def _read_only(path: Path) -> sqlite3.Connection:
    # immutable: nothing may write to the file, not even SQLite recovering a journal, so looking at a
    # backup can never change it.
    conn = sqlite3.connect(f"file:{path.as_posix()}?mode=ro&immutable=1", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def summary(conn: sqlite3.Connection) -> dict:
    """What a register holds, in the terms a lecturer would check it by."""
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}

    def one(sql: str, default=None):
        try:
            row = conn.execute(sql).fetchone()
        except sqlite3.Error:
            return default
        return row[0] if row and row[0] is not None else default

    owner_sql = ("SELECT COUNT(*) FROM accounts a JOIN roles r ON r.id = a.role_id"
                 " WHERE r.is_owner = 1 AND a.disabled = 0") if "roles" in tables else \
        "SELECT COUNT(*) FROM accounts WHERE disabled = 0"
    usernames = []
    try:
        usernames = [r[0] for r in conn.execute(
            "SELECT username FROM accounts WHERE disabled = 0 ORDER BY id")]
    except sqlite3.Error:
        pass
    return {
        "schema": one("PRAGMA user_version", 0),
        "last_change": one("SELECT MAX(at) FROM audit_log"),
        "academic_session": one("SELECT name FROM academic_sessions WHERE is_current = 1"),
        "students": one("SELECT COUNT(*) FROM people WHERE role = 'student' AND active = 1", 0),
        "courses": one("SELECT COUNT(*) FROM courses", 0),
        "classes": one("SELECT COUNT(*) FROM class_sessions WHERE cancelled_at IS NULL", 0),
        "scans": one("SELECT COUNT(*) FROM punches", 0),
        "last_scan": one("SELECT MAX(timestamp) FROM punches"),
        "corrections": one("SELECT COUNT(*) FROM attendance_marks", 0),
        "owners": one(owner_sql, 0),
        "accounts": usernames,
    }


def inspect(path: Path, need_owner: bool = True) -> dict:
    """Everything that decides whether a file can be restored, and what it holds. Raises
    RestoreError with the reason when it cannot.

    ``need_owner`` is off for importing data at first run, where the person importing makes the
    owner account themselves and nobody signs in with the file's accounts.
    """
    with path.open("rb") as handle:
        if handle.read(16) != HEADER:
            raise RestoreError("This file is not a Herewise backup. It is not a database at all.")
    try:
        conn = _read_only(path)
    except sqlite3.Error as error:
        raise RestoreError("This file could not be opened as a database.") from error
    try:
        try:
            integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
        except sqlite3.DatabaseError as error:
            raise RestoreError("This backup is damaged, so it cannot be restored. Try an older "
                               "copy.") from error
        if integrity != "ok":
            raise RestoreError("This backup is damaged, so it cannot be restored. Try an older copy.")
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        if version == 0 or REQUIRED - tables:
            raise RestoreError("This file is a database, but not a Herewise register.")
        if version > db.SCHEMA_VERSION:
            raise RestoreError("This backup was made by a newer version of Herewise. Install that "
                               "version on this computer first, then restore it.")
        held = summary(conn)
    finally:
        conn.close()
    if need_owner and not held["owners"]:
        raise RestoreError("Nobody could sign in to this backup: it has no enabled owner account. "
                           "Restoring it would lock everyone out, so it cannot be restored.")
    return held


# -- replacing --------------------------------------------------------------------------------

def keep_current(live: sqlite3.Connection, backups_folder: Path) -> Path:
    """Copy the register as it is now, under a name the automatic clean-up never touches."""
    backups_folder.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    destination = backups_folder / f"{BEFORE_PREFIX}{stamp}.db"
    copy = sqlite3.connect(str(destination))
    try:
        live.backup(copy)
    finally:
        copy.close()
    return destination


def restore(live: sqlite3.Connection, source: Path, backups_folder: Path, restorer: sqlite3.Row,
            source_label: str) -> dict:
    """Replace the live register with ``source``. The caller has checked the password."""
    held = inspect(source)                 # again: the file may have changed since it was looked at
    kept = keep_current(live, backups_folder)

    backup = _read_only(source)
    try:
        backup.backup(live)                # every page, in one step and one transaction on the live file
    except sqlite3.Error as error:
        raise RestoreError("The backup could not be written into the register, so nothing has "
                           f"changed. The register as it was is also kept as {kept.name}.") from error
    finally:
        backup.close()

    db.initialise(live)                    # an older backup is brought up to this version's schema
    with db.transaction(live):
        live.execute("DELETE FROM auth_sessions")
        live.execute("DELETE FROM setup_drafts")
        same = live.execute("SELECT id FROM accounts WHERE username = ?",
                            (restorer["username"],)).fetchone()
        db.audit(live, same["id"] if same else None, "backup.restore", detail=(
            f"{restorer['display_name']} ({restorer['username']}) restored {source_label}, as it "
            f"was on {readable(held['last_change'])}. The register as it was before is kept as "
            f"backups/{kept.name}"))
    return {"restored": summary(live), "kept": kept.name}


def terminal_of(path: Path) -> dict | None:
    """The terminal a register was set up with, so the person importing it knows it comes along."""
    try:
        conn = _read_only(path)
    except sqlite3.Error:
        return None
    try:
        row = conn.execute("SELECT name, ip, port FROM devices ORDER BY is_default DESC, id LIMIT 1").fetchone()
    except sqlite3.Error:
        row = None
    finally:
        conn.close()
    return {"name": row["name"], "ip": row["ip"], "port": row["port"]} if row else None


# -- importing the data on a new computer ------------------------------------------------------------
#
# Asked for on 2026-09-23: set the register up on one laptop and "move it all with all the data" to
# the lecturer's, then, in the same session: "only the data, not the account name and password", from
# an optional "already used Herewise? Import your data" on the first screen.
#
# So the lecturer makes their own account, and the file's accounts come across switched off with
# their passwords wiped. They cannot simply be deleted: every correction, excused absence and class
# names the account that made it (attendance_marks.account_id is NOT NULL and a foreign key), and
# that is the record of who signed what. Kept switched off, they sign nothing in and still say who
# did what. The new owner can switch one back on from Accounts and give it a new password.

MOVED = "moved"            # not an scrypt hash, so verify_password can never match it


def _free_username(conn: sqlite3.Connection, wanted: str) -> None:
    """Move an old account off the username the new owner has chosen, so theirs can have it."""
    clash = conn.execute("SELECT id, username FROM accounts WHERE username = ? COLLATE NOCASE",
                         (wanted,)).fetchone()
    if clash is None:
        return
    number = 1
    while True:
        spare = f"{clash['username']}-previous" + (f"-{number}" if number > 1 else "")
        if not conn.execute("SELECT 1 FROM accounts WHERE username = ? COLLATE NOCASE", (spare,)).fetchone():
            conn.execute("UPDATE accounts SET username = ? WHERE id = ?", (spare, clash["id"]))
            return
        number += 1


def import_data(live: sqlite3.Connection, source: Path, backups_folder: Path, username: str,
                display_name: str, password: str, source_label: str) -> dict:
    """Bring another computer's data into this empty register, with a new owner account.

    Everything is checked before the register is touched. If anything fails after the swap, the
    register as it was (empty) is put back, so a half-imported register nobody can sign in to never
    exists.
    """
    from . import auth, roles

    username, display_name = (username or "").strip(), (display_name or "").strip()
    if not username or not display_name:
        raise RestoreError("Give your name and a username to sign in with.")
    try:
        auth.validate_new_password(password)
    except ValueError as error:
        raise RestoreError(str(error)) from error
    held = inspect(source, need_owner=False)
    kept = keep_current(live, backups_folder)

    backup = _read_only(source)
    try:
        backup.backup(live)
    except sqlite3.Error as error:
        raise RestoreError("The data could not be brought in, so nothing has changed.") from error
    finally:
        backup.close()

    try:
        db.initialise(live)
        with db.transaction(live):
            live.execute("DELETE FROM auth_sessions")
            live.execute("DELETE FROM setup_drafts")
            others = live.execute("SELECT COUNT(*) FROM accounts").fetchone()[0]
            live.execute("UPDATE accounts SET disabled = 1, password_hash = ?", (MOVED,))
            _free_username(live, username)
            account_id = auth.create_account(live, username, display_name, password,
                                             roles.owner_role_id(live))
            db.audit(live, account_id, "backup.import", "accounts", account_id, (
                f"{display_name} ({username}) brought in the data from {source_label}, as it was on "
                f"{readable(held['last_change'])}. The {others} account{'s' if others != 1 else ''} "
                "from that computer came across switched off, with no password."))
    except Exception:
        put_back = sqlite3.connect(str(kept))
        try:
            put_back.backup(live)
        finally:
            put_back.close()
        raise
    return {"imported": summary(live), "account_id": account_id, "accounts_switched_off": others}


def readable(stamp: str | None) -> str:
    """'2026-09-21T10:14:59' as a person writes it: 21 September 2026 at 10:14."""
    if not stamp:
        return "an unknown date"
    try:
        moment = datetime.fromisoformat(stamp)
    except ValueError:
        return stamp
    return f"{moment.day} {moment:%B %Y} at {moment:%H:%M}"
