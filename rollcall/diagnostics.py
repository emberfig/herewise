"""Named diagnoses for "cannot reach the device" (PRD section 10), in the order a person would check.

Each check says what it found in plain English. No stack traces reach the lecturer.
"""
from __future__ import annotations

import ipaddress
import json
import platform
import socket
import subprocess
from dataclasses import asdict, dataclass

WINDOWS_GATEWAY_HINT = (
    "If Windows refuses to save the static IP, clear the Default gateway field and leave it blank. "
    "Windows 11 will not save a gateway without a DNS server, and a direct cable needs no gateway."
)


@dataclass
class Check:
    name: str
    ok: bool
    message: str


def local_ipv4_addresses() -> list[str]:
    found: set[str] = set()
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            found.add(info[4][0])
    except OSError:
        pass
    return sorted(found)


def route_source_address(ip: str, port: int) -> str | None:
    """The local address the OS would use to reach the device. No packet is sent for UDP connect."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect((ip, port))
            return s.getsockname()[0]
    except OSError:
        return None


def ping(ip: str, timeout_ms: int = 1000) -> bool:
    if platform.system() == "Windows":
        cmd = ["ping", "-n", "1", "-w", str(timeout_ms), ip]
    else:
        cmd = ["ping", "-c", "1", "-W", str(max(1, timeout_ms // 1000)), ip]
    try:
        result = subprocess.run(cmd, capture_output=True, timeout=timeout_ms / 1000 + 3,
                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (OSError, subprocess.TimeoutExpired):
        return False
    # Windows ping returns 0 for "Destination host unreachable" replies from the local stack,
    # so require a TTL in the output as well.
    return result.returncode == 0 and b"TTL=" in result.stdout.upper()


def tcp_open(ip: str, port: int, timeout: float = 2.0) -> bool:
    try:
        with socket.create_connection((ip, port), timeout=timeout):
            return True
    except OSError:
        return False


# Per physical adapter: its index (what netsh is given, so a name such as "Ethernet 2" is never
# quoted), whether DHCP is on, every IPv4 address, the ones set by hand, and its host routes. Routes
# are read from both stores because a persistent route on a disconnected adapter is not active.
_ADAPTER_SCRIPT = (
    "$r = foreach ($a in Get-NetAdapter -Physical) { $i = $a.ifIndex; "
    "$ad = @(Get-NetIPAddress -InterfaceIndex $i -AddressFamily IPv4 -ErrorAction SilentlyContinue); "
    "$if = Get-NetIPInterface -InterfaceIndex $i -AddressFamily IPv4 -ErrorAction SilentlyContinue; "
    "$rt = @(Get-NetRoute -InterfaceIndex $i -AddressFamily IPv4 -ErrorAction SilentlyContinue) + "
    "@(Get-NetRoute -InterfaceIndex $i -AddressFamily IPv4 -PolicyStore PersistentStore -ErrorAction SilentlyContinue); "
    "[pscustomobject]@{ index = $i; name = $a.Name; status = [string]$a.Status; "
    "media = [string]$a.PhysicalMediaType; dhcp = [string]$if.Dhcp; "
    "ips = @($ad | ForEach-Object { $_.IPAddress }); "
    "manual = @($ad | Where-Object { [string]$_.PrefixOrigin -eq 'Manual' } "
    "| ForEach-Object { $_.IPAddress + '/' + $_.PrefixLength }); "
    "routes = @($rt | Where-Object { $_.DestinationPrefix -like '*/32' } "
    "| ForEach-Object { $_.DestinationPrefix } | Sort-Object -Unique) } }; "
    "ConvertTo-Json -InputObject @($r) -Depth 3"
)

# Passed to diagnose() to say "read the adapters yourself", because None already means "unknown".
READ = object()


def _as_list(value) -> list:
    # PowerShell writes a one-item array as the item on some versions; never trust the shape.
    if value is None:
        return []
    return list(value) if isinstance(value, list) else [value]


def physical_adapters() -> list[dict] | None:
    """Every physical adapter, wired or not, with what `_ADAPTER_SCRIPT` reads. None if unknown."""
    if platform.system() != "Windows":
        return None
    try:
        result = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", _ADAPTER_SCRIPT],
                                capture_output=True, timeout=20,
                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        adapters = json.loads(result.stdout.decode("utf-8", errors="replace") or "[]")
    except (OSError, subprocess.TimeoutExpired, ValueError):
        return None
    for a in adapters:
        for key in ("ips", "manual", "routes"):
            a[key] = [str(v) for v in _as_list(a.get(key))]
    return adapters


def is_wired(adapter: dict) -> bool:
    return "802.3" in (adapter.get("media") or "")


def wired_only(adapters: list[dict] | None) -> list[dict] | None:
    return None if adapters is None else [a for a in adapters if is_wired(a)]


def wired_adapters() -> list[dict] | None:
    """Physical Ethernet adapters with link status and configured IPv4 addresses. None if unknown.

    Needed because Windows hides the address of a disconnected adapter from ordinary lookups, so an
    unplugged cable otherwise looks like a missing static IP (seen on this PC, 2026-09-15).
    """
    return wired_only(physical_adapters())


def others_on(adapters: list[dict] | None, network) -> list[dict]:
    """Adapters that are not Ethernet but hold an address on the terminal's network: usually a Wi-Fi
    whose router also hands out 192.168.1.x."""
    return [a for a in adapters or [] if not is_wired(a)
            and any(ipaddress.ip_address(addr) in network for addr in a.get("ips") or [])]


def diagnose(ip: str, port: int = 4370, adapters=READ) -> list[Check]:
    """`adapters` is `physical_adapters()` if the caller has already read it, so one check reads the
    network cards once. Left out, they are read here."""
    checks: list[Check] = []
    device_net = ipaddress.ip_network(f"{ip}/24", strict=False)

    if adapters is READ:
        adapters = physical_adapters()
    wired = wired_only(adapters)
    link_up = None
    if wired is not None:
        up = [a for a in wired if a.get("status") == "Up"]
        link_up = bool(up)
        if not wired:
            # It used to offer importing from a USB flash drive instead, which is not built yet
            # (known gap 9), so a lecturer with no port was sent to a screen that says so.
            checks.append(Check(
                "cable", False,
                "Windows cannot see an Ethernet port on this computer. Plug in a USB to Ethernet "
                "adapter, then run the check again.",
            ))
        elif up:
            checks.append(Check("cable", True, f"Ethernet cable connected ({', '.join(a['name'] for a in up)})."))
        else:
            checks.append(Check(
                "cable", False,
                f"The Ethernet adapter ({', '.join(a['name'] for a in wired)}) shows as disconnected. Push the "
                "cable in firmly at both ends and check the device is switched on.",
            ))

    addresses = local_ipv4_addresses()
    same_subnet = [a for a in addresses if ipaddress.ip_address(a) in device_net]
    configured = [addr for a in (wired or []) for addr in (a.get("ips") or [])
                  if ipaddress.ip_address(addr) in device_net]
    # When the adapters are known, only the Ethernet's own addresses count. A Wi-Fi whose router also
    # hands out 192.168.1.x is on a different network that happens to use the same numbers, and it
    # used to pass this check and the next one (research 2026-09-26).
    on_cable = ([addr for a in wired if a.get("status") == "Up" for addr in (a.get("ips") or [])
                 if ipaddress.ip_address(addr) in device_net] if wired is not None else same_subnet)
    suggested = device_net.network_address + 100
    if str(suggested) == ip:
        suggested += 1
    if on_cable:
        checks.append(Check("pc_address", True, f"This PC has {', '.join(on_cable)}, on the device's network."))
    elif configured and link_up is False:
        checks.append(Check(
            "pc_address", True,
            f"The static IP {', '.join(configured)} is set, and will work once the cable is connected.",
        ))
    else:
        others = others_on(adapters, device_net)
        also = (f" {' and '.join(a['name'] for a in others)} uses the same numbers, but that is a "
                "different network, not the cable." if others else "")
        checks.append(Check(
            "pc_address", False,
            f"The Ethernet adapter on this PC is not on {device_net}.{also} Give it the address "
            f"{suggested}, mask 255.255.255.0. {WINDOWS_GATEWAY_HINT}",
        ))

    source = route_source_address(ip, port)
    wired_ips = {addr for a in wired or [] for addr in (a.get("ips") or [])}
    if source and ipaddress.ip_address(source) in device_net and (wired is None or source in wired_ips):
        checks.append(Check("route", True, f"Traffic to the device leaves from {source}."))
    elif source and ipaddress.ip_address(source) in device_net:
        holder = next((a["name"] for a in adapters or [] if source in (a.get("ips") or [])), "another adapter")
        checks.append(Check(
            "route", False,
            f"Traffic to {ip} would leave from {source} on {holder}, not the Ethernet cable. That "
            "network uses the same numbers as the terminal, and Windows prefers it.",
        ))
    else:
        checks.append(Check(
            "route", False,
            f"Traffic to {ip} would leave from {source or 'no adapter'}, not the Ethernet cable. "
            "The cable may be unplugged, or the Ethernet adapter is disabled.",
        ))

    replied = ping(ip)
    checks.append(Check(
        "ping", replied,
        f"The device at {ip} answers ping." if replied else
        f"No reply from {ip}. Check the cable at both ends, that the device is on, and that "
        "Menu > COMM. > Ethernet on the device shows this IP.",
    ))

    port_open = tcp_open(ip, port)
    checks.append(Check(
        "port", port_open,
        f"Port {port} is open." if port_open else
        f"Port {port} did not accept a connection. If ping works, check the port under "
        "Menu > COMM. > PC Connection, and close ZKBio Time.Net if it is running.",
    ))
    return checks


def as_dicts(checks: list[Check]) -> list[dict]:
    return [asdict(c) for c in checks]
