"""First-run setup: the draft store and the connection test that runs before any account exists.

Screen 1 saves and resumes, and writes nothing until its review step (`docs/SCREENS.md`), so the
answers need somewhere to live that is not the tables they will eventually become. They live in one
row of `setup_drafts`, which is deleted the moment setup finishes.

Both halves refuse once an account exists. They are the only unauthenticated routes that touch
anything, so the refusal is the whole of their security: after setup there is no way in without a
password, and before it there is nobody to ask for one.
"""
from __future__ import annotations

import json
import sqlite3

from . import db, diagnostics, netsetup
from .device import DeviceError, DeviceTarget, K40


class SetupError(ValueError):
    pass


def done(conn: sqlite3.Connection) -> bool:
    return bool(conn.execute("SELECT COUNT(*) FROM accounts").fetchone()[0])


def refuse_if_done(conn: sqlite3.Connection) -> None:
    if done(conn):
        raise SetupError("Setup has already been done. Sign in instead.")


def read_draft(conn: sqlite3.Connection) -> dict | None:
    row = conn.execute("SELECT payload, updated_at FROM setup_drafts WHERE id = 1").fetchone()
    if row is None:
        return None
    try:
        payload = json.loads(row["payload"])
    except ValueError:
        # A draft this app cannot read is worth less than a clean start, and there is nothing in it
        # yet that anybody would mourn.
        return None
    return {"draft": payload, "updated_at": row["updated_at"]}


def save_draft(conn: sqlite3.Connection, payload: dict) -> dict:
    """Keep the answers so far. The password is never among them: it is typed again at the review step."""
    payload = {k: v for k, v in payload.items() if k != "password"}
    stamp = db.now()
    with db.transaction(conn):
        conn.execute(
            "INSERT INTO setup_drafts(id, payload, updated_at) VALUES (1, ?, ?)"
            " ON CONFLICT(id) DO UPDATE SET payload = excluded.payload, updated_at = excluded.updated_at",
            (json.dumps(payload), stamp),
        )
    return {"draft": payload, "updated_at": stamp}


def clear_draft(conn: sqlite3.Connection) -> None:
    with db.transaction(conn):
        conn.execute("DELETE FROM setup_drafts WHERE id = 1")


# -- the connection test ---------------------------------------------------------------------------

# Named for the person reading them, in the order the chain is walked. The mockup's sixth line
# (serial and firmware) is not a diagnostic: it needs the terminal to answer a real read.
CHAIN_LABELS = {
    "cable": "Network cable",
    "pc_address": "This computer's address",
    "route": "Route to the terminal",
    "ping": "Terminal answers",
    "port": "Port {port}",
    "identity": "Serial and firmware",
}

NOT_CHECKED = "Not checked, an earlier step failed"
NOT_CHECKED_CABLE = "Not checked, the cable is out"


def test_connection(conn: sqlite3.Connection, ip: str, port: int, comm_key: int,
                    factory=K40) -> dict:
    """Walk the diagnostic chain, then read the terminal. No device row is needed, and none is made.

    `GET /api/devices/{id}/diagnose` cannot serve screen 1: it needs a saved device, and setup has
    not saved one yet (known gap 2 in `docs/PROJECT-HANDOFF.md`).
    """
    refuse_if_done(conn)
    # Read once, for the chain and for what can be done about this computer's Ethernet.
    adapters = diagnostics.physical_adapters()
    walked = diagnostics.diagnose(ip, port, adapters=adapters)
    network = netsetup.describe(ip, adapters, walked)
    checks = [dict(c) for c in diagnostics.as_dicts(walked)]
    first_broken = next((c for c in checks if not c["ok"]), None)
    # Only the first broken link speaks (`docs/DESIGN-BRIEF.md`, Diagnostic chain). The rest say why
    # they were not reached, so a hollow circle never looks like a pass.
    reached = True
    for check in checks:
        check["label"] = CHAIN_LABELS.get(check["name"], check["name"]).format(port=port)
        check["checked"] = reached
        if not reached:
            check["message"] = NOT_CHECKED_CABLE if first_broken and first_broken["name"] == "cable" else NOT_CHECKED
            # Its own result is suppressed, so `ok` is cleared with it. Leaving a true `ok` on a
            # suppressed step drew a tick beside "Not checked, the cable is out".
            check["ok"] = False
        elif not check["ok"]:
            reached = False

    identity: dict | None = None
    read: dict = {"name": "identity", "label": CHAIN_LABELS["identity"], "ok": False, "checked": reached,
                  "message": NOT_CHECKED_CABLE if first_broken and first_broken["name"] == "cable" else NOT_CHECKED}
    if reached:
        try:
            snap = factory(DeviceTarget(ip=ip, port=port, comm_key=comm_key)).snapshot()
        except DeviceError as exc:
            read["message"] = exc.message
        else:
            identity = {"serial": snap.serial, "firmware": snap.firmware, "platform": snap.platform,
                        "users": snap.users, "user_capacity": snap.user_capacity,
                        "records": snap.records,
                        "device_time": snap.device_time.isoformat(),
                        "pc_time": snap.pc_time.isoformat(timespec="seconds"),
                        "clock_drift_seconds": snap.clock_drift_seconds}
            read.update(ok=True, message=f"Serial {snap.serial}, firmware {snap.firmware}")
    checks.append(read)

    ok = all(c["ok"] for c in checks)
    return {"ok": ok, "checks": checks, "identity": identity,
            "heading": "The terminal answered" if ok else _heading(checks),
            "remedy": "" if ok else (next((c["message"] for c in checks if not c["ok"]), "")),
            "holding": _holding(identity) if identity else None,
            "network": network}


def _holding(identity: dict) -> str:
    """What is on the terminal already, and what to do about scans left from before.

    A new register numbers each level's students from the start of its block, so a scan still on the
    terminal under one of those numbers, from a register that no longer exists, would be read as the
    new student's. Clearing the scans from Device stores them first, and a number that has scans is
    never given out again (roster.next_device_id). It used to count people only, and called a
    terminal holding nobody and fifteen old scans "empty and ready" (audit, 2026-09-24).
    """
    people = f"It holds {identity['users']} of {identity['user_capacity']:,} people"
    scans = identity.get("records") or 0
    if not scans:
        return f"{people}, so it is {'empty and ready' if not identity['users'] else 'already in use'}."
    return (f"{people} and {scans:,} {'scan' if scans == 1 else 'scans'} from before this register. "
            "Clear the scans on the Device screen before you import a roster, so none of them is "
            "read as a new student's.")


def _heading(checks: list[dict]) -> str:
    """One sentence naming the first broken link, in the words a lecturer would use."""
    broken = next((c for c in checks if not c["ok"]), None)
    if broken is None:
        return "The terminal answered"
    return {
        "cable": "The cable is not connected, or the terminal is off",
        "pc_address": "This computer is not on the terminal's network",
        "route": "Traffic to the terminal is not going down the cable",
        "ping": "The terminal did not answer",
        "port": "The terminal answered, but not on that port",
        "identity": "The terminal answered, but would not say what it is",
    }.get(broken["name"], "The terminal could not be reached")
