"""The activity log, narrowed and written as sentences (screen 38, known gap 17).

`GET /api/audit` took only a limit, and its `detail` was raw text for some actions, for example
`str(body)` for a settings change. An audit log nobody can narrow, and whose rows read like a
Python repr, is decoration rather than a record.

Two things happen here. Filters: a date range, an actor and a kind. And a sentence per action,
because "settings.update" beside "{'grace_before_minutes': '20'}" is not something a head of
department can read, and this log is what answers "who changed that".

The action names below come from the `db.audit` calls themselves, not from a guess: a sentence
keyed on a name nothing writes is a sentence nobody ever sees.

Nothing is rewritten in the table. The log is append-only and enforced by a trigger; the sentence
is made when the row is read.
"""
from __future__ import annotations

import ast
import csv
import io
import sqlite3

# Each action's sentence, with {detail} where the row's own detail belongs. An action with no
# sentence written for it falls back to its name and its detail, which is honest rather than silent.
SENTENCES = {
    "setup": "Set this computer up and made the first account",

    "account.create": "Made an account: {detail}",
    "account.disable": "Turned off the account {detail}",
    "account.enable": "Turned the account {detail} back on",
    "account.password": "Set a new password for {detail}",
    "account.role": "Changed which role an account holds: {detail}",
    "account.person": "Linked an account to a student record: {detail}",
    "role.create": "Made a role: {detail}",
    "role.update": "Changed a role: {detail}",
    "role.delete": "Deleted a role: {detail}",

    "academic_session.create": "Made the academic session {detail}",
    "academic_session.make_current": "Made an academic session the current one",
    "level.create": "Added a level: {detail}",
    "level.update": "Renamed a level: {detail}",
    "level.delete": "Removed a level: {detail}",
    "level.clear": "Deleted a level's roster and everything on it. {detail}",
    "roster.commit": "Imported a roster: {detail}",
    "roster.undo": "Took an import back out: {detail}",
    "staff.create": "Added a staff member: {detail}",
    "person.deactivate": "Made a student inactive: {detail}",
    "person.consent": "Recorded a student's consent to give a fingerprint: {detail}",
    "person.device_role": "Changed who can open the device menu: {detail}",
    "person.fallback_password": "Gave a student a keypad password instead of a fingerprint: {detail}",
    "finger.delete": "Took an enrolled finger off the terminal: {detail}",
    "finger.forget": "Forgot the fingerprints this register had recorded: {detail}",
    "course.delete": "Deleted a course: {detail}",
    "class.delete": "Deleted a class that recorded nothing: {detail}",
    "enrollment.cancel": "Stopped a fingerprint capture: {detail}",

    "course.create": "Made a course: {detail}",
    "course.update": "Renamed a course: {detail}",
    "course.add_students": "Added students to a course: {detail}",
    "course.remove_student": "Removed a student from a course: {detail}",
    "group.split": "Split a course into groups: {detail}",
    "group.create": "Added a group: {detail}",
    "group.rename": "Renamed a group: {detail}",
    "group.delete": "Took a group away: {detail}",
    "group.clear": "Took every group of a course away: {detail}",
    "group.move": "Moved a student between groups: {detail}",

    "device.create": "Added a device: {detail}",
    "device.update": "Changed the device settings: {detail}",
    "device.sync_time": "Set the device clock from this computer",
    "device.push_users": "Sent people to the device: {detail}",
    "device.clear_attendance": "Cleared the scans on the device: {detail}",
    "device.remove_person": "Took somebody off the terminal: {detail}",
    "device.empty": "Emptied the terminal of people and fingerprints: {detail}",
    "device.unlock_menu": "Unlocked the device menu: {detail}",
    "device.restart": "Restarted the terminal: {detail}",
    "device.network_setup": "Put this computer's Ethernet on the terminal's network: {detail}",
    "device.network_undo": "Took the terminal's address off this computer's Ethernet: {detail}",
    "reminder.remind_later": "Put off a reminder: {detail}",
    "reminder.cancel": "Cancelled a reminder: {detail}",
    "reminder.restore": "Brought a reminder back: {detail}",

    "punches.import.network": "Read the scans from the terminal over the cable: {detail}",
    "punches.import.usb": "Read the scans from a file carried on a USB stick: {detail}",
    "session.create": "Recorded a class: {detail}",
    "session.live_start": "Started taking attendance: {detail}",
    "session.live_end": "Ended taking attendance: {detail}",
    "session.live_reopen": "Reopened a class for the students who had not scanned: {detail}",
    "session.live_end_again": "Ended a reopened class: {detail}",
    "session.week": "Moved a class to another week of the sheet: {detail}",
    "session.group": "Changed which group a class was for: {detail}",
    "person.edit": "Changed a student's details: {detail}",
    "session.cancel": "Cancelled a class: {detail}",
    "session.restore": "Restored a cancelled class: {detail}",
    "session.assign_course": "Put a class on a course",
    "session.detect": "Worked classes out from the scans: {detail}",
    "attendance.mark": "Corrected a student's attendance: {detail}",
    "correction.request": "Asked for a correction: {detail}",
    "correction.decide": "Decided a correction request: {detail}",
    "excusal.create": "Recorded an excused absence: {detail}",
    "excusal.revoke": "Withdrew an excused absence: {detail}",

    "template.create": "Made the attendance sheet for a course",
    "template.update": "Changed the attendance sheet: {detail}",
    "template.weeks": "Changed the sheet's weeks: {detail}",
    "attendance_plan.save": "Changed the weeks and the pass mark: {detail}",
    "settings.update": "Changed settings: {detail}",

    "backup.download": "Downloaded a backup of the whole register",
    "backup.auto": "Took an automatic backup after a pull: {detail}",
    "backup.auto.failed": "Could not take the automatic backup {detail}; the scans themselves were stored",
    "backup.restore": "Replaced the whole register with a backup. {detail}",
    "backup.import": "Brought in the data from another computer. {detail}",
    "audit.export": "Exported the activity log: {detail}",
}

