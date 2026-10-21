"""Where data lives, the port, the log file and the backup taken before a schema change."""
import logging
import socket
import sqlite3
import sys

from rollcall import backups, config, db, logs


def test_packaged_data_goes_to_local_app_data_not_beside_the_program(tmp_path, monkeypatch):
    program = tmp_path / "Program Files" / "Herewise"
    program.mkdir(parents=True)
    monkeypatch.delenv("ROLLCALL_DATA_DIR", raising=False)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(program / "Herewise.exe"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "Local"))
    assert config.data_dir() == tmp_path / "Local" / "Herewise"

    (program / "portable").write_text("")                       # a copy run from a USB stick
    assert config.data_dir() == program

    monkeypatch.setenv("ROLLCALL_DATA_DIR", str(tmp_path / "chosen"))
    assert config.data_dir() == tmp_path / "chosen"


def test_a_busy_port_moves_the_app_to_the_next_one():
    first = config.free_port(first=38100)
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as taken:
        taken.bind((config.HOST, first))
        taken.listen()
        assert config.free_port(first=first) == first + 1


def test_the_log_file_is_written_in_the_data_folder(tmp_path):
    path = logs.configure(tmp_path)
    logging.getLogger("rollcall").warning("device not answering at 192.168.1.201")
    for handler in logging.getLogger().handlers:
        handler.flush()
    assert path == tmp_path / "logs" / "herewise.log"
    assert path.read_text(encoding="utf-8").count("device not answering") == 1   # once, not once per logger
    for handler in list(logging.getLogger().handlers):
        if getattr(handler, "baseFilename", "") == str(path.resolve()):
            for name in ("", "rollcall", "uvicorn", "uvicorn.error", "uvicorn.access"):
                logging.getLogger(name).removeHandler(handler)
            handler.close()


def test_an_existing_database_is_copied_before_its_schema_changes(tmp_path):
    conn = db.connect(tmp_path / "old.db")
    db.initialise(conn, target=4)
    conn.execute("INSERT INTO settings(key, value) VALUES ('marker', 'kept')")
    db.initialise(conn)                                         # 4 to the current version
    copies = list((tmp_path / "backups").glob("before-schema-*-from-4-*.db"))
    assert len(copies) == 1
    with sqlite3.connect(copies[0]) as copy:
        assert copy.execute("PRAGMA user_version").fetchone()[0] == 4
        assert copy.execute("SELECT value FROM settings WHERE key = 'marker'").fetchone()[0] == "kept"
    conn.close()


def test_a_new_database_makes_no_backup(tmp_path):
    conn = db.connect(tmp_path / "new.db")
    db.initialise(conn)
    assert not (tmp_path / "backups").exists()
    conn.close()


def test_a_pull_that_stores_scans_leaves_a_backup(tmp_path, k40_factory, fake):
    from datetime import datetime

    from fastapi.testclient import TestClient
    from fake_zk import FakeRecord

    from rollcall.app import create_app

    with TestClient(create_app(tmp_path / "b.db", k40_factory=k40_factory)) as c:
        c.post("/api/setup", json={"username": "lecturer", "display_name": "Dr", "password": "secret123",
                                   "academic_session": "2026/2027"})
        fake.records = [FakeRecord("2001", datetime(2026, 9, 15, 9, 14, 23))]
        first = c.post("/api/devices/1/pull").json()
        assert first["new"] == 1 and first["backup"]["name"].startswith("auto-")
        assert first["backup"]["bytes"] > 0

        # Nothing new to store, so nothing to protect: no second copy.
        again = c.post("/api/devices/1/pull").json()
        assert again["new"] == 0 and again["backup"] is None

        listed = c.get("/api/backups").json()["backups"]
        assert len(listed) == 1 and listed[0]["automatic"] and listed[0]["name"] == first["backup"]["name"]

        # Turned off, a pull leaves no copy.
        c.put("/api/settings", json={"auto_backup_after_pull": "0"})
        fake.records += [FakeRecord("2002", datetime(2026, 9, 15, 9, 20, 0))]
        assert c.post("/api/devices/1/pull").json()["backup"] is None
        assert len(c.get("/api/backups").json()["backups"]) == 1


def test_only_the_newest_automatic_backups_are_kept(tmp_path):
    conn = db.connect(tmp_path / "keep.db")
    db.initialise(conn)
    place = tmp_path / "backups"
    place.mkdir()
    for n in range(1, 6):
        (place / f"auto-2026091{n}-090000-after-pull.db").write_text("x")
    (place / "before-schema-6-from-5-20260919-090000.db").write_text("x")   # not automatic: kept

    dropped = backups.prune(place, keep=3)
    left = sorted(p.name for p in place.glob("*.db"))
    assert len(dropped) == 2
    assert left == ["auto-20260913-090000-after-pull.db", "auto-20260914-090000-after-pull.db",
                    "auto-20260915-090000-after-pull.db", "before-schema-6-from-5-20260919-090000.db"]
    conn.close()
