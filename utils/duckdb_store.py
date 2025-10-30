"""
DuckDB storage helpers for the pipeline.

This module provides a thin DAO used by the Prefect flow to persist
results in a central DuckDB database file, in parallel with existing
CSV tracking. We use `barcode` as the stable primary key for variants
and records flowing through the pipeline.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

import duckdb  # type: ignore
import pandas as pd


class DuckDBStore:
    """Simple DAO for DuckDB-backed storage.

    Notes:
    - Uses `barcode` (TEXT) as primary key for variant-scoped tables to avoid
      coupling to internal numeric IDs.
    - Stores JSON payloads as TEXT (JSON strings) for portability; DuckDB
      supports JSON, but TEXT is sufficient for our access patterns.
    """

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = str(db_path)
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)

    # ------------- Connection helpers -------------
    def _connect(self):
        return duckdb.connect(self.db_path, read_only=False)

    # ------------- Schema -------------
    def init_schema(self) -> None:
        with self._connect() as con:
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS molecules (
                    barcode TEXT PRIMARY KEY,
                    smiles TEXT,
                    generation INT,
                    status TEXT,
                    source TEXT,
                    created_at TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS variants (
                    barcode TEXT PRIMARY KEY,
                    smiles TEXT,
                    score DOUBLE,
                    status TEXT,
                    parent_id TEXT,
                    created_at TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS medchem_results (
                    barcode TEXT PRIMARY KEY,
                    n_rules_pass INT,
                    n_structural_pass INT,
                    rule_threshold INT,
                    structural_threshold INT,
                    filter_flags_json TEXT,
                    passed_rule_names TEXT,
                    failed_rule_names TEXT,
                    passed_structural_names TEXT,
                    failed_structural_names TEXT,
                    plots_json TEXT,
                    passed BOOLEAN,
                    created_at TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS chemap_results (
                    barcode TEXT,
                    smiles TEXT,
                    chemap_pred INT,
                    raw_json TEXT,
                    created_at TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS boltz2_results (
                    barcode TEXT PRIMARY KEY,
                    affinity_pred_value DOUBLE,
                    affinity_probability_binary DOUBLE,
                    affinity_pred_value1 DOUBLE,
                    affinity_probability_binary1 DOUBLE,
                    affinity_pred_value2 DOUBLE,
                    affinity_probability_binary2 DOUBLE,
                    boltz2_score DOUBLE,
                    pocket_residues TEXT,
                    created_at TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS docking_results (
                    barcode TEXT PRIMARY KEY,
                    best_score_kcal_mol DOUBLE,
                    pose_count INT,
                    result_file TEXT,
                    all_scores_json TEXT,
                    search_mode TEXT,
                    created_at TIMESTAMP
                );
                """
            )

    # ------------- Upserts / writes -------------
    def upsert_molecules(self, molecules: Iterable[Dict[str, Any]]) -> None:
        """Upsert basic molecule info (barcode, smiles, generation, status, source)."""
        rows = []
        now = datetime.utcnow()
        for m in molecules:
            rows.append(
                (
                    str(m.get("barcode", "")),
                    str(m.get("smiles", "")),
                    int(m.get("generation")) if m.get("generation") is not None else None,
                    str(m.get("status", "")),
                    str(m.get("source", "")),
                    now,
                )
            )
        if not rows:
            return
        df = pd.DataFrame(
            rows,
            columns=[
                "barcode",
                "smiles",
                "generation",
                "status",
                "source",
                "created_at",
            ],
        )
        with self._connect() as con:
            con.execute(
                """
                CREATE TEMPORARY TABLE _molecules_tmp AS SELECT * FROM df
                """,
                {"df": df},
            )
            con.execute(
                """
                INSERT INTO molecules AS t
                SELECT * FROM _molecules_tmp s
                ON CONFLICT (barcode) DO UPDATE SET
                    smiles = excluded.smiles,
                    generation = excluded.generation,
                    status = excluded.status,
                    source = excluded.source,
                    created_at = excluded.created_at
                """,
            )

    def upsert_variants(self, variants: Iterable[Dict[str, Any]]) -> None:
        """Upsert basic variant info (barcode, smiles, score, status, parent_id)."""
        rows = []
        now = datetime.utcnow()
        for v in variants:
            rows.append(
                (
                    str(v.get("barcode", "")),
                    str(v.get("smiles", "")),
                    float(v.get("score")) if v.get("score") is not None else None,
                    str(v.get("status", "")),
                    str(v.get("parent_id", "")),
                    now,
                )
            )
        if not rows:
            return
        df = pd.DataFrame(
            rows,
            columns=[
                "barcode",
                "smiles",
                "score",
                "status",
                "parent_id",
                "created_at",
            ],
        )
        with self._connect() as con:
            con.execute(
                """
                CREATE TEMPORARY TABLE _variants_tmp AS SELECT * FROM df
                """,
                {"df": df},
            )
            con.execute(
                """
                INSERT INTO variants AS t
                SELECT * FROM _variants_tmp s
                ON CONFLICT (barcode) DO UPDATE SET
                    smiles = excluded.smiles,
                    score = excluded.score,
                    status = excluded.status,
                    parent_id = excluded.parent_id,
                    created_at = excluded.created_at
                """,
            )

    def upsert_medchem_results(self, barcode_to_result: Dict[str, Dict[str, Any]]) -> None:
        rows = []
        now = datetime.utcnow()
        for barcode, payload in barcode_to_result.items():
            rows.append(
                (
                    barcode,
                    payload.get("n_rules_pass"),
                    payload.get("n_structural_pass"),
                    payload.get("rule_threshold"),
                    payload.get("structural_threshold"),
                    json.dumps(payload.get("filter_flags_json", {})),
                    ",".join(payload.get("passed_rule_names", []) or []),
                    ",".join(payload.get("failed_rule_names", []) or []),
                    ",".join(payload.get("passed_structural_names", []) or []),
                    ",".join(payload.get("failed_structural_names", []) or []),
                    json.dumps(payload.get("plots_json", {})),
                    bool(payload.get("passed")) if payload.get("passed") is not None else None,
                    now,
                )
            )
        if not rows:
            return
        df = pd.DataFrame(
            rows,
            columns=[
                "barcode",
                "n_rules_pass",
                "n_structural_pass",
                "rule_threshold",
                "structural_threshold",
                "filter_flags_json",
                "passed_rule_names",
                "failed_rule_names",
                "passed_structural_names",
                "failed_structural_names",
                "plots_json",
                "passed",
                "created_at",
            ],
        )
        with self._connect() as con:
            con.execute("CREATE TEMPORARY TABLE _medchem_tmp AS SELECT * FROM df", {"df": df})
            con.execute(
                """
                INSERT INTO medchem_results AS t
                SELECT * FROM _medchem_tmp s
                ON CONFLICT (barcode) DO UPDATE SET
                    n_rules_pass = excluded.n_rules_pass,
                    n_structural_pass = excluded.n_structural_pass,
                    rule_threshold = excluded.rule_threshold,
                    structural_threshold = excluded.structural_threshold,
                    filter_flags_json = excluded.filter_flags_json,
                    passed_rule_names = excluded.passed_rule_names,
                    failed_rule_names = excluded.failed_rule_names,
                    passed_structural_names = excluded.passed_structural_names,
                    failed_structural_names = excluded.failed_structural_names,
                    plots_json = excluded.plots_json,
                    passed = excluded.passed,
                    created_at = excluded.created_at
                """,
            )

    def write_chemap_results(self, chemap_df: pd.DataFrame, smiles_to_barcode: Dict[str, str]) -> None:
        if chemap_df is None or chemap_df.empty:
            return
        now = datetime.utcnow()
        records = []
        for _, row in chemap_df.iterrows():
            smi = str(row.get("SMILES", ""))
            barcode = smiles_to_barcode.get(smi, "")
            pred = row.get("ChemAP_pred")
            records.append(
                (
                    barcode,
                    smi,
                    int(pred) if pd.notna(pred) else None,
                    json.dumps({k: (row.get(k) if k in row else None) for k in chemap_df.columns}),
                    now,
                )
            )
        df = pd.DataFrame(records, columns=["barcode", "smiles", "chemap_pred", "raw_json", "created_at"])
        with self._connect() as con:
            con.execute("CREATE TEMPORARY TABLE _chemap_tmp AS SELECT * FROM df", {"df": df})
            con.execute(
                """
                INSERT INTO chemap_results
                SELECT * FROM _chemap_tmp
                """,
            )

    def upsert_boltz2_results(self, variants: Iterable[Dict[str, Any]]) -> None:
        rows = []
        now = datetime.utcnow()
        for v in variants:
            rows.append(
                (
                    str(v.get("barcode", "")),
                    v.get("affinity_pred_value"),
                    v.get("affinity_probability_binary"),
                    v.get("affinity_pred_value1"),
                    v.get("affinity_probability_binary1"),
                    v.get("affinity_pred_value2"),
                    v.get("affinity_probability_binary2"),
                    v.get("boltz2_score"),
                    json.dumps(v.get("pocket_residues")) if v.get("pocket_residues") is not None else None,
                    now,
                )
            )
        if not rows:
            return
        df = pd.DataFrame(
            rows,
            columns=[
                "barcode",
                "affinity_pred_value",
                "affinity_probability_binary",
                "affinity_pred_value1",
                "affinity_probability_binary1",
                "affinity_pred_value2",
                "affinity_probability_binary2",
                "boltz2_score",
                "pocket_residues",
                "created_at",
            ],
        )
        with self._connect() as con:
            con.execute("CREATE TEMPORARY TABLE _boltz_tmp AS SELECT * FROM df", {"df": df})
            con.execute(
                """
                INSERT INTO boltz2_results AS t
                SELECT * FROM _boltz_tmp s
                ON CONFLICT (barcode) DO UPDATE SET
                    affinity_pred_value = excluded.affinity_pred_value,
                    affinity_probability_binary = excluded.affinity_probability_binary,
                    affinity_pred_value1 = excluded.affinity_pred_value1,
                    affinity_probability_binary1 = excluded.affinity_probability_binary1,
                    affinity_pred_value2 = excluded.affinity_pred_value2,
                    affinity_probability_binary2 = excluded.affinity_probability_binary2,
                    boltz2_score = excluded.boltz2_score,
                    pocket_residues = excluded.pocket_residues,
                    created_at = excluded.created_at
                """,
            )

    def upsert_docking_results(self, results: Dict[str, Dict[str, Any]], barcode_by_variant_id: Dict[str, str], search_mode: str) -> None:
        rows = []
        now = datetime.utcnow()
        for variant_id, payload in results.items():
            if not isinstance(payload, dict) or "error" in payload:
                continue
            barcode = barcode_by_variant_id.get(variant_id)
            if not barcode:
                continue
            all_scores = payload.get("all_scores", [])
            rows.append(
                (
                    barcode,
                    payload.get("docking_score"),
                    payload.get("pose_count"),
                    payload.get("result_file"),
                    json.dumps(all_scores) if all_scores is not None else None,
                    search_mode,
                    now,
                )
            )
        if not rows:
            return
        df = pd.DataFrame(
            rows,
            columns=[
                "barcode",
                "best_score_kcal_mol",
                "pose_count",
                "result_file",
                "all_scores_json",
                "search_mode",
                "created_at",
            ],
        )
        with self._connect() as con:
            con.execute("CREATE TEMPORARY TABLE _dock_tmp AS SELECT * FROM df", {"df": df})
            con.execute(
                """
                INSERT INTO docking_results AS t
                SELECT * FROM _dock_tmp s
                ON CONFLICT (barcode) DO UPDATE SET
                    best_score_kcal_mol = excluded.best_score_kcal_mol,
                    pose_count = excluded.pose_count,
                    result_file = excluded.result_file,
                    all_scores_json = excluded.all_scores_json,
                    search_mode = excluded.search_mode,
                    created_at = excluded.created_at
                """,
            )

    # ------------- Read methods -------------
    def _extract_round_from_barcode(self, barcode: str) -> Optional[int]:
        """Extract round number from barcode pattern (e.g., 'R1-GEN-0001' -> 1)."""
        if not barcode or not isinstance(barcode, str):
            return None
        try:
            if barcode.startswith("R") and "-" in barcode:
                round_str = barcode.split("-")[0][1:]  # Extract "1" from "R1"
                return int(round_str)
        except (ValueError, IndexError):
            pass
        return None

    def get_variants_by_round(self, round_num: int) -> pd.DataFrame:
        """Query variants table filtered by round number extracted from barcode."""
        with self._connect() as con:
            # Extract round from barcode using SQL regex
            query = """
                SELECT 
                    barcode,
                    smiles,
                    score,
                    status,
                    parent_id,
                    created_at
                FROM variants
                WHERE barcode LIKE ?
            """
            pattern = f"R{round_num}-%"
            df = con.execute(query, [pattern]).df()
            if df.empty:
                return pd.DataFrame(columns=[
                    "barcode", "smiles", "score", "status", "parent_id", "created_at"
                ])
            return df

    def get_compounds_by_round(self, round_num: int) -> pd.DataFrame:
        """Query molecules table filtered by round number extracted from barcode."""
        with self._connect() as con:
            query = """
                SELECT 
                    barcode,
                    smiles,
                    generation,
                    status,
                    source,
                    created_at
                FROM molecules
                WHERE barcode LIKE ?
            """
            pattern = f"R{round_num}-%"
            df = con.execute(query, [pattern]).df()
            if df.empty:
                return pd.DataFrame(columns=[
                    "barcode", "smiles", "generation", "status", "source", "created_at"
                ])
            return df

    def get_variant_by_barcode(self, barcode: str) -> Optional[Dict[str, Any]]:
        """Get single variant with all related data (joins with medchem, chemap, boltz2, docking tables)."""
        with self._connect() as con:
            query = """
                SELECT 
                    v.barcode,
                    v.smiles,
                    v.score,
                    v.status,
                    v.parent_id,
                    v.created_at,
                    m.n_rules_pass,
                    m.n_structural_pass,
                    m.rule_threshold,
                    m.structural_threshold,
                    m.filter_flags_json,
                    m.passed_rule_names,
                    m.failed_rule_names,
                    m.passed_structural_names,
                    m.failed_structural_names,
                    m.plots_json,
                    m.passed AS medchem_passed,
                    c.chemap_pred,
                    c.raw_json AS chemap_raw_json,
                    b.affinity_pred_value,
                    b.affinity_probability_binary,
                    b.affinity_pred_value1,
                    b.affinity_probability_binary1,
                    b.affinity_pred_value2,
                    b.affinity_probability_binary2,
                    b.boltz2_score,
                    b.pocket_residues,
                    d.best_score_kcal_mol,
                    d.pose_count,
                    d.result_file,
                    d.all_scores_json,
                    d.search_mode
                FROM variants v
                LEFT JOIN medchem_results m ON v.barcode = m.barcode
                LEFT JOIN chemap_results c ON v.barcode = c.barcode
                LEFT JOIN boltz2_results b ON v.barcode = b.barcode
                LEFT JOIN docking_results d ON v.barcode = d.barcode
                WHERE v.barcode = ?
            """
            df = con.execute(query, [barcode]).df()
            if df.empty:
                return None
            row = df.iloc[0].to_dict()
            return row

    def get_all_tracking_data(self, round_num: Optional[int] = None) -> pd.DataFrame:
        """Combined view joining all tables to mimic CSV tracking report structure.
        
        Returns DataFrame with columns matching CSV structure:
        barcode, smiles, parent_id, status, source, timestamp
        Plus additional columns from joined tables.
        """
        with self._connect() as con:
            # Union of molecules (compounds) and variants
            # Extract round from barcode using DuckDB regexp_extract
            base_query = """
                WITH all_compounds AS (
                    -- Compounds from molecules table
                    SELECT 
                        barcode,
                        smiles,
                        'NONE' AS parent_id,
                        status,
                        source,
                        created_at AS timestamp
                    FROM molecules
                    
                    UNION ALL
                    
                    -- Variants from variants table
                    SELECT 
                        barcode,
                        smiles,
                        parent_id,
                        status,
                        'RETROSYNTHESIS' AS source,
                        created_at AS timestamp
                    FROM variants
                )
                SELECT 
                    ac.barcode,
                    ac.smiles,
                    ac.parent_id,
                    ac.status,
                    ac.source,
                    ac.timestamp,
                    CASE 
                        WHEN ac.source = 'RETROSYNTHESIS' THEN v.score 
                        ELSE NULL 
                    END AS score,
                    m.n_rules_pass,
                    m.n_structural_pass,
                    m.passed AS medchem_passed,
                    c.chemap_pred,
                    b.affinity_pred_value,
                    b.boltz2_score,
                    d.best_score_kcal_mol AS docking_score,
                    d.pose_count,
                    d.result_file,
                    d.all_scores_json AS all_scores
                FROM all_compounds ac
                LEFT JOIN variants v ON ac.barcode = v.barcode AND ac.source = 'RETROSYNTHESIS'
                LEFT JOIN medchem_results m ON ac.barcode = m.barcode
                LEFT JOIN chemap_results c ON ac.barcode = c.barcode
                LEFT JOIN boltz2_results b ON ac.barcode = b.barcode
                LEFT JOIN docking_results d ON ac.barcode = d.barcode
            """
            
            if round_num is not None:
                # Filter by round extracted from barcode
                base_query += f"""
                    WHERE CAST(regexp_extract(ac.barcode, 'R(\\d+)', 1) AS INT) = {round_num}
                """
            
            base_query += " ORDER BY CAST(regexp_extract(ac.barcode, 'R(\\d+)', 1) AS INT), ac.barcode"
            
            df = con.execute(base_query).df()
            
            if df.empty:
                return pd.DataFrame(columns=[
                    'barcode', 'smiles',
                    'parent_id', 'status', 'source', 'timestamp'
                ])
            
            return df

    def get_top_docked_variants(self, round_num: Optional[int] = None, limit: int = 10) -> pd.DataFrame:
        """Query docking results sorted by best_score (ascending, lower is better).
        
        Returns DataFrame with docking results and related variant information.
        """
        with self._connect() as con:
            query = """
                SELECT 
                    d.barcode,
                    v.smiles,
                    d.best_score_kcal_mol AS docking_score,
                    d.pose_count,
                    d.result_file,
                    d.all_scores_json AS all_scores,
                    d.search_mode,
                    v.status,
                    v.parent_id,
                    m.n_rules_pass,
                    m.n_structural_pass,
                    c.chemap_pred,
                    b.boltz2_score
                FROM docking_results d
                LEFT JOIN variants v ON d.barcode = v.barcode
                LEFT JOIN medchem_results m ON d.barcode = m.barcode
                LEFT JOIN chemap_results c ON d.barcode = c.barcode
                LEFT JOIN boltz2_results b ON d.barcode = b.barcode
            """
            
            if round_num is not None:
                query += f" WHERE CAST(regexp_extract(d.barcode, 'R(\\d+)', 1) AS INT) = {round_num}"
            
            query += " ORDER BY d.best_score_kcal_mol ASC LIMIT ?"
            
            df = con.execute(query, [limit]).df()
            
            if df.empty:
                return pd.DataFrame(columns=[
                    "barcode", "smiles", "docking_score", "pose_count", 
                    "result_file", "all_scores", "search_mode"
                ])
            
            return df

