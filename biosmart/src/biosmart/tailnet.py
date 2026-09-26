"""Tailscale addresses on this host.

A Tailscale address is an IPv4 address in 100.64.0.0/10 or an IPv6 address in
fd7a:115c:a1e0::/48 assigned to a local interface. Loopback and the public
LAN are not Tailscale addresses. The host UI listens on those Tailscale
addresses in addition to 127.0.0.1. It does not bind 0.0.0.0.
"""

from __future__ import annotations

import ipaddress
import re
from pathlib import Path

TAILNET_V4 = ipaddress.ip_network("100.64.0.0/10")
TAILNET_V6 = ipaddress.ip_network("fd7a:115c:a1e0::/48")

_FIB_TRIE = Path("/proc/net/fib_trie")
_IF_INET6 = Path("/proc/net/if_inet6")
_FIB_ADDRESS = re.compile(r"\|--\s+(\d+\.\d+\.\d+\.\d+)\s*$")
_FIB_LOCAL = re.compile(r"/\d+\s+host LOCAL\s*$")


def is_tailnet(address: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """True when the address is in a Tailscale range."""
    mapped = address.ipv4_mapped if isinstance(address, ipaddress.IPv6Address) else None
    if mapped is not None:
        return is_tailnet(mapped)
    if isinstance(address, ipaddress.IPv4Address):
        return address in TAILNET_V4
    return address in TAILNET_V6


def tailnet_addresses() -> list[str]:
    """Local Tailscale addresses. Empty when this host has none."""
    return tailnet_addresses_from(_read(_FIB_TRIE), _read(_IF_INET6))


def tailnet_addresses_from(fib_trie: str, if_inet6: str) -> list[str]:
    """Tailscale addresses present in the local address tables."""
    found: set[str] = set()
    for text in _ipv4_locals(fib_trie):
        address = ipaddress.IPv4Address(text)
        if is_tailnet(address):
            found.add(str(address))
    for text in _ipv6_locals(if_inet6):
        address = ipaddress.IPv6Address(text)
        if is_tailnet(address):
            found.add(str(address))
    return sorted(found, key=lambda item: (ipaddress.ip_address(item).version, int(ipaddress.ip_address(item))))


def _ipv4_locals(fib_trie: str) -> list[str]:
    if "Local:" not in fib_trie:
        return []
    body = fib_trie.split("Local:", 1)[1]
    found: list[str] = []
    pending: str | None = None
    for line in body.splitlines():
        match = _FIB_ADDRESS.search(line)
        if match:
            pending = match.group(1)
            continue
        if pending is not None and _FIB_LOCAL.search(line):
            found.append(pending)
    return found


def _ipv6_locals(if_inet6: str) -> list[str]:
    found: list[str] = []
    for line in if_inet6.splitlines():
        fields = line.split()
        if not fields:
            continue
        hex_address = fields[0]
        if len(hex_address) != 32:
            continue
        try:
            raw = bytes.fromhex(hex_address)
        except ValueError:
            continue
        found.append(str(ipaddress.IPv6Address(raw)))
    return found


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""
