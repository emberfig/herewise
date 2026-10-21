"""Setting up the lecturer's Ethernet from Herewise (0.1.16).

Everything here runs against adapters written out as data. Nothing reads this PC's network cards and
nothing asks Windows for administrator rights: `tests/conftest.py` makes both fail loudly, and each
test that needs them hands in its own fake. The one test that starts a real process runs
`cmd.exe /d /c exit 7` with the plain "open" verb, which asks nothing and changes nothing.
"""
import platform

import pytest
from fastapi.testclient import TestClient

from rollcall import auth, db, diagnostics, netsetup
from rollcall.app import create_app

from fake_windows import FakeWindows, ethernet, wifi

TERMINAL = "192.168.1.201"


def chain(broken=None):
    names = ["cable", "pc_address", "route", "ping", "port"]
    return [{"name": n, "ok": broken is None or names.index(n) < names.index(broken)} for n in names]


# -- the commands ----------------------------------------------------------------------------------

def test_a_port_on_automatic_keeps_it_and_gains_the_address_and_the_route():
    steps = netsetup.setup_steps(ethernet(), TERMINAL, "192.168.1.100")
    assert netsetup.readable(steps) == [
        "netsh interface ipv4 set interface interface=12 dhcpstaticipcoexistence=enabled",
        "netsh interface ipv4 add address name=12 address=192.168.1.100 mask=255.255.255.0",
        "netsh interface ipv4 add route prefix=192.168.1.201/32 interface=12 store=persistent",
    ]


def test_a_port_already_set_by_hand_is_not_switched_to_coexistence():
    steps = netsetup.readable(netsetup.setup_steps(ethernet(dhcp="Disabled"), TERMINAL, "192.168.1.100"))
    assert not any("dhcpstaticipcoexistence" in s for s in steps)
    assert steps[0].startswith("netsh interface ipv4 add address name=12 ")


def test_what_is_already_there_is_not_asked_for_again():
    held = ethernet(ips=["192.168.1.100"], manual=["192.168.1.100/24"], routes=["192.168.1.201/32"])
    assert netsetup.setup_steps(held, TERMINAL, None) == []
    route_only = netsetup.setup_steps(ethernet(ips=["192.168.1.100"]), TERMINAL, None)
    assert netsetup.readable(route_only) == [
        "netsh interface ipv4 add route prefix=192.168.1.201/32 interface=12 store=persistent"]


def test_the_command_line_runs_in_one_cmd_without_autorun_and_stops_on_a_failure():
    line = netsetup.command_line(netsetup.setup_steps(ethernet(), TERMINAL, "192.168.1.100"),
                                 stop_on_failure=True)
    assert line.startswith("/d /c netsh interface ipv4 set interface ")
    # A Windows that refuses coexistence must never go on to add an address, which would turn DHCP off.
    assert line.count(" && ") == 2 and " & " not in line.replace(" && ", "")


def test_the_undo_carries_on_past_a_piece_already_gone():
    held = ethernet(ips=["192.168.1.100"], manual=["192.168.1.100/24"], routes=["192.168.1.201/32"])
    line = netsetup.command_line(netsetup.undo_steps(held, TERMINAL), stop_on_failure=False)
    assert line == ("/d /c netsh interface ipv4 delete address name=12 address=192.168.1.100 & "
                    "netsh interface ipv4 delete route prefix=192.168.1.201/32 interface=12 store=persistent")


@pytest.mark.parametrize("token", ["name=Ethernet 2", "address=1.2.3.4&calc", "x|y", 'a"b', "c:\\x"])
def test_nothing_that_could_break_out_of_the_command_is_ever_run(token):
    with pytest.raises(netsetup.NetworkError):
        netsetup.command_line([["interface", "ipv4", token]], stop_on_failure=True)


def test_an_empty_change_is_refused_rather_than_run():
    with pytest.raises(netsetup.NetworkError):
        netsetup.command_line([], stop_on_failure=True)


