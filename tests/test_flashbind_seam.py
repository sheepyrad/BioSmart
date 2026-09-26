"""FlashBind seam.

The host path is a FakeScorer Run: the test drives ``biosmart run`` and reads
the event stream, the Run folder, and the Index. FlashBind's Pocket is a
Reference ligand, its Pose provider is FABind+, and FABind+ cannot be selected
as a Scorer. UniDock and Vina do not implement prepare, score, and flush.
These tests do not import flashaffinity.
"""

from __future__ import annotations

import ast
import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

from biosmart.flashbind import FlashBindScorer
from biosmart.poses import FABindPlus, Pose, PoseRound
from biosmart.scoring import Candidate, ScoreResult, ScorerFailed
from biosmart.spec import SELECTABLE_SCORERS, RunSpec

REPO = Path(__file__).resolve().parents[1]
BIOSMART_SRC = REPO / "biosmart" / "src"
SCORER_METHODS = ("prepare", "score", "flush")
UNIDOCK_AND_VINA = (
    REPO / "cgflow" / "scripts" / "opt" / "tasks" / "unidock.py",
    REPO / "cgflow" / "scripts" / "opt" / "tasks" / "autodock_vina.py",
    REPO / "cgflow" / "src" / "synthflow" / "tasks" / "unidock_vina.py",
    REPO / "cgflow" / "src" / "synthflow" / "tasks" / "autodock_vina.py",
    REPO / "cgflow" / "src" / "synthflow" / "pocket_conditional" / "trainer_unidock.py",
)


