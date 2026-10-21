"""Fingerprint enrollment driven from the PC (PRD 8.1), one finger at a time, on a background thread.

The flow is push, capture, confirm:
  1. make sure the student exists on the device (push if not)
  2. ask the device to capture a finger (pyzk enroll_user, which blocks while the student presses)
  3. confirm by reading templates back, never by trusting the return value alone

Step 3 is also how keypad enrollment is picked up if remote capture turns out not to work on this
firmware: enroll at the device, then run a finger sync.
"""
from __future__ import annotations

import sqlite3
import threading
from pathlib import Path

from . import db, services
from .device import K40

# ZKTeco numbers the fingers 0 to 9, starting at the left little finger: 6 is the right index and
# 7 the right middle, which is what the enrolment screen asks a student for and what any other
# ZKTeco tool will show for the same template. The backend used to enrol 0 and 1, the left little
# and left ring fingers, while the screen said "Right index finger", so the stored index meant
# something other than what the student was asked to press, and the screen could never mark a
# captured finger as captured because it was looking for 6 and 7 (found on a first enrolment,
# 2026-09-21).
TWO_FINGERS = (6, 7)

# How long the terminal is given to produce a finger. pyzk's enroll_user sets the socket to sixty
# seconds and waits there, so this is a statement about pyzk rather than a setting: the screen uses
# it to count down, and it has to match or the count is wrong.
CAPTURE_SECONDS = 60

# Every index, for a screen that has to name whatever it finds, including templates enrolled at the
# keypad or by an earlier version of this app.
FINGER_NAMES = {
    0: "left little finger", 1: "left ring finger", 2: "left middle finger", 3: "left index finger",
    4: "left thumb", 5: "right thumb", 6: "right index finger", 7: "right middle finger",
    8: "right ring finger", 9: "right little finger",
}


class EnrollmentError(ValueError):
    pass