def test_undo_turns_automatic_back_on_only_where_it_was_off_and_nothing_else_is_set():
    by_hand = ethernet(dhcp="Disabled", ips=["192.168.1.100"], manual=["192.168.1.100/24"])
    assert netsetup.readable(netsetup.undo_steps(by_hand, TERMINAL))[-1] == \
        "netsh interface ipv4 set address name=12 source=dhcp"
    # Somebody's own static address for another network stays, and so does automatic being off.
    theirs = ethernet(dhcp="Disabled", ips=["192.168.1.100", "10.9.8.7"],
                      manual=["192.168.1.100/24", "10.9.8.7/16"])
    steps = netsetup.readable(netsetup.undo_steps(theirs, TERMINAL))
    assert steps == ["netsh interface ipv4 delete address name=12 address=192.168.1.100"]


# -- choosing ----------------------------------------------------------------------------------------

def test_the_address_is_100_unless_it_is_taken():
    assert netsetup.pick_address(TERMINAL, []) == "192.168.1.100"
    assert netsetup.pick_address("192.168.1.100", []) == "192.168.1.101"
    # A Wi-Fi that was handed .100 by its own router: the same address twice on one computer.
    assert netsetup.pick_address(TERMINAL, ["192.168.1.100", "10.0.0.4"]) == "192.168.1.101"
    assert netsetup.pick_address("10.1.2.3", []) == "10.1.2.100"


@pytest.mark.parametrize("ip, words", [
    ("169.254.1.201", "169.254"), ("8.8.8.8", "not an address"), ("not an ip", "not an IPv4"),
    ("127.0.0.1", "not an address"),
])
def test_a_terminal_address_nobody_would_cable_to_is_refused(ip, words):
    assert words in netsetup.refusal_for(ip)


def test_the_adapter_facing_the_terminal_is_the_one_with_no_network_of_its_own():
    dock = ethernet(index=5, name="Ethernet", ips=["10.4.4.20"])      # the office, with DHCP
    usb = ethernet(index=23, name="Ethernet 2", ips=["169.254.9.9"])  # the cable to the terminal
    assert [a["name"] for a in netsetup.candidates([dock, usb, wifi()])] == ["Ethernet 2"]
    both = ethernet(index=24, name="Ethernet 3", ips=[])
    assert len(netsetup.candidates([usb, both])) == 2


# -- what the screens are told -----------------------------------------------------------------------

def test_the_offer_appears_only_where_the_chain_stopped_at_this_computer():
    adapters = [ethernet(), wifi()]
    offer = netsetup.describe(TERMINAL, adapters, chain("pc_address"))["offer"]
    assert offer["choices"][0]["name"] == "Ethernet"
    assert offer["choices"][0]["address"] == "192.168.1.100"
    assert offer["choices"][0]["dhcp"] is True
    for broken in ("cable", "ping", "port", None):
        assert netsetup.describe(TERMINAL, adapters, chain(broken))["offer"] is None


def test_a_wifi_on_the_same_numbers_gets_a_route_only_offer_and_is_named():
    adapters = [ethernet(ips=["192.168.1.100"], manual=["192.168.1.100/24"]), wifi("192.168.1.57")]
    told = netsetup.describe(TERMINAL, adapters, chain("route"))
    assert told["others"] == ["Wi-Fi"]
    choice = told["offer"]["choices"][0]
    assert choice["route_only"] is True
    assert choice["steps"] == ["netsh interface ipv4 add route prefix=192.168.1.201/32 interface=12 store=persistent"]


def test_the_manual_steps_name_the_adapter_and_the_address_and_avoid_settings():
    told = netsetup.describe(TERMINAL, [ethernet(name="Ethernet 2")], chain("pc_address"))
    steps = " ".join(told["manual"])
    assert "Ethernet 2" in steps and "192.168.1.100" in steps and "ncpa.cpl" in steps
    assert "gateway left empty" in steps


def test_what_an_undo_would_take_off_is_listed_even_when_everything_passes():
    held = ethernet(status="Disconnected", ips=["192.168.1.100"], manual=["192.168.1.100/24"],
                    routes=["192.168.1.201/32"])
    told = netsetup.describe(TERMINAL, [held], chain("cable"))
    assert told["set"] == [{"index": 12, "name": "Ethernet", "addresses": ["192.168.1.100"], "route": True,
                            "steps": ["netsh interface ipv4 delete address name=12 address=192.168.1.100",
                                      "netsh interface ipv4 delete route prefix=192.168.1.201/32 "
                                      "interface=12 store=persistent"]}]
    assert told["offer"] is None


