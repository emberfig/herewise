"""SQLite storage. One file, stdlib only, so backup is copying one file and packaging stays simple.

Two tables are append-only and enforced by triggers, not by convention:
  punches           raw scans from the device or a USB file (PRD 6.2)
  attendance_marks  lecturer corrections, latest row per student and session wins
  audit_log         who did what
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Iterator

SCHEMA_VERSION = 14

SCHEMA = """
CREATE TABLE settings(
  key   TEXT PRIMARY KEY,
  value TEXT NOT NULL
);

-- App accounts. Students never log in: they only exist on the device.
CREATE TABLE accounts(
  id            INTEGER PRIMARY KEY,
  username      TEXT NOT NULL UNIQUE COLLATE NOCASE,
  display_name  TEXT NOT NULL,
  role          TEXT NOT NULL CHECK(role IN ('admin', 'viewer')),
  password_hash TEXT NOT NULL,
  disabled      INTEGER NOT NULL DEFAULT 0,
  created_at    TEXT NOT NULL
);

CREATE TABLE auth_sessions(
  token_hash TEXT PRIMARY KEY,
  account_id INTEGER NOT NULL REFERENCES accounts(id),
  created_at TEXT NOT NULL,
  expires_at TEXT NOT NULL
);

-- A physical K40. More than one is supported from day one (PRD 4, 1,000 user cap).
CREATE TABLE devices(
  id                INTEGER PRIMARY KEY,
  name              TEXT NOT NULL,
  ip                TEXT NOT NULL,
  port              INTEGER NOT NULL DEFAULT 4370,
  comm_key          INTEGER NOT NULL DEFAULT 0,
  serial            TEXT UNIQUE,
  firmware          TEXT,
  platform          TEXT,
  last_seen_at      TEXT,
  user_count        INTEGER,
  user_capacity     INTEGER,
  template_count    INTEGER,
  template_capacity INTEGER,
  record_count      INTEGER,
  record_capacity   INTEGER,
  is_default        INTEGER NOT NULL DEFAULT 0,
  created_at        TEXT NOT NULL
);

CREATE TABLE academic_sessions(
  id         INTEGER PRIMARY KEY,
  name       TEXT NOT NULL UNIQUE,          -- "2026/2027"
  is_current INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL
);

CREATE TABLE levels(
  id             INTEGER PRIMARY KEY,
  level_number   INTEGER NOT NULL UNIQUE,   -- 100, 200 ...
  name           TEXT NOT NULL,             -- "200 Level"
  code           TEXT,                      -- "PCT 200"
  id_block_start INTEGER NOT NULL UNIQUE,   -- 2001
  id_block_end   INTEGER NOT NULL           -- 2999
);

-- Everyone who exists on a device. role 'staff' is the lecturer and any backup admin.
-- device_user_id is permanent: it is never reused, and never changes when a student changes level.
CREATE TABLE people(
  id                  INTEGER PRIMARY KEY,
  role                TEXT NOT NULL CHECK(role IN ('student', 'staff')),
  device_user_id      INTEGER NOT NULL UNIQUE CHECK(device_user_id BETWEEN 1 AND 65535),
  device_id           INTEGER NOT NULL REFERENCES devices(id),
  matric_no           TEXT UNIQUE,
  surname             TEXT NOT NULL,
  other_names         TEXT NOT NULL DEFAULT '',
  source_name         TEXT,                 -- exactly as imported
  device_name         TEXT NOT NULL,        -- shortened to fit 24 bytes
  device_privilege    INTEGER NOT NULL DEFAULT 0 CHECK(device_privilege IN (0, 14)),
  device_password     TEXT CHECK(device_password IS NULL OR (length(device_password) BETWEEN 1 AND 8
                                 AND device_password NOT GLOB '*[^0-9]*')),
  password_reason     TEXT,
  on_device           INTEGER NOT NULL DEFAULT 0,
  pushed_at           TEXT,
  consent_recorded_at TEXT,
  enrollment_notes    TEXT,
  active              INTEGER NOT NULL DEFAULT 1,
  created_at          TEXT NOT NULL
);

-- Level is per academic session, so moving up a level never touches the device.
CREATE TABLE level_memberships(
  person_id           INTEGER NOT NULL REFERENCES people(id),
  academic_session_id INTEGER NOT NULL REFERENCES academic_sessions(id),
  level_id            INTEGER NOT NULL REFERENCES levels(id),
  PRIMARY KEY(person_id, academic_session_id)
);

-- Finger templates known to be on the device, refreshed by reading templates back.
CREATE TABLE fingers(
  person_id     INTEGER NOT NULL REFERENCES people(id),
  finger_index  INTEGER NOT NULL CHECK(finger_index BETWEEN 0 AND 9),
  template_size INTEGER,
  first_seen_at TEXT NOT NULL,
  last_seen_at  TEXT NOT NULL,
  PRIMARY KEY(person_id, finger_index)
);