def test_fakescorer_host_run_writes_events_run_folder_and_index(tmp_path: Path) -> None:
    runs_root = tmp_path / "runs"
    registry = tmp_path / "registry.sqlite"
    runs_root.mkdir()
    spec_path = tmp_path / "spec.json"
    spec_path.write_text(json.dumps(_fake_spec()))
    completed = subprocess.run(
        [sys.executable, "-m", "biosmart", "run", str(spec_path)],
        cwd=REPO,
        env=_env(runs_root, registry),
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    run_folders = [path for path in runs_root.iterdir() if path.is_dir()]
    assert len(run_folders) == 1
    run_folder = run_folders[0]
    assert (run_folder / "spec.json").is_file()
    assert (run_folder / "events.jsonl").is_file()
    assert (run_folder / "run.sqlite").is_file()
    assert (run_folder / "provenance.json").is_file()
    assert (run_folder / "run.json").is_file()

    events = _events(run_folder)
    assert events[0]["type"] == "run.started"
    assert events[-1]["type"] == "run.finished"
    assert events[0]["scorer"] == "fake"
    run_id = events[0]["run_id"]
    candidates = [event for event in events if event["type"] == "candidate"]
    assert [event["canonical_smiles"] for event in candidates] == ["CCN"]
    assert [event["status"] for event in candidates] == ["scored"]
    assert candidates[0]["reward"] == pytest.approx(-0.70)
    finished = [event for event in events if event["type"] == "round.finished"]
    assert len(finished) == 1
    assert finished[0]["n_ok"] == 1

    with sqlite3.connect(f"file:{registry}?mode=ro", uri=True) as index:
        indexed = index.execute(
            "SELECT canonical_smiles, best_score, status FROM candidate_index WHERE run_id = ?",
            (run_id,),
        ).fetchall()
    assert indexed[0][0] == "CCN"
    assert indexed[0][1] == pytest.approx(-0.70)
    assert indexed[0][2] == "scored"


def test_fabind_plus_cannot_be_selected_as_a_scorer(tmp_path: Path) -> None:
    assert "fabind+" not in SELECTABLE_SCORERS
    assert "flashbind" in SELECTABLE_SCORERS
    for name in ("fabind", "fabind+", "FABind+", "unidock", "vina"):
        payload = _fake_spec()
        payload["scorer"] = name
        with pytest.raises(ValidationError) as caught:
            RunSpec.model_validate(payload)
        text = str(caught.value)
        assert "FABind+ cannot be selected as a Scorer" in text or "UniDock and Vina are not Scorers" in text

    spec_path = tmp_path / "spec.json"
    spec_path.write_text(json.dumps({**_fake_spec(), "scorer": "fabind+"}))
    completed = subprocess.run(
        [sys.executable, "-m", "biosmart", "run", str(spec_path)],
        cwd=REPO,
        env=_env(tmp_path / "runs", tmp_path / "registry.sqlite"),
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert completed.returncode == 2
    assert "FABind+ cannot be selected as a Scorer" in completed.stderr
    assert not (tmp_path / "runs").exists()


def test_flashbind_pocket_is_a_reference_ligand(tmp_path: Path) -> None:
    residues_only = _flashbind_spec(tmp_path)
    residues_only["pocket"] = {"residues": ["A:42"]}
    with pytest.raises(ValidationError, match="The Pocket for FlashBind is a Reference ligand"):
        RunSpec.model_validate(residues_only)

    both = _flashbind_spec(tmp_path)
    both["pocket"] = {"residues": ["A:42"], "reference_ligand": both["pocket"]["reference_ligand"]}
    with pytest.raises(ValidationError, match="The Pocket for FlashBind is a Reference ligand"):
        RunSpec.model_validate(both)

    spec = RunSpec.model_validate(_flashbind_spec(tmp_path))
    assert spec.scorer == "flashbind"
    assert spec.pocket.reference_ligand
    assert spec.pocket.residues == []

    structure, ligand = _structures(tmp_path)
    scorer = FlashBindScorer(work_dir=tmp_path / "run")
    context = scorer.prepare(spec.target, spec.pocket)
    assert context.startswith("flashbind:1:fabind+:")
    assert (tmp_path / "run" / "pocket" / ligand.name).is_file()
    assert (tmp_path / "run" / "target" / structure.name).is_file()
    assert scorer.pose_provider_name == "fabind+"


def test_poses_come_from_fabind_plus(tmp_path: Path) -> None:
    scorer = FlashBindScorer(work_dir=tmp_path / "run")
    assert isinstance(scorer.pose_provider, FABindPlus)
    assert scorer.pose_provider.name == "fabind+"
    assert not _implements_scorer(scorer.pose_provider)
    assert _implements_scorer(scorer)

    provider = _RecordingProvider()
    seen: dict[str, object] = {}

    def score_poses(round_no: int, candidates: list[Candidate], posed: PoseRound) -> list[ScoreResult]:
        seen["round_no"] = round_no
        seen["provider_calls_before_score"] = provider.calls
        seen["pose_ids"] = [pose.candidate_id for pose in posed.poses]
        return [
            ScoreResult(
                candidate_id=candidate.candidate_id,
                canonical_smiles=candidate.canonical_smiles,
                status="scored",
                reward=0.25,
            )
            for candidate in candidates
        ]

    wired = FlashBindScorer(
        work_dir=tmp_path / "wired",
        pose_provider=provider,
        stack_probe=lambda: None,
        score_poses=score_poses,
    )
    spec = RunSpec.model_validate(_flashbind_spec(tmp_path))
    wired.prepare(spec.target, spec.pocket)
    candidate = Candidate("000001", 1, 1, "CCN")
    results = wired.score(1, [candidate])
    assert provider.calls == 1
    assert seen["provider_calls_before_score"] == 1
    assert seen["pose_ids"] == ["000001"]
    assert results[0].reward == pytest.approx(0.25)
    assert results[0].pose is None
    assert wired.flush() == 1


def test_flashbind_keeps_a_pose_the_provider_wrote(tmp_path: Path) -> None:
    from biosmart.pose_atoms import PoseAtom, write_pose_pdb

    pose_path = tmp_path / "predicted.pdb"
    written = (PoseAtom("C", 20.5, -1.25, 4.0), PoseAtom("O", 22.4, 0.6, 3.3))
    write_pose_pdb(pose_path, written)

    class _PosingProvider:
        name = "fabind+"

        def poses(
            self,
            *,
            target: object,
            pocket: object,
            round_no: int,
            candidates: list[object],
            work_dir: Path,
        ) -> PoseRound:
            del target, pocket, round_no, work_dir
            return PoseRound(
                poses=[
                    Pose(
                        candidate_id=str(getattr(candidate, "candidate_id")),
                        canonical_smiles=str(getattr(candidate, "canonical_smiles")),
                        ligand_id=str(getattr(candidate, "candidate_id")),
                        pose_path=pose_path,
                    )
                    for candidate in candidates
                ],
                ligand_lmdb=Path("ligand"),
                pocket_indices_lmdb=Path("pocket-indices"),
                protein_id="NS5",
            )

    def score_poses(round_no: int, candidates: list[Candidate], posed: PoseRound) -> list[ScoreResult]:
        del round_no, posed
        return [
            ScoreResult(
                candidate_id=candidate.candidate_id,
                canonical_smiles=candidate.canonical_smiles,
                status="scored",
                reward=0.25,
            )
            for candidate in candidates
        ]

    scorer = FlashBindScorer(
        work_dir=tmp_path / "run",
        pose_provider=_PosingProvider(),
        stack_probe=lambda: None,
        score_poses=score_poses,
    )
    spec = RunSpec.model_validate(_flashbind_spec(tmp_path / "flash"))
    scorer.prepare(spec.target, spec.pocket)
    results = scorer.score(1, [Candidate("000001", 1, 1, "CCN")])
    assert results[0].pose is not None
    assert [(atom.element, atom.x, atom.y, atom.z) for atom in results[0].pose] == [
        ("C", pytest.approx(20.5), pytest.approx(-1.25), pytest.approx(4.0)),
        ("O", pytest.approx(22.4), pytest.approx(0.6), pytest.approx(3.3)),
    ]


def test_broken_stack_does_not_invent_scores(tmp_path: Path) -> None:
    provider = _RecordingProvider()
    scorer = FlashBindScorer(
        work_dir=tmp_path / "run",
        pose_provider=provider,
        stack_probe=lambda: "flashaffinity cannot import torch_scatter on this glibc GLIBC_2.32",
    )
    spec = RunSpec.model_validate(_flashbind_spec(tmp_path))
    scorer.prepare(spec.target, spec.pocket)
    with pytest.raises(ScorerFailed, match="GLIBC_2.32"):
        scorer.score(1, [Candidate("000001", 1, 1, "CCN")])
    assert provider.calls == 0


def test_unidock_and_vina_do_not_implement_prepare_score_and_flush() -> None:
    for path in UNIDOCK_AND_VINA:
        assert path.is_file(), path
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in tree.body:
            if not isinstance(node, ast.ClassDef):
                continue
            methods = {item.name for item in node.body if isinstance(item, ast.FunctionDef)}
            assert not set(SCORER_METHODS) <= methods, f"{path.name}:{node.name}"


class _RecordingProvider:
    name = "fabind+"

    def __init__(self) -> None:
        self.calls = 0

    def poses(
        self,
        *,
        target: object,
        pocket: object,
        round_no: int,
        candidates: list[object],
        work_dir: Path,
    ) -> PoseRound:
        del target, pocket, work_dir
        self.calls += 1
        poses = [
            Pose(
                candidate_id=str(getattr(candidate, "candidate_id")),
                canonical_smiles=str(getattr(candidate, "canonical_smiles")),
                ligand_id=str(getattr(candidate, "candidate_id")),
                pose_path=Path("posed"),
            )
            for candidate in candidates
        ]
        return PoseRound(
            poses=poses,
            ligand_lmdb=Path("ligand"),
            pocket_indices_lmdb=Path("pocket-indices"),
            protein_id="NS5",
        )


def _implements_scorer(obj: object) -> bool:
    return all(callable(getattr(obj, name, None)) for name in SCORER_METHODS)


def _fake_spec() -> dict[str, object]:
    return {
        "scorer": "fake",
        "seed": 7,
        "budget": {"iterations": 1, "candidates_per_iteration": 1},
        "target": {"name": "ns5-fixture"},
        "pocket": {"residues": ["A:42"]},
        "library": {"id": "fixture-library"},
    }


def _structures(tmp_path: Path) -> tuple[Path, Path]:
    tmp_path.mkdir(parents=True, exist_ok=True)
    structure = tmp_path / "target.pdb"
    ligand = tmp_path / "reference-ligand.mol2"
    structure.write_text("HEADER FIXTURE\n", encoding="utf-8")
    ligand.write_text("@<TRIPOS>MOLECULE\nfixture\n", encoding="utf-8")
    return structure, ligand


def _flashbind_spec(tmp_path: Path) -> dict[str, object]:
    structure, ligand = _structures(tmp_path / "inputs")
    return {
        "scorer": "flashbind",
        "seed": 7,
        "budget": {"iterations": 1, "candidates_per_iteration": 1},
        "target": {"name": "NS5", "structure": str(structure)},
        "pocket": {"reference_ligand": str(ligand)},
        "library": {"id": "fixture-library"},
    }


def _env(runs_root: Path, registry: Path) -> dict[str, str]:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(BIOSMART_SRC)
    env["BIOSMART_RUNS_ROOT"] = str(runs_root)
    env["BIOSMART_REGISTRY"] = str(registry)
    env["CUDA_VISIBLE_DEVICES"] = ""
    env.pop("BIOSMART_WORKER", None)
    env.pop("BIOSMART_FAKE_SCORER_FAIL", None)
    return env


def _events(run_folder: Path) -> list[dict[str, object]]:
    return [
        json.loads(line)
        for line in (run_folder / "events.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
