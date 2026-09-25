from __future__ import annotations

import csv
from collections import OrderedDict
import hashlib
import json
import os
from pathlib import Path
import warnings

import medchem as mc
import numpy as np
import torch
from omegaconf import MISSING, OmegaConf
from rdkit import Chem
from rdkit.Chem import QED

from gflownet.utils import sascore
from gflownet.utils.sqlite_log import BoltzinaSQLiteLogHook
from synthflow.config import Config
from synthflow.pocket_specific.trainer import RxnFlow3DTrainer_single
from synthflow.utils.boltz_reward_cache import BoltzRewardCache
from synthflow.utils.conda_env import huggingface_cache_environ, run_in_conda_env

from .docking import BaseDockingTask
from .fabind import FabindDockingRunner, FabindPair


def _cfg_bool(value: object, *, default: bool) -> bool:
    """init_empty() leaves fields as MISSING; treat like FlashBindTaskConfig defaults."""
    if value is MISSING or value is None:
        return default
    return bool(value)


def _run_conda_repr_script(
    cmd: list[str],
    *,
    conda_env: str,
    cwd: Path,
    failure_preamble: str,
    auth_hint: str,
    hf_cache: str | None = None,
) -> None:
    """Run a repr-generation script; on failure include subprocess output and setup hints."""
    env = {**os.environ}
    if hf_cache:
        env.update(huggingface_cache_environ(hf_cache))
    proc = run_in_conda_env(
        cmd,
        conda_env=conda_env,
        cwd=cwd,
        check=False,
        capture_output=True,
        env=env,
    )
    if proc.returncode == 0:
        return
    out = ((proc.stderr or "") + "\n" + (proc.stdout or "")).strip()
    tail = out[-12000:] if len(out) > 12000 else out
    raise RuntimeError(f"{failure_preamble} (exit {proc.returncode}).\n{auth_hint}\n---\n{tail}")