CREATE TABLE enrollment_attempts(
  id           INTEGER PRIMARY KEY,
  person_id    INTEGER NOT NULL REFERENCES people(id),
  finger_index INTEGER NOT NULL,
  started_at   TEXT NOT NULL,
  finished_at  TEXT,
  -- 'cancelled' is a capture the lecturer stopped, which is not a failure of the terminal
  -- and is worth telling apart from one nobody pressed a finger for.
  outcome      TEXT CHECK(outcome IN ('captured', 'not_captured', 'timeout', 'error',
                                      'cancelled')),
  detail       TEXT,
  account_id   INTEGER REFERENCES accounts(id)
);

CREATE TABLE roster_imports(
  id                  INTEGER PRIMARY KEY,
  level_id            INTEGER NOT NULL REFERENCES levels(id),
  academic_session_id INTEGER NOT NULL REFERENCES academic_sessions(id),
  device_id           INTEGER NOT NULL REFERENCES devices(id),
  file_name           TEXT,
  csv_text            TEXT NOT NULL,
  status              TEXT NOT NULL CHECK(status IN ('pending', 'committed', 'discarded')),
  created_at          TEXT NOT NULL,
  committed_at        TEXT,
  account_id          INTEGER REFERENCES accounts(id)
);

-- One lecture.
CREATE TABLE class_sessions(
  id                  INTEGER PRIMARY KEY,
  level_id            INTEGER NOT NULL REFERENCES levels(id),
  academic_session_id INTEGER NOT NULL REFERENCES academic_sessions(id),
  course_code         TEXT,
  title               TEXT,
  date                TEXT NOT NULL,        -- YYYY-MM-DD
  start_time          TEXT NOT NULL,        -- HH:MM
  end_time            TEXT NOT NULL,
  kind                TEXT NOT NULL CHECK(kind IN ('device', 'manual')),
  created_by          INTEGER REFERENCES accounts(id),
  created_at          TEXT NOT NULL,
  cancelled_at        TEXT,
  cancel_note         TEXT
);

CREATE TABLE import_batches(
  id              INTEGER PRIMARY KEY,
  source          TEXT NOT NULL CHECK(source IN ('network', 'usb')),
  device_id       INTEGER NOT NULL REFERENCES devices(id),
  file_name       TEXT,
  archived_path   TEXT,
  created_at      TEXT NOT NULL,
  records_read    INTEGER NOT NULL DEFAULT 0,
  new_count       INTEGER NOT NULL DEFAULT 0,
  duplicate_count INTEGER NOT NULL DEFAULT 0,
  skipped_count   INTEGER NOT NULL DEFAULT 0,
  first_punch_at  TEXT,
  last_punch_at   TEXT,
  account_id      INTEGER REFERENCES accounts(id),
  detail          TEXT
);

-- Raw scans. Never edited, never deleted. device_user_id is TEXT so an unknown or odd ID is kept.
CREATE TABLE punches(
  id              INTEGER PRIMARY KEY,
  device_user_id  TEXT NOT NULL,
  timestamp       TEXT NOT NULL,            -- device local time, YYYY-MM-DDTHH:MM:SS
  device_id       INTEGER NOT NULL REFERENCES devices(id),
  verify_type     INTEGER,
  punch_state     INTEGER,
  import_batch_id INTEGER REFERENCES import_batches(id),
  imported_at     TEXT NOT NULL,
  UNIQUE(device_user_id, timestamp, device_id)
);
CREATE INDEX punches_by_time ON punches(timestamp);

CREATE TABLE attendance_marks(
  id               INTEGER PRIMARY KEY,
  class_session_id INTEGER NOT NULL REFERENCES class_sessions(id),
  person_id        INTEGER NOT NULL REFERENCES people(id),
  status           TEXT NOT NULL CHECK(status IN ('present', 'absent')),
  note             TEXT NOT NULL CHECK(length(trim(note)) > 0),
  account_id       INTEGER NOT NULL REFERENCES accounts(id),
  created_at       TEXT NOT NULL
);
CREATE INDEX marks_by_session ON attendance_marks(class_session_id, person_id, id);

CREATE TABLE audit_log(
  id         INTEGER PRIMARY KEY,
  at         TEXT NOT NULL,
  account_id INTEGER REFERENCES accounts(id),
  action     TEXT NOT NULL,
  entity     TEXT,
  entity_id  INTEGER,
  detail     TEXT
);