# What each action is about, so the screen can narrow to one kind of thing.
GROUPS = {
    "Attendance": ("session.", "class.", "attendance.", "correction.", "excusal.", "punches."),
    "People": ("roster.", "staff.", "person.", "account.", "role.", "course.", "group.", "finger.",
               "enrollment."),
    "Device": ("device.", "reminder."),
    "Setting up": ("setup", "settings.", "academic_session.", "level.", "template.",
                   "attendance_plan."),
    "Records": ("backup.", "audit."),
}


def group_of(action: str) -> str:
    for name, prefixes in GROUPS.items():
        if any(action == prefix or action.startswith(prefix) for prefix in prefixes):
            return name
    return "Other"


def sentence(action: str, detail: str | None) -> str:
    """A plain sentence for one row. Never a Python repr, and never only an action name."""
    text = (detail or "").strip()
    template = SENTENCES.get(action)
    if template is None:
        return f"{action}{f': {text}' if text else ''}"
    if "{detail}" not in template:
        return template
    if not text:
        # The sentence names the thing; without a detail it stops before the colon.
        return template.split(":")[0].rstrip()
    return template.format(detail=_readable(text))


def _readable(text: str) -> str:
    """Settings were logged as str(dict). Turn that back into words rather than showing a repr."""
    if text.startswith("{") and text.endswith("}"):
        try:
            parsed = ast.literal_eval(text)
        except (ValueError, SyntaxError):
            return text
        if isinstance(parsed, dict):
            return ", ".join(f"{key.replace('_', ' ')} to {value}" for key, value in parsed.items())
    return text


def query(conn: sqlite3.Connection, *, date_from: str | None = None, date_to: str | None = None,
          account_id: int | None = None, group: str | None = None, limit: int = 200) -> list[dict]:
    sql = ("SELECT l.*, a.display_name, a.username, r.name AS role FROM audit_log l"
           " LEFT JOIN accounts a ON a.id = l.account_id"
           " LEFT JOIN roles r ON r.id = a.role_id WHERE 1 = 1")
    params: list = []
    if date_from:
        sql += " AND l.at >= ?"
        params.append(date_from)
    if date_to:
        # Inclusive of the whole day, so "to 21 September" includes everything that day.
        sql += " AND l.at <= ?"
        params.append(f"{date_to}T23:59:59")
    if account_id is not None:
        sql += " AND l.account_id = ?"
        params.append(account_id)
    sql += " ORDER BY l.id DESC LIMIT ?"
    params.append(min(max(limit, 1), 5000))

    rows = []
    for row in conn.execute(sql, params):
        item = dict(row)
        item["group"] = group_of(item["action"])
        item["sentence"] = sentence(item["action"], item["detail"])
        item["by"] = item["display_name"] or "Herewise itself"
        if group and item["group"] != group:
            continue
        rows.append(item)
    return rows


def to_csv(rows: list[dict]) -> bytes:
    """A CSV anyone can open. UTF-8 with a BOM, because Excel on Windows assumes 1252 without it."""
    out = io.StringIO(newline="")
    writer = csv.writer(out)
    writer.writerow(["When", "Who", "Their role", "What happened", "Action", "What it touched"])
    for row in rows:
        writer.writerow([row["at"], row["by"], row["role"] or "", row["sentence"], row["action"],
                         f"{row['entity'] or ''} {row['entity_id'] or ''}".strip()])
    return out.getvalue().encode("utf-8-sig")


def actors(conn: sqlite3.Connection) -> list[dict]:
    """Everyone who appears in the log, so the filter offers only people who did something."""
    rows = conn.execute(
        "SELECT a.id, a.display_name, a.username, COUNT(*) AS entries FROM audit_log l"
        " JOIN accounts a ON a.id = l.account_id GROUP BY a.id ORDER BY a.display_name")
    return [dict(r) for r in rows]
