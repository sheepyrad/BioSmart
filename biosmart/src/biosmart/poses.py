"""Pose providers.

FlashBind's Pose provider is FABind+. FABind+ is not a Scorer: it has no
prepare, score, or flush. It only produces a Candidate's 3D pose.
"""

from __future__ import annotations

import csv
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from biosmart.libraries import find_repo_root
from biosmart.spec import PocketSpec, TargetSpec


class PoseProviderError(Exception):
    """The Pose provider could not produce poses for this Scoring round."""


@dataclass(frozen=True)
class Pose:
    candidate_id: str
    canonical_smiles: str
    ligand_id: str
    pose_path: Path


@dataclass(frozen=True)
class PoseRound:
    poses: list[Pose]
    ligand_lmdb: Path
    pocket_indices_lmdb: Path
    protein_id: str


class PoseProvider(Protocol):
    name: str

    def poses(
        self,
        *,
        target: TargetSpec,
        pocket: PocketSpec,
        round_no: int,
        candidates: list[object],
        work_dir: Path,
    ) -> PoseRound:
        """Dock one Scoring round. FABind+ is the FlashBind default."""


class FABindPlus:
    """Pose provider for FlashBind. Not a Scorer the scientist picks."""

    name = "fabind+"

    def poses(
        self,
        *,
        target: TargetSpec,
        pocket: PocketSpec,
        round_no: int,
        candidates: list[object],
        work_dir: Path,
    ) -> PoseRound:
        if round_no < 1:
            raise ValueError("round_no must be >= 1")
        if not candidates:
            raise ValueError("A Scoring round needs at least one Candidate")
        if not isinstance(pocket.reference_ligand, str) or not pocket.reference_ligand:
            raise ValueError("The Pocket for FlashBind is a Reference ligand")
        if not isinstance(target.structure, str) or not target.structure:
            raise ValueError("FlashBind requires a Target structure")
        ligand = Path(pocket.reference_ligand)
        structure = Path(target.structure)
        if not ligand.is_file():
            raise FileNotFoundError(f"Reference ligand not found: {ligand}")
        if not structure.is_file():
            raise FileNotFoundError(f"Target structure not found: {structure}")

        python = environment_python("fabind")
        root = flashbind_root()
        fabind_dir = root / "FABind_plus" / "fabind"
        weights = fabind_weights(root)
        if not fabind_dir.is_dir():
            raise FileNotFoundError(f"FABind+ scripts not found: {fabind_dir}")
        if not weights.is_file():
            raise FileNotFoundError(f"FABind+ weights not found: {weights}")

        work_dir.mkdir(parents=True, exist_ok=True)
        pocket_copy = work_dir / "pocket" / ligand.name
        pocket_copy.parent.mkdir(parents=True, exist_ok=True)
        if pocket_copy.resolve() != ligand.resolve():
            shutil.copyfile(ligand, pocket_copy)
        pdb_dir = work_dir / "pdb"
        pdb_dir.mkdir(parents=True, exist_ok=True)
        protein_pdb = pdb_dir / f"{target.name}.pdb"
        if protein_pdb.resolve() != structure.resolve():
            shutil.copyfile(structure, protein_pdb)

        rows = [_candidate_row(candidate) for candidate in candidates]
        smiles_csv = work_dir / "smiles.csv"
        index_csv = work_dir / "data.csv"
        with smiles_csv.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow(["smiles", "ligand_id"])
            for _candidate_id, smiles, ligand_id in rows:
                writer.writerow([smiles, ligand_id])
        with index_csv.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow(["smiles", "pdb", "ligand_id"])
            for _candidate_id, smiles, ligand_id in rows:
                writer.writerow([smiles, target.name, ligand_id])

        preprocess_dir = work_dir / "preprocess"
        output_dir = work_dir / "output"
        preprocess_dir.mkdir(parents=True, exist_ok=True)
        output_dir.mkdir(parents=True, exist_ok=True)
        _run_fabind(
            python,
            [
                str(fabind_dir / "inference_preprocess_mol_confs.py"),
                "--index_csv",
                str(smiles_csv),
                "--save_mols_dir",
                str(preprocess_dir),
                "--num_threads",
                os.environ.get("BIOSMART_FABIND_THREADS", "8"),
                "--resume",
            ],
            cwd=fabind_dir,
        )
        _run_fabind(
            python,
            [
                str(fabind_dir / "inference_preprocess_protein.py"),
                "--pdb_file_dir",
                str(pdb_dir),
                "--save_pt_dir",
                str(preprocess_dir),
            ],
            cwd=fabind_dir,
        )
        _run_fabind(
            python,
            [
                str(fabind_dir / "inference_regression_fabind.py"),
                "--ckpt",
                str(weights),
                "--batch_size",
                "4",
                "--write-mol-to-file",
                "--sdf-output-path-post-optim",
                str(output_dir),
                "--index-csv",
                str(index_csv),
                "--preprocess-dir",
                str(preprocess_dir),
                "--instance-id",
                str(round_no),
                "--post-optim",
            ],
            cwd=fabind_dir,
        )
        ligand_lmdb = output_dir / f"ligand_sdf_{round_no}.lmdb"
        pocket_lmdb = output_dir / f"pocket_indices_{round_no}.lmdb"
        if not ligand_lmdb.exists() or not pocket_lmdb.exists():
            raise PoseProviderError("FABind+ did not write poses for this Scoring round")
        return PoseRound(
            poses=[
                Pose(
                    candidate_id=candidate_id,
                    canonical_smiles=smiles,
                    ligand_id=ligand_id,
                    pose_path=ligand_lmdb,
                )
                for candidate_id, smiles, ligand_id in rows
            ],
            ligand_lmdb=ligand_lmdb,
            pocket_indices_lmdb=pocket_lmdb,
            protein_id=target.name,
        )