class FlashBindScoringRunner:
    """Wrapper for FlashBind scripts/predict.py in vendored layout."""

    def __init__(
        self,
        *,
        flashbind_root: Path,
        conda_env: str,
        structure_dir: Path,
        protein_repr: Path,
        ligand_repr: Path,
        binary_checkpoints: list[Path],
        value_checkpoints: list[Path],
        num_workers: int = 16,
        devices: int = 1,
        accelerator: str = "gpu",
        distance_threshold: float = 20.0,
        hf_cache: str | None = None,
    ) -> None:
        self.flashbind_root = Path(flashbind_root)
        self.predict_script = self.flashbind_root / "scripts" / "predict.py"
        self.conda_env = conda_env
        self.hf_cache = hf_cache
        self.structure_dir = Path(structure_dir)
        self.protein_repr = Path(protein_repr)
        self.ligand_repr = Path(ligand_repr)
        self.binary_checkpoints = [Path(p) for p in binary_checkpoints]
        self.value_checkpoints = [Path(p) for p in value_checkpoints]
        self.num_workers = int(num_workers)
        self.devices = int(devices)
        self.accelerator = accelerator
        self.distance_threshold = float(distance_threshold)

    def run(
        self,
        *,
        oracle_dir: Path,
        sample_ids: list[str],
        ligand_lmdb: Path,
        pocket_indices_lmdb: Path,
        protein_repr: Path | None = None,
        ligand_repr: Path | None = None,
    ) -> tuple[dict[str, float], dict[str, float]]:
        if not self.predict_script.exists():
            raise FileNotFoundError(f"FlashBind predict script not found: {self.predict_script}")
        if not self.structure_dir.exists():
            raise FileNotFoundError(f"Structure directory not found: {self.structure_dir}")
        protein_repr_path = Path(protein_repr) if protein_repr is not None else self.protein_repr
        if not protein_repr_path.exists():
            raise FileNotFoundError(f"Protein repr file not found: {protein_repr_path}")
        ligand_repr_path = Path(ligand_repr) if ligand_repr is not None else self.ligand_repr
        if not ligand_repr_path.exists():
            raise FileNotFoundError(f"Ligand repr file not found: {ligand_repr_path}")

        ids_path = oracle_dir / "flashbind_ids.json"
        with ids_path.open("w", encoding="utf-8") as f:
            json.dump(sample_ids, f)

        binary_map = self._run_task(
            task="binary",
            checkpoints=self.binary_checkpoints,
            out_dir=oracle_dir / "flashbind_binary",
            ids_path=ids_path,
            ligand_lmdb=ligand_lmdb,
            pocket_indices_lmdb=pocket_indices_lmdb,
            protein_repr=protein_repr_path,
            ligand_repr=ligand_repr_path,
        )
        value_map = self._run_task(
            task="value",
            checkpoints=self.value_checkpoints,
            out_dir=oracle_dir / "flashbind_value",
            ids_path=ids_path,
            ligand_lmdb=ligand_lmdb,
            pocket_indices_lmdb=pocket_indices_lmdb,
            protein_repr=protein_repr_path,
            ligand_repr=ligand_repr_path,
        )

        affinity_scores: dict[str, float] = {}
        binary_scores: dict[str, float] = {}
        for sample_id in sample_ids:
            value_entry = value_map.get(sample_id, {})
            binary_entry = binary_map.get(sample_id, {})
            affinity_scores[sample_id] = float(value_entry.get("pred_value") or 0.0)
            binary_scores[sample_id] = float(binary_entry.get("binary") or 0.0)
        return affinity_scores, binary_scores

    def _run_task(
        self,
        *,
        task: str,
        checkpoints: list[Path],
        out_dir: Path,
        ids_path: Path,
        ligand_lmdb: Path,
        pocket_indices_lmdb: Path,
        protein_repr: Path,
        ligand_repr: Path,
    ) -> dict[str, dict]:
        if not checkpoints:
            raise ValueError(f"No checkpoints configured for task={task}")
        for ckpt in checkpoints:
            if not ckpt.exists():
                raise FileNotFoundError(f"Checkpoint not found for task={task}: {ckpt}")

        out_dir.mkdir(parents=True, exist_ok=True)
        cmd = [
            "python",
            str(self.predict_script),
            "--task",
            task,
            "--data",
            str(ids_path),
            "--structure",
            str(self.structure_dir),
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
            str(self.distance_threshold),
            "--out_dir",
            str(out_dir),
            "--devices",
            str(self.devices),
            "--accelerator",
            self.accelerator,
            "--num_workers",
            str(self.num_workers),
            "--affinity_checkpoint",
            *[str(p) for p in checkpoints],
        ]
        env = {**os.environ}
        # FlashBind scripts import `affinity` from <flashbind_root>/src.
        src_path = str(self.flashbind_root / "src")
        existing_pythonpath = env.get("PYTHONPATH", "")
        if existing_pythonpath:
            env["PYTHONPATH"] = f"{src_path}:{existing_pythonpath}"
        else:
            env["PYTHONPATH"] = src_path
        if self.hf_cache:
            env.update(huggingface_cache_environ(self.hf_cache))
        run_in_conda_env(cmd, conda_env=self.conda_env, cwd=self.flashbind_root, env=env)

        result_dir = out_dir / f"affinity_results_{ids_path.stem}"
        if len(checkpoints) > 1:
            result_file = result_dir / "affinity_predictions_ensemble.json"
        else:
            result_file = result_dir / "affinity_predictions.json"
        if not result_file.exists():
            raise FileNotFoundError(f"FlashBind output missing for task={task}: {result_file}")
        with result_file.open("r", encoding="utf-8") as f:
            raw = json.load(f)
        if not isinstance(raw, dict):
            raise ValueError(f"Unexpected prediction file format: {result_file}")
        return raw