def test_nothing_is_offered_off_windows():
    told = netsetup.describe(TERMINAL, None, chain("pc_address"))
    assert told["available"] is False and told["offer"] is None


# -- asking Windows, with a fake Windows -------------------------------------------------------------

def test_yes_to_windows_sets_the_port_up_and_the_adapter_is_read_to_prove_it():
    windows = FakeWindows([ethernet(), wifi()])
    result = netsetup.apply(TERMINAL, 12, read=windows.read, run=windows.run, settle_seconds=0)
    assert result["result"] == "done"
    assert result["address"] == "192.168.1.100"
    assert "still gets its own address automatically" in result["message"]
    assert len(windows.asked) == 1          # one prompt, not three


def test_no_to_windows_changes_nothing_and_says_so():
    windows = FakeWindows([ethernet()], answers=("no",))
    result = netsetup.apply(TERMINAL, 12, read=windows.read, run=windows.run, settle_seconds=0)
    assert result["result"] == "declined"
    assert "answered No" in result["message"]
    assert windows.adapters[0]["manual"] == []


def test_an_exit_code_of_nought_is_not_believed_over_the_adapter():
    windows = FakeWindows([ethernet()], applies=False)
    result = netsetup.apply(TERMINAL, 12, read=windows.read, run=windows.run, settle_seconds=0)
    assert result["result"] == "failed"
    assert "does not show the change" in result["message"]


def test_a_windows_that_turned_automatic_off_is_reported_not_hidden():
    windows = FakeWindows([ethernet()])
    original = windows.apply

    def ignores_coexistence(words):
        original(words)
        if words[3:5] == ["add", "address"]:
            windows.adapters[0]["dhcp"] = "Disabled"

    windows.apply = ignores_coexistence
    result = netsetup.apply(TERMINAL, 12, read=windows.read, run=windows.run, settle_seconds=0)
    assert result["result"] == "done"
    assert "turned automatic addressing off" in result["message"]


def test_the_cable_must_be_in_and_the_adapter_must_be_named_when_there_are_two():
    out = FakeWindows([ethernet(status="Disconnected")])
    with pytest.raises(netsetup.NetworkError, match="disconnected"):
        netsetup.apply(TERMINAL, 12, read=out.read, run=out.run, settle_seconds=0)
    two = FakeWindows([ethernet(), ethernet(index=23, name="Ethernet 2")])
    with pytest.raises(netsetup.NetworkError, match="Say which"):
        netsetup.apply(TERMINAL, None, read=two.read, run=two.run, settle_seconds=0)
    assert out.asked == [] and two.asked == []


def test_an_adapter_index_windows_never_reported_is_refused():
    windows = FakeWindows([ethernet()])
    with pytest.raises(netsetup.NetworkError, match="no longer there"):
        netsetup.apply(TERMINAL, 99, read=windows.read, run=windows.run, settle_seconds=0)


def test_undo_takes_off_exactly_what_setting_up_put_on():
    windows = FakeWindows([ethernet(), wifi()])
    netsetup.apply(TERMINAL, 12, read=windows.read, run=windows.run, settle_seconds=0)
    result = netsetup.undo(TERMINAL, None, read=windows.read, run=windows.run, settle_seconds=0)
    assert result["result"] == "done"
    after = windows.adapters[0]
    assert after["manual"] == [] and "192.168.1.201/32" not in after["routes"]
    assert after["dhcp"] == "Enabled"


@pytest.mark.skipif(platform.system() != "Windows", reason="ShellExecuteEx is Windows only")
def test_the_plumbing_reads_the_exit_code_of_what_it_started():
    # "open", not "runas": no prompt and no change. What is proved is the structure, the wait and the
    # exit code, which are the same for both verbs.
    assert netsetup.shell_execute("cmd.exe", "/d /c exit 7", verb="open") == netsetup.Elevation("finished", 7)
    missing = netsetup.shell_execute("no-such-program-herewise.exe", "", verb="open")
    assert missing.state == "failed"         # never read as the lecturer answering No


