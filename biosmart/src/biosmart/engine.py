"""Execute one Run and leave its Run folder, events, and Index."""

from __future__ import annotations

import json
import os
import shutil
import signal
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from biosmart.eta import estimate_eta_seconds
from biosmart.libraries import default_libraries_root, recorded_library
from biosmart.scoring import Candidate, FakeScorer, Scorer, ScorerFailed, candidate_smiles
from biosmart.spec import RunSpec
from biosmart.storage import (
    append_event,
    ingest_index,
    init_run_database,
    insert_candidate,
    insert_iteration,
    insert_scoring_round,
    spec_sha256,
    write_json,
)
from biosmart.worker import WorkerScorer


_STOP_REQUESTED = False
_POLICY_CHECKPOINT = Path("checkpoints") / "policy.json"