CREATE TRIGGER punches_immutable_update BEFORE UPDATE ON punches
BEGIN SELECT RAISE(ABORT, 'punches are immutable'); END;
CREATE TRIGGER punches_immutable_delete BEFORE DELETE ON punches
BEGIN SELECT RAISE(ABORT, 'punches are immutable'); END;
CREATE TRIGGER marks_immutable_update BEFORE UPDATE ON attendance_marks
BEGIN SELECT RAISE(ABORT, 'attendance marks are append-only'); END;
CREATE TRIGGER marks_immutable_delete BEFORE DELETE ON attendance_marks
BEGIN SELECT RAISE(ABORT, 'attendance marks are append-only'); END;
CREATE TRIGGER audit_immutable_update BEFORE UPDATE ON audit_log
BEGIN SELECT RAISE(ABORT, 'audit log is append-only'); END;
CREATE TRIGGER audit_immutable_delete BEFORE DELETE ON audit_log
BEGIN SELECT RAISE(ABORT, 'audit log is append-only'); END;
"""

# Version 2: Super Admin reminders and per-level attendance plans.
SCHEMA_V2 = """
-- A reminder has no row while it is active. A row means snoozed (until a time) or dismissed.
CREATE TABLE reminders(
  key           TEXT PRIMARY KEY,           -- "second_super_admin:1"
  status        TEXT NOT NULL CHECK(status IN ('snoozed', 'dismissed')),
  snoozed_until TEXT,
  account_id    INTEGER REFERENCES accounts(id),
  updated_at    TEXT NOT NULL
);

-- What the lecturer expects for a level this academic session: how many classes, and the pass mark.
CREATE TABLE attendance_plans(
  level_id            INTEGER NOT NULL REFERENCES levels(id),
  academic_session_id INTEGER NOT NULL REFERENCES academic_sessions(id),
  weeks               INTEGER CHECK(weeks IS NULL OR weeks BETWEEN 1 AND 52),
  classes_per_week    INTEGER CHECK(classes_per_week IS NULL OR classes_per_week BETWEEN 1 AND 20),
  total_classes       INTEGER CHECK(total_classes IS NULL OR total_classes BETWEEN 1 AND 1000),
  threshold_percent   INTEGER CHECK(threshold_percent IS NULL OR threshold_percent BETWEEN 1 AND 100),
  account_id          INTEGER REFERENCES accounts(id),
  updated_at          TEXT NOT NULL,
  PRIMARY KEY(level_id, academic_session_id)
);
"""

# Version 3: the attendance sheet template (weeks and class boxes per level and academic session).
SCHEMA_V3 = """
CREATE TABLE register_templates(
  id                  INTEGER PRIMARY KEY,
  level_id            INTEGER NOT NULL REFERENCES levels(id),
  academic_session_id INTEGER NOT NULL REFERENCES academic_sessions(id),
  title               TEXT NOT NULL,        -- "200 LEVEL PHARMACY ATTENDANCE"
  course_code         TEXT,
  week1_start         TEXT,                 -- YYYY-MM-DD
  created_at          TEXT NOT NULL,
  updated_at          TEXT NOT NULL,
  UNIQUE(level_id, academic_session_id)
);

CREATE TABLE register_weeks(
  template_id INTEGER NOT NULL REFERENCES register_templates(id),
  week_number INTEGER NOT NULL CHECK(week_number BETWEEN 1 AND 52),
  starts_on   TEXT,
  classes     INTEGER NOT NULL CHECK(classes BETWEEN 0 AND 7),
  label       TEXT,
  PRIMARY KEY(template_id, week_number)
);
"""

# Version 4: courses (a home level plus carry-over students) and excused absences. Templates and
# plans are rebuilt per course in _migrate_to_4.
SCHEMA_V4 = """
CREATE TABLE courses(
  id                  INTEGER PRIMARY KEY,
  academic_session_id INTEGER NOT NULL REFERENCES academic_sessions(id),
  level_id            INTEGER NOT NULL REFERENCES levels(id),   -- home level
  code                TEXT NOT NULL,                            -- "PCT 201"
  title               TEXT,
  created_at          TEXT NOT NULL,
  UNIQUE(academic_session_id, code)
);

-- Who takes a course. 'level' students come from the home level; 'carry_over' students are from
-- another level. Removal is a timestamp with a note, so the history stays.
CREATE TABLE course_enrolments(
  course_id    INTEGER NOT NULL REFERENCES courses(id),
  person_id    INTEGER NOT NULL REFERENCES people(id),
  kind         TEXT NOT NULL CHECK(kind IN ('level', 'carry_over')),
  added_at     TEXT NOT NULL,
  account_id   INTEGER REFERENCES accounts(id),
  removed_at   TEXT,
  removed_note TEXT,
  PRIMARY KEY(course_id, person_id)
);

