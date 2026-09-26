"""One Boltz-2 Iteration at the NS5 sampling width.

The Run is the seam. One Iteration scores 32 Candidates through a persistent
Boltz-2 Scorer worker. The test reads the event stream and the Run folder.
It does not read worker standard streams or log lines. It does not start a
Thorough Budget.
"""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
BIOSMART_SRC = REPO / "biosmart" / "src"
DEFAULT_PYTHON = REPO / ".pixi" / "envs" / "default" / "bin" / "python"
MSA = REPO / "cgflow" / "data" / "examples" / "NS5_crop.a3m"
# Pocket from configs/opt/NS5_crop_boltz_32_2000.yaml. Selected residues, not a ligand.
POCKET = ["A:16", "A:67", "A:138", "A:153", "A:184", "A:185"]
# One Iteration at the config sampling width. The checked-in Budget is 2000×32.
ITERATIONS = 1
CANDIDATES = 32
RUNS_ROOT = Path(
    os.environ.get("BIOSMART_NS5_RUNS_ROOT", "/media/backup/p2-conrad/biosmart-ns5-runs")
)
HF_CACHE = Path(os.environ.get("HF_HUB_CACHE", "/media/backup/p2-conrad/hf_cache"))
BOLTZ_CACHE = Path(os.environ.get("BOLTZ_CACHE", "/media/backup/p2-conrad/boltz_cache"))
RUN_TIMEOUT_S = 6 * 60 * 60


def test_ns5_boltz2_run_scores_one_iteration(tmp_path: Path) -> None:
    assert DEFAULT_PYTHON.is_file(), (
        "pixi default environment is not installed. Run `pixi install -e default` from the repo root."
    )
    assert MSA.is_file(), f"NS5 alignment is missing: {MSA}"
    sequence = MSA.read_text(encoding="utf-8").splitlines()[1].strip()
    assert sequence, "NS5 sequence is empty"

    runs_root = RUNS_ROOT
    runs_root.mkdir(parents=True, exist_ok=True)
    registry = tmp_path / "registry.sqlite"
    # A previous Run on this machine already cached the catalog SMILES.
    # This Scoring round must call Boltz-2, so it starts from an empty cache.
    scorer_cache = tmp_path / "scorer-cache.sqlite"
    spec_path = tmp_path / "spec.json"
    spec_path.write_text(
        json.dumps(
            {
                "scorer": "boltz2",
                "seed": 481,
                "budget": {"iterations": ITERATIONS, "candidates_per_iteration": CANDIDATES},
                "target": {"name": "NS5", "sequence": sequence, "msa": str(MSA)},
                "pocket": {"residues": POCKET},
                "library": {"id": "enamine-stock"},
            }
        )
    )

    env = os.environ.copy()
    env["PYTHONPATH"] = str(BIOSMART_SRC)
    env["BIOSMART_RUNS_ROOT"] = str(runs_root)
    env["BIOSMART_REGISTRY"] = str(registry)
    env["BIOSMART_SCORER_CACHE"] = str(scorer_cache)
    env["BIOSMART_BOLTZ_PYTHON"] = str(DEFAULT_PYTHON)
    env["HF_HUB_CACHE"] = str(HF_CACHE)
    env["HF_HOME"] = str(HF_CACHE)
    env["BOLTZ_CACHE"] = str(BOLTZ_CACHE)
    env["TMPDIR"] = os.environ.get("TMPDIR", "/media/backup/p2-conrad/tmp")
    env["PYTORCH_CUDA_ALLOC_CONF"] = "max_split_size_mb:512"

    completed = subprocess.run(
        [str(DEFAULT_PYTHON), "-m", "biosmart", "run", str(spec_path)],
        cwd=REPO,
        env=env,
        capture_output=True,
        text=True,
        timeout=RUN_TIMEOUT_S,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    run_folder = Path(completed.stdout.strip())
    assert run_folder.is_dir()
    assert runs_root.resolve() in run_folder.resolve().parents

    events = [
        json.loads(line)
        for line in (run_folder / "events.jsonl").read_text().splitlines()
        if line.strip()
    ]
    assert events[0]["type"] == "run.started"
    assert events[0]["scorer"] == "boltz2"
    assert events[0]["iterations"] == ITERATIONS
    assert events[0]["candidates_per_iteration"] == CANDIDATES
    assert events[-1]["type"] == "run.finished"

    finished = [event for event in events if event["type"] == "round.finished"]
    assert len(finished) == 1
    assert finished[0]["n_sent"] == CANDIDATES
    assert finished[0]["scorer"] == "boltz2"
    assert finished[0]["eta_seconds"] == 0
    assert finished[0]["n_ok"] >= 1

    candidates = [event for event in events if event["type"] == "candidate"]
    assert len(candidates) == CANDIDATES
    scored = [event for event in candidates if event["status"] == "scored"]
    assert scored
    assert all(isinstance(event["reward"], float) for event in scored)

    provenance = json.loads((run_folder / "provenance.json").read_text())
    assert provenance["scorer"] == "boltz2"
    assert provenance["pocket"]["residues"] == POCKET
    assert provenance["model_loads"] == 2
    assert provenance["prediction_calls"] == 2
    assert provenance["interpreter"].endswith(".pixi/envs/default/bin/python")
    assert "conda" not in provenance["interpreter"]
    assert isinstance(provenance["gpu"], str) and "3090" in provenance["gpu"]

    pocket = json.loads((run_folder / "pocket.json").read_text())
    assert pocket["residues"] == POCKET

    affinity_files = sorted(run_folder.rglob("affinity_*.json"))
    assert affinity_files, "Run folder has no Boltz-2 affinity prediction"
    prediction = json.loads(affinity_files[0].read_text())
    assert isinstance(prediction.get("affinity_pred_value"), (int, float))

    with sqlite3.connect(run_folder / "run.sqlite") as run_db:
        count = run_db.execute("SELECT COUNT(*) FROM candidates").fetchone()
        rounds = run_db.execute("SELECT n_sent, secs FROM scoring_rounds").fetchall()
    assert count == (CANDIDATES,)
    assert len(rounds) == 1
    assert rounds[0][0] == CANDIDATES
    assert rounds[0][1] > 0
