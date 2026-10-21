"""Automatic copies of the database, taken after every pull that stored something.

The complaint that ends an attendance app is a lost register: in a corpus of 177 negative reviews of
five attendance apps, "data lost or wiped" was the joint largest theme (vault
`50-Research/herewise-competitors-2026-09-19/THEMES.md`). A lecturer should never have to remember to
take a backup, so the app takes one at the moment the register changes, keeps the most recent ones and
deletes the rest.

A copy holds what the database holds, keypad passwords included (known gap 18), and stays in the data
folder beside it, with the same protection and no more.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

from . import db

PREFIX = "auto-"
SUFFIX = ".db"


def database_path(conn: sqlite3.Connection) -> Path | None:
    row = conn.execute("PRAGMA database_list").fetchone()
    source = row["file"] if row is not None else ""
    return Path(source) if source else None      # None for an in-memory database


def folder(conn: sqlite3.Connection) -> Path | None:
    path = database_path(conn)
    return (path.parent / "backups") if path else None


def take(conn: sqlite3.Connection, reason: str, keep: int = 10) -> Path | None:
    """Copy the database into backups/ and keep only the newest ``keep`` automatic copies."""
    place = folder(conn)
    if place is None:
        return None
    place.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    destination = place / f"{PREFIX}{stamp}-{reason}{SUFFIX}"
    copy = sqlite3.connect(str(destination))
    try:
        conn.backup(copy)                        # SQLite's online backup: safe while the app is running
    finally:
        copy.close()
    prune(place, keep)
    return destination


def prune(place: Path, keep: int) -> list[Path]:
    """Delete the oldest automatic copies past ``keep``. Copies made before a schema change stay."""
    automatic = sorted(place.glob(f"{PREFIX}*{SUFFIX}"), key=lambda p: p.name)
    dropped = automatic[:-keep] if keep > 0 else automatic
    for path in dropped:
        path.unlink(missing_ok=True)
    return dropped


def listing(conn: sqlite3.Connection) -> list[dict]:
    """Every copy in backups/, newest first, for the Backup screen to show the last one."""
    place = folder(conn)
    if place is None or not place.is_dir():
        return []
    rows = []
    for path in place.glob(f"*{SUFFIX}"):
        stat = path.stat()
        rows.append({"name": path.name, "bytes": stat.st_size,
                     "taken_at": datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds"),
                     "automatic": path.name.startswith(PREFIX)})
    return sorted(rows, key=lambda r: r["taken_at"], reverse=True)


def after_pull(conn: sqlite3.Connection, result: dict, account_id: int | None) -> dict | None:
    """Take a copy when a pull stored new scans, unless the setting is off. Never fails the pull."""
    if db.get_setting(conn, "auto_backup_after_pull") != "1" or not result.get("new"):
        return None
    try:
        keep = int(db.get_setting(conn, "backup_keep"))
        path = take(conn, "after-pull", keep)
    except Exception:                            # a backup must never lose the scans just stored
        db.audit(conn, account_id, "backup.auto.failed", detail="after pull")
        return None
    if path is None:
        return None
    db.audit(conn, account_id, "backup.auto", detail=path.name)
    return {"name": path.name, "bytes": path.stat().st_size}
