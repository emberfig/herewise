"""Put this computer's Ethernet on the terminal's network, with one yes to Windows.

A new computer's Ethernet port is on automatic, and a direct cable has no DHCP server, so the port
gives itself a 169.254 address and never reaches a terminal at 192.168.1.201. That is where 0.1.15
stopped on the lecturer's own laptop (2026-09-26). Changing an adapter's address needs administrator
rights, which the installer deliberately never asks for, so this asks Windows once, when the
Connection check has found the problem, and only for the adapter the check found.

What it asks for, as netsh commands on the adapter's index (never its name, so "Ethernet 2" or a
translated name needs no quoting):

1. keep DHCP on the port (`dhcpstaticipcoexistence`), so the port still works on any other network;
   without it, adding an address turns DHCP off, which is what the manual steps do;
2. add 192.168.1.100/24 beside whatever DHCP gives it, or the next free address on those numbers;
3. a host route for the terminal alone, because routes go by the longest prefix before any metric,
   and a Wi-Fi also on 192.168.1.x can otherwise win the terminal's traffic on metric.

Research, with its sources and what is still unverified: vault
`50-Research/Herewise Ethernet setup research 2026-09-26.md`.

The commands run in one `cmd.exe /d /c` so Windows asks once. `/d` skips any AutoRun command in the
registry, and the working directory is the system folder, so `netsh` resolves there first. Every
token is checked against a narrow pattern before anything runs; nothing from a request reaches the
command line except an adapter index that must match an adapter Windows reported.

An elevated process cannot hand its output back, so the verdict is never its exit code alone: the
adapter is read again afterwards, without elevation, and what it holds is what is reported.
"""
from __future__ import annotations

import ipaddress
import logging
import os
import platform
import re
import threading
import time
from dataclasses import dataclass

from . import diagnostics

log = logging.getLogger("rollcall.netsetup")

MASK = "255.255.255.0"
# The address a direct cable has always used with the tested K40, tried first.
FIRST_HOST = 100
_TOKEN = re.compile(r"^[A-Za-z0-9=./]+$")
_one_at_a_time = threading.Lock()


class NetworkError(ValueError):
    pass


@dataclass
class Elevation:
    """What asking Windows came to. `state` is one of: finished, declined, failed, timeout, unavailable."""
    state: str
    exit_code: int | None = None
    error: int | None = None


# -- reading what is there ---------------------------------------------------------------------------

def network_of(device_ip: str) -> ipaddress.IPv4Network:
    return ipaddress.ip_network(f"{device_ip}/24", strict=False)


def refusal_for(device_ip: str) -> str | None:
    """Why the terminal's address is not one this should put a computer on, or None if it is."""
    try:
        address = ipaddress.IPv4Address(device_ip)
    except ValueError:
        return f"{device_ip} is not an IPv4 address."
    if address.is_link_local:
        return ("The terminal is on a 169.254 address. Windows finds those by itself when the Ethernet "
                "port is on automatic, so there is nothing for Herewise to set.")
    if not address.is_private or address.is_loopback or address.is_multicast or address.is_unspecified:
        return (f"{device_ip} is not an address a cable between two machines would use, so Herewise "
                "will not put this computer on it. Check the terminal's address under Menu, COMM., Ethernet.")
    return None


def _in(network, addresses) -> list[str]:
    found = []
    for value in addresses or []:
        text = str(value).split("/")[0]
        try:
            if ipaddress.ip_address(text) in network:
                found.append(text)
        except ValueError:
            continue
    return found


def holds(adapter: dict, device_ip: str) -> list[str]:
    """The adapter's addresses on the terminal's network."""
    return _in(network_of(device_ip), adapter.get("ips"))


def set_by_hand(adapter: dict, device_ip: str) -> list[str]:
    """Addresses on the terminal's network that somebody, or Herewise, set by hand on this adapter."""
    return _in(network_of(device_ip), adapter.get("manual"))


def has_route(adapter: dict, device_ip: str) -> bool:
    return f"{device_ip}/32" in (adapter.get("routes") or [])


def pick_address(device_ip: str, taken) -> str:
    """192.168.1.100 unless the terminal or another adapter already has it, then the next free one."""
    network = network_of(device_ip)
    used = {device_ip, *(str(t).split("/")[0] for t in taken)}
    base = int(network.network_address)
    for host in [*range(FIRST_HOST, 200), *range(2, FIRST_HOST), *range(200, 255)]:
        candidate = str(ipaddress.IPv4Address(base + host))
        if candidate not in used:
            return candidate
    raise NetworkError(f"Every address on {network} is already in use on this computer.")