class FlashBindTask(BaseDockingTask):
    """CGFlow task that docks with FABind+ and scores with FlashBind."""

    def __init__(self, cfg: Config):
        super().__init__(cfg)
        fb_cfg = cfg.task.flashbind

        self.flashbind_root = Path(fb_cfg.root)
        self.flashbind_work_dir = Path(cfg.log_dir) / "flashbind_oracle"
        self.flashbind_work_dir.mkdir(parents=True, exist_ok=True)
        self.protein_id = str(fb_cfg.protein_id)
        self.prots_json = Path(fb_cfg.prots_json) if fb_cfg.prots_json else None
        self.repr_n_jobs = int(fb_cfg.repr_n_jobs)
        self.auto_generate_protein_repr = _cfg_bool(fb_cfg.auto_generate_protein_repr, default=True)
        self.auto_generate_ligand_repr = _cfg_bool(fb_cfg.auto_generate_ligand_repr, default=True)
        hc = getattr(fb_cfg, "hf_cache", None) or getattr(fb_cfg, "hf_hub_cache", None)
        if hc in (None, "", MISSING):
            self.hf_cache: str | None = None
        else:
            self.hf_cache = str(Path(hc).resolve())

        self.batch_docking_scores: list[float] = []
        self.batch_flashbind_scores: list[dict[str, float]] = []
        self.batch_smiles: list[str] = []
        self.batch_iteration = None
        self._last_affinity_scores: list[float] = []
        self._last_binary_scores: list[float] = []
        self._last_lilly_masks: list[float] = []
        self._last_flashbind_scores: list[float] = []
        self._scores_ready = False

        self.fabind_runner = FabindDockingRunner(
            flashbind_root=self.flashbind_root,
            pdb_file_dir=Path(fb_cfg.pdb_dir),
            work_root=self.flashbind_work_dir,
            ckpt_path=Path(fb_cfg.fabind_checkpoint),
            conda_env=str(fb_cfg.fabind_conda_env),
            num_threads=int(fb_cfg.fabind_num_threads),
            batch_size=int(fb_cfg.fabind_batch_size),
            post_optim=_cfg_bool(fb_cfg.fabind_post_optim, default=True),
        )
        self.flashbind_runner = FlashBindScoringRunner(
            flashbind_root=self.flashbind_root,
            conda_env=str(fb_cfg.flashbind_conda_env),
            structure_dir=Path(fb_cfg.pdb_dir),
            protein_repr=Path(fb_cfg.protein_repr),
            ligand_repr=Path(fb_cfg.ligand_repr),
            binary_checkpoints=[Path(p) for p in fb_cfg.binary_checkpoints],
            value_checkpoints=[Path(p) for p in fb_cfg.value_checkpoints],
            num_workers=int(fb_cfg.num_workers),
            devices=int(fb_cfg.devices),
            accelerator=str(fb_cfg.accelerator),
            distance_threshold=float(fb_cfg.distance_threshold),
            hf_cache=self.hf_cache,
        )
        self.protein_repr_path = Path(fb_cfg.protein_repr)
        self.default_ligand_repr_path = Path(fb_cfg.ligand_repr)
        self.repr_dir = self.flashbind_work_dir / "repr"
        self.repr_dir.mkdir(parents=True, exist_ok=True)
        self.generated_protein_repr_path = self.repr_dir / "esm3.lmdb"

        cache_path = OmegaConf.select(cfg, "task.flashbind.reward_cache_path", default=None)
        if cache_path is None:
            cache_path = str(Path(cfg.log_dir) / "flashbind_reward_cache.db")
        self.reward_cache = BoltzRewardCache(cache_path)
        self._ensure_protein_repr()

    def calc_affinities(self, mols: list[Chem.Mol]) -> list[float]:
        self._ensure_flashbind_scores(mols)
        return self._last_flashbind_scores

    def _ensure_flashbind_scores(self, mols: list[Chem.Mol]) -> None:
        if self._scores_ready:
            return

        n = len(mols)
        affinity_scores = [0.0] * n
        binary_scores = [0.0] * n
        lilly_masks = [0.0] * n
        flashbind_scores = [0.0] * n
        per_item_meta: list[dict[str, float | str]] = [{"status": "failed"} for _ in range(n)]
        self.batch_docking_scores = [0.0] * n
        self.batch_smiles = [""] * n

        smiles_to_indices: dict[str, list[int]] = {}
        for idx, mol in enumerate(mols):
            if mol is None:
                continue
            try:
                smiles = Chem.MolToSmiles(mol)
            except Exception:
                continue
            self.batch_smiles[idx] = smiles
            smiles_to_indices.setdefault(smiles, []).append(idx)

        cached_results = self.reward_cache.get_hits(list(smiles_to_indices.keys()))
        uncached_smiles = [s for s in smiles_to_indices if s not in cached_results]

        # Cached: hydrate affinity/binary directly.
        for smiles, (reward, info_str) in cached_results.items():
            info = {}
            if info_str:
                try:
                    info = json.loads(info_str)
                except Exception:
                    info = {}
            affinity = float(info.get("flashbind_affinity", reward))
            binary = float(info.get("flashbind_binary", 0.0))
            lilly_mask = float(info.get("lilly_pass", 1.0))
            flashbind_score = float(info.get("flashbind_score", self._combine_flashbind_scores(affinity, binary, lilly_mask)))
            for idx in smiles_to_indices.get(smiles, []):
                affinity_scores[idx] = affinity
                binary_scores[idx] = binary
                lilly_masks[idx] = lilly_mask
                flashbind_scores[idx] = flashbind_score
                per_item_meta[idx] = {
                    "status": "success",
                    "flashbind_affinity": affinity,
                    "flashbind_binary": binary,
                    "flashbind_score": flashbind_score,
                }

        uncached_pairs: list[FabindPair] = []
        smiles_by_ligand: dict[str, str] = {}
        for smiles in uncached_smiles:
            lily_mask = self._lilly_pass(smiles)
            if lily_mask == 0.0:
                for idx in smiles_to_indices.get(smiles, []):
                    affinity_scores[idx] = 0.0
                    binary_scores[idx] = 0.0
                    lilly_masks[idx] = 0.0
                    flashbind_scores[idx] = 0.0
                    per_item_meta[idx] = {
                        "status": "lilly_fail",
                        "flashbind_affinity": 0.0,
                        "flashbind_binary": 0.0,
                        "flashbind_score": 0.0,
                    }
                continue
            ligand_id = self._ligand_id_from_smiles(smiles)
            smiles_by_ligand[ligand_id] = smiles
            uncached_pairs.append(FabindPair(prot_id=self.protein_id, ligand_id=ligand_id, smiles=smiles))

        new_cache_entries: list[tuple[str, float, str]] = []
        if uncached_pairs:
            oracle_dir = self.flashbind_work_dir / f"oracle{self.oracle_idx}"
            artifacts = self.fabind_runner.run(uncached_pairs, oracle_idx=self.oracle_idx)
            ligand_repr_path = self._ensure_ligand_repr_for_pairs(uncached_pairs, oracle_dir)
            failed_sample_ids = self._load_failed_fabind_sample_ids(artifacts.preprocess_dir)
            eligible_pairs = [p for p in uncached_pairs if p.sample_id not in failed_sample_ids]
            affinity_map: dict[str, float] = {}
            binary_map: dict[str, float] = {}
            if eligible_pairs:
                affinity_map, binary_map = self.flashbind_runner.run(
                    oracle_dir=oracle_dir,
                    sample_ids=[p.sample_id for p in eligible_pairs],
                    ligand_lmdb=artifacts.ligand_sdf_lmdb,
                    pocket_indices_lmdb=artifacts.pocket_indices_lmdb,
                    protein_repr=self.protein_repr_path,
                    ligand_repr=ligand_repr_path,
                )
            for pair in uncached_pairs:
                lilly_mask = 1.0
                if pair.sample_id in failed_sample_ids:
                    affinity = 0.0
                    binary = 0.0
                    flashbind_score = 0.0
                    smiles = pair.smiles
                    for idx in smiles_to_indices.get(smiles, []):
                        affinity_scores[idx] = affinity
                        binary_scores[idx] = binary
                        lilly_masks[idx] = lilly_mask
                        flashbind_scores[idx] = flashbind_score
                        per_item_meta[idx] = {
                            "status": "fabind_preprocess_fail",
                            "flashbind_affinity": affinity,
                            "flashbind_binary": binary,
                            "flashbind_score": flashbind_score,
                        }
                    info = json.dumps(
                        {
                            "flashbind_affinity": affinity,
                            "flashbind_binary": binary,
                            "flashbind_score": flashbind_score,
                            "lilly_pass": lilly_mask,
                            "sample_id": pair.sample_id,
                            "status": "fabind_preprocess_fail",
                        }
                    )
                    new_cache_entries.append((smiles, flashbind_score, info))
                    continue
                affinity = float(affinity_map.get(pair.sample_id, 0.0))
                binary = float(binary_map.get(pair.sample_id, 0.0))
                flashbind_score = self._combine_flashbind_scores(affinity, binary, lilly_mask)
                smiles = pair.smiles
                for idx in smiles_to_indices.get(smiles, []):
                    affinity_scores[idx] = affinity
                    binary_scores[idx] = binary
                    lilly_masks[idx] = lilly_mask
                    flashbind_scores[idx] = flashbind_score
                    per_item_meta[idx] = {
                        "status": "success",
                        "flashbind_affinity": affinity,
                        "flashbind_binary": binary,
                        "flashbind_score": flashbind_score,
                    }
                info = json.dumps(
                    {
                        "flashbind_affinity": affinity,
                        "flashbind_binary": binary,
                        "flashbind_score": flashbind_score,
                        "lilly_pass": lilly_mask,
                        "sample_id": pair.sample_id,
                    }
                )
                new_cache_entries.append((smiles, flashbind_score, info))

        if new_cache_entries:
            self.reward_cache.insert_entries(new_cache_entries)

        self._last_affinity_scores = affinity_scores
        self._last_binary_scores = binary_scores
        self._last_lilly_masks = lilly_masks
        self._last_flashbind_scores = flashbind_scores
        self.batch_flashbind_scores = [
            {
                "affinity_ensemble": float(affinity_scores[i]),
                "probability_ensemble": float(binary_scores[i]),
                "flashbind_affinity": float(affinity_scores[i]),
                "flashbind_binary": float(binary_scores[i]),
                "flashbind_score": float(flashbind_scores[i]),
                "lilly_pass": float(lilly_masks[i]),
                "status": str(per_item_meta[i].get("status", "failed")),
            }
            for i in range(n)
        ]
        self._scores_ready = True

    @staticmethod
    def _ligand_id_from_smiles(smiles: str) -> str:
        digest = hashlib.sha1(smiles.encode("utf-8")).hexdigest()[:16]
        return f"lig_{digest}"

    def _load_failed_fabind_sample_ids(self, preprocess_dir: Path) -> set[str]:
        failed_csv = preprocess_dir / "failed_molecules.csv"
        if not failed_csv.exists():
            return set()
        failed_sample_ids: set[str] = set()
        try:
            with failed_csv.open("r", encoding="utf-8", newline="") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    ligand_id = str(row.get("ligand_id", "")).strip()
                    if not ligand_id:
                        continue
                    failed_sample_ids.add(f"{self.protein_id}_{ligand_id}")
        except Exception:
            return set()
        return failed_sample_ids

    @staticmethod
    def _lilly_pass(smiles: str) -> float:
        try:
            lily_mask = mc.functional.lilly_demerit_filter(
                mols=[Chem.MolFromSmiles(smiles)],
                n_jobs=-1,
                progress=False,
                return_idx=False,
            )
            if len(lily_mask.shape) == 1 and lily_mask.shape[0] == 1:
                return float(lily_mask[0])
        except Exception:
            return 0.0
        return 0.0

    @staticmethod
    def _combine_flashbind_scores(affinity_value: float, affinity_prob: float, lily_mask: float) -> float:
        normalized_aff = max(0.0, (affinity_value * -1 + 2.0) / 4.0)
        return float(normalized_aff * affinity_prob * lily_mask)

    def _ensure_protein_repr(self) -> None:
        # Prefer explicit flag; if the fallback LMDB path is missing but prots_json can
        # build ESM3, behave like autogen (YAML lists those paths as "fallback only").
        autogen = self.auto_generate_protein_repr
        if (
            not autogen
            and not self.protein_repr_path.exists()
            and self.prots_json is not None
            and self.prots_json.exists()
        ):
            autogen = True

        if autogen:
            # Always generate into run-local result directory, never project-root paths.
            self.protein_repr_path = self.generated_protein_repr_path
            if self.protein_repr_path.exists():
                return
        elif self.protein_repr_path.exists():
            return
        else:
            raise FileNotFoundError(
                "Protein repr not found: "
                f"{self.protein_repr_path}. "
                "Place a precomputed ESM3 LMDB at that path, or set "
                "flashbind.auto_generate_protein_repr: true and flashbind.prots_json "
                "so the pipeline can run FlashBind's esm3.py."
            )

        if self.prots_json is None:
            raise FileNotFoundError(
                "Protein repr is missing and flashbind.prots_json is not configured for ESM3 generation."
            )
        if not self.prots_json.exists():
            raise FileNotFoundError(f"Configured prots_json does not exist: {self.prots_json}")

        esm3_script = self.flashbind_root / "src" / "affinity" / "data" / "repr" / "esm3.py"
        if not esm3_script.exists():
            raise FileNotFoundError(f"ESM3 repr script not found: {esm3_script}")
        self.protein_repr_path.parent.mkdir(parents=True, exist_ok=True)
        _run_conda_repr_script(
            [
                "python",
                str(esm3_script),
                "--input_json",
                str(self.prots_json),
                "--output_lmdb",
                str(self.protein_repr_path),
            ],
            conda_env=self.flashbind_runner.conda_env,
            cwd=self.flashbind_root,
            failure_preamble="ESM3 protein representation (esm3.py) failed",
            auth_hint=(
                "The ESM3 checkpoint is downloaded from Hugging Face (EvolutionaryScale/esm3-sm-open-v1). "
                "If you see 401 Unauthorized, accept the model license on the Hub, then run "
                "`huggingface-cli login` or set the environment variable HF_TOKEN. "
                "See https://huggingface.co/EvolutionaryScale/esm3-sm-open-v1"
            ),
            hf_cache=self.hf_cache,
        )
        if not self.protein_repr_path.exists():
            raise FileNotFoundError(f"Failed to generate protein repr: {self.protein_repr_path}")

    def _ensure_ligand_repr_for_pairs(self, pairs: list[FabindPair], oracle_dir: Path) -> Path:
        if not self.auto_generate_ligand_repr:
            if self.default_ligand_repr_path.exists():
                return self.default_ligand_repr_path
            # Keep runs robust when config fallback path is stale/missing.
            warnings.warn(
                "flashbind.auto_generate_ligand_repr is false, but configured ligand_repr is missing: "
                f"{self.default_ligand_repr_path}. Falling back to runtime ligand representation generation.",
                RuntimeWarning,
                stacklevel=2,
            )

        ligand_json = oracle_dir / "smiles_for_torchdrug.json"
        ligand_lmdb = self.repr_dir / f"torchdrug_oracle{self.oracle_idx}.lmdb"
        ligand_json.parent.mkdir(parents=True, exist_ok=True)
        self.repr_dir.mkdir(parents=True, exist_ok=True)

        payload = {pair.ligand_id: pair.smiles for pair in pairs}
        with ligand_json.open("w", encoding="utf-8") as f:
            json.dump(payload, f)

        torchdrug_script = self.flashbind_root / "src" / "affinity" / "data" / "repr" / "torchdrug.py"
        if not torchdrug_script.exists():
            raise FileNotFoundError(f"TorchDrug repr script not found: {torchdrug_script}")

        _run_conda_repr_script(
            [
                "python",
                str(torchdrug_script),
                "--input_json",
                str(ligand_json),
                "--output_lmdb",
                str(ligand_lmdb),
                "--n_jobs",
                str(self.repr_n_jobs),
            ],
            conda_env=self.flashbind_runner.conda_env,
            cwd=self.flashbind_root,
            failure_preamble="TorchDrug ligand representation (torchdrug.py) failed",
            auth_hint="Check the conda env has torchdrug and dependencies; see FlashBind repr docs.",
            hf_cache=self.hf_cache,
        )
        if not ligand_lmdb.exists():
            raise FileNotFoundError(f"Failed to generate ligand repr LMDB: {ligand_lmdb}")
        return ligand_lmdb