class EnrollmentManager:
    def __init__(self, db_path: Path, factory=K40):
        self._db_path = db_path
        self._factory = factory
        self._guard = threading.Lock()
        self._job: dict | None = None
        self._thread: threading.Thread | None = None
        self._device = None

    def status(self) -> dict:
        with self._guard:
            return dict(self._job) if self._job else {"state": "idle"}

    def busy(self) -> bool:
        with self._guard:
            return bool(self._job and self._job["state"] in ("pushing", "waiting_for_finger"))

    def start(self, conn: sqlite3.Connection, person_id: int, finger_index: int, account_id: int,
              consent_confirmed: bool) -> dict:
        if finger_index not in range(10):
            raise EnrollmentError("Finger index must be 0 to 9.")
        if self.busy():
            raise EnrollmentError("An enrollment is already in progress.")
        person = conn.execute("SELECT * FROM people WHERE id = ? AND active = 1", (person_id,)).fetchone()
        if person is None:
            raise EnrollmentError("Unknown person.")
        if person["consent_recorded_at"] is None and not consent_confirmed:
            raise EnrollmentError(
                "Confirm this student has been told how their fingerprint is used and has agreed. "
                "Fingerprints are sensitive personal data under the Nigeria Data Protection Act 2023."
            )
        existing = conn.execute("SELECT 1 FROM fingers WHERE person_id = ? AND finger_index = ?",
                                (person_id, finger_index)).fetchone()
        if existing:
            raise EnrollmentError(f"Finger {finger_index} is already enrolled for this student. "
                                  "Run a finger sync if you think that is wrong.")

        with self._guard:
            self._job = {"state": "pushing", "person_id": person_id, "device_user_id": person["device_user_id"],
                         "name": person["device_name"], "finger_index": finger_index, "started_at": db.now(),
                         "outcome": None, "detail": "", "fingers_after": None, "attempt_id": None}

        try:
            if person["consent_recorded_at"] is None:
                with db.transaction(conn):
                    conn.execute("UPDATE people SET consent_recorded_at = ? WHERE id = ?", (db.now(), person_id))
                    db.audit(conn, account_id, "person.consent", "people", person_id, "confirmed at enrollment")
            # Always, never "only if the register thinks they are missing". A terminal emptied
            # from its own menu leaves every on_device flag saying 1 while the terminal holds
            # nobody, and the capture then waits for a finger for a user that does not exist on it:
            # the screen said "waiting for a finger" and the terminal showed nothing at all
            # (reported on a second run, reproduced on the K40 on 2026-09-22). Pushing somebody who
            # is already there writes the same record again and costs about half a second, which is
            # the price of a capture that always prompts.
            services.push_people(conn, person["device_id"], account_id, person_ids=[person_id],
                                 factory=self._factory)
            attempt_id = conn.execute(
                "INSERT INTO enrollment_attempts(person_id, finger_index, started_at, account_id) VALUES (?, ?, ?, ?)",
                (person_id, finger_index, db.now(), account_id),
            ).lastrowid
            target = services.target_for(services.device_row(conn, person["device_id"]))
        except Exception as exc:
            with self._guard:
                self._job.update(state="finished", outcome="error", detail=str(getattr(exc, "message", exc)))
            raise

        # The clock the screen counts down runs from here, not from ``started_at``: the push in
        # front of it takes about half a second for one student and most of a minute for a level,
        # and a countdown that had already spent half its time before the terminal was asked for
        # anything would be a lie.
        with self._guard:
            self._job.update(state="waiting_for_finger", attempt_id=attempt_id,
                             waiting_since=db.now(), waits_for_seconds=CAPTURE_SECONDS)
        # Kept so the capture can be stopped from another thread: the enrolling thread is blocked
        # inside pyzk and the terminal is locked to it.
        self._device = self._factory(target)
        self._thread = threading.Thread(target=self._run, args=(person_id, person["device_user_id"],
                                                                finger_index, attempt_id), daemon=True)
        self._thread.start()
        return self.status()

    def cancel(self) -> dict:
        """Stop a capture that is waiting for a finger.

        The lecturer starts a capture for the wrong student, or the student walks away; without
        this the terminal holds the enrolment for the rest of the minute and the register with it.
        """
        with self._guard:
            running = bool(self._job and self._job["state"] == "waiting_for_finger")
        if not running or self._device is None:
            raise EnrollmentError("No capture is waiting for a finger.")
        self._device.stop_capture()
        if self._thread:
            self._thread.join(10)
        return self.status()

    def _run(self, person_id: int, device_user_id: int, finger_index: int, attempt_id: int) -> None:
        conn = db.connect(self._db_path)
        try:
            try:
                result = self._device.enroll_finger(device_user_id, finger_index)
                outcome, detail, fingers_after = result.outcome, result.detail, result.fingers_after
            except Exception as exc:
                outcome, detail, fingers_after = "error", str(getattr(exc, "message", exc)), None

            stamp = db.now()
            with db.transaction(conn):
                conn.execute("UPDATE enrollment_attempts SET finished_at = ?, outcome = ?, detail = ? WHERE id = ?",
                             (stamp, outcome, detail, attempt_id))
                if fingers_after is not None:
                    for idx in fingers_after:
                        conn.execute(
                            "INSERT INTO fingers(person_id, finger_index, first_seen_at, last_seen_at) VALUES (?, ?, ?, ?)"
                            " ON CONFLICT(person_id, finger_index) DO UPDATE SET last_seen_at = excluded.last_seen_at",
                            (person_id, idx, stamp, stamp),
                        )
            with self._guard:
                self._job.update(state="finished", outcome=outcome, detail=detail, fingers_after=fingers_after,
                                 finished_at=stamp)
        finally:
            conn.close()

    def wait(self, timeout: float | None = None) -> None:
        if self._thread:
            self._thread.join(timeout)


