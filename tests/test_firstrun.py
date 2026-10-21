"""First-run setup: the draft store and the connection test that run before any account exists.

Both are known gap 2 in `docs/PROJECT-HANDOFF.md`: screen 1 saves and resumes, and tests the cable,
and neither was possible because `POST /api/setup` wrote everything at once and
`GET /api/devices/{id}/diagnose` needs a saved device row.
"""
import pytest
from fastapi.testclient import TestClient

from rollcall import firstrun
from rollcall.app import create_app
from rollcall.diagnostics import Check


@pytest.fixture
def client(tmp_path, k40_factory):
    app = create_app(tmp_path / "firstrun.db", k40_factory=k40_factory)
    with TestClient(app) as c:
        yield c


# The diagnostics read this machine's own network card and ping the cable, so leaving them live
# would make these tests pass or fail depending on whether someone had the cable plugged in. They
# have their own tests in tests/test_diagnostics.py; what is under test here is what happens to the
# chain afterwards.
def chain(**results):
    order = [("cable", "Ethernet cable connected."), ("pc_address", "This PC has 192.168.1.100."),
             ("route", "Traffic to the device leaves from 192.168.1.100."),
             ("ping", "The device at 192.168.1.201 answers ping."), ("port", "Port 4370 is open.")]
    return [Check(name, results.get(name, True),
                  message if results.get(name, True) else f"{name} failed, in words a lecturer reads.")
            for name, message in order]


@pytest.fixture
def cable(monkeypatch):
    """Make every link in the chain pass, unless a test says otherwise."""
    state = {"results": {}}

    def fake_diagnose(ip, port=4370, adapters=None):
        return chain(**state["results"])

    monkeypatch.setattr(firstrun.diagnostics, "diagnose", fake_diagnose)
    return state


def complete_setup(client):
    return client.post("/api/setup", json={"username": "lecturer", "display_name": "Dr Lecturer",
                                           "password": "secret123", "academic_session": "2026/2027"})


def test_status_offers_a_draft_to_resume_and_this_computers_address(client):
    status = client.get("/api/setup/status").json()
    assert status["needs_setup"] is True
    assert status["resume"] is None
    assert isinstance(status["this_computer"], list)

    saved = client.put("/api/setup/draft", json={"draft": {"step": 3, "display_name": "Dr Lecturer",
                                                           "academic_session": "2026/2027"}})
    assert saved.status_code == 200, saved.text
    assert saved.json()["draft"]["step"] == 3
    assert saved.json()["updated_at"]

    resumed = client.get("/api/setup/status").json()["resume"]
    assert resumed["draft"]["display_name"] == "Dr Lecturer"
    assert resumed["updated_at"] == saved.json()["updated_at"]


def test_the_draft_never_keeps_the_password(client):
    client.put("/api/setup/draft", json={"draft": {"username": "lecturer", "password": "secret123"}})
    draft = client.get("/api/setup/status").json()["resume"]["draft"]
    assert draft == {"username": "lecturer"}


def test_starting_again_discards_the_draft(client):
    client.put("/api/setup/draft", json={"draft": {"step": 2}})
    assert client.delete("/api/setup/draft").status_code == 200
    assert client.get("/api/setup/status").json()["resume"] is None


def test_finishing_setup_deletes_the_draft_and_closes_every_setup_route(client):
    client.put("/api/setup/draft", json={"draft": {"step": 4}})
    assert complete_setup(client).status_code == 200

    status = client.get("/api/setup/status").json()
    assert status == {"needs_setup": False, "resume": None, "this_computer": status["this_computer"]}
    for call in (lambda: client.put("/api/setup/draft", json={"draft": {"step": 1}}),
                 lambda: client.delete("/api/setup/draft"),
                 lambda: client.post("/api/setup/test-device", json={"ip": "192.168.1.201"})):
        response = call()
        assert response.status_code == 400, response.text
        assert response.json()["error"] == "Setup has already been done. Sign in instead."


def test_the_connection_test_reads_the_terminal_without_a_device_row(client, fake, cable):
    result = client.post("/api/setup/test-device",
                         json={"ip": "192.168.1.201", "port": 4370, "comm_key": 0}).json()
    assert result["ok"] is True
    assert result["heading"] == "The terminal answered"
    assert result["identity"]["serial"] == fake.serial
    assert result["holding"] == "It holds 0 of 1,000 people, so it is empty and ready."
    identity = result["checks"][-1]
    assert identity["label"] == "Serial and firmware"
    assert identity["ok"] and identity["checked"]
    assert [c["label"] for c in result["checks"]][-3:] == ["Terminal answers", "Port 4370", "Serial and firmware"]
    # No device row was created: setup writes nothing until its review step.
    assert client.get("/api/setup/status").json()["needs_setup"] is True


def test_a_terminal_with_scans_from_before_is_not_called_empty(client, fake, cable):
    # A new register numbers its students from the start of each level's block. Scans still on the
    # terminal under those numbers, from a register that is gone, would be read as theirs. Setup
    # called such a terminal "empty and ready" because it counted people only (audit, 2026-09-24).
    from datetime import datetime
    from fake_zk import FakeRecord
    fake.records.extend(FakeRecord(str(2001 + i), datetime(2026, 9, 23, 22, i)) for i in range(15))
    result = client.post("/api/setup/test-device",
                         json={"ip": "192.168.1.201", "port": 4370, "comm_key": 0}).json()
    assert result["identity"]["records"] == 15
    assert "empty and ready" not in result["holding"]
    assert "15 scans" in result["holding"] and "Clear the scans" in result["holding"]


def test_a_terminal_that_does_not_answer_stops_the_chain_and_names_the_first_broken_link(client, fake, cable):
    cable["results"] = {"ping": False, "port": False}
    result = client.post("/api/setup/test-device", json={"ip": "192.0.2.201"}).json()
    assert result["ok"] is False
    assert result["identity"] is None and result["holding"] is None
    # Only the first broken link speaks; everything after it says it was not reached.
    broken = next(c for c in result["checks"] if not c["ok"])
    assert result["heading"] and result["remedy"] == broken["message"]
    after = result["checks"][result["checks"].index(broken) + 1:]
    assert all(not c["checked"] for c in after)
    assert all(c["message"].startswith("Not checked") for c in after)
    # A step whose result was suppressed must never read as a pass: the glyph is drawn from `ok`.
    assert all(c["ok"] is False for c in after)


def test_a_link_after_the_broken_one_never_reads_as_a_pass(client, cable):
    """The cable is out, so the address check is not reached even though it would have passed."""
    cable["results"] = {"cable": False}
    checks = {c["name"]: c for c in client.post("/api/setup/test-device",
                                                json={"ip": "192.168.1.201"}).json()["checks"]}
    assert checks["cable"]["ok"] is False and checks["cable"]["checked"] is True
    assert checks["pc_address"]["ok"] is False
    assert checks["pc_address"]["checked"] is False
    assert checks["pc_address"]["message"] == "Not checked, the cable is out"
