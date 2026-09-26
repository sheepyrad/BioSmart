"""Export, archive, and import a Run.

Drive the runs API with a FakeScorer. Assert the event stream, the Run folder,
and the Index. Top Candidates export as SDF (route in an SD tag) and as CSV.
One compressed archive of the Run folder, or the folder itself, rebuilds the
Index. Provenance and Scorer working files stay inside the Run folder. The
Runs root is the configured directory, here a stand-in for a large disk.
"""

from __future__ import annotations

import csv
import io
import json
import os
import shutil
import sqlite3
import stat
import subprocess
import sys
import tarfile
from pathlib import Path
from typing import Any
from urllib import error as urlerror
from urllib import request as urlrequest
from urllib.parse import urlencode

import pytest

TESTS = Path(__file__).resolve().parent
if str(TESTS) not in sys.path:
    sys.path.insert(0, str(TESTS))

from biosmart.index import RunFolderError
from biosmart.transfer import _extract_run_folder, write_run_archive
from test_candidate_index import _delete_index, _get, _index_rows
from test_one_run_server import EXPECTED_CANDIDATES, EventStream, _read_events, _request, _serve, _spec

_ZSTD_MAGIC = b"\x28\xb5\x2f\xfd"


def _route(smiles: str) -> list[dict[str, str]]:
    return [
        {
            "action": "Firstblock",
            "block": smiles,
            "smiles": smiles,
            "library": "fixture-library",
        }
    ]


def _download(port: int, path: str) -> tuple[int, bytes, str]:
    request = urlrequest.Request(f"http://127.0.0.1:{port}{path}")
    try:
        with urlrequest.urlopen(request, timeout=30) as response:
            disposition = response.headers.get("Content-Disposition", "")
            return response.status, response.read(), disposition
    except urlerror.HTTPError as exc:
        return exc.code, exc.read(), exc.headers.get("Content-Disposition", "")


def _sdf_properties(text: str) -> list[dict[str, str]]:
    records: list[dict[str, str]] = []
    for chunk in text.split("$$$$"):
        if "> <" not in chunk:
            continue
        props: dict[str, str] = {}
        for part in chunk.split("> <")[1:]:
            name, _, rest = part.partition(">")
            props[name.strip()] = rest.split("\n\n", 1)[0].strip()
        records.append(props)
    return records


def _rewrite_candidate_events(run_folder: Path) -> None:
    events_path = run_folder / "events.jsonl"
    rewritten: list[str] = []
    for line in events_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        event = json.loads(line)
        if event.get("type") == "candidate":
            event["canonical_smiles"] = "C"
        rewritten.append(json.dumps(event))
    events_path.write_text("\n".join(rewritten) + "\n", encoding="utf-8")


