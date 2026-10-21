"""Fill a scratch database with a term's worth of realistic register, for looking at screens.

    python scripts/demo_data.py [--reset]

Never point this at the lecturer's data. It writes to ROLLCALL_DATA_DIR, or %TEMP%\\herewise-dev,
the same folder scripts/dev_server.py uses, and refuses to touch a database it did not make unless
--reset is given.

The roster is synthetic. Real student names stay out of anything that can be screenshotted, and one
name carries Yoruba tone marks because the PDF and the device both had faults only those found.
Everything is written through the real modules, so a screen built against this sees exactly the
shapes the backend produces.
"""
from __future__ import annotations

import os
import random
import sys
import tempfile
from datetime import date, datetime, time, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from rollcall import auth, courses, db, groups, register, roles, roster, templates  # noqa: E402
from rollcall.device import RawPunch  # noqa: E402
from rollcall.punches import store_punches  # noqa: E402

SURNAMES = ["ADEBAYO", "AFOLABI", "BALOGUN", "CHUKWU", "DANJUMA", "EZE", "GARBA", "IBRAHIM",
            "JOHNSON", "KAMALU", "LAWAL", "MUSA", "NWOSU", "OKAFOR", "OLADIPO", "OYELARAN", "SANI",
            "TIJANI", "UDOH", "YUSUF", "AKINWUMI", "BELLO", "EKWUEME", "FASHOLA", "IGWE",
            "OGUNDIPE", "ONYEKACHI", "ADEWALE", "NNAMDI", "SALAMI"]
GIVEN = ["Folake", "Takme", "Sule", "Ngozi", "Aisha", "Chinaza", "Musa", "Halima", "Tayo", "Ifeoma",
         "Bola", "Emeka", "Yusuf", "Temi", "Kelechi", "Zainab", "Dayo", "Amaka", "Segun", "Hadiza",
         "Oluwaseun", "Chidi", "Fatima", "Obinna"]
# The two the faults were found with: a 40 character name, and one with Yoruba tone marks.
LONG_NAME = "OYELARAN-ADEBOWALE Oluwatimilehin Adeola"
YORUBA_NAME = "ỌLÁBÍSÍ Ṣóyínká Adéwálé"

LECTURER = ("aokonkwo", "Dr A. Okonkwo", "herewise-dev-pass")
REP = ("cumeh", "Chidi Umeh", "herewise-dev-pass")
VIEWER = ("eexams", "E. Nwankwo", "herewise-dev-pass")

COURSES = [("PCT 201", "Pharmaceutics", 200), ("PCT 203", "Physiology", 200),
           ("PCT 209", "Pharmacognosy", 200), ("PCT 211", "Pharmacology", 200)]


def data_folder() -> Path:
    return Path(os.environ.get("ROLLCALL_DATA_DIR") or (Path(tempfile.gettempdir()) / "herewise-dev"))


def roster_csv(count: int, rng: random.Random) -> str:
    lines = ["matric_no,name,level"]
    for n in range(1, count + 1):
        if n == 7:
            name = LONG_NAME
        elif n == 12:
            name = YORUBA_NAME
        else:
            name = f"{rng.choice(SURNAMES)} {rng.choice(GIVEN)}"
        lines.append(f"PCT/24/{n:04d},{name},200")
    return "\n".join(lines) + "\n"