# -- the routes --------------------------------------------------------------------------------------

@pytest.fixture
def app_client(tmp_path, k40_factory, monkeypatch):
    windows = FakeWindows([ethernet(), wifi()])
    monkeypatch.setattr(diagnostics, "physical_adapters", windows.read)
    monkeypatch.setattr(netsetup, "run_elevated", windows.run)
    for name, value in {"local_ipv4_addresses": lambda: [], "route_source_address": lambda ip, port: None,
                        "ping": lambda ip: False, "tcp_open": lambda ip, port: False}.items():
        monkeypatch.setattr(diagnostics, name, value)
    original = netsetup.apply
    monkeypatch.setattr(netsetup, "apply", lambda ip, index=None, **kw: original(ip, index, settle_seconds=0, **kw))
    original_undo = netsetup.undo
    monkeypatch.setattr(netsetup, "undo", lambda ip, index=None, **kw: original_undo(ip, index, settle_seconds=0, **kw))
    app = create_app(tmp_path / "net.db", k40_factory=k40_factory)
    with TestClient(app) as client:
        client.windows = windows
        yield client


def sign_up(client):
    client.post("/api/setup", json={"username": "lecturer", "display_name": "Lecturer",
                                    "password": "secret123", "academic_session": "2026/2027"})


def test_the_connection_check_carries_the_offer(app_client):
    sign_up(app_client)
    result = app_client.get("/api/devices/1/diagnose").json()
    assert result["ok"] is False
    assert result["network"]["offer"]["choices"][0]["index"] == 12


def test_setting_up_from_the_connection_check_is_audited_and_walks_the_chain_again(app_client, tmp_path):
    sign_up(app_client)
    answer = app_client.post("/api/devices/1/network/setup", json={"adapter": 12})
    assert answer.status_code == 200, answer.text
    assert answer.json()["setup"]["result"] == "done"
    checks = {c["name"]: c for c in answer.json()["diagnosis"]["checks"]}
    assert checks["pc_address"]["ok"] is True
    conn = db.connect(tmp_path / "net.db")
    try:
        row = conn.execute("SELECT detail FROM audit_log WHERE action = 'device.network_setup'").fetchone()
    finally:
        conn.close()
    assert row["detail"] == "Ethernet, 192.168.1.100"


def test_a_page_from_anywhere_else_never_reaches_the_prompt(app_client):
    sign_up(app_client)
    refused = app_client.post("/api/devices/1/network/setup", json={"adapter": 12},
                              headers={"Origin": "https://example.com"})
    assert refused.status_code == 403
    # A plain form post, the one kind of cross-site request a browser sends without asking first.
    form = app_client.post("/api/devices/1/network/setup", content='{"adapter": 12}',
                           headers={"Content-Type": "text/plain"})
    assert form.status_code == 422
    assert app_client.windows.asked == []


def test_changing_the_network_needs_the_permission_to_change_the_device(app_client, tmp_path):
    sign_up(app_client)
    conn = db.connect(tmp_path / "net.db")
    try:
        viewer = conn.execute("SELECT id FROM roles WHERE name = 'Viewer'").fetchone()["id"]
        auth.create_account(conn, "reader", "Reader", "secret123", viewer)
    finally:
        conn.close()
    app_client.post("/api/logout")
    signed_in = app_client.post("/api/login", json={"username": "reader", "password": "secret123"})
    assert signed_in.status_code == 200, signed_in.text
    assert app_client.post("/api/devices/1/network/setup", json={"adapter": 12}).status_code == 403
    assert app_client.windows.asked == []


def test_setup_can_do_it_before_any_account_and_not_after(app_client):
    before = app_client.post("/api/setup/network", json={"ip": TERMINAL, "port": 4370, "adapter": 12})
    assert before.status_code == 200, before.text
    assert before.json()["setup"]["result"] == "done"
    assert "network" in before.json()["tested"]
    sign_up(app_client)
    after = app_client.post("/api/setup/network", json={"ip": TERMINAL, "port": 4370, "adapter": 12})
    assert after.status_code == 400