-- An excused absence for a date range, for one course or every course (course_id NULL).
CREATE TABLE excusals(
  id          INTEGER PRIMARY KEY,
  person_id   INTEGER NOT NULL REFERENCES people(id),
  course_id   INTEGER REFERENCES courses(id),
  date_from   TEXT NOT NULL,
  date_to     TEXT NOT NULL,
  category    TEXT NOT NULL CHECK(category IN ('medical', 'official', 'bereavement', 'other')),
  note        TEXT NOT NULL CHECK(length(trim(note)) > 0),
  account_id  INTEGER NOT NULL REFERENCES accounts(id),
  created_at  TEXT NOT NULL,
  revoked_at  TEXT,
  revoked_by  INTEGER REFERENCES accounts(id),
  revoke_note TEXT,
  CHECK(date_to >= date_from)
);
CREATE INDEX excusals_by_person ON excusals(person_id, date_from, date_to);

ALTER TABLE class_sessions ADD COLUMN course_id INTEGER REFERENCES courses(id);
"""

SCHEMA_V5 = """
-- Roles people create and name themselves, built from the fixed permission vocabulary in roles.py.
CREATE TABLE roles(
  id          INTEGER PRIMARY KEY,
  name        TEXT NOT NULL UNIQUE COLLATE NOCASE,
  description TEXT NOT NULL DEFAULT '',
  is_owner    INTEGER NOT NULL DEFAULT 0,   -- exactly one: always holds every permission
  built_in    INTEGER NOT NULL DEFAULT 0,   -- seeded at setup, otherwise an ordinary row
  created_at  TEXT NOT NULL,
  updated_at  TEXT NOT NULL
);
CREATE UNIQUE INDEX roles_one_owner ON roles(is_owner) WHERE is_owner = 1;

CREATE TABLE role_permissions(
  role_id    INTEGER NOT NULL REFERENCES roles(id),
  permission TEXT NOT NULL,
  PRIMARY KEY (role_id, permission)
) WITHOUT ROWID;

-- A correction someone asked for but may not apply. Append-only apart from its one decision.
CREATE TABLE correction_requests(
  id               INTEGER PRIMARY KEY,
  class_session_id INTEGER NOT NULL REFERENCES class_sessions(id),
  person_id        INTEGER NOT NULL REFERENCES people(id),
  status           TEXT NOT NULL CHECK(status IN ('present', 'absent')),
  note             TEXT NOT NULL CHECK(length(trim(note)) > 0),
  requested_by     INTEGER NOT NULL REFERENCES accounts(id),
  requested_at     TEXT NOT NULL,
  state            TEXT NOT NULL DEFAULT 'pending' CHECK(state IN ('pending', 'approved', 'rejected')),
  decided_by       INTEGER REFERENCES accounts(id),
  decided_at       TEXT,
  decision_note    TEXT,
  mark_id          INTEGER REFERENCES attendance_marks(id)
);
CREATE INDEX requests_by_state ON correction_requests(state, id);
CREATE INDEX requests_by_session ON correction_requests(class_session_id, person_id);

CREATE TRIGGER requests_no_delete BEFORE DELETE ON correction_requests
BEGIN SELECT RAISE(ABORT, 'correction requests are append-only'); END;

CREATE TRIGGER requests_decide_once BEFORE UPDATE ON correction_requests
WHEN OLD.state <> 'pending'
  OR NEW.class_session_id <> OLD.class_session_id OR NEW.person_id <> OLD.person_id
  OR NEW.status <> OLD.status OR NEW.note <> OLD.note
  OR NEW.requested_by <> OLD.requested_by OR NEW.requested_at <> OLD.requested_at