def remove_finger(conn: sqlite3.Connection, person_id: int, finger_index: int, account_id: int,
                  factory=K40) -> dict:
    """Take one enrolled finger off the terminal and out of the register.

    Asked for after the first real enrolment: a finger captured for the wrong student, or captured
    badly, had no way back except clearing the whole person off the device. The terminal is the
    thing that has to change first, because the register is only a record of what is on it.
    """
    person = conn.execute("SELECT * FROM people WHERE id = ? AND active = 1", (person_id,)).fetchone()
    if person is None:
        raise EnrollmentError("Unknown person.")
    if finger_index not in range(10):
        raise EnrollmentError("Finger index must be 0 to 9.")
    if not conn.execute("SELECT 1 FROM fingers WHERE person_id = ? AND finger_index = ?",
                        (person_id, finger_index)).fetchone():
        raise EnrollmentError("That finger is not enrolled for this student.")

    device = services.device_row(conn, person["device_id"])
    left = factory(services.target_for(device)).delete_finger(person["device_user_id"], finger_index)
    name = f"{person['surname']} {person['other_names']}".strip()
    with db.transaction(conn):
        conn.execute("DELETE FROM fingers WHERE person_id = ? AND finger_index = ?",
                     (person_id, finger_index))
        # What the terminal says it still holds is what the register keeps, so one cannot drift
        # from the other.
        conn.execute("DELETE FROM fingers WHERE person_id = ? AND finger_index NOT IN "
                     f"({','.join(str(int(i)) for i in left) or 'NULL'})", (person_id,))
        for index in left:
            conn.execute(
                "INSERT INTO fingers(person_id, finger_index, first_seen_at, last_seen_at)"
                " VALUES (?, ?, ?, ?) ON CONFLICT(person_id, finger_index)"
                " DO UPDATE SET last_seen_at = excluded.last_seen_at",
                (person_id, index, db.now(), db.now()))
        db.audit(conn, account_id, "finger.delete", "people", person_id,
                 f"{FINGER_NAMES.get(finger_index, f'finger {finger_index}')} for "
                 f"{person['matric_no']} {name}, {len(left)} left on the terminal")
    return {"person_id": person_id, "fingers": left}


def level_progress(conn: sqlite3.Connection, level_id: int) -> dict:
    rows = conn.execute(
        "SELECT p.id, p.device_user_id, p.matric_no, p.surname, p.other_names, p.device_name, p.on_device,"
        " p.device_password IS NOT NULL AS has_password, p.password_reason, p.consent_recorded_at,"
        " (SELECT group_concat(finger_index) FROM fingers f WHERE f.person_id = p.id) AS finger_list"
        " FROM people p JOIN level_memberships m ON m.person_id = p.id"
        " JOIN academic_sessions a ON a.id = m.academic_session_id AND a.is_current = 1"
        " WHERE m.level_id = ? AND p.active = 1 AND p.role = 'student' ORDER BY p.device_user_id",
        (level_id,),
    ).fetchall()
    students = []
    for r in rows:
        fingers = sorted(int(x) for x in r["finger_list"].split(",")) if r["finger_list"] else []
        item = dict(r)
        item.pop("finger_list")
        item["fingers"] = fingers
        item["has_password"] = bool(item["has_password"])
        item["complete"] = len(fingers) >= 2 or item["has_password"]
        item["next_finger"] = next((f for f in TWO_FINGERS if f not in fingers), None)
        students.append(item)
    return {
        "total": len(students),
        "two_fingers": sum(1 for s in students if len(s["fingers"]) >= 2),
        "one_finger": sum(1 for s in students if len(s["fingers"]) == 1),
        "password_only": sum(1 for s in students if not s["fingers"] and s["has_password"]),
        "not_started": sum(1 for s in students if not s["fingers"] and not s["has_password"]),
        "complete": sum(1 for s in students if s["complete"]),
        "next_student_id": next((s["id"] for s in students if not s["complete"]), None),
        "students": students,
    }