def candidates(adapters: list[dict]) -> list[dict]:
    """Wired adapters with the cable in. Where there are several, the one with no address from a
    network (only 169.254, or nothing) is the one facing the terminal: a direct cable has no DHCP
    server, a docking station's cable to the office has one."""
    up = [a for a in diagnostics.wired_only(adapters) or [] if a.get("status") == "Up"]
    if len(up) <= 1:
        return up
    facing = [a for a in up if not [ip for ip in a.get("ips") or []
                                    if not ipaddress.ip_address(ip).is_link_local]]
    return facing or up


# -- the commands ------------------------------------------------------------------------------------

def setup_steps(adapter: dict, device_ip: str, address: str | None) -> list[list[str]]:
    """netsh arguments that put `adapter` on the terminal's network, leaving out what is already done."""
    index = int(adapter["index"])
    steps: list[list[str]] = []
    if address:
        if (adapter.get("dhcp") or "").lower() == "enabled":
            steps.append(["interface", "ipv4", "set", "interface", f"interface={index}",
                          "dhcpstaticipcoexistence=enabled"])
        steps.append(["interface", "ipv4", "add", "address", f"name={index}", f"address={address}",
                      f"mask={MASK}"])
    if not has_route(adapter, device_ip):
        steps.append(["interface", "ipv4", "add", "route", f"prefix={device_ip}/32",
                      f"interface={index}", "store=persistent"])
    return steps


def undo_steps(adapter: dict, device_ip: str) -> list[list[str]]:
    """netsh arguments that take the terminal's network back off `adapter`.

    Removes every address on the terminal's numbers set by hand, and the terminal's host route. If
    DHCP was off and nothing else is left, it goes back on, which is what "automatic" means in
    Windows. The coexistence flag is left as it is: with no address set by hand it changes nothing.
    """
    index = int(adapter["index"])
    ours = set_by_hand(adapter, device_ip)
    steps = [["interface", "ipv4", "delete", "address", f"name={index}", f"address={ip}"] for ip in ours]
    if has_route(adapter, device_ip):
        steps.append(["interface", "ipv4", "delete", "route", f"prefix={device_ip}/32",
                      f"interface={index}", "store=persistent"])
    others = [m for m in adapter.get("manual") or [] if m.split("/")[0] not in ours]
    if ours and (adapter.get("dhcp") or "").lower() != "enabled" and not others:
        steps.append(["interface", "ipv4", "set", "address", f"name={index}", "source=dhcp"])
    return steps


def command_line(steps: list[list[str]], *, stop_on_failure: bool) -> str:
    """The parameters for `cmd.exe`: `/d /c netsh ... && netsh ...`.

    `&&` for setting up, so a Windows that refuses coexistence never goes on to add an address that
    would then turn DHCP off. `&` for undoing, so one piece already gone does not stop the rest.
    """
    if not steps:
        raise NetworkError("There is nothing to change.")
    for step in steps:
        for token in step:
            if not _TOKEN.match(token):
                raise NetworkError(f"Refused to run a command holding {token!r}.")
    joiner = " && " if stop_on_failure else " & "
    return "/d /c " + joiner.join("netsh " + " ".join(step) for step in steps)


def readable(steps: list[list[str]]) -> list[str]:
    """The commands as Windows' own prompt shows them under Show more details."""
    return ["netsh " + " ".join(step) for step in steps]


# -- what the screens are told -----------------------------------------------------------------------

def manual_steps(adapter_name: str, address: str) -> list[str]:
    """The same change by hand, for when Windows' question is answered No or cannot be answered.

    Through the old Network Connections window, not Settings: Windows 11's Settings refuses a manual
    address with no gateway and no DNS server (2026-09-15), and this one saves it.
    """
    return [
        "Press Windows and R together, type ncpa.cpl and press Enter.",
        f"Right-click {adapter_name} and choose Properties. Windows may ask for an administrator's "
        "permission here.",
        "Double-click Internet Protocol Version 4 (TCP/IPv4).",
        f"Choose Use the following IP address. IP address {address}, subnet mask {MASK}, default "
        "gateway left empty, DNS servers left empty.",
        "Press OK, then Close, and run the check again.",
    ]


MANUAL_NOTE = ("Done by hand, this turns automatic addressing off on that port. Choose Obtain an IP "
               "address automatically again when the port is needed on another network.")


