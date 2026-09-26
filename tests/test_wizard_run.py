"""Wizard: Target, Pocket, Preset, Scorer, Start.

Drive the runs API with FakeScorer. A library older than 30 days warns and
does not refuse Start. Progress and ETA come from Scoring rounds.
"""

from __future__ import annotations

import json
import re
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from biosmart.residues import read_structure, sequence_for
from biosmart.spec import RunSpec
from biosmart.storage import init_run_database, insert_scoring_round
from biosmart.wizard import prepare_start_payload


def _atom(serial: int, atom_name: str, resname: str, chain: str, resseq: int) -> str:
    return (
        f"ATOM  {serial:5d} {atom_name:>4s} {resname:3s} {chain}{resseq:4d}"
        "      11.000   6.000  -6.000  1.00  0.00           N"
    )


PDB = "\n".join(
    [
        _atom(1, "N", "ALA", "A", 10),
        _atom(2, "CA", "ALA", "A", 10),
        _atom(3, "N", "GLY", "A", 11),
        _atom(4, "N", "SER", "B", 2),
        "END",
        "",
    ]
)

MMCIF = """data_test
loop_
_atom_site.group_PDB
_atom_site.label_comp_id
_atom_site.auth_asym_id
_atom_site.auth_seq_id
ATOM ALA A 10
ATOM GLY A 11
#
"""


