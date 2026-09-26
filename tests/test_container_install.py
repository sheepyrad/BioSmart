"""Container install opens the localhost host.

The image is built from the same pixi.lock as the pixi install. The container
runs as the invoking user and starts at boot. A launcher opens the localhost host.
"""

from __future__ import annotations

from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]


def test_image_is_built_from_the_pixi_lockfile() -> None:
    dockerfile = (REPO / "deploy" / "Dockerfile").read_text(encoding="utf-8")
    install = (REPO / "deploy" / "install.sh").read_text(encoding="utf-8")
    assert (REPO / "pixi.lock").is_file()
    assert "COPY pixi.toml pixi.lock" in dockerfile
    assert "pixi install --locked --frozen --all" in dockerfile
    assert "pixi.lock" in install
    assert "deploy/Dockerfile" in install


def test_container_runs_as_the_invoking_user_and_starts_at_boot() -> None:
    compose = (REPO / "deploy" / "compose.yaml").read_text(encoding="utf-8")
    install = (REPO / "deploy" / "install.sh").read_text(encoding="utf-8")
    assert "restart: unless-stopped" in compose
    assert 'user: "${BIOSMART_UID:?}:${BIOSMART_GID:?}"' in compose
    assert "network_mode: host" in compose
    assert "BIOSMART_UID=$(id -u)" in install
    assert "BIOSMART_GID=$(id -g)" in install


def test_launcher_opens_the_localhost_host() -> None:
    desktop = (REPO / "deploy" / "biosmart.desktop").read_text(encoding="utf-8")
    opener = (REPO / "deploy" / "open-host.sh").read_text(encoding="utf-8")
    assert "Exec=xdg-open http://127.0.0.1:8000" in desktop
    assert "http://127.0.0.1:8000" in opener
    assert "xdg-open" in opener


def test_localhost_host_page(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    pytest.importorskip("fastapi")
    monkeypatch.setenv("BIOSMART_RUNS_ROOT", str(tmp_path / "runs"))
    monkeypatch.setenv("BIOSMART_REGISTRY", str(tmp_path / "registry.sqlite"))
    from fastapi.testclient import TestClient

    from biosmart.server import create_app

    with TestClient(create_app()) as client:
        response = client.get("/")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "This host is on localhost." in response.text


def test_later_scoring_round_reuses_scores_from_this_run(tmp_path: Path) -> None:
    from biosmart.boltz2_client import Boltz2WorkerScorer
    from biosmart.scoring import Candidate

    scorer = Boltz2WorkerScorer(
        work_dir=tmp_path / "work",
        cache_path=tmp_path / "cache.sqlite",
        msa=None,
        seed=1,
        python=tmp_path / "python",
    )
    scorer._context_hash = "ctx"
    scorer.version = "2.0.3"
    calls: list[dict[str, object]] = []

    class Worker:
        def call(self, payload: dict[str, object]) -> dict[str, object]:
            calls.append(payload)
            raw_candidates = payload["candidates"]
            assert isinstance(raw_candidates, list)
            return {
                "model_loads": 1,
                "prediction_calls": 1,
                "results": [
                    {
                        "candidate_id": item["candidate_id"],
                        "canonical_smiles": item["canonical_smiles"],
                        "status": "scored",
                        "reward": -0.2,
                        "failure_reason": None,
                        "raw": {"affinity_pred_value": 1.0},
                    }
                    for item in raw_candidates
                    if isinstance(item, dict)
                ],
            }

    scorer._ensure_worker = lambda: Worker()  # type: ignore[method-assign]
    first = scorer.score(
        1,
        [
            Candidate("000001", 1, 1, "CCO"),
            Candidate("000002", 1, 1, "CCN"),
        ],
    )
    second = scorer.score(
        2,
        [
            Candidate("000003", 2, 2, "CCO"),
            Candidate("000004", 2, 2, "CCN"),
        ],
    )
    assert len(calls) == 1
    assert [item.status for item in first] == ["scored", "scored"]
    assert [item.reward for item in second] == [item.reward for item in first]