class FlashBindMOOTask(FlashBindTask):
    avg_reward_info: OrderedDict[str, float]

    def __init__(self, cfg: Config):
        super().__init__(cfg)
        self.objectives = self.cfg.task.moo.objectives
        allowed = {"flashbind", "qed", "sa", "lilly"}
        assert set(self.objectives) <= allowed, f"Invalid objectives: {set(self.objectives) - allowed}"

    def compute_rewards(self, mols: list[Chem.Mol]) -> torch.Tensor:
        self.save_pose(mols)
        self._scores_ready = False
        flat_r: list[torch.Tensor] = []
        self.avg_reward_info = OrderedDict()
        for prop in self.objectives:
            if prop == "flashbind":
                fr = self.calc_flashbind_reward(mols)
            elif prop == "qed":
                fr = self.calc_qed_reward(mols)
            elif prop == "sa":
                fr = self.calc_sa_reward(mols)
            elif prop == "lilly":
                fr = self.calc_lilly_reward(mols)
            else:
                raise NotImplementedError(f"Objective {prop} is not implemented")
            flat_r.append(fr)
            self.avg_reward_info[prop] = fr.mean().item()
        flat_rewards = torch.stack(flat_r, dim=1).prod(dim=1, keepdim=True)
        assert flat_rewards.shape[0] == len(mols)
        return flat_rewards

    def calc_flashbind_reward(self, mols: list[Chem.Mol]) -> torch.Tensor:
        self._ensure_flashbind_scores(mols)
        self.batch_affinity = self._last_flashbind_scores
        self.update_storage(mols, self._last_flashbind_scores)
        return torch.tensor(self._last_flashbind_scores, dtype=torch.float32).clip(min=1e-5)

    def calc_qed_reward(self, mols: list[Chem.Mol]) -> torch.Tensor:
        def calc_score(mol: Chem.Mol) -> float:
            try:
                return QED.qed(mol)
            except Exception:
                return 0.0

        return torch.tensor([calc_score(mol) for mol in mols])

    def calc_sa_reward(self, mols: list[Chem.Mol]) -> torch.Tensor:
        def calc_score(mol: Chem.Mol) -> float:
            try:
                return (10 - sascore.calculateScore(mol)) / 9
            except Exception:
                return 0.0

        return torch.tensor([calc_score(mol) for mol in mols])

    def calc_lilly_reward(self, mols: list[Chem.Mol]) -> torch.Tensor:
        def calc_score(mol: Chem.Mol) -> float:
            try:
                smiles = Chem.MolToSmiles(mol)
                return self._lilly_pass(smiles)
            except Exception:
                return 0.0

        return torch.tensor([calc_score(mol) for mol in mols])

    def update_storage(self, mols: list[Chem.Mol], scores: list[float]):
        smiles_list = [Chem.MolToSmiles(mol) for mol in mols if mol is not None]
        filtered_scores = [s for mol, s in zip(mols, scores, strict=False) if mol is not None]
        self.topn_affinity.update(zip(smiles_list, filtered_scores, strict=True))
        # FlashBind affinity is expected to be higher-is-better.
        topn = sorted(list(self.topn_affinity.items()), key=lambda v: v[1], reverse=True)[:1000]
        self.topn_affinity = OrderedDict(topn)


