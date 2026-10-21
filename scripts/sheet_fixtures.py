"""Write the Living sheet gallery fixtures by running the real backend on a scratch database.

Run:  python scripts/sheet_fixtures.py

Every fixture is the output of templates.grid, so it matches GET /api/templates/{id}/sheet exactly and
cannot drift from it. The roster is synthetic: real student names never go into rollcall/static, which is
packaged with the app. Fixed seed and fixed dates, so re-running changes nothing unless the contract does.
"""

import json
import random
import sys
import tempfile
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from rollcall import courses, db, register, roster, templates  # noqa: E402
from rollcall.device import RawPunch  # noqa: E402
from rollcall.punches import store_punches  # noqa: E402

OUT = ROOT / "rollcall" / "static" / "gallery" / "fixtures"
TODAY = date(2026, 10, 21)          # a Wednesday in week 6 of a course starting 14 September
WEEK1 = "2026-09-14"
GENERATED_AT = "2026-10-21T09:00:00"

SURNAMES = ["ADEBAYO", "AFOLABI", "BALOGUN", "CHUKWU", "DANJUMA", "EZE", "GARBA", "IBRAHIM", "JOHNSON",
            "KAMALU", "LAWAL", "MUSA", "NWOSU", "OKAFOR", "OLADIPO", "OYELARAN", "SANI", "TIJANI", "UDOH",
            "YUSUF", "AKINWUMI", "BELLO", "EKWUEME", "FASHOLA", "IGWE", "OGUNDIPE", "ONYEKACHI", "ADEWALE"]
GIVEN = ["Folake", "Takme", "Sule", "Ngozi", "Aisha", "Chinaza", "Musa", "Halima", "Tayo", "Ifeoma", "Bola",
         "Emeka", "Yusuf", "Temi", "Kelechi", "Zainab", "Dayo", "Amaka", "Segun", "Hadiza", "Oluwaseun"]
# At the 40 character limit the brief names, and long enough to test the frozen column.
LONG_NAMES = ["OYELARAN-ADEBOWALE Oluwatimilehin Adeola", "EKWUEME-NWACHUKWU Chukwuemeka Ifeanyi"]


def synthetic_roster(count: int, rng: random.Random) -> str:
    lines = ["matric_no,name,level"]
    for n in range(1, count + 1):
        name = LONG_NAMES[n % 2] if n in (7, 131) else f"{rng.choice(SURNAMES)} {rng.choice(GIVEN)}"
        lines.append(f"PCT/24/{n:04d},{name},200")
    return "\n".join(lines) + "\n"


def fresh(folder: Path, name: str):
    conn = db.connect(folder / f"{name}.db")
    db.initialise(conn)
    conn.execute("INSERT INTO academic_sessions(name, is_current, created_at) VALUES ('2026/2027', 1, ?)", (db.now(),))
    conn.execute("INSERT INTO devices(name, ip, is_default, created_at) VALUES ('K40', '192.168.1.201', 1, ?)",
                 (db.now(),))
    owner = conn.execute("SELECT id FROM roles WHERE is_owner = 1").fetchone()["id"]
    conn.execute("INSERT INTO accounts(username, display_name, role_id, password_hash, created_at)"
                 " VALUES ('lecturer', 'Course lecturer', ?, 'x', ?)", (owner, db.now()))
    return conn


def import_roster(conn, text: str) -> tuple[int, int]:
    level = conn.execute("SELECT id FROM levels WHERE level_number = 200").fetchone()["id"]
    import_id = conn.execute(
        "INSERT INTO roster_imports(level_id, academic_session_id, device_id, csv_text, status, created_at)"
        " VALUES (?, 1, 1, ?, 'pending', ?)", (level, text, db.now())).lastrowid
    roster.commit(conn, import_id, 1)
    course_id = courses.create_course(conn, 1, level, "PCT 201", "Pharmaceutics", 1)
    return course_id, templates.ensure_template(conn, course_id)


def add_carry_over(conn, course_id: int, count: int) -> None:
    entries = [{"matric_no": f"PCT/23/{n:04d}", "name": f"{SURNAMES[n % len(SURNAMES)]} {GIVEN[n % len(GIVEN)]}",
                "level": 300} for n in range(1, count + 1)]
    entries[3]["name"] = LONG_NAMES[0]
    courses.carry_over_commit(conn, course_id, entries, 1)