def build(conn, rng: random.Random, today: date) -> None:
    owner = roles.owner_role_id(conn)
    rep_role = conn.execute("SELECT id FROM roles WHERE name = 'Course rep'").fetchone()["id"]
    viewer_role = conn.execute("SELECT id FROM roles WHERE name = 'Viewer'").fetchone()["id"]
    with db.transaction(conn):
        account = auth.create_account(conn, *LECTURER[:2], LECTURER[2], owner)
        rep_account = auth.create_account(conn, *REP[:2], REP[2], rep_role)
        auth.create_account(conn, *VIEWER[:2], VIEWER[2], viewer_role)
        conn.execute("INSERT INTO academic_sessions(name, is_current, created_at) VALUES ('2026/2027', 1, ?)",
                     (db.now(),))
        conn.execute("INSERT INTO devices(name, ip, port, comm_key, is_default, serial, firmware,"
                     " platform, created_at) VALUES ('K40', '192.168.1.201', 4370, 0, 1,"
                     " 'FDDW250226081', 'Ver 6.60', 'ZLM60_TFT', ?)", (db.now(),))

    level = conn.execute("SELECT id FROM levels WHERE level_number = 200").fetchone()["id"]
    import_id = conn.execute(
        "INSERT INTO roster_imports(level_id, academic_session_id, device_id, file_name, csv_text,"
        " status, created_at, account_id) VALUES (?, 1, 1, 'pct200.csv', ?, 'pending', ?, ?)",
        (level, roster_csv(258, rng), db.now(), account)).lastrowid
    roster.commit(conn, import_id, account)
    # An import makes no course (2026-09-24): the lecturer makes each one, and it takes the level.
    made = [courses.create_course(conn, 1, level, code, title, account) for code, title, _ in COURSES]

    # Carry-over students on the second course, as the real one has.
    entries = [{"matric_no": f"PCT/23/{n:04d}",
                "name": f"{SURNAMES[n % len(SURNAMES)]} {GIVEN[n % len(GIVEN)]}", "level": 300}
               for n in range(1, 13)]
    entries[3]["name"] = LONG_NAME
    courses.carry_over_commit(conn, made[1], entries, account)

    # Everyone is on the device, so pushes and enrolment screens have something to show.
    conn.execute("UPDATE people SET on_device = 1 WHERE role = 'student'")

    # The lecturer is the only Super Admin, which raises the "choose a second" reminder.
    staff = conn.execute(
        "INSERT INTO people(role, device_user_id, device_id, surname, other_names, source_name,"
        " device_name, device_privilege, device_password, on_device, created_at)"
        " VALUES ('staff', 1, 1, 'OKONKWO', 'A.', 'OKONKWO A.', 'OKONKWO A.', 14, '2468', 1, ?)",
        (db.now(),)).lastrowid
    conn.execute("UPDATE accounts SET person_id = ? WHERE id = ?", (staff, account))
    # The course representative is on the register, which is exactly why "nobody corrects their own
    # record" cannot be a permission. Linking the account here makes that refusal real to look at.
    rep_person = conn.execute(
        "SELECT p.id FROM people p JOIN course_enrolments e ON e.person_id = p.id"
        " WHERE e.course_id = ? ORDER BY p.device_user_id LIMIT 1 OFFSET 2", (made[0],)).fetchone()
    conn.execute("UPDATE people SET surname = 'UMEH', other_names = 'Chidi' WHERE id = ?",
                 (rep_person["id"],))
    conn.execute("UPDATE accounts SET person_id = ? WHERE id = ?", (rep_person["id"], rep_account))

    week1 = today - timedelta(days=today.weekday() + 7 * 5)     # week 1 started five weeks ago
    for course_id, (code, title, _) in zip(made, COURSES):
        # PCT 211 is taken in groups (take_in_groups): a lecture for everybody and a practical for
        # each group every week, so each student has two classes a week and each week two boxes.
        per_week = 2 if code == "PCT 211" else 1
        template_id = templates.ensure_template(conn, course_id)
        templates.update_template(conn, template_id, account, title=f"200 LEVEL ATTENDANCE",
                                  course_code=code, week1_start=week1.isoformat())
        templates.generate_weeks(conn, template_id, account, weeks=12, classes_per_week=per_week,
                                 week1_start=week1.isoformat())
        register.save_plan(conn, course_id, account, weeks=12, classes_per_week=per_week,
                           total_classes=None, threshold_percent=75)

    hold_classes(conn, made, account, rng, week1, today)
    take_in_groups(conn, made[3], account, rng, week1, today)
    # One class Herewise could not place, because these four courses share every student: the state
    # screen 6 exists for, and the one a lecturer actually meets.
    conn.execute("UPDATE class_sessions SET course_id = NULL WHERE id ="
                 " (SELECT id FROM class_sessions WHERE course_id = ? AND cancelled_at IS NULL"
                 "  ORDER BY date DESC LIMIT 1 OFFSET 1)", (made[1],))
    raise_requests(conn, made[0], account, rep_account)
    conn.commit()


