"""Headless NS5 Boltz-2 Run.

The Run is the seam. A short invocation of the existing NS5 Boltz-2 example
must leave scored candidates in the Run folder. The test reads that score
database. It does not read logs.
"""

from __future__ import annotations

import os
import sqlite3
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
CGFLOW = REPO / "cgflow"
CONFIG = CGFLOW / "configs" / "opt" / "NS5_crop_boltz_32_2000.yaml"
DEFAULT_PYTHON = REPO / ".pixi" / "envs" / "default" / "bin" / "python"
DEFAULT_BIN = DEFAULT_PYTHON.parent
LIBRARY = Path(
    os.environ.get(
        "BIOSMART_NS5_ENV_DIR",
        "/media/data/conrad_hku/cache/cgflow_env/envs/enamine_stock",
    )
)
# One Iteration and one Candidate. The checked-in config is 2000×32.
NUM_STEPS = "1"
NUM_SAMPLING_PER_STEP = "1"
RUN_TIMEOUT_S = 90 * 60


def test_ns5_boltz2_run_records_scored_candidates(tmp_path: Path) -> None:
    assert CONFIG.is_file(), f"NS5 Boltz-2 config is missing: {CONFIG}"
    assert DEFAULT_PYTHON.is_file(), (
        "pixi default environment is not installed. Run `pixi install` from the repo root."
    )
    assert LIBRARY.is_dir(), (
        "Building-block library is missing at "
        f"{LIBRARY}. Set BIOSMART_NS5_ENV_DIR to a library with workflow.yaml and blocks/."
    )

    result_dir = tmp_path / "run"
    env = os.environ.copy()
    env["PATH"] = str(DEFAULT_BIN) + os.pathsep + env.get("PATH", "")
    env["HF_HUB_CACHE"] = os.environ.get("HF_HUB_CACHE", "/media/data/conrad_hku/hf_cache")

    subprocess.run(
        [
            str(DEFAULT_PYTHON),
            "scripts/opt/opt_boltz.py",
            "--config",
            str(CONFIG),
            "--result_dir",
            str(result_dir),
            "--env_dir",
            str(LIBRARY),
            "--num_steps",
            NUM_STEPS,
            "--num_sampling_per_step",
            NUM_SAMPLING_PER_STEP,
        ],
        cwd=CGFLOW,
        env=env,
        check=True,
        timeout=RUN_TIMEOUT_S,
    )

    score_dbs = sorted(result_dir.rglob("boltz_scores_*.db"))
    assert score_dbs, f"Run folder has no Boltz score database under {result_dir}"

    rows: list[tuple[str, float]] = []
    for db_path in score_dbs:
        with sqlite3.connect(db_path) as conn:
            rows.extend(
                conn.execute("SELECT smiles, affinity_ensemble FROM results").fetchall()
            )

    assert rows, "Boltz score database has no candidates"
    smiles, affinity = rows[0]
    assert isinstance(smiles, str) and smiles.strip(), "scored candidate is missing a SMILES string"
    assert isinstance(affinity, float), "scored candidate is missing an affinity"
