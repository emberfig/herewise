"""The upgrade a lecturer actually performs: a register made by 0.1.0 opened by 0.1.1.

0.1.0 shipped schema 6. 0.1.1 is schema 8, and the two migrations between them are not additions
of empty tables: 7 rebuilds `enrollment_attempts` so an attempt may be recorded as cancelled, and 8
adds a column to `people` and writes the moment import tracking began. A rebuild is where rows go
missing, so this fills every table those two touch with the kind of rows a term produces, migrates,
and checks each one is still there and still says the same thing.

`test_migration_from_version_1_keeps_data` covers the chain from the beginning on an empty
database. This covers the step somebody's own register takes.
"""
from __future__ import annotations

import sqlite3

import pytest

from rollcall import db


def old_register(path) -> sqlite3.Connection:
    """A schema 6 register with a term's shape in it."""
    conn = db.connect(path)
    db.initialise(conn, target=6)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 6
    conn.execute("INSERT INTO academic_sessions(name, is_current, created_at)"
                 " VALUES ('2026/2027', 1, ?)", (db.now(),))
    conn.execute("INSERT INTO devices(name, ip, is_default, created_at)"
                 " VALUES ('K40', '192.168.1.201', 1, ?)", (db.now(),))
    owner = conn.execute("SELECT id FROM roles WHERE is_owner = 1").fetchone()["id"]
    conn.execute("INSERT INTO accounts(username, display_name, role_id, password_hash, created_at)"
                 " VALUES ('lecturer', 'Dr Lecturer', ?, 'x', ?)", (owner, db.now()))
    for index in range(1, 4):
        conn.execute(
            "INSERT INTO people(role, device_user_id, device_id, matric_no, surname, other_names,"
            " device_name, active, on_device, created_at)"
            " VALUES ('student', ?, 1, ?, ?, 'Test', ?, 1, 1, ?)",
            (2000 + index, f"PCT/24/{index:04d}", f"SURNAME{index}", f"SURNAME{index} Test",
             db.now()))
    conn.execute("INSERT INTO level_memberships(person_id, academic_session_id, level_id)"
                 " VALUES (1, 1, 2)")
    conn.execute("INSERT INTO fingers(person_id, finger_index, template_size, first_seen_at,"
                 " last_seen_at) VALUES (1, 6, 512, ?, ?)", (db.now(), db.now()))
    # The table migration 7 rebuilds, with one of every outcome schema 6 allowed.
    for person, outcome in ((1, "captured"), (2, "not_captured"), (3, "timeout")):
        conn.execute(
            "INSERT INTO enrollment_attempts(person_id, finger_index, started_at, finished_at,"
            " outcome, detail, account_id) VALUES (?, 6, ?, ?, ?, 'from 0.1.0', 1)",
            (person, db.now(), db.now(), outcome))
    conn.commit()
    return conn


def test_a_register_made_by_0_1_0_keeps_everything_through_the_upgrade(tmp_path):
    conn = old_register(tmp_path / "theirs.db")
    before = {name: conn.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0]
              for name in ("people", "fingers", "enrollment_attempts", "level_memberships",
                           "accounts", "devices", "academic_sessions")}
    attempts_before = [tuple(row) for row in conn.execute(
        "SELECT person_id, finger_index, outcome, detail FROM enrollment_attempts ORDER BY id")]

    db.initialise(conn)

    assert conn.execute("PRAGMA user_version").fetchone()[0] == db.SCHEMA_VERSION == 14
    after = {name: conn.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0] for name in before}
    assert after == before
    # The rebuilt table keeps its rows and their words, not just their number.
    assert [tuple(row) for row in conn.execute(
        "SELECT person_id, finger_index, outcome, detail FROM enrollment_attempts ORDER BY id")] \
        == attempts_before
    conn.close()


def test_the_upgrade_adds_what_0_1_1_needs(tmp_path):
    conn = old_register(tmp_path / "theirs.db")
    db.initialise(conn)

    # Schema 7: an attempt may now be recorded as cancelled, which is what stopping a capture writes.
    conn.execute("INSERT INTO enrollment_attempts(person_id, finger_index, started_at,"
                 " finished_at, outcome, detail, account_id)"
                 " VALUES (1, 7, ?, ?, 'cancelled', 'stopped', 1)", (db.now(), db.now()))
    assert conn.execute("SELECT COUNT(*) FROM enrollment_attempts WHERE outcome = 'cancelled'"
                        ).fetchone()[0] == 1

    # Schema 8: which import created a student, and the moment that began being recorded. Everyone
    # who was already here predates it, which is what stops an older import claiming it created
    # nobody.
    assert [row["roster_import_id"] for row in conn.execute(
        "SELECT roster_import_id FROM people ORDER BY id")] == [None, None, None]
    assert db.get_setting(conn, "roster_tracking_from")

    # Schema 9: classes taken live. Every class that was already here was entered by hand or found
    # in the scans, so none of them may come through looking open: an open class counts nowhere,
    # and a register that lost its classes to an upgrade would read 0 of 12.
    assert conn.execute("SELECT COUNT(*) FROM class_sessions WHERE opened_at IS NOT NULL"
                        ).fetchone()[0] == 0

    # Schema 10: the week a class was put in. Every class already here keeps being placed by its date.
    assert conn.execute("SELECT COUNT(*) FROM class_sessions WHERE week_number IS NOT NULL"
                        ).fetchone()[0] == 0
    conn.close()


def test_a_register_from_a_newer_version_is_refused(tmp_path):
    """A lecturer who runs 0.1.0 again after 0.1.1 must be told, not have their register rewritten."""
    conn = old_register(tmp_path / "theirs.db")
    db.initialise(conn)
    with pytest.raises(RuntimeError):
        db.initialise(conn, target=6)
    conn.close()
