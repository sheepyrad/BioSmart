#!/usr/bin/env python
"""
Event-driven pipeline runner.

This script wires together:
- DB initialization and simple durable task queue (LISTEN/NOTIFY)
- Long-running workers for generation, retrosynthesis, medchem, boltz-2, and docking

Notes
- External tools are invoked via utils.environment_manager.env_manager
- This is a first functional scaffold; refine batching/concurrency as needed
"""

from __future__ import annotations

import json
import os
import signal
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

import logging

from utils.logging_utils import setup_logging
from utils.db import DB
from utils.environment_manager import env_manager
from utils.molecule_processing import extract_smiles_from_sdf
from utils.molecule_processing import smiles_to_sdf

from utils.retrosynformer import run_retrosynthesis
from utils.retro_utils import extract_variants_from_retrosynthesis
from utils.medchem_filter import filter_by_pass_count, generate_filter_plots
from utils.boltz_filter import boltz_filter_variants
from utils.redocking import redock_compound


logger = logging.getLogger("event_pipeline")


# --------------------------- Config helpers ---------------------------

import argparse
import yaml


@dataclass
class PipelineConfig:
    db_url: str
    outputs_root: Path
    target_unique: int
    generator_name: str
    n_samples: int
    # DiffSBDD
    diffsbdd_checkpoint: Optional[str]
    diffsbdd_resi_list: Optional[List[str]]
    diffsbdd_sanitize: bool
    pdbfile: Optional[str]
    # Pocket2Mol
    p2m_center: Optional[List[float]]
    p2m_bbox_size: Optional[float]
    p2m_out_dir: Optional[str]
    # CGFlow
    cgflow_config: Optional[str]
    cgflow_checkpoint: Optional[str]
    cgflow_out_dir: Optional[str]
    # Retrosynthesis
    score_threshold: float
    retro_timeout: int
    retro_top_n: int
    # Medchem
    medchem_rule_threshold: int
    medchem_structural_threshold: int
    medchem_batch_size: int
    medchem_batch_timeout: int
    # Boltz
    boltz_pocket_residues: Optional[List[int]]
    # Docking
    unidock_search_mode: str
    unidock_batch_size: int
    unidock_center: List[float]
    unidock_box_size: List[int]
    # Concurrency
    generator_workers: int
    retrosyn_workers: int
    medchem_workers: int
    boltz_workers: int
    docking_workers: int


def _get(d: dict, path: str, default=None):
    cur = d
    for part in path.split('.'):
        if not isinstance(cur, dict) or part not in cur:
            return default
        cur = cur[part]
    return cur


