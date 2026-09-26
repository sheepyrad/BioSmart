"""FlashBind Scorer.

FlashBind scores a docked pose. Poses come from FABind+, the Pose provider.
Scoring runs in the ``flashaffinity`` environment. On glibc 2.31 that
environment's ``torch_scatter`` wheel does not import, and this Scorer
stops instead of inventing a score.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

from biosmart.pose_atoms import atoms_from_pose_record
from biosmart.poses import (
    FABindPlus,
    PoseProvider,
    PoseProviderError,
    PoseRound,
    environment_python,
    flashbind_root,
)
from biosmart.scoring import Candidate, ScoreResult, ScorerFailed
from biosmart.spec import PocketSpec, TargetSpec
from biosmart.storage import flush_scorer_cache

StackProbe = Callable[[], str | None]
PoseScorer = Callable[[int, list[Candidate], PoseRound], list[ScoreResult]]


class FlashBindScorer:
    name = "flashbind"
    version = "1"

    def __init__(
        self,
        *,
        cache_path: Path | None = None,
        work_dir: Path | None = None,
        pose_provider: PoseProvider | None = None,
        stack_probe: StackProbe | None = None,
        score_poses: PoseScorer | None = None,
    ) -> None:
        if cache_path is not None and not isinstance(cache_path, Path):
            raise TypeError("cache_path must be a Path")
        if work_dir is not None and not isinstance(work_dir, Path):
            raise TypeError("work_dir must be a Path")
        self._cache_path = cache_path
        self._work_dir = work_dir
        self.pose_provider = FABindPlus() if pose_provider is None else pose_provider
        if self.pose_provider.name != "fabind+":
            raise ValueError("FlashBind's Pose provider is FABind+")
        self._stack_probe = stack_probe
        self._score_poses = score_poses
        self._context_hash: str | None = None
        self._target: TargetSpec | None = None
        self._pocket: PocketSpec | None = None
        self._pending: list[tuple[str, float]] = []

    @property
    def pose_provider_name(self) -> str:
        return self.pose_provider.name

    def prepare(self, target: TargetSpec, pocket: PocketSpec) -> str:
        if not isinstance(target, TargetSpec) or not isinstance(pocket, PocketSpec):
            raise TypeError("prepare requires a Target and a Pocket")
        ligand_text = pocket.reference_ligand
        if not isinstance(ligand_text, str) or not ligand_text.strip() or pocket.residues:
            raise ValueError("The Pocket for FlashBind is a Reference ligand")
        if not isinstance(target.structure, str) or not target.structure.strip():
            raise ValueError("FlashBind requires a Target structure")
        ligand = Path(ligand_text)
        structure = Path(target.structure)
        if not ligand.is_file():
            raise FileNotFoundError(f"Reference ligand not found: {ligand}")
        if not structure.is_file():
            raise FileNotFoundError(f"Target structure not found: {structure}")
        digest = hashlib.sha256()
        digest.update(structure.read_bytes())
        digest.update(b"\0")
        digest.update(ligand.read_bytes())
        self._target = target
        self._pocket = pocket
        self._context_hash = f"flashbind:{self.version}:fabind+:{digest.hexdigest()}"
        if self._work_dir is not None:
            _copy_inputs(self._work_dir, structure, ligand)
        return self._context_hash

    def score(self, round_no: int, candidates: list[Candidate]) -> list[ScoreResult]:
        if round_no < 1:
            raise ValueError("round_no must be >= 1")
        if self._context_hash is None or self._target is None or self._pocket is None:
            raise ValueError("prepare before score")
        if self._work_dir is None:
            raise ValueError("FlashBind needs a Run folder")
        problem = self._stack_problem()
        if problem:
            raise ScorerFailed(problem)
        round_dir = self._work_dir / "scorer" / f"round_{round_no}"
        try:
            posed = self.pose_provider.poses(
                target=self._target,
                pocket=self._pocket,
                round_no=round_no,
                candidates=list(candidates),
                work_dir=round_dir,
            )
        except PoseProviderError as exc:
            raise ScorerFailed(str(exc)) from exc
        if self._score_poses is not None:
            results = self._score_poses(round_no, candidates, posed)
        else:
            results = score_posed_round(round_no, candidates, posed, round_dir)
        if len(results) != len(candidates):
            raise ScorerFailed("FlashBind returned a different number of scores than Candidates")
        for candidate, result in zip(candidates, results, strict=True):
            if result.candidate_id != candidate.candidate_id:
                raise ScorerFailed("FlashBind scores are not in Candidate order")
            if result.reward is not None and result.status == "scored":
                self._pending.append((result.canonical_smiles, result.reward))
        return _with_predicted_poses(results, posed)

    def flush(self) -> int:
        if self._cache_path is None or self._context_hash is None:
            written = len(self._pending)
            self._pending.clear()
            return written
        written = flush_scorer_cache(
            self._cache_path,
            scorer=self.name,
            scorer_version=self.version,
            context_hash=self._context_hash,
            entries=self._pending,
        )
        self._pending.clear()
        return written

    def _stack_problem(self) -> str | None:
        if self._stack_probe is not None:
            return self._stack_probe()
        try:
            python = environment_python("flashaffinity")
        except (OSError, ValueError) as exc:
            return str(exc)
        return flashaffinity_import_error(python)


def flashaffinity_import_error(python: Path) -> str | None:
    """None when ``torch_scatter`` imports. Otherwise the platform limitation."""
    if not isinstance(python, Path) or not python.is_file():
        raise FileNotFoundError(f"flashaffinity interpreter not found: {python}")
    completed = subprocess.run(
        [str(python), "-c", "import torch_scatter"],
        capture_output=True,
        text=True,
        check=False,
        timeout=180,
    )
    if completed.returncode == 0:
        return None
    detail = ((completed.stderr or "") + "\n" + (completed.stdout or "")).strip()
    last = detail.splitlines()[-1] if detail else "torch_scatter failed to import"
    if "GLIBC_" in detail:
        return (
            "flashaffinity cannot import torch_scatter on this glibc "
            f"(the wheel needs a newer glibc than this host). {last}"
        )
    return last


def score_posed_round(
    round_no: int,
    candidates: list[Candidate],
    posed: PoseRound,
    round_dir: Path,
) -> list[ScoreResult]:
    """Score FABind+ poses with FlashBind in the flashaffinity environment."""
    if round_no < 1:
        raise ValueError("round_no must be >= 1")
    python = environment_python("flashaffinity")
    root = flashbind_root()
    by_id = {pose.candidate_id: pose for pose in posed.poses}
    if [pose.candidate_id for pose in posed.poses] != [candidate.candidate_id for candidate in candidates]:
        raise ScorerFailed("FABind+ poses are not in Candidate order")
    ids_path = round_dir / "pose_ids.json"
    pose_keys = [f"{posed.protein_id}_{by_id[candidate.candidate_id].ligand_id}" for candidate in candidates]
    ids_path.write_text(json.dumps(pose_keys), encoding="utf-8")
    protein_repr = _protein_repr(python, root, round_dir)
    ligand_repr = _ligand_repr(python, root, round_dir, posed)
    binary = _predict(
        python,
        root,
        task="binary",
        weights=_weight_list("BIOSMART_FLASHBIND_BINARY", root / "checkpoints", "binary"),
        out_dir=round_dir / "binary",
        ids_path=ids_path,
        structure_dir=round_dir / "pdb",
        ligand_lmdb=posed.ligand_lmdb,
        pocket_indices_lmdb=posed.pocket_indices_lmdb,
        protein_repr=protein_repr,
        ligand_repr=ligand_repr,
    )
    value = _predict(
        python,
        root,
        task="value",
        weights=_weight_list("BIOSMART_FLASHBIND_VALUE", root / "checkpoints", "value"),
        out_dir=round_dir / "value",
        ids_path=ids_path,
        structure_dir=round_dir / "pdb",
        ligand_lmdb=posed.ligand_lmdb,
        pocket_indices_lmdb=posed.pocket_indices_lmdb,
        protein_repr=protein_repr,
        ligand_repr=ligand_repr,
    )
    results: list[ScoreResult] = []
    for candidate, pose_key in zip(candidates, pose_keys, strict=True):
        value_entry = value.get(pose_key)
        binary_entry = binary.get(pose_key)
        if not isinstance(value_entry, dict) or not isinstance(binary_entry, dict):
            results.append(
                ScoreResult(
                    candidate_id=candidate.candidate_id,
                    canonical_smiles=candidate.canonical_smiles,
                    status="failed",
                    reward=None,
                    failure_reason="FlashBind did not return a score",
                )
            )
            continue
        if value_entry.get("status") == "failed" or binary_entry.get("status") == "failed":
            results.append(
                ScoreResult(
                    candidate_id=candidate.candidate_id,
                    canonical_smiles=candidate.canonical_smiles,
                    status="failed",
                    reward=None,
                    failure_reason="FlashBind did not return a score",
                )
            )
            continue
        affinity = float(value_entry.get("pred_value") or 0.0)
        probability = float(binary_entry.get("binary") or 0.0)
        results.append(
            ScoreResult(
                candidate_id=candidate.candidate_id,
                canonical_smiles=candidate.canonical_smiles,
                status="scored",
                reward=_reward(affinity, probability),
            )
        )
    return results


def _with_predicted_poses(results: list[ScoreResult], posed: PoseRound) -> list[ScoreResult]:
    """Keep a pose FABind+ already wrote on the score. Do not build one."""
    by_id = {pose.candidate_id: pose for pose in posed.poses}
    attached: list[ScoreResult] = []
    for result in results:
        if result.pose:
            attached.append(result)
            continue
        record = by_id.get(result.candidate_id)
        atoms = None
        if record is not None:
            atoms = atoms_from_pose_record(record.pose_path, f"{posed.protein_id}_{record.ligand_id}")
        attached.append(result if not atoms else replace(result, pose=atoms))
    return attached


def _reward(affinity: float, probability: float) -> float:
    normalized = max(0.0, (-affinity + 2.0) / 4.0)
    return float(normalized * probability)


def _copy_inputs(work_dir: Path, structure: Path, ligand: Path) -> None:
    target_dir = work_dir / "target"
    pocket_dir = work_dir / "pocket"
    target_dir.mkdir(parents=True, exist_ok=True)
    pocket_dir.mkdir(parents=True, exist_ok=True)
    structure_dest = target_dir / structure.name
    ligand_dest = pocket_dir / ligand.name
    if structure_dest.resolve() != structure.resolve():
        shutil.copyfile(structure, structure_dest)
    if ligand_dest.resolve() != ligand.resolve():
        shutil.copyfile(ligand, ligand_dest)


def _protein_repr(python: Path, root: Path, round_dir: Path) -> Path:
    override = os.environ.get("BIOSMART_PROTEIN_REPR", "").strip()
    if override:
        path = Path(override)
        if not path.exists():
            raise ScorerFailed(f"Protein representation not found: {path}")
        return path
    prots = os.environ.get("BIOSMART_PROTS_JSON", "").strip()
    if not prots:
        raise ScorerFailed("FlashBind needs BIOSMART_PROTS_JSON or BIOSMART_PROTEIN_REPR")
    prots_path = Path(prots)
    if not prots_path.is_file():
        raise ScorerFailed(f"Protein sequence file not found: {prots_path}")
    dest = round_dir / "repr" / "esm3.lmdb"
    dest.parent.mkdir(parents=True, exist_ok=True)
    script = root / "src" / "affinity" / "data" / "repr" / "esm3.py"
    _run_flashaffinity(
        python,
        [str(script), "--input_json", str(prots_path), "--output_lmdb", str(dest)],
        cwd=root,
        pythonpath=root / "src",
    )
    if not dest.exists():
        raise ScorerFailed("FlashBind did not write a protein representation")
    return dest


def _ligand_repr(python: Path, root: Path, round_dir: Path, posed: PoseRound) -> Path:
    payload = {pose.ligand_id: pose.canonical_smiles for pose in posed.poses}
    smiles_path = round_dir / "repr" / "smiles.json"
    dest = round_dir / "repr" / "torchdrug.lmdb"
    smiles_path.parent.mkdir(parents=True, exist_ok=True)
    smiles_path.write_text(json.dumps(payload), encoding="utf-8")
    script = root / "src" / "affinity" / "data" / "repr" / "torchdrug.py"
    _run_flashaffinity(
        python,
        [
            str(script),
            "--input_json",
            str(smiles_path),
            "--output_lmdb",
            str(dest),
            "--n_jobs",
            "1",
        ],
        cwd=root,
        pythonpath=root / "src",
    )
    if not dest.exists():
        raise ScorerFailed("FlashBind did not write a ligand representation")
    return dest


def _predict(
    python: Path,
    root: Path,
    *,
    task: str,
    weights: list[Path],
    out_dir: Path,
    ids_path: Path,
    structure_dir: Path,
    ligand_lmdb: Path,
    pocket_indices_lmdb: Path,
    protein_repr: Path,
    ligand_repr: Path,
) -> dict[str, object]:
    if not weights:
        raise ScorerFailed(f"FlashBind {task} weights are missing")
    out_dir.mkdir(parents=True, exist_ok=True)
    script = root / "scripts" / "predict.py"
    _run_flashaffinity(
        python,
        [
            str(script),
            "--task",
            task,
            "--data",
            str(ids_path),
            "--structure",
            str(structure_dir),
            "--structure_type",
            "pdb",
            "--ligand",
            str(ligand_lmdb),
            "--ligand_type",
            "sdf",
            "--pocket_indices",
            str(pocket_indices_lmdb),
            "--protein_repr",
            str(protein_repr),
            "--ligand_repr",
            str(ligand_repr),
            "--distance_threshold",
            "20.0",
            "--out_dir",
            str(out_dir),
            "--devices",
            "1",
            "--accelerator",
            "gpu",
            "--num_workers",
            "0",
            "--affinity_checkpoint",
            *[str(path) for path in weights],
        ],
        cwd=root,
        pythonpath=root / "src",
    )
    result_dir = out_dir / f"affinity_results_{ids_path.stem}"
    result_file = (
        result_dir / "affinity_predictions_ensemble.json"
        if len(weights) > 1
        else result_dir / "affinity_predictions.json"
    )
    if not result_file.is_file():
        raise ScorerFailed(f"FlashBind did not write {task} scores")
    payload = json.loads(result_file.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ScorerFailed(f"FlashBind {task} scores are not an object")
    return payload


def _weight_list(env_name: str, directory: Path, prefix: str) -> list[Path]:
    override = os.environ.get(env_name, "").strip()
    if override:
        paths = [Path(part) for part in override.split(os.pathsep) if part]
    else:
        paths = sorted(directory.glob(f"{prefix}_*.ckpt")) if directory.is_dir() else []
    missing = [path for path in paths if not path.is_file()]
    if missing:
        raise ScorerFailed(f"FlashBind weights not found: {missing[0]}")
    return paths


def _run_flashaffinity(python: Path, args: list[str], *, cwd: Path, pythonpath: Path) -> None:
    env = os.environ.copy()
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = f"{pythonpath}{os.pathsep}{existing}" if existing else str(pythonpath)
    completed = subprocess.run(
        [str(python), *args],
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode == 0:
        return
    detail = ((completed.stderr or "") + "\n" + (completed.stdout or "")).strip()
    tail = detail[-4000:] if len(detail) > 4000 else detail
    if "GLIBC_" in detail:
        raise ScorerFailed(
            "flashaffinity cannot import torch_scatter on this glibc "
            f"(the wheel needs a newer glibc than this host).\n{tail}"
        )
    raise ScorerFailed(f"FlashBind scoring failed (exit {completed.returncode}).\n{tail}")
