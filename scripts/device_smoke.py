#!/usr/bin/env python3
"""Drive a running Roll Call server against the real K40 and check the results on the device itself.

Usage: python scripts/device_smoke.py [base_url]
Run it against a server started with a scratch ROLLCALL_DATA_DIR, never the lecturer's database. A
folder that has been used before is fine: the script signs in instead of setting up again.
It pushes the level 200 roster and a test admin, reads everything back from the device, lets one
enrollment time out with nobody pressing, then deletes every user it created so the device is empty.
"""
import sys
import time
from pathlib import Path

# The last check pushes Yoruba, German and Hausa names and prints what came back. A Windows console
# is cp1252 unless told otherwise, so printing the result killed the run after every check had
# already passed (2026-09-21). Nothing is lost by replacing what a console cannot draw.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import httpx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from rollcall.device import DeviceTarget, K40  # noqa: E402

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000"
k40 = K40(DeviceTarget("192.168.1.201"))


def check(label, ok, extra=""):
    print(f"[{'PASS' if ok else 'FAIL'}] {label} {extra}")
    if not ok:
        raise SystemExit(1)


def call(c, method, path, **kw):
    r = c.request(method, path, **kw)
    if r.status_code >= 400:
        print("   ", method, path, r.status_code, r.text[:300])
    return r


before = k40.snapshot()
check("device starts empty", before.users == 0 and before.templates == 0 and before.records == 0,
      f"users={before.users} templates={before.templates} records={before.records}")

