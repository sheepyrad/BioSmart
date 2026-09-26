"""Host UI on localhost and the host Tailscale address.

The stand-in address is in 100.64.0.0/10 and is assigned to the loopback
interface, which stands in for the tailnet interface. A browser on the host
opens 127.0.0.1. A browser on another computer opens the stand-in. FakeScorer
drives the Run. The test reads the event stream, the Run folder, and the
Index. It does not read worker standard streams.
"""

from __future__ import annotations

import ipaddress
import json
import os
import re
import subprocess
from pathlib import Path
from urllib import request as urlrequest

import pytest

from biosmart.server import _open_listener
from biosmart.tailnet import is_tailnet, tailnet_addresses, tailnet_addresses_from
from test_one_run_server import (
    EXPECTED_CANDIDATES,
    EventStream,
    _assert_finished_folder,
    _assert_index,
    _events_for,
    _listening,
    _read_events,
    _request,
    _serve,
    _spec,
)

# 100.64.0.0/10. CI has no Tailscale, so this address is the tailnet interface.
_STAND_IN = "100.64.90.3"
# A LAN address on the same interface. The host must not listen here.
_LAN = "192.168.90.3"
_FIB = """
Main:
  +-- 0.0.0.0/0 3 0 5
     |-- 0.0.0.0
        /0 universe UNICAST
Local:
  +-- 0.0.0.0/0 2 0 2
     +-- 127.0.0.0/8 2 0 2
        |-- 127.0.0.1
           /32 host LOCAL
     |-- 0.0.0.0
        /0 universe UNICAST
     |-- 192.168.90.3
        /32 host LOCAL
     |-- 172.30.0.2
        /32 host LOCAL
     |-- 100.64.90.3
        /32 host LOCAL
     |-- 100.128.0.1
        /32 host LOCAL
     |-- 100.127.255.254
        /32 host LOCAL
"""
# fd7a:115c:a1e0::8 is inside the Tailscale prefix. The others are not.
_INET6 = """
00000000000000000000000000000001 01 80 10 80       lo
fe800000000000000000000000000001 02 40 20 80     eth0
fd7a115ca1e000000000000000000008 03 40 00 80   tail0
fd7a115ca1e100000000000000000001 03 40 00 80   tail0
20010db8000000000000000000000001 04 40 00 80     eth0
"""


def test_tailnet_addresses_are_only_the_tailscale_ranges() -> None:
    found = tailnet_addresses_from(_FIB, _INET6)
    assert found == ["100.64.90.3", "100.127.255.254", "fd7a:115c:a1e0::8"]
    assert "0.0.0.0" not in found
    assert "127.0.0.1" not in found
    assert _LAN not in found
    assert "172.30.0.2" not in found
    assert "100.128.0.1" not in found
    refused = ipaddress.ip_address("192.168.90.3")
    assert not is_tailnet(refused)
    assert is_tailnet(ipaddress.ip_address(_STAND_IN))
    assert is_tailnet(ipaddress.ip_address("fd7a:115c:a1e0::8"))


def test_listener_refuses_a_public_lan_address_and_an_unspecified_address() -> None:
    for host in ("0.0.0.0", "::", _LAN, "203.0.113.8", "10.1.2.3"):
        with pytest.raises(ValueError, match="public LAN"):
            _open_listener(host, 0)


def test_host_listens_on_localhost_and_the_tailscale_address(tmp_path: Path) -> None:
    saved_token = os.environ.pop("BIOSMART_TOKEN", None)
    _assign(_STAND_IN)
    _assign(_LAN)
    try:
        assert _STAND_IN in tailnet_addresses()
        assert _LAN not in tailnet_addresses()
        with _serve(tmp_path, extra_env={"BIOSMART_SKIP_DOCTOR": "1"}) as server:
            listeners = _listening(server.pid)
            assert listeners
            assert {port for _ip, port in listeners} == {server.port}
            listened = {ip for ip, _port in listeners}
            assert listened == {"127.0.0.1", *tailnet_addresses()}
            assert _STAND_IN in listened
            assert _LAN not in listened
            assert "0.0.0.0" not in listened
            assert "::" not in listened
            for ip in listened:
                address = ipaddress.ip_address(ip)
                assert str(address) == "127.0.0.1" or is_tailnet(address)

            maps = Path(f"/proc/{server.pid}/maps").read_text(encoding="utf-8")
            assert "torch" not in maps

            local_page = _page("127.0.0.1", server.port)
            remote_page = _page(_STAND_IN, server.port)
            assert local_page == remote_page
            assert "BioSmart" in remote_page
            assert re.search(r"token|password", remote_page, flags=re.IGNORECASE) is None

            stream = EventStream(server.port, _STAND_IN)
            try:
                status, created = _request(
                    server.port,
                    "POST",
                    "/api/v1/runs",
                    _spec(),
                    host=_STAND_IN,
                )
                assert status == 201
                run_id = created["run_id"]
                assert created["status"] == "running"
                streamed = stream.wait_until(
                    lambda events: any(
                        event.get("type") == "run.finished" and event.get("run_id") == run_id
                        for event in events
                    )
                )
            finally:
                stream.close()

        run_folder = server.runs_root / run_id
        assert run_folder.is_dir()
        file_events = _read_events(run_folder)
        assert _events_for(streamed, run_id) == file_events
        _assert_finished_folder(run_folder, run_id)
        _assert_index(server.registry, run_id, EXPECTED_CANDIDATES)
        provenance = json.loads((run_folder / "provenance.json").read_text(encoding="utf-8"))
        assert provenance["gpu"] is None
        assert provenance["scorer"] == "fake"
    finally:
        _remove(_STAND_IN)
        _remove(_LAN)
        if saved_token is not None:
            os.environ["BIOSMART_TOKEN"] = saved_token


def _page(host: str, port: int) -> str:
    req = urlrequest.Request(f"http://{host}:{port}/")
    assert req.get_header("Authorization") is None
    with urlrequest.urlopen(req, timeout=10) as response:
        assert response.status == 200
        assert "text/html" in response.headers["content-type"]
        assert response.headers.get("WWW-Authenticate") is None
        body = response.read().decode()
    return body


def _assign(address: str) -> None:
    _ip("addr", "replace", f"{address}/32", "dev", "lo")


def _remove(address: str) -> None:
    completed = _ip("addr", "del", f"{address}/32", "dev", "lo", check=False)
    if completed.returncode == 0:
        return
    detail = f"{completed.stderr} {completed.stdout}".lower()
    if any(phrase in detail for phrase in ("cannot assign", "cannot find", "no such", "not found")):
        return
    message = (completed.stderr or completed.stdout).strip()
    raise AssertionError(message or f"ip addr del failed ({completed.returncode})")


def _ip(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    binary = "/usr/sbin/ip" if Path("/usr/sbin/ip").is_file() else "ip"
    command = [binary, *args]
    if os.geteuid() != 0:
        command = ["sudo", "-n", *command]
    completed = subprocess.run(command, check=False, text=True, capture_output=True)
    if check and completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip()
        raise AssertionError(detail or f"ip failed ({completed.returncode})")
    return completed