def describe(device_ip: str, adapters: list[dict] | None, checks) -> dict:
    """What the Connection check and setup's test can offer, beside the chain itself.

    `offer` only when the chain stopped at this computer's address or the route, the two links this
    fixes: a missing cable is the person's to plug in first, and a terminal that does not answer on
    the right numbers is not the computer's fault. `set` lists the Ethernet adapters holding the
    terminal's address or route, which is what an undo would remove, and `others` names any other
    adapter (usually Wi-Fi) on the terminal's numbers.
    """
    out = {"available": adapters is not None, "offer": None, "refused": None, "manual": [],
           "manual_note": MANUAL_NOTE, "set": [], "others": []}
    if adapters is None:
        return out
    network = network_of(device_ip)
    out["others"] = [a["name"] for a in diagnostics.others_on(adapters, network)]
    for adapter in diagnostics.wired_only(adapters):
        by_hand = set_by_hand(adapter, device_ip)
        if by_hand or has_route(adapter, device_ip):
            out["set"].append({"index": adapter["index"], "name": adapter["name"], "addresses": by_hand,
                               "route": has_route(adapter, device_ip),
                               "steps": readable(undo_steps(adapter, device_ip))})

    broken = next((c for c in checks if not _field(c, "ok")), None)
    if broken is None or _field(broken, "name") not in ("pc_address", "route"):
        return out
    refused = refusal_for(device_ip)
    if refused:
        out["refused"] = refused
        return out
    choices = candidates(adapters)
    if not choices:
        return out
    taken = [ip for a in adapters for ip in a.get("ips") or []]
    address = pick_address(device_ip, taken)
    offers = []
    for adapter in choices:
        already = holds(adapter, device_ip)
        steps = setup_steps(adapter, device_ip, None if already else address)
        if steps:
            offers.append({"index": adapter["index"], "name": adapter["name"],
                           "address": already[0] if already else address, "route_only": bool(already),
                           "dhcp": (adapter.get("dhcp") or "").lower() == "enabled",
                           "steps": readable(steps)})
    if not offers:
        return out
    out["offer"] = {"choices": offers, "others": out["others"]}
    out["manual"] = manual_steps(offers[0]["name"], offers[0]["address"])
    return out


def _field(check, name):
    return check[name] if isinstance(check, dict) else getattr(check, name)


def diagnosis(device_ip: str, port: int) -> dict:
    """The Connection check's whole answer: the chain, and what can be done about this computer.
    The network cards are read once, for both."""
    adapters = diagnostics.physical_adapters()
    checks = diagnostics.diagnose(device_ip, port, adapters=adapters)
    return {"ok": all(c.ok for c in checks), "checks": diagnostics.as_dicts(checks),
            "network": describe(device_ip, adapters, checks)}


# -- doing it ----------------------------------------------------------------------------------------

def _adapter(adapters: list[dict] | None, index: int | None, device_ip: str, *, need_up: bool) -> dict:
    if adapters is None:
        raise NetworkError("Herewise can only set up the Ethernet port on Windows.")
    wired = diagnostics.wired_only(adapters)
    if not wired:
        raise NetworkError("Windows cannot see an Ethernet port on this computer.")
    pool = candidates(adapters) if need_up else wired
    if index is None:
        if len(pool) != 1:
            raise NetworkError("Say which Ethernet adapter to set up." if pool else
                               "The Ethernet cable is not connected. Plug it in, then try again.")
        return pool[0]
    match = next((a for a in wired if int(a["index"]) == int(index)), None)
    if match is None:
        raise NetworkError("That Ethernet adapter is no longer there. Run the check again.")
    if need_up and match.get("status") != "Up":
        raise NetworkError(f"{match['name']} shows as disconnected. Plug the cable in, then try again.")
    return match


def apply(device_ip: str, index: int | None = None, *, read=None, run=None,
          settle_seconds: float = 10.0) -> dict:
    """Ask Windows once to put the adapter on the terminal's network, then read what it did."""
    read = read or diagnostics.physical_adapters
    run = run or run_elevated
    refused = refusal_for(device_ip)
    if refused:
        raise NetworkError(refused)
    adapters = read()
    adapter = _adapter(adapters, index, device_ip, need_up=True)
    already = holds(adapter, device_ip)
    address = already[0] if already else pick_address(device_ip, [ip for a in adapters for ip in a.get("ips") or []])
    steps = setup_steps(adapter, device_ip, None if already else address)
    report = {"adapter": adapter["name"], "index": adapter["index"], "address": address,
              "steps": readable(steps)}
    if not steps:
        return {**report, "result": "already", "message": f"{adapter['name']} is already set up for the terminal."}
    return _ask(report, command_line(steps, stop_on_failure=True), run, read, settle_seconds,
                done=lambda a: bool(holds(a, device_ip)) and has_route(a, device_ip),
                what="set up")


