import pytest

from rollcall import diagnostics


@pytest.fixture
def world(monkeypatch):
    state = {"wired": [{"name": "Ethernet", "status": "Up", "media": "802.3", "ips": ["192.168.1.100"]}],
             "others": [],
             "addresses": ["192.168.1.100", "192.168.8.254"], "source": "192.168.1.100", "ping": True, "port": True}
    monkeypatch.setattr(diagnostics, "physical_adapters",
                        lambda: None if state["wired"] is None else state["wired"] + state["others"])
    monkeypatch.setattr(diagnostics, "local_ipv4_addresses", lambda: state["addresses"])
    monkeypatch.setattr(diagnostics, "route_source_address", lambda ip, port: state["source"])
    monkeypatch.setattr(diagnostics, "ping", lambda ip: state["ping"])
    monkeypatch.setattr(diagnostics, "tcp_open", lambda ip, port: state["port"])
    return state


def results(ip="192.168.1.201"):
    return {c.name: c for c in diagnostics.diagnose(ip)}


def test_all_good(world):
    assert all(c.ok for c in results().values())


def test_unplugged_cable_is_not_reported_as_a_missing_static_ip(world):
    # What this PC actually showed on 2026-09-15: adapter disconnected, its IP hidden from lookups.
    world.update(wired=[{"name": "Ethernet", "status": "Disconnected", "media": "802.3", "ips": ["192.168.1.100"]}],
                 addresses=["192.168.8.254"], source="192.168.8.254", ping=False, port=False)
    r = results()
    assert not r["cable"].ok and "disconnected" in r["cable"].message
    assert r["pc_address"].ok and "will work once the cable is connected" in r["pc_address"].message


def test_missing_static_ip_with_cable_connected(world):
    world.update(wired=[{"name": "Ethernet", "status": "Up", "media": "802.3", "ips": ["169.254.3.4"]}],
                 addresses=["169.254.3.4"], source="169.254.3.4", ping=False, port=False)
    r = results()
    assert r["cable"].ok
    assert not r["pc_address"].ok and "gateway" in r["pc_address"].message
    assert "192.168.1.100" in r["pc_address"].message


def test_no_ethernet_port_points_to_usb(world):
    world.update(wired=[], addresses=["192.168.8.254"], source="192.168.8.254", ping=False, port=False)
    message = results()["cable"].message
    assert "USB" in message
    # The USB flash drive import is not built (known gap 9), so it must not be offered.
    assert "flash drive" not in message


def test_cable_check_is_skipped_off_windows(world):
    world["wired"] = None
    assert "cable" not in results()


WIFI_ON_THE_SAME_NUMBERS = {"name": "Wi-Fi", "status": "Up", "media": "Native 802.11", "ips": ["192.168.1.57"]}


def test_a_wifi_on_the_terminals_numbers_is_not_this_computers_address(world):
    # Many home and MiFi routers hand out 192.168.1.x. Before 2026-09-26 the Wi-Fi's address passed
    # this check although the Ethernet had nothing (research 2026-09-26).
    world.update(wired=[{"name": "Ethernet", "status": "Up", "media": "802.3", "ips": ["169.254.3.4"]}],
                 others=[WIFI_ON_THE_SAME_NUMBERS], addresses=["169.254.3.4", "192.168.1.57"],
                 source="192.168.1.57", ping=False, port=False)
    r = results()
    assert not r["pc_address"].ok
    assert "Wi-Fi uses the same numbers" in r["pc_address"].message


def test_traffic_leaving_by_a_wifi_on_the_same_numbers_fails_the_route(world):
    # The Ethernet holds the address, but Windows prefers the Wi-Fi on metric, so the terminal's
    # traffic leaves by the Wi-Fi. The route check used to pass any source inside 192.168.1.0/24.
    world.update(wired=[{"name": "Ethernet", "status": "Up", "media": "802.3", "ips": ["192.168.1.100"]}],
                 others=[WIFI_ON_THE_SAME_NUMBERS], addresses=["192.168.1.100", "192.168.1.57"],
                 source="192.168.1.57")
    r = results()
    assert r["pc_address"].ok
    assert not r["route"].ok
    assert "Wi-Fi" in r["route"].message and "not the Ethernet cable" in r["route"].message


def test_the_suggested_address_is_never_the_terminals_own(world):
    world.update(wired=[{"name": "Ethernet", "status": "Up", "media": "802.3", "ips": ["169.254.3.4"]}],
                 addresses=["169.254.3.4"], source="169.254.3.4", ping=False, port=False)
    assert "10.0.0.101" in results("10.0.0.100")["pc_address"].message


def test_the_adapters_are_read_once_when_the_caller_already_has_them(world, monkeypatch):
    monkeypatch.setattr(diagnostics, "physical_adapters", lambda: pytest.fail("read the adapters twice"))
    checks = {c.name: c for c in diagnostics.diagnose("192.168.1.201", adapters=world["wired"])}
    assert checks["cable"].ok