def hold_classes(conn, course_id: int, weeks: int, per_week: int, rng: random.Random,
                 skip: set[tuple[int, int]], extra_in_week: int | None) -> None:
    """Hold every class up to TODAY except those in skip, scan most students, correct and excuse a few."""
    people = courses.members(conn, course_id)
    start = date.fromisoformat(WEEK1)
    # Excused students stay away from the scanner on those days, because a scan beats an excusal.
    away = [(people[30], start, start + timedelta(days=10), "medical", "Clinic note 114", None),
            (people[31], start + timedelta(days=21), start + timedelta(days=25), "official",
             "Inter-faculty sports", course_id)]
    held = []
    for week in range(weeks):
        for slot in range(per_week):
            day = start + timedelta(days=7 * week + (1 if slot == 0 else 3))
            if day >= TODAY or (week + 1, slot + 1) in skip:
                continue
            held.append(register.create_session(conn, course_id, day.isoformat(), "09:00", "11:00", "device", 1))
            absent = {a[0]["id"] for a in away if a[1] <= day <= a[2]}
            present = [p for p in people if rng.random() < 0.9 and p["id"] not in absent]
            when = datetime.combine(day, datetime.strptime("09:04", "%H:%M").time())
            store_punches(conn, 1, [RawPunch(str(p["device_user_id"]), when + timedelta(seconds=17 * i), 1, 255)
                                    for i, p in enumerate(present)], "network", 1)
    if extra_in_week:
        day = start + timedelta(days=7 * (extra_in_week - 1) + 4)
        register.create_session(conn, course_id, day.isoformat(), "14:00", "16:00", "manual", 1)
    # Corrections both ways on the first held classes.
    for i, session_id in enumerate(held[:4]):
        register.add_mark(conn, session_id, people[i + 2]["id"], "present", "Scanner would not read the thumb", 1)
        register.add_mark(conn, session_id, people[i + 20]["id"], "absent", "Left before the class began", 1)
    for person, date_from, date_to, category, note, course in away:
        register.add_excusal(conn, person["id"], date_from.isoformat(), date_to.isoformat(), category, note, 1,
                             course_id=course)


def sheet(conn, template_id: int) -> dict:
    data = templates.grid(conn, template_id, today=TODAY)
    # Wall-clock stamps pinned, so a regenerated fixture differs only when the contract does.
    data["generated_at"] = data["template"]["created_at"] = data["template"]["updated_at"] = GENERATED_AT
    return data


def build(folder: Path) -> dict[str, dict]:
    out = {}

    # 12 weeks by 2 classes: the usual course. Week 3's second class never happened; week 6 had an extra.
    conn = fresh(folder, "w24")
    rng = random.Random(20260919)
    course_id, tid = import_roster(conn, synthetic_roster(258, rng))
    add_carry_over(conn, course_id, 12)
    templates.generate_weeks(conn, tid, 1, weeks=12, classes_per_week=2, week1_start=WEEK1)
    hold_classes(conn, course_id, 12, 2, rng, skip={(3, 2)}, extra_in_week=5)
    out["sheet-24"] = sheet(conn, tid)
    conn.close()

    # 15 weeks by 2 classes: the widest sheet the brief names, with a revision week label.
    conn = fresh(folder, "w30")
    rng = random.Random(20260920)
    course_id, tid = import_roster(conn, synthetic_roster(258, rng))
    add_carry_over(conn, course_id, 12)
    templates.generate_weeks(conn, tid, 1, weeks=15, classes_per_week=2, week1_start=WEEK1)
    weeks = [{"classes": 2} for _ in range(15)]
    weeks[14]["label"] = "REVISION"
    templates.set_weeks(conn, tid, 1, weeks)
    hold_classes(conn, course_id, 15, 2, rng, skip={(2, 1)}, extra_in_week=None)
    out["sheet-30"] = sheet(conn, tid)
    conn.close()

    # 12 weeks by 1 class, held so far: single-class headers must fit on one line.
    conn = fresh(folder, "w12")
    rng = random.Random(20260921)
    course_id, tid = import_roster(conn, synthetic_roster(40, rng))
    templates.generate_weeks(conn, tid, 1, weeks=12, classes_per_week=1, week1_start=WEEK1)
    hold_classes(conn, course_id, 12, 1, rng, skip=set(), extra_in_week=None)
    out["sheet-12"] = sheet(conn, tid)
    conn.close()

    # Start date set, nothing held yet.
    conn = fresh(folder, "noclasses")
    rng = random.Random(20260922)
    _, tid = import_roster(conn, synthetic_roster(258, rng))
    templates.generate_weeks(conn, tid, 1, weeks=12, classes_per_week=2, week1_start="2026-11-02")
    out["sheet-no-classes"] = sheet(conn, tid)
    conn.close()

    # No week 1 start date: the default template straight after import, with a class already held.
    conn = fresh(folder, "nostart")
    rng = random.Random(20260923)
    course_id, tid = import_roster(conn, synthetic_roster(258, rng))
    register.create_session(conn, course_id, "2026-09-15", "09:00", "11:00", "device", 1)
    out["sheet-no-start"] = sheet(conn, tid)
    conn.close()

    # A course with nobody on it.
    conn = fresh(folder, "empty")
    level = conn.execute("SELECT id FROM levels WHERE level_number = 300").fetchone()["id"]
    course_id = courses.create_course(conn, 1, level, "PCT 305", "Pharmaceutical Microbiology", 1)
    tid = templates.ensure_template(conn, course_id, 1)
    templates.generate_weeks(conn, tid, 1, weeks=12, classes_per_week=2, week1_start=WEEK1)
    out["sheet-empty"] = sheet(conn, tid)
    conn.close()
    return out


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        fixtures = build(Path(tmp))
    for name, data in fixtures.items():
        (OUT / f"{name}.json").write_text(json.dumps(data, separators=(",", ":")) + "\n", encoding="utf-8")
        cells = sum(len(s["cells"]) for s in data["students"])
        print(f"{name:18} {data['total_registered']:4} students, {len(data['weeks']):2} weeks, "
              f"{cells:5} boxes, {data['classes_held']:2} held, {len(data['warnings'])} warning(s)")


if __name__ == "__main__":
    main()