@pytest.fixture
def host(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    pytest.importorskip("fastapi")
    monkeypatch.setenv("BIOSMART_RUNS_ROOT", str(tmp_path / "runs"))
    monkeypatch.setenv("BIOSMART_REGISTRY", str(tmp_path / "registry.sqlite"))
    monkeypatch.setenv("BIOSMART_LIBRARIES_ROOT", str(tmp_path / "libraries"))
    monkeypatch.setenv("BIOSMART_INPUTS", str(tmp_path / "inputs"))
    monkeypatch.setenv("BIOSMART_LIGANDS", str(tmp_path / "ligands"))
    monkeypatch.setenv("BIOSMART_ALIGNMENTS", str(tmp_path / "alignments"))
    monkeypatch.setenv("CUDA_VISIBLE_DEVICES", "")
    from fastapi.testclient import TestClient

    from biosmart.server import create_app

    with TestClient(create_app()) as client:
        yield client


def _spec(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "scorer": "fake",
        "seed": 7,
        "budget": {"iterations": 2, "candidates_per_iteration": 2},
        "target": {"name": "ns5-fixture"},
        "pocket": {"residues": ["A:42"]},
        "library": {"id": "fixture-library"},
    }
    payload.update(overrides)
    return payload


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
    (folder / "library.json").write_text(json.dumps(payload) + "\n")


def _wait_run(host, run_id: str, predicate, timeout: float = 20.0) -> dict[str, object]:
    deadline = time.monotonic() + timeout
    last: dict[str, object] = {}
    while time.monotonic() < deadline:
        listed = host.get("/api/v1/runs")
        assert listed.status_code == 200
        runs = listed.json()["runs"]
        match = next((item for item in runs if item["run_id"] == run_id), None)
        if match is not None:
            last = match
            if predicate(match):
                return match
        time.sleep(0.05)
    raise AssertionError(f"run {run_id} timed out at {last!r}")


def test_wizard_order_is_target_pocket_preset_scorer_start(host) -> None:
    page = host.get("/").text
    steps = re.findall(r'<li data-step="([^"]+)"', page)
    assert steps == ["target", "pocket", "preset", "scorer", "start"]
    assert "Reference ligand" in page
    assert "Selected residues" in page
    assert "Advanced" in page
    assert "Paused" in page
    assert 'id="wizard-start"' in page
    assert "checkpoint" not in page.lower()
    assert "boltz" not in page.lower()
    assert not re.search(r'type\s*=\s*"(search|url)"', page, flags=re.IGNORECASE)
    text_inputs = re.findall(r'<input\b[^>]*type\s*=\s*"text"[^>]*>', page, flags=re.IGNORECASE)
    assert len(text_inputs) == 1
    assert "candidate-query" in text_inputs[0]
    assert "path" not in text_inputs[0].lower()


def test_residues_come_from_the_target_without_a_path(host, tmp_path: Path) -> None:
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    (inputs / "ns5.pdb").write_text(PDB)
    (tmp_path / "outside.pdb").write_text(PDB)
    parsed = read_structure(inputs / "ns5.pdb")
    assert [item["id"] for item in parsed["residues"]] == ["A:10", "A:11", "B:2"]
    assert sequence_for(parsed, ["A:11"]) == "AG"
    cif = tmp_path / "pocket.cif"
    cif.write_text(MMCIF)
    assert [item["id"] for item in read_structure(cif)["residues"]] == ["A:10", "A:11"]

    listed = host.get("/api/v1/inputs/ns5.pdb/residues")
    assert listed.status_code == 200
    body = listed.json()
    assert [item["id"] for item in body["residues"]] == ["A:10", "A:11", "B:2"]
    assert body["chains"][0]["sequence"] == "AG"
    assert str(tmp_path) not in listed.text
    assert "outside.pdb" not in listed.text
    missing = host.get("/api/v1/inputs/missing.pdb/residues")
    assert missing.status_code == 404


def test_reference_ligand_upload_and_a_typed_path_is_refused(host, tmp_path: Path) -> None:
    uploaded = host.post(
        "/api/v1/reference-ligands",
        files={"file": ("site.sdf", b"reference-ligand\n", "chemical/x-mdl-sdfile")},
    )
    assert uploaded.status_code == 201, uploaded.text
    ligand = uploaded.json()["ligand"]
    assert ligand["id"] == "site.sdf"
    assert "path" not in ligand
    assert str(tmp_path) not in uploaded.text
    assert (tmp_path / "ligands" / "site.sdf").read_bytes() == b"reference-ligand\n"

    escaped = host.post(
        "/api/v1/reference-ligands",
        files={"file": ("../../secret.sdf", b"nope", "chemical/x-mdl-sdfile")},
    )
    assert escaped.status_code == 422

    inputs = tmp_path / "inputs"
    inputs.mkdir()
    (inputs / "ns5.pdb").write_text(PDB)
    prepared = prepare_start_payload(
        {
            "scorer": "flashbind",
            "seed": 1,
            "preset": "quick",
            "target": {"name": "ns5.pdb", "structure": "ns5.pdb"},
            "pocket": {"reference_ligand": "site.sdf"},
            "library": {"id": "fixture-library"},
        },
        inputs_root=inputs,
        ligands_root=tmp_path / "ligands",
        alignments_root=tmp_path / "alignments",
    )
    spec = RunSpec.model_validate(prepared)
    assert spec.pocket.reference_ligand is not None
    assert Path(spec.pocket.reference_ligand).read_bytes() == b"reference-ligand\n"
    assert Path(spec.target.structure or "").read_text().startswith("ATOM")
    assert spec.pocket.residues == []

    refused = host.post(
        "/api/v1/runs",
        json=_spec(
            scorer="flashbind",
            preset="quick",
            budget=None,
            target={"name": "ns5.pdb", "structure": "/tmp/ns5.pdb"},
            pocket={"reference_ligand": "/tmp/site.sdf"},
        ),
    )
    assert refused.status_code == 422
    assert "Target" in refused.json()["detail"] or "Reference ligand" in refused.json()["detail"]
    assert not list((tmp_path / "runs").glob("*")) if (tmp_path / "runs").exists() else True


def test_boltz2_sequence_is_filled_from_selected_residues(tmp_path: Path) -> None:
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    (inputs / "ns5.pdb").write_text(PDB)
    prepared = prepare_start_payload(
        {
            "scorer": "boltz2",
            "seed": 3,
            "preset": "quick",
            "target": {"name": "ns5.pdb"},
            "pocket": {"residues": ["A:10", "A:11"]},
            "library": {"id": "fixture-library"},
        },
        inputs_root=inputs,
        ligands_root=tmp_path / "ligands",
        alignments_root=tmp_path / "alignments",
    )
    spec = RunSpec.model_validate(prepared)
    assert spec.target.sequence == "AG"
    assert spec.pocket.residues == ["A:10", "A:11"]
    assert spec.pocket.reference_ligand is None


def test_scorers_are_boltz2_and_flashbind_with_pocket_prompts(host) -> None:
    listed = host.get("/api/v1/scorers")
    assert listed.status_code == 200
    scorers = listed.json()["scorers"]
    assert [item["id"] for item in scorers] == ["boltz2", "flashbind"]
    assert scorers[0]["name"] == "Boltz-2"
    assert scorers[0]["prompt"] == "Boltz-2 asks for selected residues."
    assert scorers[1]["name"] == "FlashBind"
    assert scorers[1]["prompt"] == "FlashBind asks for a Reference ligand."
    assert scorers[1]["pose_provider"] == "FABind+"
    assert all(item["name"] != "FABind+" for item in scorers)


def test_advanced_settings_are_taken_from_the_schema(host) -> None:
    response = host.get("/api/v1/schema")
    assert response.status_code == 200
    body = response.json()
    advanced = body["advanced"]
    assert [field["path"] for field in advanced] == ["seed", "target.sequence", "target.msa"]
    assert advanced[0]["widget"] == "number"
    assert advanced[0]["title"] == "Seed"
    assert advanced[1]["widget"] == "text"
    assert advanced[2]["widget"] == "file"
    schema = body["schema"]
    assert schema["properties"]["seed"]["advanced"] is True
    encoded = json.dumps(schema)
    assert "fabind" not in encoded.lower()
    assert "reference_ligand" not in {field["path"] for field in advanced}


def test_preset_eta_uses_recorded_scoring_rounds(host, tmp_path: Path) -> None:
    unknown = host.get("/api/v1/presets")
    assert unknown.status_code == 200
    presets = {item["id"]: item for item in unknown.json()["presets"]}
    assert list(presets) == ["quick", "standard", "thorough"]
    assert presets["quick"]["iterations"] == 100
    assert presets["quick"]["candidates_per_iteration"] == 16
    assert presets["standard"] == {
        "id": "standard",
        "name": "Standard",
        "iterations": 1000,
        "candidates_per_iteration": 32,
        "eta_seconds": None,
    }
    assert presets["thorough"]["iterations"] == 2000
    assert all(item["eta_seconds"] is None for item in presets.values())

    folder = tmp_path / "runs" / "recorded"
    folder.mkdir(parents=True)
    database = folder / "run.sqlite"
    init_run_database(database)
    insert_scoring_round(database, round_no=1, scorer="fake", n_sent=16, n_ok=16, n_failed=0, secs=8.0)
    estimated = {item["id"]: item for item in host.get("/api/v1/presets").json()["presets"]}
    assert estimated["quick"]["eta_seconds"] == pytest.approx((8.0 / 16) * (100 * 16))
    assert estimated["thorough"]["eta_seconds"] == pytest.approx((8.0 / 16) * (2000 * 64))


def test_stale_library_warns_and_does_not_refuse_start(host, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BIOSMART_SKIP_DOCTOR", "1")
    created = datetime.now(timezone.utc) - timedelta(days=31)
    _stamp_library(tmp_path / "libraries", "enamine-stock-old", created)
    listed = host.get("/api/v1/libraries").json()
    reminder = listed["libraries"][0]["reminder"]
    assert "older than 30 days" in reminder

    started = host.post("/api/v1/runs", json=_spec(library={"id": "enamine-stock-old"}))
    assert started.status_code == 201, started.text
    run_id = started.json()["run_id"]
    finished = _wait_run(host, run_id, lambda run: run["status"] == "finished")
    assert finished["status"] == "finished"
    events = (tmp_path / "runs" / run_id / "events.jsonl").read_text()
    assert "older than 30 days" in events
    assert "run.finished" in events


def test_progress_eta_queue_cancel_stop_and_resume(host, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BIOSMART_SKIP_DOCTOR", "1")
    monkeypatch.setenv("BIOSMART_FAKE_SCORER_BLOCK_ROUND", "2")
    release = tmp_path / "release"
    monkeypatch.setenv("BIOSMART_FAKE_SCORER_RELEASE", str(release))

    started = host.post("/api/v1/runs", json=_spec())
    assert started.status_code == 201, started.text
    first_id = started.json()["run_id"]
    assert started.json()["status"] == "running"
    running = _wait_run(
        host,
        first_id,
        lambda run: run["iteration"] == 1 and isinstance(run["eta_seconds"], (int, float)),
    )
    assert running["status"] == "running"
    assert running["iterations"] == 2
    assert running["round_no"] == 1
    assert running["eta_seconds"] > 0
    detail = host.get(f"/api/v1/runs/{first_id}")
    assert detail.status_code == 200
    assert detail.json()["eta_seconds"] == running["eta_seconds"]
    assert str(tmp_path) not in detail.text

    queued = host.post("/api/v1/runs", json=_spec())
    assert queued.status_code == 201
    second_id = queued.json()["run_id"]
    assert queued.json()["status"] == "queued"
    waiting = _wait_run(host, second_id, lambda run: run["status"] == "queued")
    assert waiting["iteration"] is None

    cancelled = host.post(f"/api/v1/runs/{second_id}/cancel")
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"
    assert _wait_run(host, second_id, lambda run: run["status"] == "cancelled")["status"] == "cancelled"

    paused = host.post(f"/api/v1/runs/{first_id}/stop")
    assert paused.status_code == 200
    assert paused.json()["status"] == "paused"
    assert _wait_run(host, first_id, lambda run: run["status"] == "paused")["status"] == "paused"

    release.write_text("continue\n")
    resumed = host.post(f"/api/v1/runs/{first_id}/resume")
    assert resumed.status_code == 200
    assert resumed.json()["run_id"] == first_id
    finished = _wait_run(host, first_id, lambda run: run["status"] == "finished")
    assert finished["status"] == "finished"
    assert finished["eta_seconds"] == 0
    manifest = json.loads((tmp_path / "runs" / first_id / "run.json").read_text())
    assert manifest["status"] == "finished"
