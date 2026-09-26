"""Inspect Candidates, then export and archive the Run.

Drive the runs API with a FakeScorer. Paging, scores, and filter reasons come
from the Index. The pose and the export read the Run database. Deleting the
Index does not change the exported scores. The page returns a stored pose
when the Scorer returned one, and does not draw an RDKit embed when it did not.
"""

from __future__ import annotations

import csv
import io
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any
from urllib import request as urlrequest
from urllib.parse import urlencode

import pytest

TESTS = Path(__file__).resolve().parent
if str(TESTS) not in sys.path:
    sys.path.insert(0, str(TESTS))

from test_candidate_index import _delete_index
from test_one_run_server import EventStream, _request, _serve

_ZSTD_MAGIC = b"\x28\xb5\x2f\xfd"
_STORED_POSE = (
    {"element": "C", "x": 20.5, "y": -1.25, "z": 4.0},
    {"element": "C", "x": 21.8, "y": -0.4, "z": 4.2},
    {"element": "O", "x": 22.4, "y": 0.6, "z": 3.3},
)


def _pdb() -> str:
    lines = []
    for serial, name, x in ((1, "N", 10.0), (2, "CA", 11.0), (3, "C", 12.0), (4, "O", 13.0)):
        lines.append(
            f"ATOM  {serial:5d} {name:>4s} ALA A  10    {x:8.3f}   6.000  -6.000  1.00  0.00           {name[0]}"
        )
    lines.append("END")
    return "\n".join(lines) + "\n"


def _spec() -> dict[str, Any]:
    return {
        "scorer": "fake",
        "seed": 0,
        "budget": {"iterations": 2, "candidates_per_iteration": 2},
        "target": {"name": "ns5", "structure": "ns5.pdb"},
        "pocket": {"residues": ["A:10"]},
        "library": {"id": "fixture-library"},
    }


def _get(port: int, path: str, params: dict[str, Any] | None = None) -> tuple[int, dict[str, Any]]:
    query = {} if params is None else {key: value for key, value in params.items() if value is not None}
    if query:
        path = f"{path}?{urlencode(query)}"
    return _request(port, "GET", path)


def _download(port: int, path: str) -> tuple[int, bytes, str]:
    request = urlrequest.Request(f"http://127.0.0.1:{port}{path}")
    with urlrequest.urlopen(request, timeout=30) as response:
        disposition = response.headers.get("Content-Disposition", "")
        return response.status, response.read(), disposition


def _finish(server: Any, spec: dict[str, Any]) -> str:
    stream = EventStream(server.port)
    try:
        status, created = _request(server.port, "POST", "/api/v1/runs", spec)
        assert status == 201, created
        run_id = created["run_id"]
        stream.wait_until(
            lambda events: any(
                event.get("type") in {"run.finished", "run.failed"} and event.get("run_id") == run_id
                for event in events
            )
        )
        return str(run_id)
    finally:
        stream.close()


def _rewards(run_folder: Path) -> dict[str, float]:
    with sqlite3.connect(run_folder / "run.sqlite") as database:
        return {
            str(row[0]): float(row[1])
            for row in database.execute(
                "SELECT id, reward FROM candidates WHERE reward IS NOT NULL ORDER BY id"
            )
        }


def _pose_file(tmp_path: Path) -> Path:
    path = tmp_path / "fake-poses.json"
    path.write_text(json.dumps({"000001": list(_STORED_POSE)}), encoding="utf-8")
    return path