def load_config_from_yaml(config_path: Path) -> PipelineConfig:
    with open(config_path, 'r') as f:
        y = yaml.safe_load(f) or {}

    db_url = y.get('db_url')
    if not db_url:
        raise RuntimeError("'db_url' is required in YAML config")

    outputs_root = Path(y.get('outputs_root', 'outputs')).absolute()
    target_unique = int(y.get('target_unique', 1000))

    gen = y.get('generator', {}) or {}
    generator_name = gen.get('name', 'diffsbdd')
    n_samples = int(gen.get('n_samples', 200))

    diffsbdd = gen.get('diffsbdd', {}) or {}
    diffsbdd_checkpoint = diffsbdd.get('checkpoint')
    diffsbdd_resi_list = diffsbdd.get('resi_list') or []
    diffsbdd_sanitize = bool(diffsbdd.get('sanitize', True))
    pdbfile = _get(y, 'generator.common.pdbfile') or y.get('pdbfile')  # allow top-level fallback

    p2m = gen.get('pocket2mol', {}) or {}
    p2m_center = p2m.get('center')
    p2m_bbox_size = p2m.get('bbox_size')
    p2m_out_dir = p2m.get('out_dir')

    cgflow = gen.get('cgflow', {}) or {}
    cgflow_config = cgflow.get('config_path')
    cgflow_checkpoint = cgflow.get('checkpoint_path')
    cgflow_out_dir = cgflow.get('out_dir')

    thresholds = y.get('thresholds', {}) or {}
    score_threshold = float(thresholds.get('score_threshold', 0.7))
    medchem_rule_threshold = int(thresholds.get('medchem_rule_threshold', 13))
    medchem_structural_threshold = int(thresholds.get('medchem_structural_threshold', 27))

    timeouts = y.get('timeouts', {}) or {}
    retro_timeout = int(timeouts.get('retrosynthesis_sec', 300))

    retrosynthesis_cfg = y.get('retrosynthesis', {}) or {}
    retro_top_n = int(retrosynthesis_cfg.get('top_n', 5))

    medchem = y.get('medchem', {}) or {}
    medchem_batch_size = int(medchem.get('batch_size', 256))
    medchem_batch_timeout = int(medchem.get('batch_timeout_sec', 5))

    boltz = y.get('boltz', {}) or {}
    boltz_pocket_residues = boltz.get('pocket_residues')

    unidock = y.get('unidock', {}) or {}
    unidock_search_mode = unidock.get('search_mode', 'balance')
    unidock_batch_size = int(unidock.get('batch_size', 1200))
    unidock_center = unidock.get('center', [114.817, 75.602, 82.416])
    unidock_box_size = unidock.get('box_size', [38, 70, 58])

    conc = y.get('concurrency', {}) or {}
    generator_workers = int(conc.get('generator_workers', 1))
    retrosyn_workers = int(conc.get('retrosyn_workers', 1))
    medchem_workers = int(conc.get('medchem_workers', 1))
    boltz_workers = int(conc.get('boltz_workers', 1))
    docking_workers = int(conc.get('docking_workers', 1))

    return PipelineConfig(
        db_url=db_url,
        outputs_root=outputs_root,
        target_unique=target_unique,
        generator_name=generator_name,
        n_samples=n_samples,
        diffsbdd_checkpoint=diffsbdd_checkpoint,
        diffsbdd_resi_list=diffsbdd_resi_list,
        diffsbdd_sanitize=diffsbdd_sanitize,
        pdbfile=pdbfile,
        p2m_center=p2m_center,
        p2m_bbox_size=p2m_bbox_size,
        p2m_out_dir=p2m_out_dir,
        cgflow_config=cgflow_config,
        cgflow_checkpoint=cgflow_checkpoint,
        cgflow_out_dir=cgflow_out_dir,
        score_threshold=score_threshold,
        retro_timeout=retro_timeout,
        retro_top_n=retro_top_n,
        medchem_rule_threshold=medchem_rule_threshold,
        medchem_structural_threshold=medchem_structural_threshold,
        medchem_batch_size=medchem_batch_size,
        medchem_batch_timeout=medchem_batch_timeout,
        boltz_pocket_residues=boltz_pocket_residues,
        unidock_search_mode=unidock_search_mode,
        unidock_batch_size=unidock_batch_size,
        unidock_center=unidock_center,
        unidock_box_size=unidock_box_size,
        generator_workers=generator_workers,
        retrosyn_workers=retrosyn_workers,
        medchem_workers=medchem_workers,
        boltz_workers=boltz_workers,
        docking_workers=docking_workers,
    )


stop_event = threading.Event()


def _graceful_shutdown(signum, frame):
    logger.info("Shutdown signal received. Stopping workers...")
    stop_event.set()


for sig in (signal.SIGINT, signal.SIGTERM):
    signal.signal(sig, _graceful_shutdown)


# --------------------------- Workers ---------------------------

