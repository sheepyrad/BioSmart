"""prepare, score, and flush on one local Scorer worker.

The worker speaks the same JSON-lines as the tailnet acceptor, on stdin
and stdout. One process serves both Scoring rounds.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
BIOSMART_SRC = REPO / "biosmart" / "src"


def test_one_worker_prepares_once_then_scores_and_flushes(tmp_path: Path) -> None:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(BIOSMART_SRC)
    env["PYTHONUNBUFFERED"] = "1"
    env["CUDA_VISIBLE_DEVICES"] = ""
    worker = subprocess.Popen(
        [sys.executable, "-u", "-m", "biosmart", "worker", "--stdio"],
        cwd=REPO,
        env=env,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )
    assert worker.stdin is not None and worker.stdout is not None
    try:
        prepared = _call(
            worker,
            {
                "op": "prepare",
                "seed": 7,
                "ordinal": 0,
                "target": {"name": "ns5-fixture"},
                "pocket": {"residues": ["A:42"]},
            },
        )
        assert prepared["ok"] is True
        assert prepared["scorer"] == "fake"
        first = _call(
            worker,
            {
                "op": "score",
                "round_no": 1,
                "candidates": [
                    {
                        "candidate_id": "000001",
                        "iteration": 1,
                        "round_no": 1,
                        "canonical_smiles": "CCO",
                    }
                ],
            },
        )
        assert worker.poll() is None
        second = _call(
            worker,
            {
                "op": "score",
                "round_no": 2,
                "candidates": [
                    {
                        "candidate_id": "000002",
                        "iteration": 2,
                        "round_no": 2,
                        "canonical_smiles": "CCN",
                    }
                ],
            },
        )
        flushed = _call(worker, {"op": "flush"})
        missing = _call(worker, {"op": "queue"})
    finally:
        if worker.poll() is None:
            worker.stdin.close()
            worker.wait(timeout=10)
    assert first["ok"] is True
    assert second["ok"] is True
    assert first["results"][0]["status"] == "scored"
    assert second["results"][0]["canonical_smiles"] == "CCN"
    assert flushed["ok"] is True
    assert flushed["entries"] == 2
    assert missing["ok"] is False
    assert "results" not in missing
    assert worker.returncode == 0


def test_worker_env_links_libcuda_and_keeps_caches_off_home(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("HF_HUB_CACHE", str(tmp_path / "hf"))
    monkeypatch.setenv("BOLTZ_CACHE", str(tmp_path / "boltz"))
    monkeypatch.setenv("TMPDIR", str(tmp_path / "tmp"))
    monkeypatch.setenv("CUDA_VISIBLE_DEVICES", "")
    monkeypatch.delenv("LIBRARY_PATH", raising=False)
    monkeypatch.delenv("TRITON_CACHE_DIR", raising=False)
    from biosmart.boltz2_client import cuda_link_dir, worker_environment

    env = worker_environment()
    assert env["HF_HUB_CACHE"] == str(tmp_path / "hf")
    assert env["TRITON_CACHE_DIR"] == str(tmp_path / "tmp" / "triton_cache")
    assert "CUDA_VISIBLE_DEVICES" not in env
    assert not Path(env["HF_HUB_CACHE"]).is_relative_to(Path.home())
    link = cuda_link_dir()
    if link is not None:
        assert str(link) in env["LIBRARY_PATH"].split(os.pathsep)
        assert (link / "libcuda.so").is_file()


def test_triton_cache_stays_inside_the_writable_volume(monkeypatch, tmp_path: Path) -> None:
    volume = tmp_path / "tmp"
    monkeypatch.setenv("HF_HUB_CACHE", str(tmp_path / "hf"))
    monkeypatch.setenv("BOLTZ_CACHE", str(tmp_path / "boltz"))
    monkeypatch.setenv("TMPDIR", str(volume))
    monkeypatch.delenv("TRITON_CACHE_DIR", raising=False)
    from biosmart.boltz2_client import worker_environment

    env = worker_environment()
    cache = Path(env["TRITON_CACHE_DIR"])
    assert cache.is_relative_to(volume)
    assert cache.is_dir()


def _call(worker: subprocess.Popen[str], payload: dict[str, object]) -> dict[str, object]:
    assert worker.stdin is not None and worker.stdout is not None
    worker.stdin.write(json.dumps(payload) + "\n")
    worker.stdin.flush()
    line = worker.stdout.readline()
    assert line, "worker closed stdout"
    parsed = json.loads(line)
    assert isinstance(parsed, dict)
    assert b"<html" not in line.lower().encode()
    return parsed
