"""Localhost host: Doctor, Building-block library, and Target.

The page is the host the launcher opens. Tests drive the server API.
A library older than 30 days is a reminder. Start stays available.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from biosmart.doctor import Check, DoctorReport
from biosmart.libraries import Library
from biosmart.uploads import parse_multipart

REPO = Path(__file__).resolve().parents[1]


@pytest.fixture
def host(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    pytest.importorskip("fastapi")
    monkeypatch.setenv("BIOSMART_RUNS_ROOT", str(tmp_path / "runs"))
    monkeypatch.setenv("BIOSMART_REGISTRY", str(tmp_path / "registry.sqlite"))
    monkeypatch.setenv("BIOSMART_LIBRARIES_ROOT", str(tmp_path / "libraries"))
    monkeypatch.setenv("BIOSMART_INPUTS", str(tmp_path / "inputs"))
    from fastapi.testclient import TestClient

    from biosmart.server import create_app

    with TestClient(create_app()) as client:
        yield client


def _stamp_library(root: Path, library_id: str, created_at: datetime) -> None:
    folder = root / library_id
    folder.mkdir(parents=True)
    payload = {
        "id": library_id,
        "source": "Enamine Stock",
        "created_at": created_at.isoformat(),
        "druglike": False,
        "path": str(folder),
        "supplier_file": "stock.zip",
    }
    (folder / "library.json").write_text(json.dumps(payload, indent=2) + "\n")


def test_host_page_shows_doctor_library_and_target_without_a_path_field(host) -> None:
    response = host.get("/")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    page = response.text
    assert "This host is on localhost." in page
    assert "Doctor" in page
    assert "Building-block library" in page
    assert "Target" in page
    assert "~/BioSmart/inputs" in page
    assert "Enamine Stock" in page
    assert "Enamine Catalog" in page
    assert "SMILES list" in page
    assert "Automated fix applied." in page
    assert "Apply fix" in page
    assert "Default" in page
    assert "Start remains available." in page
    assert "checkpoint" not in page.lower()
    assert "ckpt" not in page.lower()
    assert "boltz" not in page.lower()
    assert "<textarea" not in page.lower()
    tags = re.findall(r"<input\b[^>]*>", page, flags=re.IGNORECASE)
    assert tags
    text_inputs = []
    for tag in tags:
        assert "path" not in tag.lower()
        if re.search(r'id\s*=\s*"candidate-query"', tag, flags=re.IGNORECASE):
            assert re.search(r'type\s*=\s*"text"', tag, flags=re.IGNORECASE)
            text_inputs.append(tag)
            continue
        assert re.search(r'type\s*=\s*"(file|checkbox)"', tag, flags=re.IGNORECASE)
    assert text_inputs == [tag for tag in tags if "candidate-query" in tag]


def test_font_is_served_from_the_host(host) -> None:
    response = host.get("/fonts/fraunces-700.woff2")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("font/woff2")
    assert response.content[:4] == b"wOF2"
    assert host.get("/fonts/../host_page.html").status_code == 404


def test_inputs_mount_is_the_host_inputs_folder() -> None:
    compose = (REPO / "deploy" / "compose.yaml").read_text(encoding="utf-8")
    assert "BIOSMART_INPUTS: /biosmart/inputs" in compose
    assert "${BIOSMART_INPUTS:?}:/biosmart/inputs\n" in compose


def test_doctor_reports_checks_and_an_automated_fix(host, monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[str] = []

    def fake_apply(check_id: str, workstation: object = None, *, fetch: object = None) -> DoctorReport:
        if check_id != "weights":
            raise ValueError(f"Doctor check {check_id!r} has no automated fix")
        seen.append(check_id)
        return DoctorReport(
            (
                Check(
                    id="weights",
                    name="Weights",
                    ok=True,
                    blocking=True,
                    summary="Weights are present",
                    detail="Pose model, FABind+, FlashBind, Boltz-2, and ESM3 are on disk.",
                ),
            )
        )

    monkeypatch.setattr("biosmart.server.apply_fix", fake_apply)
    report = host.get("/api/v1/doctor")
    assert report.status_code == 200
    body = report.json()
    assert [item["id"] for item in body["checks"]] == [
        "gpu",
        "vram",
        "environments",
        "weights",
        "library",
    ]
    refused = host.post("/api/v1/doctor/fix/gpu")
    assert refused.status_code == 422
    assert "no automated fix" in refused.json()["detail"]
    assert seen == []

    applied = host.post("/api/v1/doctor/fix/weights")
    assert applied.status_code == 200
    fixed = applied.json()
    assert seen == ["weights"]
    assert fixed["applied"] == "weights"
    assert fixed["checks"][0]["ok"] is True
    assert "Pose model" in fixed["checks"][0]["detail"]
    assert "Boltz-2" in fixed["checks"][0]["detail"]
    assert "checkpoint" not in applied.text
    assert "ckpt" not in applied.text


def test_library_list_marks_the_default_and_a_staleness_reminder(host, tmp_path: Path) -> None:
    root = tmp_path / "libraries"
    now = datetime.now(timezone.utc)
    _stamp_library(root, "enamine-stock-old", now - timedelta(days=31))
    _stamp_library(root, "enamine-stock-new", now)

    listed = host.get("/api/v1/libraries")
    assert listed.status_code == 200
    body = listed.json()
    assert body["default_id"] == "enamine-stock-new"
    assert body["stale_after_days"] == 30
    by_id = {item["id"]: item for item in body["libraries"]}
    assert set(by_id) == {"enamine-stock-old", "enamine-stock-new"}
    assert by_id["enamine-stock-new"]["default"] is True
    assert by_id["enamine-stock-old"]["default"] is False
    assert by_id["enamine-stock-new"]["reminder"] is None
    reminder = by_id["enamine-stock-old"]["reminder"]
    assert isinstance(reminder, str)
    assert "older than 30 days" in reminder
    assert "path" not in by_id["enamine-stock-old"]
    assert str(root) not in listed.text

    doctor = host.get("/api/v1/doctor")
    library = next(item for item in doctor.json()["checks"] if item["id"] == "library")
    assert library["ok"] is True
    assert library["blocking"] is True


def test_build_library_from_an_upload(host, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    def fake_build(source_file: Path, libraries_root: Path, *, druglike: bool = False, cpu: int | None = None) -> Library:
        captured["name"] = source_file.name
        captured["bytes"] = source_file.read_bytes()
        captured["druglike"] = druglike
        captured["root"] = libraries_root
        created = datetime.now(timezone.utc)
        library_id = "enamine-stock-upload"
        folder = libraries_root / library_id
        folder.mkdir(parents=True)
        library = Library(
            id=library_id,
            source="Enamine Stock",
            created_at=created,
            druglike=druglike,
            path=folder,
            supplier_file=source_file.name,
        )
        (folder / "library.json").write_text(json.dumps(library.to_dict(), indent=2) + "\n")
        return library

    monkeypatch.setattr("biosmart.server.build_stock_library", fake_build)
    payload = b"PK\x03\x04\r\nstock-bytes"
    response = host.post(
        "/api/v1/libraries/build",
        data={"source": "stock", "druglike": "false"},
        files={"file": ("stock.zip", payload, "application/zip")},
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert captured["bytes"] == payload
    assert captured["name"] == "stock.zip"
    assert captured["druglike"] is False
    assert body["default_id"] == "enamine-stock-upload"
    assert body["library"]["source"] == "Enamine Stock"
    assert body["library"]["druglike"] is False
    assert body["library"]["supplier_file"] == "stock.zip"
    assert "path" not in body["library"]
    assert str(tmp_path) not in response.text

    listed = host.get("/api/v1/libraries").json()
    assert listed["default_id"] == "enamine-stock-upload"
    assert listed["libraries"][0]["default"] is True


def test_catalog_and_a_path_do_not_build_a_library(host, tmp_path: Path) -> None:
    catalog = host.post(
        "/api/v1/libraries/build",
        data={"source": "catalog"},
        files={"file": ("catalog.sdf", b"catalog", "chemical/x-mdl-sdfile")},
    )
    assert catalog.status_code == 422
    assert "Enamine Stock" in catalog.json()["detail"]
    smiles = host.post(
        "/api/v1/libraries/build",
        data={"source": "smiles"},
        files={"file": ("blocks.smi", b"CCO\tid\n", "text/plain")},
    )
    assert smiles.status_code == 422
    escaped = host.post(
        "/api/v1/libraries/build",
        data={"source": "stock"},
        files={"file": ("../../secret.zip", b"nope", "application/zip")},
    )
    assert escaped.status_code == 422
    as_path = host.post(
        "/api/v1/libraries/build",
        json={"file": str(tmp_path / "secret.zip"), "source": "stock"},
    )
    assert as_path.status_code == 422
    assert not (tmp_path / "libraries").exists()


def test_target_upload_and_choice_stay_inside_inputs(host, tmp_path: Path) -> None:
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    waiting = inputs / "waiting.pdb"
    waiting.write_text("HEADER    WAITING\nEND\n")
    outside = tmp_path / "outside.pdb"
    outside.write_text("HEADER    OUTSIDE\nEND\n")

    listed = host.get("/api/v1/inputs")
    assert listed.status_code == 200
    body = listed.json()
    assert body["chosen_id"] is None
    assert [item["id"] for item in body["targets"]] == ["waiting.pdb"]
    assert str(inputs) not in listed.text
    assert "outside.pdb" not in listed.text

    uploaded = host.post(
        "/api/v1/inputs",
        files={"file": ("ns5.pdb", b"HEADER    NS5\nEND\n", "chemical/x-pdb")},
    )
    assert uploaded.status_code == 201, uploaded.text
    assert uploaded.json()["chosen_id"] == "ns5.pdb"
    assert str(tmp_path) not in uploaded.text
    assert (inputs / "ns5.pdb").read_bytes().startswith(b"HEADER")

    chosen = host.post("/api/v1/inputs/waiting.pdb/choose")
    assert chosen.status_code == 200
    assert chosen.json()["chosen_id"] == "waiting.pdb"
    again = host.get("/api/v1/inputs").json()
    assert again["chosen_id"] == "waiting.pdb"
    assert {item["id"] for item in again["targets"]} == {"waiting.pdb", "ns5.pdb"}

    rejected = host.post("/api/v1/inputs/notes.txt/choose")
    assert rejected.status_code == 422
    traversal = host.post("/api/v1/inputs/..%2Foutside.pdb/choose")
    assert traversal.status_code in {404, 422}
    missing = host.post("/api/v1/inputs/missing.pdb/choose")
    assert missing.status_code == 404
    assert outside.read_text().startswith("HEADER    OUTSIDE")


def test_multipart_keeps_binary_supplier_bytes() -> None:
    boundary = "BioSmartBoundary"
    payload = b"PK\x03\x04\r\n--not-the-boundary\x00\xff"
    body = (
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="source"\r\n\r\n'
        f"stock\r\n"
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="file"; filename="stock.zip"\r\n'
        "Content-Type: application/zip\r\n\r\n"
    ).encode() + payload + f"\r\n--{boundary}--\r\n".encode()
    parts = parse_multipart(f"multipart/form-data; boundary={boundary}", body)
    fields = {name: data for name, filename, data in parts if filename is None}
    files = [(filename, data) for _name, filename, data in parts if filename is not None]
    assert fields["source"] == b"stock"
    assert files == [("stock.zip", payload)]