def generator_worker(db: DB, cfg: PipelineConfig, worker_id: int) -> None:
    """Continuously generate molecules until target_unique reached; enqueue retrosynthesis tasks."""
    logger.info(f"[generator-{worker_id}] started")
    from utils.ligand_generation import run_ligand_generation, combine_pocket2mol_outputs
    from utils.molecule_processing import extract_smiles_from_sdf
    from rdkit import Chem

    outputs_dir = cfg.outputs_root / "generator"
    outputs_dir.mkdir(parents=True, exist_ok=True)

    def to_inchikey(smiles: str) -> Optional[str]:
        try:
            mol = Chem.MolFromSmiles(smiles)
            if not mol:
                return None
            return Chem.inchi.MolToInchiKey(mol)
        except Exception:
            return None

    generation = 1
    while not stop_event.is_set():
        current = db.count_unique_molecules()
        if current >= cfg.target_unique:
            logger.info(f"[generator-{worker_id}] target reached: {current} >= {cfg.target_unique}")
            time.sleep(5)
            continue

        base_name = f"gen_{int(time.time())}"
        out_dir = outputs_dir / base_name
        out_dir.mkdir(parents=True, exist_ok=True)

        if cfg.generator_name.lower() == "pocket2mol":
            # Pocket2Mol emits a directory; combine to SDF
            run_ligand_generation(
                model="pocket2mol",
                pdbfile=cfg.pdbfile,
                center=cfg.p2m_center,
                bbox_size=cfg.p2m_bbox_size,
                out_dir=str(out_dir),
                n_samples=cfg.n_samples,
                log_callback=logger.info,
            ).join()
            sdf_path = out_dir / "combined.sdf"
            combine_pocket2mol_outputs(out_dir, sdf_path)
        elif cfg.generator_name.lower() == "cgflow":
            run_ligand_generation(
                model="cgflow",
                checkpoint=cfg.cgflow_checkpoint,
                cgflow_config=cfg.cgflow_config,
                out_dir=str(out_dir),
                n_samples=cfg.n_samples,
                log_callback=logger.info,
            ).join()
            # try to use samples.sdf
            sdf_path = out_dir / "samples.sdf"
        else:
            sdf_path = out_dir / "generated.sdf"
            run_ligand_generation(
                model="diffsbdd",
                checkpoint=cfg.diffsbdd_checkpoint,
                pdbfile=cfg.pdbfile,
                outfile=str(sdf_path),
                resi_list=cfg.diffsbdd_resi_list.split() if cfg.diffsbdd_resi_list else None,
                n_samples=cfg.n_samples,
                sanitize=cfg.diffsbdd_sanitize,
                log_callback=logger.info,
            ).join()

        if not sdf_path.exists() or sdf_path.stat().st_size == 0:
            logger.warning(f"[generator-{worker_id}] no molecules produced at {sdf_path}")
            continue

        compounds = extract_smiles_from_sdf(sdf_path)
        inserted = 0
        for idx, comp in enumerate(compounds, 1):
            smiles = comp.get("smiles")
            inchikey = to_inchikey(smiles) if smiles else None
            if not smiles or not inchikey:
                continue
            m_id = db.upsert_molecule(
                smiles=smiles,
                inchikey=inchikey,
                generation=generation,
                barcode=f"GEN-{worker_id}-{idx:05d}",
                source="AI_GENERATION",
            )
            if m_id:
                inserted += 1
                db.enqueue_task("retrosynthesis", {"molecule_id": m_id})
        logger.info(f"[generator-{worker_id}] inserted {inserted} new molecules")


def retrosyn_worker(db: DB, cfg: PipelineConfig, worker_id: int) -> None:
    logger.info(f"[retrosyn-{worker_id}] started")
    for _ in db.listen(["retrosynthesis"]):
        if stop_event.is_set():
            break
        jobs = db.dequeue("retrosynthesis", limit=1)
        if not jobs:
            continue
        task_id, payload = jobs[0]
        try:
            molecule_id = int(payload["molecule_id"])  # type: ignore
            mol = db.get_molecule(molecule_id)
            if not mol:
                raise RuntimeError(f"molecule {molecule_id} not found")

            smiles = mol["smiles"]
            outputs_dir = cfg.outputs_root / "retrosyn" / f"mol_{molecule_id}"
            outputs_dir.mkdir(parents=True, exist_ok=True)
            out_csv = outputs_dir / "retrosyn.csv"

            ok = run_retrosynthesis(smiles, out_csv, timeout=cfg.retro_timeout)
            variants = []
            if ok:
                variants = extract_variants_from_retrosynthesis(out_csv, max_variants=cfg.retro_top_n)
            kept_ids: List[int] = []
            for v in variants:
                v_score = v.get("score")
                if v_score is None or v_score < cfg.score_threshold:
                    continue
                vid = db.insert_variant(
                    molecule_id=molecule_id,
                    smiles=v.get("smiles"),
                    score=v_score,
                    status="PASSSCORE",
                    barcode=v.get("barcode"),
                )
                kept_ids.append(vid)
            if kept_ids:
                db.enqueue_task("medchem", {"variant_ids": kept_ids})
            db.complete_task(task_id)
        except Exception as e:
            logger.exception("retrosynthesis task failed")
            db.fail_task(task_id, str(e))