def undo(device_ip: str, index: int | None = None, *, read=None, run=None,
         settle_seconds: float = 10.0) -> dict:
    """Ask Windows once to take the terminal's address and route back off the adapter."""
    read = read or diagnostics.physical_adapters
    run = run or run_elevated
    adapters = read()
    if index is None:
        holding = [a for a in diagnostics.wired_only(adapters) or []
                   if set_by_hand(a, device_ip) or has_route(a, device_ip)]
        if len(holding) != 1:
            raise NetworkError("Say which Ethernet adapter to put back." if holding else
                               "No Ethernet adapter here holds the terminal's address.")
        index = holding[0]["index"]
    adapter = _adapter(adapters, index, device_ip, need_up=False)
    steps = undo_steps(adapter, device_ip)
    report = {"adapter": adapter["name"], "index": adapter["index"],
              "address": ", ".join(set_by_hand(adapter, device_ip)), "steps": readable(steps)}
    if not steps:
        return {**report, "result": "already", "message": f"{adapter['name']} holds nothing Herewise would take off."}
    return _ask(report, command_line(steps, stop_on_failure=False), run, read, settle_seconds,
                done=lambda a: not set_by_hand(a, device_ip) and not has_route(a, device_ip),
                what="put back")


def _ask(report: dict, parameters: str, run, read, settle_seconds: float, *, done, what: str) -> dict:
    if not _one_at_a_time.acquire(blocking=False):
        raise NetworkError("Windows is already being asked. Answer its question first.")
    try:
        log.info("asking Windows to %s %s: %s", what, report["adapter"], parameters)
        outcome = run(parameters)
    finally:
        _one_at_a_time.release()
    log.info("Windows answered %s (exit %s, error %s)", outcome.state, outcome.exit_code, outcome.error)
    if outcome.state == "declined":
        return {**report, "result": "declined",
                "message": "Windows' question was answered No, so this computer is as it was. The "
                           "steps to do it by hand are below."}
    if outcome.state == "unavailable":
        return {**report, "result": "failed",
                "message": "Herewise can only ask Windows for this on Windows."}
    if outcome.state == "failed":
        return {**report, "result": "failed",
                "message": f"Windows could not start its own tool for this (error {outcome.error}). The "
                           "steps to do it by hand are below."}

    # Whatever the exit code said, the adapter is the evidence. A new address is tentative for a
    # moment while Windows checks nobody else has it, so give it a few seconds to appear.
    deadline = time.monotonic() + settle_seconds
    adapter = None
    while True:
        adapters = read() or []
        adapter = next((a for a in adapters if int(a.get("index", -1)) == int(report["index"])), None)
        if adapter is not None and done(adapter):
            break
        if time.monotonic() >= deadline:
            break
        time.sleep(1.0)
    worked = adapter is not None and done(adapter)
    report["dhcp"] = (adapter or {}).get("dhcp")
    if worked:
        if what == "set up":
            kept = (report["dhcp"] or "").lower() == "enabled"
            message = (f"{report['adapter']} now has {report['address']} for the terminal"
                       + (", and still gets its own address automatically on any other network."
                          if kept else ". Windows turned automatic addressing off on that port, so put it "
                          "back from here when the port is needed on another network."))
        else:
            message = f"{report['adapter']} no longer holds the terminal's address."
        return {**report, "result": "done", "exit_code": outcome.exit_code, "message": message}
    if outcome.state == "timeout":
        message = "Windows did not finish in time, and the adapter does not show the change yet."
    else:
        message = (f"Windows ran the commands (exit code {outcome.exit_code}) but {report['adapter']} does "
                   "not show the change. The steps to do it by hand are below.")
    return {**report, "result": "failed", "exit_code": outcome.exit_code, "message": message}


# -- asking Windows ----------------------------------------------------------------------------------

SEE_MASK_NOCLOSEPROCESS = 0x00000040
SEE_MASK_NOASYNC = 0x00000100
ERROR_CANCELLED = 1223
SW_HIDE = 0
WAIT_OBJECT_0 = 0
WAIT_TIMEOUT = 0x102


