"""Page, filter, and search Candidates.

Drive the runs API with a FakeScorer. Assert the event stream, the Run folder,
and the Index. Finishing a Run rebuilds the Index from the Run folder. Deleting
the Index and importing the Run folder restores the same Candidates.
"""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import pytest

TESTS = Path(__file__).resolve().parent
if str(TESTS) not in sys.path:
    sys.path.insert(0, str(TESTS))

from test_one_run_server import EventStream, _read_events, _request, _serve

# Seed 0 walks the catalog from index 0. Seed 3 walks it from index 3.
# Rewards are ``-((seed * 10 + k) % 100) / 100``. Descriptor literals are the
# RDKit values for those SMILES (average mass, Crippen logP, QED, InChIKey).
# Morgan radius 2, 2048 bits: Tanimoto(CCO, CCC) is 3/7.
SEED_0 = (
    ("000001", "CCO", 0.0, "LFQSCWFLJHTTHZ-UHFFFAOYSA-N", 46.069, -0.0014, 0.4068, 0),
    ("000002", "CCN", -0.01, "QUSNBJAOOMFDIB-UHFFFAOYSA-N", 45.085, -0.035, 0.4062, 0),
    ("000003", "CC(=O)O", -0.02, "QTBSBXVTEAMEQO-UHFFFAOYSA-N", 60.052, 0.0909, 0.4299, 0),
    ("000004", "c1ccccc1", -0.03, "UHOVQNZJYSORNB-UHFFFAOYSA-N", 78.114, 1.6866, 0.4426, 1),
)
SEED_3 = (
    ("000001", "c1ccccc1", -0.30, "UHOVQNZJYSORNB-UHFFFAOYSA-N", 78.114, 1.6866, 0.4426, 1),
    ("000002", "CCC", -0.31, "ATUOYWHBWRKTHZ-UHFFFAOYSA-N", 44.097, 1.4163, 0.3855, 0),
    ("000003", "CO", -0.32, "OKKJLVBELUTLKV-UHFFFAOYSA-N", 32.042, -0.3915, 0.3853, 0),
    ("000004", "CCO", -0.33, "LFQSCWFLJHTTHZ-UHFFFAOYSA-N", 46.069, -0.0014, 0.4068, 0),
)
CCO_CCC_SIMILARITY = 0.4286


def _spec(seed: int) -> dict[str, Any]:
    return {
        "scorer": "fake",
        "seed": seed,
        "budget": {"iterations": 2, "candidates_per_iteration": 2},
        "target": {"name": "ns5-fixture"},
        "pocket": {"residues": ["A:42"]},
        "library": {"id": "fixture-library"},
    }


def _get(port: int, path: str, params: dict[str, Any] | None = None) -> tuple[int, dict[str, Any]]:
    query = {} if params is None else {key: value for key, value in params.items() if value is not None}
    if query:
        path = f"{path}?{urlencode(query)}"
    return _request(port, "GET", path)


def _index_rows(registry: Path, run_id: str) -> list[tuple[Any, ...]]:
    with sqlite3.connect(f"file:{registry}?mode=ro", uri=True) as index:
        return index.execute(
            """
            SELECT candidate_id, canonical_smiles, best_score, status, failure_reason
            FROM candidate_index
            WHERE run_id = ?
            ORDER BY candidate_id
            """,
            (run_id,),
        ).fetchall()


def _database_smiles(run_folder: Path) -> list[str]:
    with sqlite3.connect(run_folder / "run.sqlite") as run_db:
        return [
            row[0]
            for row in run_db.execute("SELECT canonical_smiles FROM candidates ORDER BY id")
        ]


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


def _delete_index(registry: Path) -> None:
    with sqlite3.connect(registry) as connection:
        connection.execute("DROP TABLE IF EXISTS candidate_fp")
        connection.execute("DROP TABLE IF EXISTS candidate_props")
        connection.execute("DROP TABLE IF EXISTS candidate_index")


def _assert_candidate(actual: dict[str, Any], expected: tuple[Any, ...], *, run_id: str) -> None:
    candidate_id, smiles, score, inchikey, mw, logp, qed, rings = expected
    assert actual["run_id"] == run_id
    assert actual["candidate_id"] == candidate_id
    assert actual["canonical_smiles"] == smiles
    assert actual["status"] == "scored"
    assert actual["failure_reason"] is None
    assert actual["best_score"] == pytest.approx(score)
    assert actual["inchikey"] == inchikey
    assert actual["mw"] == pytest.approx(mw, abs=1e-3)
    assert actual["logp"] == pytest.approx(logp, abs=1e-3)
    assert actual["qed"] == pytest.approx(qed, abs=1e-3)
    assert actual["rings"] == rings
    assert actual["pains"] is False
    assert 1.0 <= actual["sa"] <= 10.0