def medchem_worker(db: DB, cfg: PipelineConfig, worker_id: int) -> None:
    logger.info(f"[medchem-{worker_id}] started")
    buffer: List[int] = []
    last_flush = time.time()
    for _ in db.listen(["medchem"]):
        if stop_event.is_set():
            break
        # drain queue
        jobs = db.dequeue("medchem", limit=cfg.medchem_batch_size)
        for task_id, payload in jobs:
            try:
                buffer.extend([int(x) for x in payload.get("variant_ids", [])])
                db.complete_task(task_id)
            except Exception as e:
                db.fail_task(task_id, str(e))

        if not buffer:
            # periodic flush
            if time.time() - last_flush > cfg.medchem_batch_timeout:
                last_flush = time.time()
            continue

        if len(buffer) >= cfg.medchem_batch_size or (time.time() - last_flush) >= cfg.medchem_batch_timeout:
            batch = buffer[: cfg.medchem_batch_size]
            buffer = buffer[cfg.medchem_batch_size :]
            last_flush = time.time()
            try:
                variants = db.get_variants(batch)
                if not variants:
                    continue
                filtered, df = filter_by_pass_count(
                    input_variants=variants,
                    rule_threshold=cfg.medchem_rule_threshold,
                    structural_threshold=cfg.medchem_structural_threshold,
                    smiles_key="smiles",
                )
                plots_dir = cfg.outputs_root / "medchem" / f"batch_{int(time.time())}"
                generate_filter_plots(df, plots_dir)

                filtered_ids = set(v["id"] for v in filtered if "id" in v)

                # Persist results per variant
                for row in variants:
                    vid = int(row["id"])  # type: ignore
                    passed = vid in filtered_ids
                    # Build a compact flags dict
                    filter_flags_json = {}
                    if df is not None and not df.empty:
                        try:
                            rec = df[df["smiles"] == row["smiles"]].iloc[0].to_dict()
                            # remove heavy fields
                            rec.pop("mol", None)
                            filter_flags_json = {k: bool(v) for k, v in rec.items() if isinstance(v, (bool, int))}
                        except Exception:
                            filter_flags_json = {}
                    db.upsert_medchem_results(
                        variant_id=vid,
                        payload={
                            "n_rules_pass": int(df.loc[df["smiles"] == row["smiles"], "n_rules_pass"].iloc[0]) if df is not None and not df.empty else None,
                            "n_structural_pass": int(df.loc[df["smiles"] == row["smiles"], "n_structural_pass"].iloc[0]) if df is not None and not df.empty else None,
                            "rule_threshold": cfg.medchem_rule_threshold,
                            "structural_threshold": cfg.medchem_structural_threshold,
                            "filter_flags_json": filter_flags_json,
                            "passed_rule_names": None,
                            "failed_rule_names": None,
                            "passed_structural_names": None,
                            "failed_structural_names": None,
                            "plots_json": {"dir": str(plots_dir)},
                            "passed": passed,
                        },
                    )
                    db.update_variant_status(vid, "PASSFILTER" if passed else "FAILFILTER")

                passed_ids = [int(v["id"]) for v in variants if int(v["id"]) in filtered_ids]
                if passed_ids:
                    db.enqueue_task("boltz2", {"variant_ids": passed_ids})
            except Exception:
                logger.exception("medchem batch failed")


def boltz_worker(db: DB, cfg: PipelineConfig, worker_id: int) -> None:
    logger.info(f"[boltz-{worker_id}] started")
    for _ in db.listen(["boltz2"]):
        if stop_event.is_set():
            break
        jobs = db.dequeue("boltz2", limit=1)
        if not jobs:
            continue
        task_id, payload = jobs[0]
        try:
            variant_ids = [int(x) for x in payload.get("variant_ids", [])]
            variants = db.get_variants(variant_ids)
            if not variants:
                db.complete_task(task_id)
                continue
            # Prepare round dir per batch
            round_dir = cfg.outputs_root / "boltz2"
            round_dir.mkdir(parents=True, exist_ok=True)
            passed, failed = boltz_filter_variants(
                variants=variants,
                pdb_file=cfg.pdbfile,
                round_dir=round_dir,
                center=tuple(cfg.unidock_center),
                box_size=tuple(cfg.unidock_box_size),
                pocket_residues=cfg.boltz_pocket_residues,
                log_callback=logger.info,
            )
            # Persist all metrics available in variants
            for v in passed + failed:
                vid = int(v.get("id", 0))
                if not vid:
                    continue
                aff = {
                    k: v.get(k)
                    for k in [
                        "affinity_pred_value",
                        "affinity_probability_binary",
                        "affinity_pred_value1",
                        "affinity_probability_binary1",
                        "affinity_pred_value2",
                        "affinity_probability_binary2",
                        "screening_score",
                    ]
                }
                db.upsert_boltz2_results(
                    variant_id=vid,
                    payload={
                        **aff,
                        "pocket_residues": cfg.boltz_pocket_residues,
                        "passed": True,  # pocket-conditioned: always proceed
                    },
                )
                db.update_variant_status(vid, v.get("status", "BOLTZ2_DONE"))

            # Always proceed to docking with variants that passed MedChem (pocket-conditioned)
            to_dock_ids = [int(v.get("id")) for v in passed] if passed else [int(v.get("id")) for v in variants]
            if to_dock_ids:
                db.enqueue_task("docking", {"variant_ids": to_dock_ids})
            db.complete_task(task_id)
        except Exception as e:
            logger.exception("boltz task failed")
            db.fail_task(task_id, str(e))