def raise_requests(conn, course_id, account, rep_account) -> None:
    """One request waiting and one already decided, so screen 41 has both states to show."""
    held = conn.execute(
        "SELECT id FROM class_sessions WHERE course_id = ? AND cancelled_at IS NULL"
        " ORDER BY date DESC LIMIT 2", (course_id,)).fetchall()
    if len(held) < 2:
        return
    # Someone actually absent from that class, so the change line reads absent to present rather
    # than present to present.
    def absent_in(session_id):
        return next(s["person_id"] for s in register.session_register(conn, session_id)["students"]
                    if s["status"] == "absent")

    waiting = register.request_correction(
        conn, held[0]["id"], absent_in(held[0]["id"]), "present",
        "She signed the paper sheet at the door. The scanner would not read her thumb.", rep_account)
    decided = register.request_correction(
        conn, held[1]["id"], absent_in(held[1]["id"]), "present",
        "He was in the hall the whole time, I marked him on my own list.", rep_account)
    register.decide_request(conn, decided, True, "Checked against the queue video.", account)
    return waiting


def hold_classes(conn, course_ids, account, rng, week1, today) -> None:
    """Five weeks of classes, with scans, a cancellation, corrections, excusals and a live class."""
    slots = [(0, time(9, 0), time(11, 0)), (2, time(12, 0), time(14, 0)),
             (3, time(15, 0), time(17, 0)), (4, time(8, 0), time(10, 0))]
    punches, marks, excusals = [], [], []

    for index, course_id in enumerate(course_ids):
        members = courses.members(conn, course_id)
        weekday, start, end = slots[index]
        for week in range(6):
            day = week1 + timedelta(days=7 * week + weekday)
            if day > today:
                continue
            if week == 3 and index == 1:
                continue                                  # a week with no class at all
            session_id = register.create_session(conn, course_id, day.isoformat(),
                                                 start.strftime("%H:%M"), end.strftime("%H:%M"),
                                                 "device", account)
            if week == 4 and index == 2:
                register.cancel_session(conn, session_id, "Lecture hall double booked.", account)
                continue
            # Most students scan, a few do not, and one class is still running today.
            for person in members:
                if rng.random() < 0.08:
                    continue
                moment = datetime.combine(day, start) + timedelta(minutes=rng.randint(-8, 25))
                punches.append(RawPunch(user_id=str(person["device_user_id"]), timestamp=moment,
                                        verify_type=1, punch_state=255))
            if week == 2 and index == 0:
                marks.append((session_id, members[4]["id"], "present",
                              "Scanner was not working when they arrived. Signed the paper sheet."))
                marks.append((session_id, members[9]["id"], "absent",
                              "Scanned for a friend who was not in the hall."))

    # Stored week by week, the way a lecturer actually pulls: one batch after each week's classes,
    # so "last pulled" and screen 5 show one realistic pull rather than a term in one go.
    punches.sort(key=lambda p: p.timestamp)
    by_week: dict[int, list] = {}
    for punch in punches:
        by_week.setdefault((punch.timestamp.date() - week1).days // 7, []).append(punch)
    for _, weekly in sorted(by_week.items()):
        store_punches(conn, 1, weekly, "network", account)
    for session_id, person_id, status, note in marks:
        register.add_mark(conn, session_id, person_id, status, note, account)

    members = courses.members(conn, course_ids[0])
    register.add_excusal(conn, members[2]["id"], (week1 + timedelta(days=14)).isoformat(),
                         (week1 + timedelta(days=18)).isoformat(), "medical",
                         "Hospital admission, letter from the clinic.", account, course_ids[0])
    register.add_excusal(conn, members[6]["id"], (week1 + timedelta(days=7)).isoformat(),
                         (week1 + timedelta(days=9)).isoformat(), "official",
                         "Representing the faculty at the inter-university games.", account, None)

    # A class today, so Today has rows to show. Only when the weekly slot did not already put one
    # there: two classes at the same time on the same day is not a state the app should be shown in.
    already = conn.execute(
        "SELECT 1 FROM class_sessions WHERE course_id = ? AND date = ? AND start_time = '09:00'",
        (course_ids[0], today.isoformat())).fetchone()
    if already:
        return None
    today_id = register.create_session(conn, course_ids[0], today.isoformat(), "09:00", "11:00",
                                       "device", account)
    todays = courses.members(conn, course_ids[0])
    store_punches(conn, 1, [
        RawPunch(user_id=str(p["device_user_id"]),
                 timestamp=datetime.combine(today, time(9, 0)) + timedelta(minutes=rng.randint(-5, 20)),
                 verify_type=1, punch_state=255)
        for p in todays if rng.random() > 0.11], "network", account)
    register.create_session(conn, course_ids[2], today.isoformat(), "15:00", "17:00", "device", account)
    return today_id


def take_in_groups(conn, course_id, account, rng, week1, today) -> None:
    """PCT 211 split into Groups A to D, the way a department runs practicals (asked for on 2026-09-29).

    Its Friday lecture stays a class for everybody; each group also has a practical on Tuesdays. One
    student moves from Group A to Group B from week 3, so both sheets show the boxes that were not
    theirs; one Group B student scans at Group A's practical in week 2, which the register lists
    rather than counts; and a carry-over student joins after the split and is in no group yet. The
    other three courses keep their whole roster.
    """
    made = groups.split(conn, course_id, 4, "matric", account)
    ids = [g["id"] for g in made]
    mover = sorted(groups.in_group_on(conn, ids[0], week1.isoformat()))[3]
    visitor = sorted(groups.in_group_on(conn, ids[1], week1.isoformat()))[5]

    # The practicals first: a move with no class of the old group to keep is the same as a wrong
    # group, and changes the whole stretch (groups.move), so the classes have to exist before it.
    starts = [time(8, 0), time(10, 30), time(13, 0), time(15, 30)]
    practicals = []
    for week in range(6):
        day = week1 + timedelta(days=7 * week + 1)                 # Tuesdays
        if day >= today:
            continue
        for group_id, start in zip(ids, starts):
            end = (datetime.combine(day, start) + timedelta(minutes=90)).time()
            practicals.append((week, group_id, register.create_session(
                conn, course_id, day.isoformat(), start.strftime("%H:%M"), end.strftime("%H:%M"), "device",
                account, group_id=group_id)))
    moved_on = week1 + timedelta(days=7 * 2 + 1)
    groups.move(conn, course_id, mover, ids[1], "from_today", account, day=moved_on.isoformat())

    punches = []
    for week, group_id, session_id in practicals:
        s = conn.execute("SELECT * FROM class_sessions WHERE id = ?", (session_id,)).fetchone()
        start = datetime.fromisoformat(f"{s['date']}T{s['start_time']}")
        expected = [p["device_user_id"] for p in groups.class_members(conn, s)]
        if week == 1 and group_id == ids[0]:
            expected.append(conn.execute("SELECT device_user_id FROM people WHERE id = ?",
                                         (visitor,)).fetchone()[0])
        for user_id in expected:
            if rng.random() < 0.1:
                continue
            moment = start + timedelta(minutes=rng.randint(-8, 25))
            punches.append(RawPunch(user_id=str(user_id), timestamp=moment, verify_type=1, punch_state=255))
    punches.sort(key=lambda p: p.timestamp)
    store_punches(conn, 1, punches, "network", account)
    # Joined after the split, so in no group until somebody puts them in one.
    courses.carry_over_commit(conn, course_id, [{"matric_no": "PCT/23/0101", "name": "BELLO Kelechi",
                                                 "level": 300}], account)


def main() -> None:
    folder = data_folder()
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "rollcall.db"
    if path.exists():
        if "--reset" not in sys.argv:
            print(f"{path} already exists. Run with --reset to replace it.")
            return
        path.unlink()
        for extra in folder.glob("rollcall.db-*"):
            extra.unlink()

    conn = db.connect(path)
    db.initialise(conn)
    build(conn, random.Random(20260920), date.today())
    conn.close()
    print(f"Demo register written to {path}")
    print(f"  sign in as {LECTURER[0]} / {LECTURER[2]} (owns everything)")
    print(f"             {REP[0]} / {REP[2]} (Course rep: can ask for corrections, not apply them)")
    print(f"             {VIEWER[0]} / {VIEWER[2]} (Viewer: reads only)")


if __name__ == "__main__":
    main()