class FlashBindMOOTrainer(RxnFlow3DTrainer_single[FlashBindMOOTask]):
    def setup_task(self):
        self.task = FlashBindMOOTask(cfg=self.cfg)

    def build_training_data_loader(self):
        """Same as Boltz trainer but keeps a separate score DB."""
        from pathlib import Path

        from rxnflow.base.gflownet.sqlite_log import CustomSQLiteLogHook

        model = self._wrap_for_mp(self.sampling_model)
        replay_buffer = self._wrap_for_mp(self.replay_buffer)

        if self.cfg.replay.use:
            assert self.cfg.replay.num_from_replay != 0
            assert self.cfg.replay.num_new_samples != 0

        n_drawn = self.cfg.algo.num_from_policy
        n_replayed = self.cfg.replay.num_from_replay or n_drawn if self.cfg.replay.use else 0
        n_new_replay_samples = self.cfg.replay.num_new_samples or n_drawn if self.cfg.replay.use else None
        n_from_dataset = self.cfg.algo.num_from_dataset

        src = self.create_data_source(replay_buffer=replay_buffer)
        if n_from_dataset:
            src.do_sample_dataset(self.training_data, n_from_dataset, backwards_model=model)
        if n_drawn:
            src.do_sample_model(model, n_drawn, n_new_replay_samples)
        if n_replayed and replay_buffer is not None:
            src.do_sample_replay(n_replayed)
        if self.cfg.log_dir:
            train_dir = str(Path(self.cfg.log_dir) / "train")
            src.add_sampling_hook(CustomSQLiteLogHook(train_dir, self.ctx))
            src.add_sampling_hook(BoltzinaSQLiteLogHook(train_dir, self.task))
        for hook in self.sampling_hooks:
            src.add_sampling_hook(hook)
        return self._make_data_loader(src)

    def log(self, info, index, key):
        self.add_extra_info(info)
        super().log(info, index, key)

    def add_extra_info(self, info):
        for prop, fr in self.task.avg_reward_info.items():
            info[f"sample_r_{prop}_avg"] = fr
        if len(self.task.batch_affinity) > 0:
            info["sample_flashbind_score_avg"] = np.mean(self.task.batch_affinity)
        if len(self.task._last_binary_scores) > 0:
            info["sample_flashbind_binary_avg"] = np.mean(self.task._last_binary_scores)
        best_scores = list(self.task.topn_affinity.values())
        for topn in [10, 100, 1000]:
            if len(best_scores) > topn:
                info[f"top{topn}_flashbind_score"] = np.mean(best_scores[:topn])