def docking_worker(db: DB, cfg: PipelineConfig, worker_id: int) -> None:
    logger.info(f"[docking-{worker_id}] started")
    for _ in db.listen(["docking"]):
        if stop_event.is_set():
            break
        jobs = db.dequeue("docking", limit=1)
        if not jobs:
            continue
        task_id, payload = jobs[0]
        try:
            variant_ids = [int(x) for x in payload.get("variant_ids", [])]
            variants = db.get_variants(variant_ids)
            if not variants:
                db.complete_task(task_id)
                continue
            results_dir = cfg.outputs_root / "docking"
            results_dir.mkdir(parents=True, exist_ok=True)

            for v in variants:
                variant_id = str(v["id"])  # use string for redock_compound API
                smiles = v["smiles"]
                redock_params = (
                    cfg.unidock_center[0],
                    cfg.unidock_center[1],
                    cfg.unidock_center[2],
                    cfg.unidock_box_size[0],
                    cfg.unidock_box_size[1],
                    cfg.unidock_box_size[2],
                    cfg.unidock_search_mode,
                )
                thread, storage = redock_compound(
                    variant_id, smiles, redock_params, receptor=cfg.pdbfile, log_callback=logger.info
                )
                if not thread:
                    continue
                thread.join()
                if storage.get("status") == "success":
                    data = storage.get("data", {})
                    vdata = data.get(variant_id)
                    if vdata:
                        db.upsert_docking_results(
                            variant_id=int(variant_id),
                            payload={
                                "best_score_kcal_mol": vdata.get("docking_score"),
                                "pose_count": vdata.get("pose_count"),
                                "result_file": vdata.get("result_file"),
                                "all_scores": vdata.get("all_scores", []),
                                "search_mode": cfg.unidock_search_mode,
                            },
                        )
                        db.update_variant_status(int(variant_id), "DOCKED")
                else:
                    db.update_variant_status(int(variant_id), "DOCKFAIL")

            db.complete_task(task_id)
        except Exception as e:
            logger.exception("docking task failed")
            db.fail_task(task_id, str(e))


def run_workers(cfg: PipelineConfig) -> None:
    db = DB(cfg.db_url)
    db.init_schema()

    # spin up threads
    threads: List[threading.Thread] = []
    # Generators
    for i in range(cfg.generator_workers):
        t = threading.Thread(target=generator_worker, args=(db, cfg, i + 1), daemon=True)
        t.start()
        threads.append(t)
    # Retrosynthesis
    for i in range(cfg.retrosyn_workers):
        t = threading.Thread(target=retrosyn_worker, args=(db, cfg, i + 1), daemon=True)
        t.start()
        threads.append(t)
    # Medchem
    for i in range(cfg.medchem_workers):
        t = threading.Thread(target=medchem_worker, args=(db, cfg, i + 1), daemon=True)
        t.start()
        threads.append(t)
    # Boltz-2
    for i in range(cfg.boltz_workers):
        t = threading.Thread(target=boltz_worker, args=(db, cfg, i + 1), daemon=True)
        t.start()
        threads.append(t)
    # Docking
    for i in range(cfg.docking_workers):
        t = threading.Thread(target=docking_worker, args=(db, cfg, i + 1), daemon=True)
        t.start()
        threads.append(t)

    # Main loop
    logger.info("Workers started. Press Ctrl+C to stop.")
    try:
        while not stop_event.is_set():
            time.sleep(1)
    finally:
        logger.info("Shutting down workers...")
        stop_event.set()
        for t in threads:
            t.join(timeout=2)


def main():
    parser = argparse.ArgumentParser(description="Event-driven drug pipeline")
    parser.add_argument("--config", type=str, default="config/pipeline.yaml", help="Path to YAML config")
    args = parser.parse_args()

    cfg = load_config_from_yaml(Path(args.config))
    cfg.outputs_root.mkdir(parents=True, exist_ok=True)
    setup_logging(cfg.outputs_root)
    run_workers(cfg)


if __name__ == "__main__":
    main()


