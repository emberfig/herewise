"""Network cards as data, and a UAC prompt that answers as told.

Used by tests/test_netsetup.py and by `scripts/dev_server.py --fake-network`, so the Ethernet setup
can be pressed on a screen without anything on this PC being read or changed. A Yes applies the
netsh commands Herewise builds to the data, the way Windows would; nothing else is simulated.
"""
from __future__ import annotations

import ipaddress

from rollcall import netsetup

PRETEND = " (pretend)"


def ethernet(**over) -> dict:
    """A laptop's Ethernet with the cable in and nothing on the other end but the terminal."""
    adapter = {"index": 12, "name": "Ethernet", "status": "Up", "media": "802.3", "dhcp": "Enabled",
               "ips": ["169.254.40.7"], "manual": [], "routes": ["255.255.255.255/32"]}
    adapter.update(over)
    return adapter


def wifi(ip: str = "10.20.0.14", **over) -> dict:
    adapter = {"index": 17, "name": "Wi-Fi", "status": "Up", "media": "Native 802.11", "dhcp": "Enabled",
               "ips": [ip], "manual": [], "routes": []}
    adapter.update(over)
    return adapter


class FakeWindows:
    """`answers` is what the prompt says, in turn; the last one repeats. "yes" applies the commands."""

    def __init__(self, adapters, answers=("yes",), exit_code=0, applies=True):
        self.adapters = adapters
        self.answers = list(answers)
        self.exit_code = exit_code
        self.applies = applies
        self.asked: list[str] = []

    def read(self):
        return [dict(a, ips=list(a["ips"]), manual=list(a["manual"]), routes=list(a["routes"]))
                for a in self.adapters]

    def run(self, parameters: str) -> netsetup.Elevation:
        answer = self.answers[min(len(self.asked), len(self.answers) - 1)]
        self.asked.append(parameters)
        if answer == "no":
            return netsetup.Elevation("declined", error=netsetup.ERROR_CANCELLED)
        if self.applies:
            for command in parameters.removeprefix("/d /c ").replace(" && ", " & ").split(" & "):
                self.apply(command.split())
        return netsetup.Elevation("finished", exit_code=self.exit_code)

    def apply(self, words: list[str]) -> None:
        args = dict(w.split("=", 1) for w in words if "=" in w)
        index = int(args.get("name") or args.get("interface"))
        adapter = next(a for a in self.adapters if a["index"] == index)
        verb, noun = words[3], words[4]
        if (verb, noun) == ("add", "address"):
            adapter["ips"].append(args["address"])
            adapter["manual"].append(args["address"] + "/24")
        elif (verb, noun) == ("add", "route"):
            adapter["routes"].append(args["prefix"])
        elif (verb, noun) == ("delete", "address"):
            adapter["ips"].remove(args["address"])
            adapter["manual"].remove(args["address"] + "/24")
        elif (verb, noun) == ("delete", "route"):
            adapter["routes"].remove(args["prefix"])
        elif (verb, noun) == ("set", "address") and args.get("source") == "dhcp":
            adapter["dhcp"] = "Enabled"

    # -- what the rest of the diagnostic chain would see, for the dev server -----------------------

    def addresses(self) -> list[str]:
        return [ip for a in self.adapters if a["status"] == "Up" for ip in a["ips"]]

    def source_for(self, device_ip: str, _port=None) -> str | None:
        """The address Windows would send from: the host route first, then the lowest metric,
        which for a Wi-Fi on the same numbers is the Wi-Fi (research 2026-09-26)."""
        network = ipaddress.ip_network(f"{device_ip}/24", strict=False)
        up = [a for a in self.adapters if a["status"] == "Up"]
        def on(a):
            return [ip for ip in a["ips"] if ipaddress.ip_address(ip) in network]
        for a in up:
            if f"{device_ip}/32" in a["routes"] and on(a):
                return on(a)[0]
        others = [a for a in up if "802.3" not in a["media"] and on(a)]
        if others:
            return on(others[0])[0]
        wired = [a for a in up if "802.3" in a["media"] and on(a)]
        if wired:
            return on(wired[0])[0]
        return up[0]["ips"][0] if up and up[0]["ips"] else None

    def reaches(self, device_ip: str) -> bool:
        source = self.source_for(device_ip)
        return any(source in a["ips"] for a in self.adapters if "802.3" in a["media"] and a["status"] == "Up") \
            and ipaddress.ip_address(source) in ipaddress.ip_network(f"{device_ip}/24", strict=False)