def _assert_pages(port: int, run_id: str, expected: tuple[tuple[Any, ...], ...]) -> None:
    status, first = _get(port, f"/api/v1/runs/{run_id}/candidates", {"limit": 2})
    assert status == 200, first
    assert [row["candidate_id"] for row in first["candidates"]] == ["000001", "000002"]
    _assert_candidate(first["candidates"][0], expected[0], run_id=run_id)
    _assert_candidate(first["candidates"][1], expected[1], run_id=run_id)
    assert isinstance(first["next_cursor"], str) and first["next_cursor"]

    status, second = _get(
        port,
        f"/api/v1/runs/{run_id}/candidates",
        {"limit": 2, "cursor": first["next_cursor"]},
    )
    assert status == 200, second
    assert [row["candidate_id"] for row in second["candidates"]] == ["000003", "000004"]
    _assert_candidate(second["candidates"][0], expected[2], run_id=run_id)
    _assert_candidate(second["candidates"][1], expected[3], run_id=run_id)
    assert second["next_cursor"] is None

    status, heavy = _get(port, f"/api/v1/runs/{run_id}/candidates", {"limit": 2, "sort": "mw"})
    assert status == 200, heavy
    by_mw = sorted(expected, key=lambda row: (row[4], row[0]))
    _assert_candidate(heavy["candidates"][0], by_mw[0], run_id=run_id)
    _assert_candidate(heavy["candidates"][1], by_mw[1], run_id=run_id)
    status, heavy_rest = _get(
        port,
        f"/api/v1/runs/{run_id}/candidates",
        {"limit": 2, "sort": "mw", "cursor": heavy["next_cursor"]},
    )
    assert status == 200, heavy_rest
    _assert_candidate(heavy_rest["candidates"][0], by_mw[2], run_id=run_id)
    _assert_candidate(heavy_rest["candidates"][1], by_mw[3], run_id=run_id)
    assert heavy_rest["next_cursor"] is None

    status, scored = _get(port, f"/api/v1/runs/{run_id}/candidates", {"filter": "scored", "limit": 10})
    assert status == 200, scored
    assert [row["canonical_smiles"] for row in scored["candidates"]] == [row[1] for row in expected]
    assert scored["next_cursor"] is None

    status, heavy_only = _get(
        port,
        f"/api/v1/runs/{run_id}/candidates",
        {"min_mw": 50, "limit": 10},
    )
    assert status == 200, heavy_only
    assert [row["canonical_smiles"] for row in heavy_only["candidates"]] == [
        row[1] for row in expected if row[4] >= 50
    ]

    status, lipophilic = _get(
        port,
        f"/api/v1/runs/{run_id}/candidates",
        {"min_logp": 1, "limit": 10},
    )
    assert status == 200, lipophilic
    assert [row["canonical_smiles"] for row in lipophilic["candidates"]] == [
        row[1] for row in expected if row[5] >= 1
    ]


def _assert_search(port: int, seed_0: str, seed_3: str) -> None:
    status, benzene = _get(port, "/api/v1/search", {"smarts": "c1ccccc1", "limit": 10})
    assert status == 200, benzene
    assert {(row["run_id"], row["canonical_smiles"]) for row in benzene["candidates"]} == {
        (seed_0, "c1ccccc1"),
        (seed_3, "c1ccccc1"),
    }
    assert benzene["next_cursor"] is None

    status, amine = _get(port, "/api/v1/search", {"smarts": "[#7]", "limit": 10})
    assert status == 200, amine
    assert [(row["run_id"], row["canonical_smiles"]) for row in amine["candidates"]] == [(seed_0, "CCN")]

    found: list[dict[str, Any]] = []
    cursor = None
    for _page in range(5):
        status, page = _get(
            port,
            "/api/v1/search",
            {"similar_to": "CCO", "threshold": 0.4, "limit": 1, "cursor": cursor},
        )
        assert status == 200, page
        assert len(page["candidates"]) == 1
        found.append(page["candidates"][0])
        cursor = page["next_cursor"]
        if cursor is None:
            break
    else:
        raise AssertionError("similarity search did not end")
    assert [(row["canonical_smiles"], row["run_id"]) for row in found] == [
        ("CCO", seed_0 if seed_0 < seed_3 else seed_3),
        ("CCO", seed_3 if seed_0 < seed_3 else seed_0),
        ("CCC", seed_3),
    ]
    assert found[0]["similarity"] == pytest.approx(1.0)
    assert found[1]["similarity"] == pytest.approx(1.0)
    assert found[2]["similarity"] == pytest.approx(CCO_CCC_SIMILARITY, abs=1e-4)
    assert found[2]["run_id"] == seed_3