def _zstd_decompress(path: Path) -> bytes:
    try:
        import zstandard
    except ImportError:
        zstandard = None
    if zstandard is not None:
        decompressor = zstandard.ZstdDecompressor()
        with path.open("rb") as handle:
            return decompressor.stream_reader(handle).read()
    completed = subprocess.run(
        ["zstd", "-d", "-c", "-q", str(path)],
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    return completed.stdout


def _archive_names(path: Path) -> set[str]:
    with tarfile.open(fileobj=io.BytesIO(_zstd_decompress(path)), mode="r:") as tar:
        return set(tar.getnames())


def _archive_bytes(path: Path, name: str) -> bytes:
    with tarfile.open(fileobj=io.BytesIO(_zstd_decompress(path)), mode="r:") as tar:
        extracted = tar.extractfile(name)
        assert extracted is not None
        return extracted.read()


def _routes_in_database(run_folder: Path) -> list[tuple[str, str, str]]:
    with sqlite3.connect(run_folder / "run.sqlite") as database:
        return list(
            database.execute(
                "SELECT id, canonical_smiles, route_json FROM candidates ORDER BY id"
            )
        )


def test_export_archive_and_import_rebuild_the_index(tmp_path: Path) -> None:
    large_disk = tmp_path / "large-disk"
    runs_root = large_disk / "runs"
    registry = tmp_path / "registry.sqlite"
    assert not runs_root.exists()

    with _serve(
        tmp_path,
        extra_env={"BIOSMART_SKIP_DOCTOR": "1"},
        runs_root=runs_root,
        registry=registry,
    ) as server:
        assert server.runs_root == runs_root
        assert registry.parent != runs_root
        stream = EventStream(server.port)
        try:
            status, created = _request(server.port, "POST", "/api/v1/runs", _spec())
            assert status == 201, created
            run_id = created["run_id"]
            streamed = stream.wait_until(
                lambda events: any(
                    event.get("type") == "run.finished" and event.get("run_id") == run_id
                    for event in events
                )
            )
        finally:
            stream.close()

        run_folder = runs_root / run_id
        assert run_folder.is_dir()
        assert run_folder.parent == runs_root
        assert not (tmp_path / "runs").exists()
        assert [event for event in streamed if event.get("run_id") == run_id] == _read_events(run_folder)

        events = _read_events(run_folder)
        assert events[0]["type"] == "run.started"
        assert events[-1]["type"] == "run.finished"
        candidates = [event for event in events if event["type"] == "candidate"]
        assert [event["canonical_smiles"] for event in candidates] == [
            smiles for smiles, _reward in EXPECTED_CANDIDATES
        ]
        assert [event["route"] for event in candidates] == [
            _route(smiles) for smiles, _reward in EXPECTED_CANDIDATES
        ]

        provenance_path = run_folder / "provenance.json"
        provenance = json.loads(provenance_path.read_text())
        assert provenance["run_id"] == run_id
        assert provenance["seed"] == 7
        assert provenance["scorer"] == "fake"
        assert provenance["library"]["id"] == "fixture-library"
        provenance_bytes = provenance_path.read_bytes()

        stored = _routes_in_database(run_folder)
        assert [smiles for _candidate_id, smiles, _route_json in stored] == [
            smiles for smiles, _reward in EXPECTED_CANDIDATES
        ]
        assert [json.loads(route_json) for _candidate_id, _smiles, route_json in stored] == [
            _route(smiles) for smiles, _reward in EXPECTED_CANDIDATES
        ]

        working_bytes: dict[int, bytes] = {}
        for round_no in (1, 2):
            working = run_folder / "scorer" / f"round_{round_no}" / "round.json"
            assert working.is_file()
            assert working.is_relative_to(run_folder)
            payload = json.loads(working.read_text())
            assert payload["round_no"] == round_no
            assert payload["scorer"] == "fake"
            assert payload["scorer_version"] == "0"
            assert payload["context_hash"] == provenance["context_hash"]
            assert len(payload["candidates"]) == 2
            working_bytes[round_no] = working.read_bytes()

        before = _index_rows(server.registry, run_id)
        assert [row[1] for row in before] == [smiles for smiles, _reward in EXPECTED_CANDIDATES]
        assert [row[2] for row in before] == pytest.approx(
            [reward for _smiles, reward in EXPECTED_CANDIDATES]
        )

        sdf_status, sdf_bytes, sdf_disposition = _download(
            server.port,
            f"/api/v1/runs/{run_id}/export?{urlencode({'format': 'sdf', 'top': 2})}",
        )
        csv_status, csv_bytes, csv_disposition = _download(
            server.port,
            f"/api/v1/runs/{run_id}/export?{urlencode({'format': 'csv', 'top': 2})}",
        )
        assert sdf_status == 200
        assert csv_status == 200
        assert f'filename="{run_id}-top-2.sdf"' in sdf_disposition
        assert f'filename="{run_id}-top-2.csv"' in csv_disposition

        sdf_records = _sdf_properties(sdf_bytes.decode())
        assert [record["canonical_smiles"] for record in sdf_records] == ["CCN", "CC(=O)O"]
        assert [json.loads(record["route"]) for record in sdf_records] == [_route("CCN"), _route("CC(=O)O")]
        assert sdf_bytes.decode().count("$$$$") == 2

        table = list(csv.DictReader(io.StringIO(csv_bytes.decode())))
        assert table[0].keys() == {
            "candidate_id",
            "canonical_smiles",
            "reward",
            "status",
            "iteration",
            "round_no",
            "route",
        }
        assert [row["canonical_smiles"] for row in table] == ["CCN", "CC(=O)O"]
        assert [row["candidate_id"] for row in table] == ["000001", "000002"]
        assert [json.loads(row["route"]) for row in table] == [_route("CCN"), _route("CC(=O)O")]
        assert [float(row["reward"]) for row in table] == pytest.approx([-0.70, -0.71])
        assert [row["status"] for row in table] == ["scored", "scored"]

        _rewrite_candidate_events(run_folder)
        _delete_index(server.registry)
        again_status, again_sdf, _again_disposition = _download(
            server.port,
            f"/api/v1/runs/{run_id}/export?{urlencode({'format': 'sdf', 'top': 2})}",
        )
        assert again_status == 200
        assert again_sdf == sdf_bytes

        destination = large_disk / f"{run_id}.tar.zst"
        archived_status, archived = _request(
            server.port,
            "POST",
            f"/api/v1/runs/{run_id}/archive",
            {"destination": str(destination)},
        )
        assert archived_status == 200, archived
        archive = Path(archived["archive"])
        assert archive == destination
        assert archive.is_file()
        assert list(large_disk.glob("*.tar.zst")) == [archive]
        assert archive.read_bytes()[:4] == _ZSTD_MAGIC
        names = _archive_names(archive)
        assert names > {run_id}
        assert all(name == run_id or name.startswith(f"{run_id}/") for name in names)
        assert f"{run_id}/provenance.json" in names
        assert f"{run_id}/scorer/round_1/round.json" in names
        assert f"{run_id}/scorer/round_2/round.json" in names
        assert f"{run_id}/run.sqlite" in names
        assert _archive_bytes(archive, f"{run_id}/provenance.json") == provenance_bytes
        assert _archive_bytes(archive, f"{run_id}/scorer/round_1/round.json") == working_bytes[1]
        assert _archive_bytes(archive, f"{run_id}/scorer/round_2/round.json") == working_bytes[2]

        shutil.rmtree(run_folder)
        imported_status, imported = _request(
            server.port,
            "POST",
            "/api/v1/runs/import",
            {"archive": str(archive)},
        )
        assert imported_status == 200, imported
        assert imported["run_id"] == run_id
        assert imported["status"] == "finished"
        assert imported["candidates"] == 4
        assert _index_rows(server.registry, run_id) == before
        assert "C" not in {row[1] for row in _index_rows(server.registry, run_id)}
        restored = runs_root / run_id
        assert restored.is_dir()
        assert (restored / "provenance.json").read_bytes() == provenance_bytes
        assert (restored / "scorer" / "round_1" / "round.json").read_bytes() == working_bytes[1]
        assert (restored / "scorer" / "round_2" / "round.json").read_bytes() == working_bytes[2]
        assert any(
            event.get("type") == "candidate" and event.get("canonical_smiles") == "C"
            for event in _read_events(restored)
        )
        assert [smiles for _candidate_id, smiles, _route_json in _routes_in_database(restored)] == [
            smiles for smiles, _reward in EXPECTED_CANDIDATES
        ]

        listed, page = _get(
            server.port,
            f"/api/v1/runs/{run_id}/candidates",
            {"sort": "best_score", "limit": 2},
        )
        assert listed == 200, page
        assert [row["canonical_smiles"] for row in page["candidates"]] == ["CCN", "CC(=O)O"]

        moved = tmp_path / "moved-run"
        shutil.copytree(restored, moved)
        shutil.rmtree(restored)
        _delete_index(server.registry)
        folder_status, folder_imported = _request(
            server.port,
            "POST",
            "/api/v1/runs/import",
            {"folder": str(moved)},
        )
        assert folder_status == 200, folder_imported
        assert folder_imported["run_id"] == run_id
        assert folder_imported["candidates"] == 4
        assert _index_rows(server.registry, run_id) == before
        assert (runs_root / run_id / "provenance.json").read_bytes() == provenance_bytes
        assert (runs_root / run_id / "scorer" / "round_1" / "round.json").is_file()
        listed, page = _get(
            server.port,
            f"/api/v1/runs/{run_id}/candidates",
            {"sort": "best_score", "limit": 2},
        )
        assert listed == 200, page
        assert [row["canonical_smiles"] for row in page["candidates"]] == ["CCN", "CC(=O)O"]
        assert [path for path in runs_root.iterdir() if path.is_dir()] == [runs_root / run_id]


def _zstd_compress(data: bytes) -> bytes:
    try:
        import zstandard
    except ImportError:
        zstandard = None
    if zstandard is not None:
        return bytes(zstandard.ZstdCompressor(level=3).compress(data))
    completed = subprocess.run(
        ["zstd", "-q", "-c"],
        input=data,
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    return completed.stdout


def _hostile_archive(kind: str) -> bytes:
    run_id = "a" * 32
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as tar:
        info = tarfile.TarInfo(name=f"{run_id}/hostile")
        if kind == "fifo":
            info.type = tarfile.FIFOTYPE
            info.mode = 0o644
            tar.addfile(info)
        else:
            payload = kind.encode("ascii")
            info.type = tarfile.REGTYPE
            info.mode = 0o2755 if kind == "setgid" else 0o4755
            info.size = len(payload)
            tar.addfile(info, io.BytesIO(payload))
    return _zstd_compress(buffer.getvalue())


@pytest.mark.parametrize("kind", ["fifo", "setuid", "setgid"])
def test_import_refuses_fifo_or_setuid_member(tmp_path: Path, kind: str) -> None:
    archive = tmp_path / f"{kind}.tar.zst"
    archive.write_bytes(_hostile_archive(kind))
    work = tmp_path / "work"
    work.mkdir()
    with pytest.raises(RunFolderError, match="not a Run folder file"):
        _extract_run_folder(archive, work)
    hostile = work / "unpacked" / ("a" * 32) / "hostile"
    assert not hostile.exists()
    assert not hostile.is_fifo()
    for path in (work / "unpacked").rglob("*"):
        mode = path.lstat().st_mode
        assert not stat.S_ISFIFO(mode)
        assert not stat.S_ISCHR(mode)
        assert not stat.S_ISBLK(mode)
        assert mode & 0o6000 == 0


def test_setgid_directory_round_trips(tmp_path: Path) -> None:
    parent = tmp_path / "setgid-parent"
    parent.mkdir()
    os.chmod(parent, 0o2755)
    run_id = "b" * 32
    run_folder = parent / run_id
    nested = run_folder / "scorer" / "round_1"
    nested.mkdir(parents=True)
    assert stat.S_ISGID(run_folder.stat().st_mode)
    assert stat.S_ISGID(nested.stat().st_mode)
    (run_folder / "run.json").write_text(json.dumps({"run_id": run_id}) + "\n", encoding="utf-8")
    sqlite3.connect(run_folder / "run.sqlite").close()
    (nested / "round.json").write_text("{}\n", encoding="utf-8")

    archive = tmp_path / f"{run_id}.tar.zst"
    write_run_archive(run_folder, archive)
    with tarfile.open(fileobj=io.BytesIO(_zstd_decompress(archive)), mode="r:") as tar:
        modes = {member.name: member.mode for member in tar.getmembers() if member.isdir()}
    assert modes[run_id] & 0o2000
    assert modes[f"{run_id}/scorer/round_1"] & 0o2000

    work = tmp_path / "work"
    work.mkdir()
    extracted = _extract_run_folder(archive, work)
    assert extracted == work / "unpacked" / run_id
    assert (extracted / "run.json").read_text(encoding="utf-8") == json.dumps({"run_id": run_id}) + "\n"
    assert (extracted / "run.sqlite").is_file()
    assert (extracted / "scorer" / "round_1" / "round.json").read_text(encoding="utf-8") == "{}\n"
    for path in (extracted, extracted / "scorer", extracted / "scorer" / "round_1"):
        assert stat.S_IMODE(path.stat().st_mode) == 0o755