def _rejected_embed(smiles: str, pocket_atoms: list[dict[str, Any]]) -> list[dict[str, float]]:
    """The generated conformer this page used to caption as the pose."""
    from rdkit import Chem
    from rdkit.Chem import AllChem

    parsed = Chem.MolFromSmiles(smiles)
    assert parsed is not None
    hydrated = Chem.AddHs(parsed)
    params = AllChem.ETKDGv3()
    params.randomSeed = 0xB105
    if AllChem.EmbedMolecule(hydrated, params) != 0:
        AllChem.Compute2DCoords(hydrated)
    else:
        try:
            AllChem.UFFOptimizeMolecule(hydrated, maxIters=40)
        except ValueError:
            pass
    conformer = hydrated.GetConformer()
    atoms: list[dict[str, float]] = []
    for atom in hydrated.GetAtoms():
        if atom.GetAtomicNum() == 1:
            continue
        position = conformer.GetAtomPosition(atom.GetIdx())
        atoms.append({"x": float(position.x), "y": float(position.y), "z": float(position.z)})
    assert atoms
    if not pocket_atoms:
        return [{"x": round(atom["x"], 3), "y": round(atom["y"], 3), "z": round(atom["z"], 3)} for atom in atoms]
    origin = _center(atoms)
    pocket = _center(pocket_atoms)
    return [
        {
            "x": round(atom["x"] + pocket[0] - origin[0], 3),
            "y": round(atom["y"] + pocket[1] - origin[1], 3),
            "z": round(atom["z"] + pocket[2] - origin[2], 3),
        }
        for atom in atoms
    ]


def _center(atoms: list[dict[str, Any]]) -> tuple[float, float, float]:
    count = len(atoms)
    return (
        sum(float(atom["x"]) for atom in atoms) / count,
        sum(float(atom["y"]) for atom in atoms) / count,
        sum(float(atom["z"]) for atom in atoms) / count,
    )


def _overlaps(rejected: list[dict[str, float]], returned: list[dict[str, Any]]) -> bool:
    return any(
        abs(atom["x"] - float(got["x"])) < 0.05
        and abs(atom["y"] - float(got["y"])) < 0.05
        and abs(atom["z"] - float(got["z"])) < 0.05
        for atom in rejected
        for got in returned
    )


def _assert_not_an_embed(payload: dict[str, Any]) -> None:
    assert payload["pose"] is None
    assert payload["stored"] is False
    rejected = _rejected_embed(str(payload["canonical_smiles"]), list(payload["pocket_atoms"]))
    assert rejected
    assert not _overlaps(rejected, list(payload["pose"] or []))