def run_elevated(parameters: str, timeout_seconds: float = 120.0) -> Elevation:
    """Run `cmd.exe <parameters>` as administrator: one UAC prompt, no window, and wait for it."""
    return shell_execute("cmd.exe", parameters, verb="runas", timeout_seconds=timeout_seconds)


def shell_execute(program: str, parameters: str, *, verb: str, timeout_seconds: float = 120.0) -> Elevation:
    """ShellExecuteExW on a program in the system folder, waiting for it and reading its exit code.

    Split from run_elevated so the plumbing can be tested with verb "open", which asks nothing and
    changes nothing (tests/test_netsetup.py runs `cmd.exe /d /c exit 7`).
    """
    if platform.system() != "Windows":
        return Elevation("unavailable")
    import ctypes
    from ctypes import wintypes

    class ShellExecuteInfo(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.DWORD), ("fMask", wintypes.ULONG), ("hwnd", wintypes.HWND),
                    ("lpVerb", wintypes.LPCWSTR), ("lpFile", wintypes.LPCWSTR),
                    ("lpParameters", wintypes.LPCWSTR), ("lpDirectory", wintypes.LPCWSTR),
                    ("nShow", ctypes.c_int), ("hInstApp", wintypes.HINSTANCE),
                    ("lpIDList", ctypes.c_void_p), ("lpClass", wintypes.LPCWSTR),
                    ("hkeyClass", wintypes.HKEY), ("dwHotKey", wintypes.DWORD),
                    ("hIconOrMonitor", wintypes.HANDLE), ("hProcess", wintypes.HANDLE)]

    shell32 = ctypes.WinDLL("shell32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    ole32 = ctypes.WinDLL("ole32")
    shell32.ShellExecuteExW.argtypes = [ctypes.POINTER(ShellExecuteInfo)]
    shell32.ShellExecuteExW.restype = wintypes.BOOL
    kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel32.WaitForSingleObject.restype = wintypes.DWORD
    kernel32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    kernel32.GetExitCodeProcess.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.GetSystemDirectoryW.argtypes = [wintypes.LPWSTR, wintypes.UINT]
    kernel32.GetSystemDirectoryW.restype = wintypes.UINT
    user32.GetForegroundWindow.restype = wintypes.HWND
    ole32.CoInitializeEx.argtypes = [ctypes.c_void_p, wintypes.DWORD]
    ole32.CoInitializeEx.restype = ctypes.c_long

    # The system folder from Windows itself, not from an environment variable a user can set.
    buffer = ctypes.create_unicode_buffer(260)
    if not kernel32.GetSystemDirectoryW(buffer, 260):
        return Elevation("failed", error=ctypes.get_last_error())
    system = buffer.value
    # ShellExecuteEx reports a missing program with the same 1223 as a No to the prompt (seen here,
    # 2026-09-26), so a missing program must be found out first or it reads as the lecturer's choice.
    if not os.path.isfile(os.path.join(system, program)):
        return Elevation("failed", error=2)

    # ShellExecuteEx can hand work to COM, so the calling thread needs COM; a request thread has not.
    initialised = ole32.CoInitializeEx(None, 0x2 | 0x4) in (0, 1)   # apartment, no OLE1 DDE
    try:
        info = ShellExecuteInfo()
        info.cbSize = ctypes.sizeof(ShellExecuteInfo)
        info.fMask = SEE_MASK_NOCLOSEPROCESS | SEE_MASK_NOASYNC
        # Owned by whatever window was just clicked, so the prompt comes to the front rather than
        # flashing on the taskbar.
        info.hwnd = user32.GetForegroundWindow()
        info.lpVerb = verb
        info.lpFile = f"{system}\\{program}"
        info.lpParameters = parameters
        info.lpDirectory = system
        info.nShow = SW_HIDE
        if not shell32.ShellExecuteExW(ctypes.byref(info)):
            error = ctypes.get_last_error()
            return Elevation("declined" if error == ERROR_CANCELLED else "failed", error=error)
        if not info.hProcess:
            return Elevation("finished")
        try:
            waited = kernel32.WaitForSingleObject(info.hProcess, int(timeout_seconds * 1000))
            if waited == WAIT_TIMEOUT:
                return Elevation("timeout")
            code = wintypes.DWORD()
            kernel32.GetExitCodeProcess(info.hProcess, ctypes.byref(code))
            return Elevation("finished", exit_code=int(code.value))
        finally:
            kernel32.CloseHandle(info.hProcess)
    finally:
        if initialised:
            ole32.CoUninitialize()
