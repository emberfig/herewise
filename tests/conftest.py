import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from fake_zk import FakeDevice  # noqa: E402
from rollcall import db  # noqa: E402
from rollcall.device import K40  # noqa: E402

ROSTER = ROOT / "data" / "synthetic_200_roster.csv"


@pytest.fixture(autouse=True)
def this_computer_is_left_alone(monkeypatch):
    """No test reads this PC's network cards or asks Windows for administrator rights.

    Reading the cards made results depend on whether the cable was in, and cost seconds a call; a
    real request for rights would put a UAC prompt in front of whoever ran the suite and, answered
    Yes, change this PC's Ethernet. A test that needs either sets its own fake over these.
    """
    from rollcall import diagnostics, netsetup

    def refuse(*_, **__):
        raise AssertionError("a test tried to ask Windows for administrator rights")

    monkeypatch.setattr(diagnostics, "physical_adapters", lambda: None)
    monkeypatch.setattr(netsetup, "run_elevated", refuse)


@pytest.fixture
def fake():
    return FakeDevice()


@pytest.fixture
def k40_factory(fake):
    return lambda target: K40(target, zk_factory=fake.factory())


@pytest.fixture
def conn(tmp_path):
    c = db.connect(tmp_path / "test.db")
    db.initialise(c)
    c.execute("INSERT INTO academic_sessions(name, is_current, created_at) VALUES ('2026/2027', 1, ?)", (db.now(),))
    c.execute("INSERT INTO devices(name, ip, is_default, created_at) VALUES ('K40', '192.168.1.201', 1, ?)", (db.now(),))
    owner = c.execute("SELECT id FROM roles WHERE is_owner = 1").fetchone()["id"]
    c.execute("INSERT INTO accounts(username, display_name, role_id, password_hash, created_at)"
              " VALUES ('lecturer', 'Lecturer', ?, 'x', ?)", (owner, db.now()))
    yield c
    c.close()