def test_page_pose_export_and_archive_read_the_run(tmp_path: Path) -> None:
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    (inputs / "ns5.pdb").write_text(_pdb())
    with _serve(
        tmp_path,
        extra_env={
            "BIOSMART_SKIP_DOCTOR": "1",
            "BIOSMART_INPUTS": str(inputs),
            "BIOSMART_FAKE_SCORER_POSE": str(_pose_file(tmp_path)),
        },
    ) as server:
        page = _download(server.port, "/")
        assert page[0] == 200
        html = page[1].decode()
        assert "Parallel coordinates" in html
        assert "Filter reason" in html
        assert "Export SDF" in html
        assert "Export CSV" in html
        assert ">Archive<" in html
        assert "/vendor/echarts.min.js" in html
        assert "plotly" not in html.lower()
        assert 'id="candidate-query"' in html
        assert "type=\"text\"" in html
        assert "has no stored pose" in html
        assert "Pose of Candidate " in html
        chart = _download(server.port, "/vendor/echarts.min.js")
        assert chart[0] == 200
        assert b"parallel" in chart[1]
        missing = urlrequest.Request(f"http://127.0.0.1:{server.port}/vendor/not-echarts.js")
        try:
            urlrequest.urlopen(missing, timeout=10)
        except Exception as exc:
            assert getattr(exc, "code", None) == 404
        else:
            raise AssertionError("unexpected vendor file")

        run_id = _finish(server, _spec())
        status, listed = _get(server.port, f"/api/v1/runs/{run_id}/candidates", {"limit": 2})
        assert status == 200, listed
        assert [row["candidate_id"] for row in listed["candidates"]] == ["000001", "000002"]
        assert listed["candidates"][0]["best_score"] == pytest.approx(0.0)
        assert listed["candidates"][0]["failure_reason"] is None
        assert listed["next_cursor"]
        status, rest = _get(
            server.port,
            f"/api/v1/runs/{run_id}/candidates",
            {"limit": 2, "cursor": listed["next_cursor"]},
        )
        assert status == 200, rest
        assert [row["candidate_id"] for row in rest["candidates"]] == ["000003", "000004"]
        assert rest["next_cursor"] is None

        status, lipophilic = _get(
            server.port,
            f"/api/v1/runs/{run_id}/candidates",
            {"min_logp": 1, "max_logp": 3, "limit": 10},
        )
        assert status == 200, lipophilic
        assert [row["canonical_smiles"] for row in lipophilic["candidates"]] == ["c1ccccc1"]

        status, found = _get(server.port, "/api/v1/search", {"smarts": "c1ccccc1", "limit": 10})
        assert status == 200, found
        assert any(row["canonical_smiles"] == "c1ccccc1" and row["run_id"] == run_id for row in found["candidates"])

        status, pose = _get(server.port, f"/api/v1/runs/{run_id}/candidates/000001/pose")
        assert status == 200, pose
        assert pose["canonical_smiles"] == "CCO"
        assert pose["pocket"]["residues"] == ["A:10"]
        assert pose["stored"] is True
        assert {atom["residue"] for atom in pose["pocket_atoms"]} == {"A:10"}
        assert [
            (atom["element"], atom["x"], atom["y"], atom["z"]) for atom in pose["pose"]
        ] == [
            (atom["element"], pytest.approx(atom["x"]), pytest.approx(atom["y"]), pytest.approx(atom["z"]))
            for atom in _STORED_POSE
        ]
        stored_x = sum(atom["x"] for atom in pose["pose"]) / len(pose["pose"])
        pocket_x = sum(atom["x"] for atom in pose["pocket_atoms"]) / len(pose["pocket_atoms"])
        assert abs(stored_x - pocket_x) > 1.0
        with sqlite3.connect(server.runs_root / run_id / "run.sqlite") as database:
            pose_ref = database.execute(
                "SELECT pose_ref FROM candidates WHERE id = ?",
                ("000001",),
            ).fetchone()[0]
        assert pose_ref == "poses/000001.pdb"
        pose_path = server.runs_root / run_id / pose_ref
        assert pose_path.is_file()
        stored_coords = [
            (float(line[30:38]), float(line[38:46]), float(line[46:54]))
            for line in pose_path.read_text(encoding="utf-8").splitlines()
            if line.startswith("HETATM")
        ]
        assert stored_coords == [
            (pytest.approx(atom["x"]), pytest.approx(atom["y"]), pytest.approx(atom["z"]))
            for atom in pose["pose"]
        ]
        assert not _overlaps(
            _rejected_embed(pose["canonical_smiles"], pose["pocket_atoms"]),
            pose["pose"],
        )
        assert str(tmp_path) not in str(pose)

        status, unposed = _get(server.port, f"/api/v1/runs/{run_id}/candidates/000002/pose")
        assert status == 200, unposed
        assert unposed["canonical_smiles"] == "CCN"
        _assert_not_an_embed(unposed)
        with sqlite3.connect(server.runs_root / run_id / "run.sqlite") as database:
            missing_ref = database.execute(
                "SELECT pose_ref FROM candidates WHERE id = ?",
                ("000002",),
            ).fetchone()[0]
        assert missing_ref is None

        rewards = _rewards(server.runs_root / run_id)
        with sqlite3.connect(server.registry) as index:
            index.execute("UPDATE candidate_index SET best_score = 999 WHERE run_id = ?", (run_id,))
        status, posed = _get(server.port, f"/api/v1/runs/{run_id}/candidates/000004/pose")
        assert status == 200, posed
        assert posed["score"] == pytest.approx(rewards["000004"])
        assert posed["score"] != pytest.approx(999)

        code, body, disposition = _download(server.port, f"/api/v1/runs/{run_id}/export?format=csv&top=4")
        assert code == 200
        assert "attachment;" in disposition
        table = list(csv.DictReader(io.StringIO(body.decode())))
        exported = {row["candidate_id"]: float(row["reward"]) for row in table}
        assert set(exported) == set(rewards)
        for candidate_id, reward in rewards.items():
            assert exported[candidate_id] == pytest.approx(reward)
        assert 999.0 not in exported.values()

        code, sdf, sdf_disposition = _download(server.port, f"/api/v1/runs/{run_id}/export?format=sdf&top=1")
        assert code == 200
        assert "sdf" in sdf_disposition
        assert b"$$$$" in sdf
        text = sdf.decode()
        assert "> <route>" in text
        assert "> <canonical_smiles>" in text

        _delete_index(server.registry)
        code, again, _ = _download(server.port, f"/api/v1/runs/{run_id}/export?format=csv&top=4")
        assert code == 200
        again_rows = list(csv.DictReader(io.StringIO(again.decode())))
        assert {row["candidate_id"]: float(row["reward"]) for row in again_rows} == exported

        code, archive, archive_disposition = _download(server.port, f"/api/v1/runs/{run_id}/archive")
        assert code == 200
        assert archive[:4] == _ZSTD_MAGIC
        assert f'filename="{run_id}.tar.zst"' in archive_disposition
        assert str(tmp_path) not in archive_disposition


