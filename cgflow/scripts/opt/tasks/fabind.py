from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

from synthflow.utils.conda_env import run_in_conda_env


@dataclass(frozen=True)
class FabindPair:
    prot_id: str
    ligand_id: str
    smiles: str

    @property
    def sample_id(self) -> str:
        return f"{self.prot_id}_{self.ligand_id}"


@dataclass(frozen=True)
class FabindDockingArtifacts:
    smiles_csv: Path
    index_csv: Path
    preprocess_dir: Path
    output_dir: Path
    ligand_sdf_lmdb: Path
    pocket_indices_lmdb: Path
    sample_ids: list[str]


class FabindDockingRunner:
    """Thin wrapper around FABind_plus inference scripts."""

    def __init__(
        self,
        flashbind_root: Path,
        pdb_file_dir: Path,
        work_root: Path,
        ckpt_path: Path,
        *,
        conda_env: str = "fabind",
        num_threads: int = 8,
        batch_size: int = 4,
        post_optim: bool = True,
    ) -> None:
        self.flashbind_root = Path(flashbind_root)
        self.fabind_dir = self.flashbind_root / "FABind_plus" / "fabind"
        self.pdb_file_dir = Path(pdb_file_dir)
        self.work_root = Path(work_root)
        self.ckpt_path = Path(ckpt_path)
        self.conda_env = conda_env
        self.num_threads = int(num_threads)
        self.batch_size = int(batch_size)
        self.post_optim = bool(post_optim)

    def run(self, pairs: list[FabindPair], *, oracle_idx: int) -> FabindDockingArtifacts:
        if not pairs:
            raise ValueError("FABind docking requires at least one pair.")
        if not self.fabind_dir.exists():
            raise FileNotFoundError(f"FABind directory not found: {self.fabind_dir}")
        if not self.pdb_file_dir.exists():
            raise FileNotFoundError(f"PDB directory not found: {self.pdb_file_dir}")
        if not self.ckpt_path.exists():
            raise FileNotFoundError(f"FABind checkpoint not found: {self.ckpt_path}")

        batch_dir = self.work_root / f"oracle{oracle_idx}"
        preprocess_dir = batch_dir / "fabind_preprocess"
        output_dir = batch_dir / "fabind_output"
        preprocess_dir.mkdir(parents=True, exist_ok=True)
        output_dir.mkdir(parents=True, exist_ok=True)

        smiles_csv = batch_dir / "smiles.csv"
        with smiles_csv.open("w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["smiles", "ligand_id"])
            for pair in pairs:
                writer.writerow([pair.smiles, pair.ligand_id])

        index_csv = batch_dir / "data.csv"
        with index_csv.open("w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            # FABind inference expects smiles,pdb,ligand_id per row.
            writer.writerow(["smiles", "pdb", "ligand_id"])
            for pair in pairs:
                writer.writerow([pair.smiles, pair.prot_id, pair.ligand_id])

        run_in_conda_env(
            [
                "python",
                str(self.fabind_dir / "inference_preprocess_mol_confs.py"),
                "--index_csv",
                str(smiles_csv),
                "--save_mols_dir",
                str(preprocess_dir),
                "--num_threads",
                str(self.num_threads),
                "--resume",
            ],
            conda_env=self.conda_env,
            cwd=self.fabind_dir,
        )
        run_in_conda_env(
            [
                "python",
                str(self.fabind_dir / "inference_preprocess_protein.py"),
                "--pdb_file_dir",
                str(self.pdb_file_dir),
                "--save_pt_dir",
                str(preprocess_dir),
            ],
            conda_env=self.conda_env,
            cwd=self.fabind_dir,
        )

        infer_cmd = [
            "python",
            str(self.fabind_dir / "inference_regression_fabind.py"),
            "--ckpt",
            str(self.ckpt_path),
            "--batch_size",
            str(self.batch_size),
            "--write-mol-to-file",
            "--sdf-output-path-post-optim",
            str(output_dir),
            "--index-csv",
            str(index_csv),
            "--preprocess-dir",
            str(preprocess_dir),
            "--instance-id",
            str(oracle_idx),
        ]
        if self.post_optim:
            infer_cmd.append("--post-optim")
        run_in_conda_env(infer_cmd, conda_env=self.conda_env, cwd=self.fabind_dir)

        ligand_sdf_lmdb = output_dir / f"ligand_sdf_{oracle_idx}.lmdb"
        pocket_indices_lmdb = output_dir / f"pocket_indices_{oracle_idx}.lmdb"
        if not ligand_sdf_lmdb.exists():
            raise FileNotFoundError(f"Expected FABind ligand output missing: {ligand_sdf_lmdb}")
        if not pocket_indices_lmdb.exists():
            raise FileNotFoundError(f"Expected FABind pocket output missing: {pocket_indices_lmdb}")

        return FabindDockingArtifacts(
            smiles_csv=smiles_csv,
            index_csv=index_csv,
            preprocess_dir=preprocess_dir,
            output_dir=output_dir,
            ligand_sdf_lmdb=ligand_sdf_lmdb,
            pocket_indices_lmdb=pocket_indices_lmdb,
            sample_ids=[pair.sample_id for pair in pairs],
        )