def environment_python(env_name: str) -> Path:
    """Interpreter for a pixi or conda environment. FABind+ uses ``fabind``."""
    if env_name not in {"fabind", "flashaffinity"}:
        raise ValueError(f"unknown environment {env_name}")
    override_name = "BIOSMART_FABIND_PYTHON" if env_name == "fabind" else "BIOSMART_FLASHAFFINITY_PYTHON"
    override = os.environ.get(override_name, "").strip()
    if override:
        path = Path(override)
        if not path.is_file():
            raise FileNotFoundError(f"{env_name} interpreter not found: {path}")
        return path
    pixi = find_repo_root() / ".pixi" / "envs" / env_name / "bin" / "python"
    if pixi.is_file():
        return pixi
    conda = _conda_python(env_name)
    if conda is not None:
        return conda
    raise FileNotFoundError(
        f"The {env_name} environment is not installed. Install the pixi environment named {env_name}."
    )


def flashbind_root() -> Path:
    override = os.environ.get("BIOSMART_FLASHBIND_ROOT", "").strip()
    if override:
        root = Path(override)
    else:
        root = find_repo_root() / "cgflow" / "src" / "FlashBind"
    if not root.is_dir():
        raise FileNotFoundError(f"FlashBind tree not found: {root}")
    return root


def fabind_weights(root: Path) -> Path:
    override = os.environ.get("BIOSMART_FABIND_WEIGHTS", "").strip()
    if override:
        return Path(override)
    return root / "FABind_plus" / "ckpt" / "fabind_plus_best_ckpt.bin"


def _candidate_row(candidate: object) -> tuple[str, str, str]:
    candidate_id = getattr(candidate, "candidate_id", None)
    smiles = getattr(candidate, "canonical_smiles", None)
    if not isinstance(candidate_id, str) or not isinstance(smiles, str) or not candidate_id or not smiles:
        raise ValueError("Candidate is missing an id or canonical SMILES")
    return candidate_id, smiles, candidate_id


def _run_fabind(python: Path, args: list[str], *, cwd: Path) -> None:
    env = os.environ.copy()
    _preload_ijit(env)
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
    raise PoseProviderError(f"FABind+ pose provider failed (exit {completed.returncode}).\n{tail}")


def _conda_python(env_name: str) -> Path | None:
    conda = shutil.which("conda")
    bases: list[Path] = []
    if conda:
        bases.append(Path(conda).resolve().parents[1])
    conda_exe = os.environ.get("CONDA_EXE", "").strip()
    if conda_exe:
        bases.append(Path(conda_exe).resolve().parents[1])
    seen: set[Path] = set()
    for base in bases:
        if base in seen:
            continue
        seen.add(base)
        python = base / "envs" / env_name / "bin" / "python"
        if python.is_file():
            return python
    return None


def _preload_ijit(env: dict[str, str]) -> None:
    """Older FABind+ torch builds need an iJIT shim on this host."""
    stub = Path.home() / ".cache" / "synthflow" / "libittnotify_stub.so"
    if not stub.is_file():
        built = _build_ijit_stub(stub)
        if built is None:
            return
        stub = built
    existing = env.get("LD_PRELOAD", "").strip()
    env["LD_PRELOAD"] = f"{stub}:{existing}" if existing else str(stub)


def _build_ijit_stub(so_path: Path) -> Path | None:
    if shutil.which("gcc") is None:
        return None
    so_path.parent.mkdir(parents=True, exist_ok=True)
    source = """
unsigned int iJIT_GetNewMethodID(void) {
    static unsigned int i = 1U;
    return i++;
}
int iJIT_NotifyEvent(int event_type, void* event_data) {
    (void)event_type;
    (void)event_data;
    return 0;
}
int iJIT_IsProfilingActive(void) { return 0; }
"""
    with tempfile.NamedTemporaryFile("w", suffix=".c", delete=False) as handle:
        handle.write(source)
        c_path = Path(handle.name)
    try:
        completed = subprocess.run(
            ["gcc", "-shared", "-fPIC", "-o", str(so_path), str(c_path)],
            capture_output=True,
            text=True,
            check=False,
        )
    finally:
        c_path.unlink(missing_ok=True)
    if completed.returncode != 0 or not so_path.is_file():
        return None
    return so_path