def test_predicted_structure_file_is_the_ligand_pose(tmp_path: Path) -> None:
    from biosmart.pose_atoms import ligand_pose_from_prediction

    prediction = tmp_path / "predictions" / "000001"
    prediction.mkdir(parents=True)
    (prediction / "000001_model_0.pdb").write_text(
        "\n".join(
            (
                "ATOM      1  CA  ALA A  10      10.000   6.000  -6.000  1.00  0.00           C",
                "HETATM    2  C   LIG B   1      20.500  -1.250   4.000  1.00  0.00           C",
                "HETATM    3  O   LIG B   1      22.400   0.600   3.300  1.00  0.00           O",
                "HETATM    4  O   HOH W   1       1.000   1.000   1.000  1.00  0.00           O",
                "END",
            )
        )
        + "\n",
        encoding="utf-8",
    )
    atoms = ligand_pose_from_prediction(tmp_path, "000001")
    assert atoms is not None
    assert [(atom.element, atom.x, atom.y, atom.z) for atom in atoms] == [
        ("C", pytest.approx(20.5), pytest.approx(-1.25), pytest.approx(4.0)),
        ("O", pytest.approx(22.4), pytest.approx(0.6), pytest.approx(3.3)),
    ]


def test_worker_returns_the_pose_the_scorer_returned() -> None:
    from biosmart.pose_atoms import PoseAtom
    from biosmart.scoring import ScoreResult
    from biosmart.worker import _score_payload, _score_result

    result = ScoreResult(
        "000001",
        "CCO",
        "scored",
        0.0,
        pose=(PoseAtom("C", 20.5, -1.25, 4.0), PoseAtom("O", 22.4, 0.6, 3.3)),
    )
    again = _score_result(_score_payload(result))
    assert again.pose == result.pose
    assert _score_result(_score_payload(ScoreResult("000002", "CCN", "scored", -0.1))).pose is None


def test_failed_candidates_include_the_filter_reason(tmp_path: Path) -> None:
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    spec = _spec()
    spec["target"] = {"name": "ns5"}
    with _serve(
        tmp_path,
        extra_env={
            "BIOSMART_SKIP_DOCTOR": "1",
            "BIOSMART_FAKE_SCORER_FAIL": "1",
            "BIOSMART_INPUTS": str(inputs),
        },
    ) as server:
        run_id = _finish(server, spec)
        status, failed = _get(server.port, f"/api/v1/runs/{run_id}/candidates", {"filter": "failed", "limit": 10})
        assert status == 200, failed
        assert failed["candidates"]
        assert {row["failure_reason"] for row in failed["candidates"]} == {"FakeScorer failed"}
        assert all(row["best_score"] is None for row in failed["candidates"])
        status, pose = _get(server.port, f"/api/v1/runs/{run_id}/candidates/000001/pose")
        assert status == 200, pose
        assert pose["failure_reason"] == "FakeScorer failed"
        assert pose["score"] is None
        _assert_not_an_embed(pose)
