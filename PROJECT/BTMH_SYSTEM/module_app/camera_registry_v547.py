"""BTMH 5.4.7 camera registry repair helpers.

This module repairs one specific legacy failure mode safely: a bundled/example
Hikvision endpoint can survive in a customer's persistent registry even after the
PC has moved to a different private LAN. The repair is conservative:

* only an exact legacy example host is eligible;
* credentials/path/port are preserved byte-for-byte semantically;
* the replacement host is inferred from the PC's current private IPv4 subnet;
* exactly one candidate must accept TCP on the saved RTSP port;
* otherwise nothing is changed.

It does not open FaceID/PAD or switch the active camera.
"""
from __future__ import annotations

import ipaddress
import os
import re
import socket
import subprocess
from collections.abc import Callable, Iterable
from urllib.parse import urlsplit

from .camera_connection_v544 import update_connection_source
from .camera_profiles import normalize_camera_source

LEGACY_HIKVISION_HOSTS = {"192.168.1.200"}


def _is_private_ipv4(value: str) -> bool:
    try:
        addr = ipaddress.ip_address(str(value).strip())
        return bool(addr.version == 4 and addr.is_private and not addr.is_loopback and not addr.is_link_local)
    except ValueError:
        return False


def local_private_ipv4s() -> list[str]:
    """Best-effort discovery of local private IPv4 addresses without dependencies."""
    found: set[str] = set()
    try:
        for item in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            value = str(item[4][0])
            if _is_private_ipv4(value):
                found.add(value)
    except OSError:
        pass

    # Windows machines can have several NICs (Ethernet/Wi-Fi/VPN). ``ipconfig``
    # gives a useful fallback even when hostname resolution only exposes one NIC.
    if os.name == "nt":
        try:
            proc = subprocess.run(
                ["ipconfig"], capture_output=True, text=True, timeout=2.0,
                encoding="utf-8", errors="ignore", check=False,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            for value in re.findall(r"(?<!\d)(?:\d{1,3}\.){3}\d{1,3}(?!\d)", proc.stdout or ""):
                if _is_private_ipv4(value):
                    found.add(value)
        except (OSError, subprocess.SubprocessError):
            pass
    return sorted(found)


def _tcp_open(host: str, port: int, timeout: float = 0.35) -> bool:
    try:
        with socket.create_connection((host, int(port)), timeout=timeout):
            return True
    except OSError:
        return False


def candidate_hosts_for_legacy(legacy_host: str, local_ips: Iterable[str]) -> list[str]:
    """Map legacy x.y.z.L to each current private /24 as x.y.C.L.

    The existing camera host's final octet is retained. This intentionally does
    not guess across arbitrary addresses; it only handles a moved /24 LAN such as
    192.168.1.200 -> 192.168.10.200.
    """
    try:
        old = ipaddress.ip_address(str(legacy_host).strip())
        if old.version != 4:
            return []
    except ValueError:
        return []
    suffix = str(old).split(".")[-1]
    out: set[str] = set()
    for value in local_ips:
        if not _is_private_ipv4(value):
            continue
        parts = str(value).split(".")
        if len(parts) != 4:
            continue
        candidate = ".".join(parts[:3] + [suffix])
        if candidate != str(old):
            out.add(candidate)
    return sorted(out)


def legacy_hikvision_repair_plan(
    row: dict,
    *,
    local_ips: Iterable[str] | None = None,
    probe: Callable[[str, int], bool] | None = None,
) -> dict | None:
    """Return a verified one-row repair plan, or ``None`` when ambiguous/unsafe."""
    name = str(row.get("name") or "")
    source = normalize_camera_source(str(row.get("source") or ""))
    parsed = urlsplit(source)
    host = str(parsed.hostname or "")
    if "hikvision" not in name.lower() or parsed.scheme.lower() != "rtsp":
        return None
    if host not in LEGACY_HIKVISION_HOSTS:
        return None
    port = int(parsed.port or 554)
    candidates = candidate_hosts_for_legacy(host, local_ips if local_ips is not None else local_private_ipv4s())
    checker = probe or _tcp_open
    reachable = [candidate for candidate in candidates if checker(candidate, port)]
    if len(reachable) != 1:
        return None
    replacement = reachable[0]
    path = (parsed.path or "/") + (("?" + parsed.query) if parsed.query else "")
    repaired = update_connection_source(source, replacement, port, path, None, None)
    return {
        "device_id": int(row.get("id") or 0),
        "name": name,
        "previous_source": source,
        "new_source": normalize_camera_source(repaired),
        "previous_host": host,
        "new_host": replacement,
        "port": port,
        "reason": "legacy-host-on-current-private-subnet",
    }
