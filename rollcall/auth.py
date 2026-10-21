"""App accounts. Students have no app account of their own unless someone gives them one.

What an account may do comes from the role it holds, and roles are rows people create and edit:
`rollcall/roles.py`. Nothing here decides permissions.
"""
from __future__ import annotations

import hashlib
import hmac
import secrets
import sqlite3
import threading
import time
from datetime import datetime, timedelta

from . import db
from .names import fold

SESSION_HOURS = 12
_N, _R, _P = 2 ** 14, 8, 1


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=_N, r=_R, p=_P, dklen=32)
    return f"scrypt${_N}${_R}${_P}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, n, r, p, salt_hex, digest_hex = stored.split("$")
    except ValueError:
        return False
    if scheme != "scrypt":
        return False
    digest = hashlib.scrypt(password.encode("utf-8"), salt=bytes.fromhex(salt_hex),
                            n=int(n), r=int(r), p=int(p), dklen=len(bytes.fromhex(digest_hex)))
    return hmac.compare_digest(digest.hex(), digest_hex)


def validate_new_password(password: str) -> None:
    if len(password) < 6:
        raise ValueError("Password must be at least 6 characters.")


def set_password(conn: sqlite3.Connection, account_id: int, password: str) -> None:
    """Set a new password for someone who has forgotten theirs (known gap 3).

    Whoever does this never learns the old password: only the new hash is written. Every session
    that account had is ended, because a forgotten password often means somebody else has it.
    """
    validate_new_password(password)
    if conn.execute("SELECT 1 FROM accounts WHERE id = ?", (account_id,)).fetchone() is None:
        raise ValueError("Unknown account.")
    conn.execute("UPDATE accounts SET password_hash = ? WHERE id = ?",
                 (hash_password(password), account_id))
    conn.execute("DELETE FROM auth_sessions WHERE account_id = ?", (account_id,))


def create_account(conn: sqlite3.Connection, username: str, display_name: str, password: str,
                   role_id: int, person_id: int | None = None) -> int:
    if conn.execute("SELECT 1 FROM roles WHERE id = ?", (role_id,)).fetchone() is None:
        raise ValueError("Unknown role.")
    if not (username or "").strip():
        raise ValueError("Give the account a username.")
    if not (display_name or "").strip():
        raise ValueError("Give the account a display name.")
    validate_new_password(password)
    cur = conn.execute(
        "INSERT INTO accounts(username, display_name, role_id, person_id, password_hash, created_at)"
        " VALUES (?, ?, ?, ?, ?, ?)",
        (username.strip(), display_name.strip(), role_id, person_id, hash_password(password), db.now()),
    )
    return int(cur.lastrowid)


def login(conn: sqlite3.Connection, username: str, password: str) -> tuple[str, sqlite3.Row] | None:
    row = conn.execute("SELECT * FROM accounts WHERE username = ? AND disabled = 0", (username.strip(),)).fetchone()
    if row is None:
        # Spend the same time as a real check so usernames cannot be probed by timing.
        verify_password(password, hash_password("not-a-real-password"))
        return None
    if not verify_password(password, row["password_hash"]):
        return None
    token = secrets.token_urlsafe(32)
    expires = datetime.now() + timedelta(hours=SESSION_HOURS)
    conn.execute(
        "INSERT INTO auth_sessions(token_hash, account_id, created_at, expires_at) VALUES (?, ?, ?, ?)",
        (_token_hash(token), row["id"], db.now(), expires.isoformat(timespec="seconds")),
    )
    return token, row


class LoginThrottle:
    """Slows repeated wrong passwords without ever locking anyone out for long (OWASP, Authentication).

    Five wrong attempts for a username within 15 minutes are free. After that each further wrong
    attempt makes the next one wait twice as long, from 30 seconds up to 15 minutes. It applies to any
    username typed, existing or not, so it reveals nothing, and while a wait runs the password is not
    checked at all. A hard lockout was rejected: on a shared machine a course representative could
    use it to keep the lecturer out. Kept in memory: a restart clears it, which only the machine's
    user can do.
    """

    FREE, WINDOW, FIRST_WAIT, LONGEST_WAIT = 5, 15 * 60, 30, 15 * 60

    def __init__(self, clock=time.monotonic):
        self._clock = clock
        self._lock = threading.Lock()
        self._state: dict[str, tuple[int, float, float]] = {}   # key: (failures, first, blocked_until)

    def wait_seconds(self, username: str) -> int:
        with self._lock:
            state = self._state.get(fold(username.strip()))
            return max(0, int(state[2] - self._clock() + 0.999)) if state else 0

    def failed(self, username: str) -> None:
        key, now = fold(username.strip()), self._clock()
        with self._lock:
            failures, first, _ = self._state.get(key, (0, now, 0.0))
            if now - first > self.WINDOW:
                failures, first = 0, now
            failures += 1
            wait = 0.0
            if failures > self.FREE:
                wait = min(self.LONGEST_WAIT, self.FIRST_WAIT * 2 ** (failures - self.FREE - 1))
            self._state[key] = (failures, first, now + wait)

    def succeeded(self, username: str) -> None:
        with self._lock:
            self._state.pop(fold(username.strip()), None)


def account_for_token(conn: sqlite3.Connection, token: str | None) -> sqlite3.Row | None:
    if not token:
        return None
    row = conn.execute(
        "SELECT a.* FROM auth_sessions s JOIN accounts a ON a.id = s.account_id"
        " WHERE s.token_hash = ? AND s.expires_at > ? AND a.disabled = 0",
        (_token_hash(token), db.now()),
    ).fetchone()
    return row


def logout(conn: sqlite3.Connection, token: str | None) -> None:
    if token:
        conn.execute("DELETE FROM auth_sessions WHERE token_hash = ?", (_token_hash(token),))


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("ascii")).hexdigest()
