"""Resident Boltz-2 Scorer. Models load once and score the Candidates of one Scoring round.

The worker acceptor imports this module inside the pixi default process.
The engine does not.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

import yaml

from biosmart.scoring import Candidate, ScoreResult, ScorerFailed
from biosmart.spec import PocketSpec, TargetSpec

SCORER_NAME = "boltz2"


def context_hash(
    *,
    version: str,
    sequence: str,
    residues: list[str],
    msa_sha256: str,
) -> str:
    payload = json.dumps(
        {
            "scorer": SCORER_NAME,
            "version": version,
            "sequence": sequence,
            "residues": list(residues),
            "msa_sha256": msa_sha256,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode()).hexdigest()


def _sha256_file(path: Path | None) -> str:
    if path is None:
        return hashlib.sha256(b"").hexdigest()
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _contacts(residues: list[str]) -> list[list[str | int]]:
    contacts: list[list[str | int]] = []
    for residue in residues:
        if ":" not in residue:
            raise ValueError(f"Boltz-2 Pocket residue must be CHAIN:NUMBER, got {residue!r}")
        chain_id, res_id = residue.split(":", 1)
        contacts.append([chain_id.strip(), int(res_id.strip())])
    if not contacts:
        raise ValueError("Boltz-2 Pocket is selected residues")
    return contacts


def _write_yaml(
    path: Path,
    *,
    sequence: str,
    smiles: str,
    residues: list[str],
    msa: Path | None,
) -> None:
    document: dict[str, Any] = {
        "sequences": [
            {"protein": {"id": "A", "sequence": sequence}},
            {"ligand": {"id": "B", "smiles": smiles}},
        ],
        "properties": [{"affinity": {"binder": "B"}}],
        "constraints": [
            {"pocket": {"binder": "B", "contacts": _contacts(residues)}},
        ],
    }
    if msa is not None:
        document["sequences"][0]["protein"]["msa"] = str(msa.resolve())

    def represent_list(dumper: yaml.SafeDumper, data: list[Any]) -> yaml.nodes.SequenceNode:
        flow = bool(data) and isinstance(data[0], list) and len(data[0]) == 2
        return dumper.represent_sequence("tag:yaml.org,2002:seq", data, flow_style=flow)

    yaml.add_representer(list, represent_list, Dumper=yaml.SafeDumper)
    path.write_text(
        yaml.dump(document, Dumper=yaml.SafeDumper, default_flow_style=False, sort_keys=False),
        encoding="utf-8",
    )


def _shaped_reward(summary: dict[str, Any]) -> float:
    """Same shaping the CGFlow Boltz-2 task maximises. Higher is better."""
    if "affinity_pred_value1" in summary:
        value = float(summary["affinity_pred_value1"])
        probability = float(summary["affinity_probability_binary1"])
    else:
        value = float(summary["affinity_pred_value"])
        probability = float(summary["affinity_probability_binary"])
    normalized = max(0.0, (-value + 2.0) / 4.0)
    return float(normalized * probability)


class Boltz2Resident:
    """Boltz-2 structure and affinity models kept for the life of the worker."""

    def __init__(self) -> None:
        self.version = ""
        self.model_loads = 0
        self.prediction_calls = 0
        self.gpu: str | None = None
        self._structure: Any = None
        self._affinity: Any = None
        self._cache: Path | None = None
        self._diffusion: Any = None
        self._pairformer: Any = None
        self._msa_args: Any = None
        self._prepared = False
        self._sequence = ""
        self._residues: list[str] = []
        self._msa: Path | None = None
        self._work_dir: Path | None = None
        self._seed: int | None = None

    def prepare(self, request: dict[str, Any]) -> dict[str, Any]:
        import torch
        from importlib.metadata import version

        target = request["target"]
        pocket = request["pocket"]
        sequence = str(target["sequence"]).strip()
        residues = [str(residue) for residue in pocket["residues"]]
        if not sequence:
            raise ValueError("Boltz-2 Target needs a sequence")
        _contacts(residues)
        msa_value = target.get("msa")
        msa = Path(msa_value) if msa_value else None
        if msa is not None and not msa.is_file():
            raise FileNotFoundError(f"Target MSA not found: {msa}")
        cache = Path(request["cache_dir"])
        work_dir = Path(request["work_dir"])
        work_dir.mkdir(parents=True, exist_ok=True)
        self._sequence = sequence
        self._residues = residues
        self._msa = msa
        self._work_dir = work_dir
        self._seed = int(request["seed"])
        self.version = version("boltz")
        if torch.cuda.is_available():
            self.gpu = torch.cuda.get_device_name(0)
        if not self._prepared:
            self._load(cache)
            self._prepared = True
        digest = context_hash(
            version=self.version,
            sequence=sequence,
            residues=residues,
            msa_sha256=_sha256_file(msa),
        )
        return {
            "context_hash": digest,
            "version": self.version,
            "model_loads": self.model_loads,
            "prediction_calls": self.prediction_calls,
            "gpu": self.gpu,
            "scorer": SCORER_NAME,
        }

    def score(self, request: dict[str, Any]) -> dict[str, Any]:
        if not self._prepared or self._work_dir is None:
            raise RuntimeError("Boltz-2 prepare must run before score")
        round_no = int(request["round_no"])
        if round_no < 1:
            raise ValueError("round_no must be >= 1")
        candidates = request["candidates"]
        if not isinstance(candidates, list):
            raise TypeError("candidates must be a list")
        unique: list[dict[str, Any]] = []
        seen: set[str] = set()
        for candidate in candidates:
            smiles = str(candidate["canonical_smiles"])
            if smiles not in seen:
                seen.add(smiles)
                unique.append(candidate)
        by_smiles: dict[str, dict[str, Any]] = {}
        if unique:
            by_smiles = self._predict_unique(round_no, unique)
        results = []
        for candidate in candidates:
            smiles = str(candidate["canonical_smiles"])
            found = by_smiles.get(smiles)
            if found is None:
                results.append(
                    {
                        "candidate_id": candidate["candidate_id"],
                        "canonical_smiles": smiles,
                        "status": "failed",
                        "reward": None,
                        "failure_reason": "Boltz-2 did not return a score",
                    }
                )
            else:
                results.append(
                    {
                        "candidate_id": candidate["candidate_id"],
                        "canonical_smiles": smiles,
                        "status": found["status"],
                        "reward": found["reward"],
                        "failure_reason": found["failure_reason"],
                        "raw": found["raw"],
                    }
                )
        return {"results": results, "model_loads": self.model_loads, "prediction_calls": self.prediction_calls}

    def flush(self, request: dict[str, Any]) -> dict[str, Any]:
        del request
        return {
            "model_loads": self.model_loads,
            "prediction_calls": self.prediction_calls,
            "version": self.version,
            "gpu": self.gpu,
        }

    def _load(self, cache: Path) -> None:
        import torch
        from boltz.main import (
            CCD_URL,
            Boltz2DiffusionParams,
            MSAModuleArgs,
            PairformerArgsV2,
            download_boltz2,
        )
        import urllib.request
        from boltz.model.models.boltz2 import Boltz2
        from rdkit import Chem

        torch.set_grad_enabled(False)
        torch.set_float32_matmul_precision("highest")
        Chem.SetDefaultPickleProperties(Chem.PropertyPickleOptions.AllProps)
        for key in ("CUEQ_DEFAULT_CONFIG", "CUEQ_DISABLE_AOT_TUNING"):
            import os

            os.environ[key] = os.environ.get(key, "1")
        cache.mkdir(parents=True, exist_ok=True)
        ccd = cache / "ccd.pkl"
        if not ccd.is_file():
            urllib.request.urlretrieve(CCD_URL, str(ccd))
        download_boltz2(cache)
        self._cache = cache
        self._diffusion = Boltz2DiffusionParams()
        self._diffusion.step_scale = 1.5
        self._pairformer = PairformerArgsV2()
        self._msa_args = MSAModuleArgs(
            subsample_msa=False,
            num_subsampled_msa=1024,
            use_paired_feature=True,
        )
        self._structure = self._load_checkpoint(
            Boltz2,
            cache / "boltz2_conf.ckpt",
            predict_args={
                "recycling_steps": 3,
                "sampling_steps": 200,
                "diffusion_samples": 1,
                "max_parallel_samples": None,
                "write_confidence_summary": True,
                "write_full_pae": False,
                "write_full_pde": False,
            },
            steering={"fk_steering": True, "guidance_update": True},
            affinity_mw_correction=None,
        )
        self._affinity = self._load_checkpoint(
            Boltz2,
            cache / "boltz2_aff.ckpt",
            predict_args={
                "recycling_steps": 5,
                "sampling_steps": 200,
                "diffusion_samples": 5,
                "max_parallel_samples": 1,
                "write_confidence_summary": False,
                "write_full_pae": False,
                "write_full_pde": False,
            },
            steering={"fk_steering": False, "guidance_update": False},
            affinity_mw_correction=False,
        )

    def _load_checkpoint(
        self,
        model_cls: Any,
        checkpoint: Path,
        *,
        predict_args: dict[str, Any],
        steering: dict[str, bool],
        affinity_mw_correction: bool | None,
    ) -> Any:
        import inspect

        import torch
        from boltz.main import BoltzSteeringParams

        if not checkpoint.is_file():
            raise FileNotFoundError(f"Boltz-2 weights not found: {checkpoint}")
        # Published checkpoints carry hyperparameters from a newer trainer.
        # Drop keys this Boltz-2 build does not accept, then load the matching weights.
        saved = torch.load(checkpoint, map_location="cpu", weights_only=False)
        hyperparameters = dict(saved.get("hyper_parameters") or {})
        steering_args = BoltzSteeringParams()
        steering_args.fk_steering = steering["fk_steering"]
        steering_args.guidance_update = steering["guidance_update"]
        hyperparameters.update(
            {
                "predict_args": predict_args,
                "diffusion_process_args": asdict(self._diffusion),
                "ema": False,
                "pairformer_args": asdict(self._pairformer),
                "msa_args": asdict(self._msa_args),
            }
        )
        if affinity_mw_correction is None:
            hyperparameters["use_trifast"] = True
            hyperparameters["steering_args"] = asdict(steering_args)
        else:
            hyperparameters["affinity_mw_correction"] = affinity_mw_correction
            hyperparameters["steering_args"] = {
                "fk_steering": False,
                "guidance_update": False,
            }
        allowed = set(inspect.signature(model_cls.__init__).parameters) - {"self"}
        module = model_cls(**{key: value for key, value in hyperparameters.items() if key in allowed})
        module.load_state_dict(saved["state_dict"], strict=True)
        module.eval()
        self.model_loads += 1
        return module

    def _predict_unique(self, round_no: int, unique: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
        assert self._work_dir is not None
        round_dir = self._work_dir / f"round-{round_no:04d}"
        inputs = round_dir / "inputs"
        inputs.mkdir(parents=True, exist_ok=True)
        stems: dict[str, str] = {}
        for candidate in unique:
            stem = str(candidate["candidate_id"])
            smiles = str(candidate["canonical_smiles"])
            stems[smiles] = stem
            _write_yaml(
                inputs / f"{stem}.yaml",
                sequence=self._sequence,
                smiles=smiles,
                residues=self._residues,
                msa=self._msa,
            )
        out_dir = self._run_predict(inputs, round_dir / "out")
        found: dict[str, dict[str, Any]] = {}
        for smiles, stem in stems.items():
            summary = _read_affinity(out_dir, stem)
            if summary is None:
                found[smiles] = {
                    "status": "failed",
                    "reward": None,
                    "failure_reason": "Boltz-2 affinity file is missing",
                    "raw": None,
                }
                continue
            found[smiles] = {
                "status": "scored",
                "reward": _shaped_reward(summary),
                "failure_reason": None,
                "raw": summary,
            }
        return found

    def _run_predict(self, inputs: Path, out_parent: Path) -> Path:
        """One structure pass and one affinity pass on the resident models."""
        import torch
        from boltz.data.module.inferencev2 import Boltz2InferenceDataModule
        from boltz.data.write.writer import BoltzAffinityWriter, BoltzWriter
        from boltz.main import (
            BoltzProcessedInput,
            check_inputs,
            filter_inputs_affinity,
            filter_inputs_structure,
            process_inputs,
        )
        from pytorch_lightning import Trainer, seed_everything

        if self._seed is not None:
            seed_everything(self._seed, workers=True)
        cache = self._cache
        if cache is None or self._structure is None or self._affinity is None:
            raise RuntimeError("Boltz-2 models are not loaded")
        out_parent.mkdir(parents=True, exist_ok=True)
        out_dir = out_parent / f"boltz_results_{inputs.name}"
        out_dir.mkdir(parents=True, exist_ok=True)
        data = check_inputs(inputs)
        mol_dir = cache / "mols"
        manifest = process_inputs(
            data=data,
            out_dir=out_dir,
            ccd_path=cache / "ccd.pkl",
            mol_dir=mol_dir,
            use_msa_server=False,
            msa_server_url="https://api.colabfold.com",
            msa_pairing_strategy="greedy",
            boltz2=True,
            preprocessing_threads=1,
            max_msa_seqs=8192,
        )
        filtered = filter_inputs_structure(manifest=manifest, outdir=out_dir, override=False)
        processed_dir = out_dir / "processed"
        processed = BoltzProcessedInput(
            manifest=filtered,
            targets_dir=processed_dir / "structures",
            msa_dir=processed_dir / "msa",
            constraints_dir=processed_dir / "constraints" if (processed_dir / "constraints").exists() else None,
            template_dir=processed_dir / "templates" if (processed_dir / "templates").exists() else None,
            extra_mols_dir=processed_dir / "mols" if (processed_dir / "mols").exists() else None,
        )
        if filtered.records:
            writer = BoltzWriter(
                data_dir=processed.targets_dir,
                output_dir=out_dir / "predictions",
                output_format="pdb",
                boltz2=True,
            )
            trainer = _trainer(out_dir, writer)
            data_module = Boltz2InferenceDataModule(
                manifest=processed.manifest,
                target_dir=processed.targets_dir,
                msa_dir=processed.msa_dir,
                mol_dir=mol_dir,
                num_workers=0,
                constraints_dir=processed.constraints_dir,
                template_dir=processed.template_dir,
                extra_mols_dir=processed.extra_mols_dir,
            )
            self._predict_with(trainer, self._structure, data_module)
        if any(record.affinity for record in manifest.records):
            affinity_manifest = filter_inputs_affinity(manifest=manifest, outdir=out_dir, override=False)
            if affinity_manifest.records:
                writer = BoltzAffinityWriter(
                    data_dir=processed.targets_dir,
                    output_dir=out_dir / "predictions",
                )
                trainer = _trainer(out_dir, writer)
                data_module = Boltz2InferenceDataModule(
                    manifest=affinity_manifest,
                    target_dir=out_dir / "predictions",
                    msa_dir=processed.msa_dir,
                    mol_dir=mol_dir,
                    num_workers=0,
                    constraints_dir=processed.constraints_dir,
                    template_dir=processed.template_dir,
                    extra_mols_dir=processed.extra_mols_dir,
                    override_method="other",
                    affinity=True,
                )
                self._park(self._structure)
                self._predict_with(trainer, self._affinity, data_module)
                self._park(self._affinity)
        return out_dir

    def _predict_with(self, trainer: Any, module: Any, data_module: Any) -> None:
        trainer.predict(module, datamodule=data_module, return_predictions=False)
        self.prediction_calls += 1

    def _park(self, module: Any) -> None:
        import torch

        module.cpu()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()


def _trainer(out_dir: Path, writer: Any) -> Any:
    from pytorch_lightning import Trainer

    return Trainer(
        default_root_dir=out_dir,
        strategy="auto",
        callbacks=[writer],
        accelerator="gpu",
        devices=1,
        precision="bf16-mixed",
        logger=False,
        enable_checkpointing=False,
    )


class Boltz2Scorer:
    """Scorer seam around one resident Boltz-2. Loaded once per worker process."""

    name = SCORER_NAME

    def __init__(self, *, seed: int, ordinal: int, cache_dir: Path, work_dir: Path) -> None:
        del ordinal
        self.seed = seed
        self._cache_dir = cache_dir
        self._work_dir = work_dir
        self._resident = Boltz2Resident()
        self._pending: list[tuple[str, float]] = []
        self.version = "0"
        self.gpu: str | None = None
        self.model_loads = 0
        self.prediction_calls = 0

    def prepare(self, target: TargetSpec, pocket: PocketSpec) -> str:
        sequence = (target.sequence or "").strip()
        if not sequence:
            raise ValueError("Boltz-2 Target needs a sequence")
        if not pocket.residues:
            raise ValueError("Boltz-2 Pocket is selected residues")
        response = self._resident.prepare(
            {
                "target": {
                    "name": target.name,
                    "sequence": sequence,
                    "msa": target.msa,
                },
                "pocket": {"residues": list(pocket.residues)},
                "cache_dir": str(self._cache_dir),
                "work_dir": str(self._work_dir),
                "seed": self.seed,
            }
        )
        self._copy_facts(response)
        context_hash = response.get("context_hash")
        if not isinstance(context_hash, str) or not context_hash:
            raise ValueError("Boltz-2 prepare did not return a scoring context")
        return context_hash

    def score(self, round_no: int, candidates: list[Candidate]) -> list[ScoreResult]:
        try:
            response = self._resident.score(
                {
                    "round_no": round_no,
                    "candidates": [
                        {
                            "candidate_id": candidate.candidate_id,
                            "canonical_smiles": candidate.canonical_smiles,
                            "iteration": candidate.iteration,
                            "round_no": candidate.round_no,
                        }
                        for candidate in candidates
                    ],
                }
            )
        except ScorerFailed:
            raise
        except Exception as exc:
            raise ScorerFailed(str(exc)) from exc
        self._copy_facts(response)
        results: list[ScoreResult] = []
        staged: set[str] = set()
        for item in response["results"]:
            raw = item.get("raw")
            reward = item.get("reward")
            result = ScoreResult(
                candidate_id=str(item["candidate_id"]),
                canonical_smiles=str(item["canonical_smiles"]),
                status=str(item["status"]),
                reward=None if reward is None else float(reward),
                failure_reason=None if item.get("failure_reason") is None else str(item["failure_reason"]),
                raw=raw if isinstance(raw, dict) else None,
            )
            results.append(result)
            if (
                result.status == "scored"
                and result.reward is not None
                and result.canonical_smiles not in staged
            ):
                staged.add(result.canonical_smiles)
                self._pending.append((result.canonical_smiles, result.reward))
        return results

    def staged_entries(self) -> list[tuple[str, float]]:
        return list(self._pending)

    def flush(self) -> int:
        stats = self._resident.flush({})
        self._copy_facts(stats)
        written = len(self._pending)
        self._pending.clear()
        return written

    def _copy_facts(self, response: dict[str, Any]) -> None:
        version = response.get("version")
        if isinstance(version, str) and version:
            self.version = version
        gpu = response.get("gpu")
        if isinstance(gpu, str):
            self.gpu = gpu
        if "model_loads" in response:
            self.model_loads = int(response["model_loads"])
        if "prediction_calls" in response:
            self.prediction_calls = int(response["prediction_calls"])


def _read_affinity(out_dir: Path, stem: str) -> dict[str, Any] | None:
    matches = sorted(out_dir.rglob(f"affinity_{stem}.json"))
    if not matches:
        return None
    payload = json.loads(matches[0].read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or "affinity_pred_value" not in payload:
        return None
    return payload