BEGIN SELECT RAISE(ABORT, 'a correction request is decided once, and only its decision changes'); END;
"""

SCHEMA_V6 = """
-- First-run setup saves its answers here so someone can close the app and carry on later. One row,
-- deleted the moment setup finishes, so it never outlives the screen that owns it. Nothing else is
-- written until the review step, which is the whole point of screen 1.
CREATE TABLE setup_drafts(
  id         INTEGER PRIMARY KEY CHECK (id = 1),
  payload    TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
"""

SCHEMA_V7 = """
-- A capture can be stopped now, so an attempt can end 'cancelled'. SQLite cannot alter a CHECK, so
-- the table is rebuilt: every row is kept, and the rows already in it are all older outcomes.
CREATE TABLE enrollment_attempts_v7(
  id           INTEGER PRIMARY KEY,
  person_id    INTEGER NOT NULL REFERENCES people(id),
  finger_index INTEGER NOT NULL,
  started_at   TEXT NOT NULL,
  finished_at  TEXT,
  outcome      TEXT CHECK(outcome IN ('captured', 'not_captured', 'timeout', 'error', 'cancelled')),
  detail       TEXT,
  account_id   INTEGER REFERENCES accounts(id)
);
INSERT INTO enrollment_attempts_v7(id, person_id, finger_index, started_at, finished_at, outcome,
                                   detail, account_id)
  SELECT id, person_id, finger_index, started_at, finished_at, outcome, detail, account_id
  FROM enrollment_attempts;
DROP TABLE enrollment_attempts;
ALTER TABLE enrollment_attempts_v7 RENAME TO enrollment_attempts;
"""

SCHEMA_V8 = """
-- Which import created a student, so the wrong file can be undone exactly rather than by guessing
-- from names and times. Null for everyone imported before this, and for anybody added by hand.
ALTER TABLE people ADD COLUMN roster_import_id INTEGER REFERENCES roster_imports(id);
CREATE INDEX idx_people_import ON people(roster_import_id);
-- When this started being recorded. An import committed before it cannot be taken back, and says
-- so, rather than claiming it created nobody.
INSERT OR REPLACE INTO settings(key, value)
  VALUES ('roster_tracking_from', strftime('%Y-%m-%dT%H:%M:%S', 'now', 'localtime'));
"""

SCHEMA_V9 = """
-- A class taken live: the lecturer presses Start in the room and End when the queue is done
-- (asked for on 2026-09-22, the way a lecturer actually takes attendance). Its window is exactly
-- opened_at to closed_at, and while closed_at is null it is still being taken: nobody is absent yet
-- and it is counted nowhere. Null in both for a class entered by hand or found in the scans.
ALTER TABLE class_sessions ADD COLUMN opened_at TEXT;
ALTER TABLE class_sessions ADD COLUMN closed_at TEXT;
-- The one import batch the scans read during it go into, so a class of 120 is one row in the
-- activity log rather than a row for every student who scanned.
ALTER TABLE class_sessions ADD COLUMN live_batch_id INTEGER REFERENCES import_batches(id);
-- One terminal, so one class taking attendance at a time. NULLs are distinct in a unique index, so
-- the key is the expression rather than the column.
CREATE UNIQUE INDEX one_open_class ON class_sessions(ifnull(closed_at, 'open'))
  WHERE opened_at IS NOT NULL AND closed_at IS NULL;
"""

SCHEMA_V10 = """
-- The week of the sheet a class belongs to, chosen by the lecturer when they start it (asked for on
-- 2026-09-23: "the terminal should ask if the attendance is in the first week or the second week").
-- A course's weeks are its own numbering, not the calendar's, so a make-up class or a class after a
-- break goes where the lecturer says. Null for a class found in the scans or made before this: those
-- are placed by their date, as they always were.
ALTER TABLE class_sessions ADD COLUMN week_number INTEGER CHECK(week_number IS NULL OR week_number >= 1);
"""

SCHEMA_V11 = """
-- The device IDs a level had when its roster was cleared (asked for on 2026-09-23: "when i delete a
-- roster everything related to that roster will be deleted"). The students and their scans go, but
-- their IDs may still be on the terminal with a finger behind them, and the terminal keeps its scan
-- log. So the IDs are retired rather than freed: no new student is given one, and a pull leaves out
-- any scan from one instead of bringing the cleared attendance back.
CREATE TABLE retired_ids(
  first_id   INTEGER PRIMARY KEY,
  last_id    INTEGER NOT NULL CHECK(last_id >= first_id),
  level_name TEXT NOT NULL,
  cleared_at TEXT NOT NULL
);
"""

SCHEMA_V12 = """
-- Seven settings taken off the Settings screen on 2026-09-23, once attendance was taken with Start
-- and End ("remove all of those settings"). Each keeps the value it always defaulted to, now fixed
-- in the code: the grace either side of a class and the numbers for working classes out from scans
-- (register.py), how long a reminder waits (reminders.py). "Where attendance usually comes from"
-- was read by nothing but the Settings screen itself. A changed value is dropped with its row.
DELETE FROM settings WHERE key IN ('grace_before_minutes', 'grace_after_minutes',
  'default_input_path', 'reminder_snooze_days', 'auto_create_sessions',
  'auto_session_min_students', 'auto_session_gap_minutes');
"""

SCHEMA_V13 = """
-- A course's groups (asked for on 2026-09-29: "create sub groups ... a,b,c,d for 200 level for a
-- particular course ... and still be able to use the full roster for some courses"). A course with
-- no groups is exactly what it was.
CREATE TABLE course_groups(
  id         INTEGER PRIMARY KEY,
  course_id  INTEGER NOT NULL REFERENCES courses(id),
  name       TEXT NOT NULL COLLATE NOCASE CHECK(length(trim(name)) > 0),
  position   INTEGER NOT NULL,
  created_at TEXT NOT NULL,
  UNIQUE(course_id, name)
);

-- Who is in which group, and from when to when, so a student who changes group keeps the classes
-- they already had with the old one. since NULL is from the start of the course; until is the first
-- day they are no longer in it, NULL while they still are. One group at a time per course.
CREATE TABLE course_group_members(
  id         INTEGER PRIMARY KEY,
  course_id  INTEGER NOT NULL REFERENCES courses(id),
  group_id   INTEGER NOT NULL REFERENCES course_groups(id),
  person_id  INTEGER NOT NULL REFERENCES people(id),
  since      TEXT,
  until      TEXT,
  added_at   TEXT NOT NULL,
  account_id INTEGER REFERENCES accounts(id),
  CHECK(since IS NULL OR until IS NULL OR until > since)
);
CREATE UNIQUE INDEX one_group_at_a_time ON course_group_members(course_id, person_id) WHERE until IS NULL;
CREATE INDEX group_members_by_group ON course_group_members(group_id, person_id);

-- The group a class was for. NULL is everybody on the course, which is every class made before this.
ALTER TABLE class_sessions ADD COLUMN group_id INTEGER REFERENCES course_groups(id);
"""

SCHEMA_V14 = """
-- A class taken live and ended, opened again for whoever had not scanned (asked for on 2026-10-22:
-- "reopening the attendance again for those that haven't signed to be able to sign"). One row per
-- reopening. The class counts the scans inside each of its windows and nowhere between them:
-- opened_at to the first row's ended_at, each row's reopened_at to the next row's ended_at, and
-- the last row's reopened_at to the class's closed_at. A scan made after it ended and before it
-- was reopened is in no window, because that gap may have been another class's.
CREATE TABLE class_reopenings(
  id               INTEGER PRIMARY KEY,
  class_session_id INTEGER NOT NULL REFERENCES class_sessions(id),
  ended_at         TEXT NOT NULL,
  reopened_at      TEXT NOT NULL CHECK(reopened_at >= ended_at),
  account_id       INTEGER REFERENCES accounts(id),
  present_before   INTEGER NOT NULL,
  created_at       TEXT NOT NULL
);
CREATE INDEX reopenings_by_class ON class_reopenings(class_session_id, id);
-- What a window was is evidence, like a scan: kept as written.
CREATE TRIGGER reopenings_immutable_update BEFORE UPDATE ON class_reopenings
BEGIN SELECT RAISE(ABORT, 'class reopenings are append-only'); END;
CREATE TRIGGER reopenings_immutable_delete BEFORE DELETE ON class_reopenings
BEGIN SELECT RAISE(ABORT, 'class reopenings are append-only'); END;
"""

MIGRATIONS = {1: SCHEMA, 2: SCHEMA_V2, 3: SCHEMA_V3, 4: SCHEMA_V4, 5: SCHEMA_V5, 6: SCHEMA_V6,
              7: SCHEMA_V7, 8: SCHEMA_V8, 9: SCHEMA_V9, 10: SCHEMA_V10, 11: SCHEMA_V11, 12: SCHEMA_V12,
              13: SCHEMA_V13, 14: SCHEMA_V14}

DEFAULT_SETTINGS = {
    "attendance_threshold_percent": "75",
    "clock_drift_warn_seconds": "120",
    "excused_rule": "excluded",
    # A4 everywhere but North America, the Philippines and parts of Latin America (ISO 216).
    "paper_size": "a4",
    # A copy of the database after every pull that stored scans: lost registers are what users punish.
    "auto_backup_after_pull": "1",
    "backup_keep": "10",
}

DEFAULT_LEVELS = [100, 200, 300, 400, 500]


def now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def connect(path: Path | str) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path), timeout=30, isolation_level=None, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    from .names import fold  # names has no imports from this package, so there is no cycle
    conn.create_function("fold", 1, fold, deterministic=True)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 30000")
    return conn


@contextmanager
def transaction(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    else:
        conn.execute("COMMIT")


def backup_before_migration(conn: sqlite3.Connection, version: int, target: int) -> Path | None:
    """Copy an existing database before its schema changes, into backups/ beside it.

    The migration itself runs in one transaction, so a failure rolls back; this covers the other case,
    a migration that succeeds and turns out wrong, which nothing else could undo. A new database
    (version 0) has nothing to keep. The copy holds what the database holds, keypad passwords included
    (known gap 18), and stays in the same folder with the same protection.
    """
    if version == 0:
        return None
    row = conn.execute("PRAGMA database_list").fetchone()
    source = row["file"] if row is not None else ""
    if not source:
        return None                                   # an in-memory database
    folder = Path(source).parent / "backups"
    folder.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    destination = folder / f"before-schema-{target}-from-{version}-{stamp}.db"
    copy = sqlite3.connect(str(destination))
    try:
        conn.backup(copy)                             # SQLite's online backup: safe with WAL
    finally:
        copy.close()
    return destination


def initialise(conn: sqlite3.Connection, target: int | None = None) -> None:
    """Bring the database up to ``target`` (default: latest), one migration at a time, in one transaction."""
    target = SCHEMA_VERSION if target is None else target
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    if version == target:
        return
    if version > target:
        raise RuntimeError(f"database schema {version} is newer than this app ({target})")
    backup_before_migration(conn, version, target)
    # Versions 4 and 5 rebuild tables that other tables point at. Foreign keys are checked by hand at
    # the end instead, because SQLite cannot drop a referenced table while enforcement is on.
    conn.execute("PRAGMA foreign_keys = OFF")
    try:
        with transaction(conn):
            for step in range(version + 1, target + 1):
                if step == 4:
                    _migrate_to_4(conn)
                    continue
                if step == 5:
                    _migrate_to_5(conn)
                    continue
                for statement in _split_sql(MIGRATIONS[step]):
                    conn.execute(statement)
                if step == 1:
                    for number in DEFAULT_LEVELS:
                        block = number // 100
                        conn.execute(
                            "INSERT OR IGNORE INTO levels(level_number, name, code, id_block_start, id_block_end)"
                            " VALUES (?, ?, NULL, ?, ?)",
                            (number, f"{number} Level", block * 1000 + 1, block * 1000 + 999),
                        )
            for key, value in DEFAULT_SETTINGS.items():
                conn.execute("INSERT OR IGNORE INTO settings(key, value) VALUES (?, ?)", (key, value))
            broken = conn.execute("PRAGMA foreign_key_check").fetchall()
            if broken:
                raise RuntimeError(f"migration left broken references: {[tuple(r) for r in broken[:5]]}")
            conn.execute(f"PRAGMA user_version = {target}")
    finally:
        conn.execute("PRAGMA foreign_keys = ON")


def _migrate_to_4(conn: sqlite3.Connection) -> None:
    """Courses become the unit for classes, sheets, plans and eligibility, so carry-over students fit.

    Existing data (development databases only at this point) gets one course per level and academic
    session that has members, classes, a template or a plan, named after the template's course code,
    the level code or the level name.
    """
    for statement in _split_sql(SCHEMA_V4):
        conn.execute(statement)

    pairs = conn.execute(
        "SELECT level_id, academic_session_id FROM level_memberships"
        " UNION SELECT level_id, academic_session_id FROM class_sessions"
        " UNION SELECT level_id, academic_session_id FROM register_templates"
        " UNION SELECT level_id, academic_session_id FROM attendance_plans"
    ).fetchall()
    stamp = now()
    course_for: dict[tuple[int, int], int] = {}
    for level_id, academic_id in pairs:
        level = conn.execute("SELECT * FROM levels WHERE id = ?", (level_id,)).fetchone()
        template = conn.execute("SELECT * FROM register_templates WHERE level_id = ? AND academic_session_id = ?",
                                (level_id, academic_id)).fetchone()
        base = (template["course_code"] if template and template["course_code"] else None) or level["code"] or level["name"]
        code, n = base, 2
        while conn.execute("SELECT 1 FROM courses WHERE academic_session_id = ? AND code = ?", (academic_id, code)).fetchone():
            code, n = f"{base} ({n})", n + 1
        course_id = conn.execute(
            "INSERT INTO courses(academic_session_id, level_id, code, title, created_at) VALUES (?, ?, ?, NULL, ?)",
            (academic_id, level_id, code, stamp)).lastrowid
        course_for[(level_id, academic_id)] = course_id
        conn.execute(
            "INSERT INTO course_enrolments(course_id, person_id, kind, added_at) SELECT ?, person_id, 'level', ?"
            " FROM level_memberships WHERE level_id = ? AND academic_session_id = ?",
            (course_id, stamp, level_id, academic_id))
        conn.execute("UPDATE class_sessions SET course_id = ? WHERE level_id = ? AND academic_session_id = ?",
                     (course_id, level_id, academic_id))

    conn.execute(
        "CREATE TABLE register_templates_v4(id INTEGER PRIMARY KEY, course_id INTEGER NOT NULL UNIQUE REFERENCES courses(id),"
        " title TEXT NOT NULL, week1_start TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL)")
    for t in conn.execute("SELECT * FROM register_templates").fetchall():
        conn.execute("INSERT INTO register_templates_v4(id, course_id, title, week1_start, created_at, updated_at)"
                     " VALUES (?, ?, ?, ?, ?, ?)",
                     (t["id"], course_for[(t["level_id"], t["academic_session_id"])], t["title"], t["week1_start"],
                      t["created_at"], t["updated_at"]))
    conn.execute("DROP TABLE register_templates")
    conn.execute("ALTER TABLE register_templates_v4 RENAME TO register_templates")

    conn.execute(
        "CREATE TABLE attendance_plans_v4(course_id INTEGER PRIMARY KEY REFERENCES courses(id),"
        " weeks INTEGER CHECK(weeks IS NULL OR weeks BETWEEN 1 AND 52),"
        " classes_per_week INTEGER CHECK(classes_per_week IS NULL OR classes_per_week BETWEEN 1 AND 20),"
        " total_classes INTEGER CHECK(total_classes IS NULL OR total_classes BETWEEN 1 AND 1000),"
        " threshold_percent INTEGER CHECK(threshold_percent IS NULL OR threshold_percent BETWEEN 1 AND 100),"
        " account_id INTEGER REFERENCES accounts(id), updated_at TEXT NOT NULL)")
    for p in conn.execute("SELECT * FROM attendance_plans").fetchall():
        conn.execute("INSERT INTO attendance_plans_v4(course_id, weeks, classes_per_week, total_classes,"
                     " threshold_percent, account_id, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                     (course_for[(p["level_id"], p["academic_session_id"])], p["weeks"], p["classes_per_week"],
                      p["total_classes"], p["threshold_percent"], p["account_id"], p["updated_at"]))
    conn.execute("DROP TABLE attendance_plans")
    conn.execute("ALTER TABLE attendance_plans_v4 RENAME TO attendance_plans")


def _migrate_to_5(conn: sqlite3.Connection) -> None:
    """Roles stop being two hard-coded strings and become rows people can name and edit.

    `accounts.role` was a TEXT column with a CHECK constraint naming 'admin' and 'viewer', so the
    table has to be rebuilt rather than altered: SQLite will not drop a column a CHECK constraint
    mentions. Existing admins become the owner role and existing viewers the seeded Viewer role.

    `accounts.person_id` arrives here too. It ties an account to the student record it belongs to,
    which is what lets the app refuse to let a course representative correct their own attendance.
    """
    from . import roles  # imported here because roles imports this module

    for statement in _split_sql(SCHEMA_V5):
        conn.execute(statement)

    seeded: dict[str, int] = {}
    for name, description, is_owner, permissions in roles.SEED_ROLES:
        cur = conn.execute(
            "INSERT INTO roles(name, description, is_owner, built_in, created_at, updated_at)"
            " VALUES (?, ?, ?, 1, ?, ?)",
            (name, description, 1 if is_owner else 0, now(), now()))
        seeded[name] = int(cur.lastrowid)
        conn.executemany("INSERT INTO role_permissions(role_id, permission) VALUES (?, ?)",
                         [(seeded[name], key) for key in permissions])

    owner_id = seeded[roles.OWNER_ROLE]
    viewer_id = seeded["Viewer"]
    conn.execute(
        "CREATE TABLE accounts_v5("
        " id INTEGER PRIMARY KEY,"
        " username TEXT NOT NULL UNIQUE COLLATE NOCASE,"
        " display_name TEXT NOT NULL,"
        " role_id INTEGER NOT NULL REFERENCES roles(id),"
        " person_id INTEGER REFERENCES people(id),"
        " password_hash TEXT NOT NULL,"
        " disabled INTEGER NOT NULL DEFAULT 0,"
        " created_at TEXT NOT NULL)")
    conn.execute(
        "INSERT INTO accounts_v5(id, username, display_name, role_id, person_id, password_hash,"
        " disabled, created_at)"
        " SELECT id, username, display_name, CASE WHEN role = 'admin' THEN ? ELSE ? END, NULL,"
        " password_hash, disabled, created_at FROM accounts",
        (owner_id, viewer_id))
    conn.execute("DROP TABLE accounts")
    conn.execute("ALTER TABLE accounts_v5 RENAME TO accounts")
    # One account per person, so "this account is that student" can never be ambiguous.
    conn.execute("CREATE UNIQUE INDEX accounts_person ON accounts(person_id) WHERE person_id IS NOT NULL")


def _split_sql(script: str) -> list[str]:
    """Split on semicolons that end a statement, keeping trigger bodies intact."""
    statements, buffer = [], []
    for line in script.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("--"):
            continue
        buffer.append(line)
        joined = "\n".join(buffer)
        if sqlite3.complete_statement(joined):
            statements.append(joined.strip())
            buffer = []
    return statements


def get_setting(conn: sqlite3.Connection, key: str) -> str:
    row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else DEFAULT_SETTINGS[key]


def audit(conn: sqlite3.Connection, account_id: int | None, action: str,
          entity: str | None = None, entity_id: int | None = None, detail: str | None = None) -> None:
    conn.execute(
        "INSERT INTO audit_log(at, account_id, action, entity, entity_id, detail) VALUES (?, ?, ?, ?, ?, ?)",
        (now(), account_id, action, entity, entity_id, detail),
    )