created_ids = []
with httpx.Client(base_url=BASE, timeout=240) as c:
    try:
        account = {"username": "smoke", "password": "smoke-test-1"}
        first_run = c.post("/api/setup", json={**account, "display_name": "Smoke test",
                                               "academic_session": "2026/2027"})
        if first_run.status_code == 409:                 # the folder has been used before: sign in instead
            call(c, "POST", "/api/login", json=account)
        elif first_run.status_code >= 400:
            check("setup", False, first_run.text[:200])
        diag = call(c, "GET", "/api/devices/1/diagnose").json()
        for item in diag["checks"]:
            print("   ", "ok " if item["ok"] else "BAD", item["name"], "-", item["message"])
        check("diagnostics all pass", diag["ok"])

        status = call(c, "GET", "/api/devices/1/status").json()
        check("status reads serial", status["serial"] == "FDDW250226081", status["serial"])
        check("clock within limit", status["clock_warning"] is None, f"drift={status['clock_drift_seconds']}s")

        levels = call(c, "GET", "/api/levels").json()
        lvl = next(l["id"] for l in levels if l["level_number"] == 200)
        preview = call(c, "POST", f"/api/levels/{lvl}/roster/preview",
                       files={"file": ("synthetic_200_roster.csv", (ROOT / "data/synthetic_200_roster.csv").read_bytes())}).json()
        check("preview 258 new, 2001-2258", preview["new"] == 258 and preview["id_range"] == [2001, 2258])
        call(c, "POST", f"/api/roster-imports/{preview['import_id']}/commit")

        started = time.time()
        push = call(c, "POST", "/api/devices/1/push", json={"level_id": lvl}).json()
        created_ids += list(range(2001, 2259))
        check("pushed 258 to device", push.get("pushed") == 258, f"in {time.time() - started:.1f}s")

        students = call(c, "GET", f"/api/levels/{lvl}/students").json()["students"]
        expected = {s["device_user_id"]: s["device_name"] for s in students}
        on_device = {int(u.user_id): u for u in k40.read_users()}
        mismatched = [(i, expected[i], on_device[i].name) for i in expected if i not in on_device
                      or on_device[i].name != expected[i]]
        check("every device name reads back exactly", not mismatched, str(mismatched[:3]))
        check("every uid equals user_id", all(u.uid == i for i, u in on_device.items()))

        staff = call(c, "POST", "/api/staff", json={"surname": "ROLLCALL", "other_names": "Smoke Admin",
                                                     "device_user_id": 999, "super_admin": True,
                                                     "password": "4321"}).json()
        call(c, "POST", "/api/devices/1/push", json={"person_ids": [staff["person_id"]]})
        created_ids.append(999)
        admin = next(u for u in k40.read_users() if u.user_id == "999")
        check("test admin is privilege 14 with password", admin.privilege == 14 and admin.has_password)

        reminder_keys = [r["key"] for r in call(c, "GET", "/api/reminders").json()]
        check("one admin raises the second Super Admin reminder", reminder_keys == ["second_super_admin:1"])
        second = call(c, "POST", f"/api/people/{students[0]['id']}/device-role",
                      json={"super_admin": True, "password": "1111", "confirm_student": True}).json()
        on_device = {u.user_id: u for u in k40.read_users()}
        check("chosen second admin is privilege 14 on the device",
              on_device["2001"].privilege == 14 and second["super_admins_on_device"] == 2)
        check("reminder clears once there are two", call(c, "GET", "/api/reminders").json() == [])

        unlock = call(c, "POST", "/api/devices/1/unlock-menu", json={"confirm_serial": before.serial}).json()
        on_device = {u.user_id: u for u in k40.read_users()}
        check("unlock-menu demoted both admins over TCP",
              sorted(unlock["demoted_user_ids"]) == ["2001", "999"]
              and on_device["999"].privilege == 0 and on_device["2001"].privilege == 0)

        pull1 = call(c, "POST", "/api/devices/1/pull").json()
        pull2 = call(c, "POST", "/api/devices/1/pull").json()
        check("pull works and repeats cleanly", pull1["records_read"] == pull2["records_read"] and pull2["new"] == 0,
              pull1["message"])

        sync = call(c, "POST", "/api/devices/1/sync-fingers").json()
        check("finger sync sees all users", sync["device_users"] == 259 and not sync["missing_from_device"], str(sync))

        print("    enrollment timeout test: nobody presses a finger, this waits up to about 3 minutes")
        first = students[0]
        call(c, "POST", "/api/enrollment/start", json={"person_id": first["id"], "finger_index": 0,
                                                        "consent_confirmed": True})
        t0 = time.time()
        while True:
            state = call(c, "GET", "/api/enrollment/status").json()
            if state["state"] == "finished":
                break
            time.sleep(3)
        check("enrollment with no finger ends without capture", state["outcome"] in ("timeout", "not_captured"),
              f"{state['outcome']} after {time.time() - t0:.0f}s: {state['detail']}")
        after = k40.snapshot()
        check("device answers normally after the enrollment attempt", after.serial == "FDDW250226081")

        cleared = call(c, "POST", "/api/devices/1/clear-attendance", json={"confirm_serial": "FDDW250226081"})
        check("guarded clear runs", cleared.status_code == 200, cleared.text[:200])
    finally:
        with k40.session() as conn:
            for uid in created_ids:
                conn.delete_user(uid=uid)
            conn.refresh_data()
        end = k40.snapshot()
        print(f"    cleanup: users={end.users} templates={end.templates} records={end.records}")
        check("device left empty", end.users == 0 and end.templates == 0)

# Names beyond ASCII: Yoruba, German and Hausa letters must come back from the terminal exactly as sent.
# Checked first on 2026-09-19; what the terminal's own screen shows still needs someone to look.
from rollcall.names import device_name  # noqa: E402

wide = {9901: device_name("ỌLÁBÍSÍ", "Ṣẹ́gun Oluwaṣeun"), 9902: device_name("MÜLLER", "Zoë"),
        9903: device_name("ƊANLAMI", "Ɓala")}
try:
    k40.push_users([{"user_id": uid, "name": name, "privilege": 0, "password": ""} for uid, name in wide.items()])
    back = {int(u.user_id): u.name for u in k40.read_users()}
    check("names beyond ASCII read back exactly", all(back.get(uid) == name for uid, name in wide.items()),
          str({uid: back.get(uid) for uid in wide}))
finally:
    for uid in wide:
        k40.delete_user(uid)
    end = k40.snapshot()
    check("device left empty after the name check", end.users == 0 and end.templates == 0)