def test_finish_and_import_rebuild_the_index_for_page_filter_and_search(tmp_path: Path) -> None:
    with _serve(tmp_path, extra_env={"BIOSMART_SKIP_DOCTOR": "1"}) as server:
        stream = EventStream(server.port)
        try:
            status, first = _request(server.port, "POST", "/api/v1/runs", _spec(0))
            assert status == 201
            seed_0 = first["run_id"]
            stream.wait_until(
                lambda events: any(
                    event.get("type") == "run.finished" and event.get("run_id") == seed_0 for event in events
                )
            )
            status, second = _request(server.port, "POST", "/api/v1/runs", _spec(3))
            assert status == 201
            seed_3 = second["run_id"]
            streamed = stream.wait_until(
                lambda events: any(
                    event.get("type") == "run.finished" and event.get("run_id") == seed_3 for event in events
                )
            )
        finally:
            stream.close()

        folder_0 = server.runs_root / seed_0
        folder_3 = server.runs_root / seed_3
        assert [event for event in streamed if event.get("run_id") == seed_0] == _read_events(folder_0)
        assert [event for event in streamed if event.get("run_id") == seed_3] == _read_events(folder_3)
        assert _database_smiles(folder_0) == [row[1] for row in SEED_0]
        assert _database_smiles(folder_3) == [row[1] for row in SEED_3]

        _assert_pages(server.port, seed_0, SEED_0)
        _assert_pages(server.port, seed_3, SEED_3)
        status, best = _get(
            server.port,
            f"/api/v1/runs/{seed_0}/candidates",
            {"min_score": -0.015, "limit": 10},
        )
        assert status == 200, best
        assert [row["canonical_smiles"] for row in best["candidates"]] == ["CCO", "CCN"]
        _assert_search(server.port, seed_0, seed_3)

        before = {
            seed_0: _index_rows(server.registry, seed_0),
            seed_3: _index_rows(server.registry, seed_3),
        }
        assert [row[1] for row in before[seed_0]] == [row[1] for row in SEED_0]
        assert [row[2] for row in before[seed_0]] == pytest.approx([row[2] for row in SEED_0])

        _rewrite_candidate_events(folder_0)
        _rewrite_candidate_events(folder_3)
        _delete_index(server.registry)
        for folder, run_id in ((folder_0, seed_0), (folder_3, seed_3)):
            imported_status, imported = _request(
                server.port,
                "POST",
                "/api/v1/runs/import",
                {"folder": str(folder)},
            )
            assert imported_status == 200, imported
            assert imported["run_id"] == run_id
            assert imported["status"] == "finished"
            assert imported["candidates"] == 4

        assert _index_rows(server.registry, seed_0) == before[seed_0]
        assert _index_rows(server.registry, seed_3) == before[seed_3]
        assert "C" not in {row[1] for row in _index_rows(server.registry, seed_0)}
        assert any(
            event.get("type") == "candidate" and event.get("canonical_smiles") == "C"
            for event in _read_events(folder_0)
        )
        assert _database_smiles(folder_0) == [row[1] for row in SEED_0]
        _assert_pages(server.port, seed_0, SEED_0)
        _assert_pages(server.port, seed_3, SEED_3)
        _assert_search(server.port, seed_0, seed_3)


def test_failed_candidates_page_with_the_failure_reason(tmp_path: Path) -> None:
    with _serve(
        tmp_path,
        extra_env={"BIOSMART_SKIP_DOCTOR": "1", "BIOSMART_FAKE_SCORER_FAIL": "1"},
    ) as server:
        stream = EventStream(server.port)
        try:
            status, created = _request(server.port, "POST", "/api/v1/runs", _spec(7))
            assert status == 201
            run_id = created["run_id"]
            streamed = stream.wait_until(
                lambda events: any(
                    event.get("type") == "run.failed" and event.get("run_id") == run_id for event in events
                )
            )
        finally:
            stream.close()

        run_folder = server.runs_root / run_id
        assert [event for event in streamed if event.get("run_id") == run_id] == _read_events(run_folder)
        manifest = json.loads((run_folder / "run.json").read_text())
        assert manifest["status"] == "failed"
        assert _database_smiles(run_folder) == ["CCN", "CC(=O)O"]

        listed, body = _get(server.port, f"/api/v1/runs/{run_id}/candidates", {"filter": "failed", "limit": 1})
        assert listed == 200, body
        assert len(body["candidates"]) == 1
        first = body["candidates"][0]
        assert first["candidate_id"] == "000001"
        assert first["canonical_smiles"] == "CCN"
        assert first["status"] == "failed"
        assert first["failure_reason"] == "FakeScorer failed"
        assert first["best_score"] is None
        assert first["inchikey"] == "QUSNBJAOOMFDIB-UHFFFAOYSA-N"
        assert isinstance(body["next_cursor"], str)

        listed, rest = _get(
            server.port,
            f"/api/v1/runs/{run_id}/candidates",
            {"filter": "failed", "limit": 1, "cursor": body["next_cursor"]},
        )
        assert listed == 200, rest
        second = rest["candidates"][0]
        assert second["canonical_smiles"] == "CC(=O)O"
        assert second["status"] == "failed"
        assert second["failure_reason"] == "FakeScorer failed"
        assert second["inchikey"] == "QTBSBXVTEAMEQO-UHFFFAOYSA-N"
        assert rest["next_cursor"] is None

        hidden, scored = _get(server.port, f"/api/v1/runs/{run_id}/candidates", {"filter": "scored"})
        assert hidden == 200, scored
        assert scored["candidates"] == []
