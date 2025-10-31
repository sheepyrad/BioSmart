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
import logging

logger = logging.getLogger(__name__)


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

                CREATE TABLE IF NOT EXISTS jobs (
                    job_id TEXT PRIMARY KEY,
                    job_name TEXT,
                    output_dir TEXT UNIQUE NOT NULL,
                    parameters_json TEXT,
                    status TEXT,
                    created_at TIMESTAMP,
                    completed_at TIMESTAMP,
                    user_id TEXT
                );
                """
            )

    # ------------- Upserts / writes -------------
    def _ensure_scalar(self, value, default=None):
        """Ensure a value is a scalar (not DataFrame, Series, etc.) for DuckDB storage."""
        if value is None:
            return default
        if isinstance(value, pd.DataFrame):
            logger.error(f"CRITICAL: DataFrame detected in _ensure_scalar! Shape: {value.shape}, Columns: {list(value.columns)}")
            return default
        if isinstance(value, pd.Series):
            logger.error(f"CRITICAL: Series detected in _ensure_scalar! Length: {len(value)}, Index: {list(value.index)}")
            # If it's a Series with one value, extract it
            if len(value) == 1:
                try:
                    return value.iloc[0]
                except Exception:
                    return default
            return default
        return value
    
    def upsert_molecules(self, molecules: Iterable[Dict[str, Any]]) -> None:
        """Upsert basic molecule info (barcode, smiles, generation, status, source)."""
        rows = []
        now = datetime.utcnow()
        for m in molecules:
            # Aggressive sanitization - check every value
            barcode = m.get("barcode", "")
            smiles = m.get("smiles", "")
            generation = m.get("generation")
            status = m.get("status", "")
            source = m.get("source", "")
            
            # Check each value individually
            if isinstance(barcode, (pd.DataFrame, pd.Series)):
                logger.error(f"CRITICAL: DataFrame/Series in barcode: {type(barcode)}")
                barcode = ""
            if isinstance(smiles, (pd.DataFrame, pd.Series)):
                logger.error(f"CRITICAL: DataFrame/Series in smiles: {type(smiles)}")
                smiles = ""
            if isinstance(generation, (pd.DataFrame, pd.Series)):
                logger.error(f"CRITICAL: DataFrame/Series in generation: {type(generation)}")
                generation = None
            if isinstance(status, (pd.DataFrame, pd.Series)):
                logger.error(f"CRITICAL: DataFrame/Series in status: {type(status)}")
                status = ""
            if isinstance(source, (pd.DataFrame, pd.Series)):
                logger.error(f"CRITICAL: DataFrame/Series in source: {type(source)}")
                source = ""
            
            rows.append(
                (
                    str(self._ensure_scalar(barcode, "")),
                    str(self._ensure_scalar(smiles, "")),
                    int(self._ensure_scalar(generation, None)) if self._ensure_scalar(generation, None) is not None else None,
                    str(self._ensure_scalar(status, "")),
                    str(self._ensure_scalar(source, "")),
                    now,
                )
            )
        if not rows:
            return
        
        # Final check - ensure no DataFrames/Series in rows
        cleaned_rows = []
        for row_idx, row in enumerate(rows):
            cleaned_row = []
            for col_idx, val in enumerate(row):
                if isinstance(val, (pd.DataFrame, pd.Series)):
                    logger.error(f"CRITICAL: DataFrame/Series found in molecules row {row_idx}, col {col_idx}! Type: {type(val)}")
                    # Convert to None or empty string depending on column
                    if col_idx in [0, 1, 3, 4]:  # barcode, smiles, status, source - should be strings
                        cleaned_row.append("")
                    else:
                        cleaned_row.append(None)
                else:
                    cleaned_row.append(val)
            cleaned_rows.append(tuple(cleaned_row))
        rows = cleaned_rows
        
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
        
        # Final check on the DataFrame itself - scan all cells
        for col in df.columns:
            for idx in df.index:
                val = df.at[idx, col]
                if isinstance(val, (pd.DataFrame, pd.Series)):
                    logger.error(f"CRITICAL: DataFrame/Series found in molecules DataFrame at row {idx}, col '{col}'! Type: {type(val)}")
                    df.at[idx, col] = "" if col != "generation" else None
        
        # Also check dtypes - if any column has object dtype with DataFrame/Series, convert
        for col in df.columns:
            if df[col].dtype == 'object':
                for idx in df.index:
                    val = df.at[idx, col]
                    if isinstance(val, (pd.DataFrame, pd.Series)):
                        logger.error(f"CRITICAL: DataFrame/Series in object column '{col}' at row {idx}")
                        df.at[idx, col] = "" if col != "generation" else None
        
        # Convert DataFrame to native Python types before passing to DuckDB
        # This ensures no pandas objects remain - extract scalar from each cell
        df_converted = df.copy()
        for col in df_converted.columns:
            for idx in df_converted.index:
                val = df_converted.at[idx, col]
                # If it's a DataFrame/Series, convert to string representation
                if isinstance(val, pd.DataFrame):
                    logger.error(f"CRITICAL: DataFrame still present in '{col}' at row {idx} after all checks!")
                    df_converted.at[idx, col] = "" if col != "generation" else None
                elif isinstance(val, pd.Series):
                    logger.error(f"CRITICAL: Series still present in '{col}' at row {idx} after all checks!")
                    df_converted.at[idx, col] = val.iloc[0] if len(val) > 0 else ("" if col != "generation" else None)
                elif pd.isna(val):
                    df_converted.at[idx, col] = None
                else:
                    # Convert to native Python type
                    if isinstance(val, (pd.Timestamp, pd.Timedelta)):
                        df_converted.at[idx, col] = val.to_pydatetime() if hasattr(val, 'to_pydatetime') else str(val)
                    elif isinstance(val, (pd.Interval, pd.Period)):
                        df_converted.at[idx, col] = str(val)
                    else:
                        # Already a native type
                        df_converted.at[idx, col] = val
        
        with self._connect() as con:
            temp_view = "_molecules_tmp_view"
            con.register(temp_view, df_converted)
            try:
                con.execute(
                    f"""
                    INSERT INTO molecules AS t
                    SELECT * FROM {temp_view} s
                    ON CONFLICT (barcode) DO UPDATE SET
                        smiles = excluded.smiles,
                        generation = excluded.generation,
                        status = excluded.status,
                        source = excluded.source,
                        created_at = excluded.created_at
                    """
                )
            finally:
                unregister = getattr(con, "unregister", None)
                if callable(unregister):
                    unregister(temp_view)

    def upsert_variants(self, variants: Iterable[Dict[str, Any]]) -> None:
        """Upsert basic variant info (barcode, smiles, score, status, parent_id)."""
        rows = []
        now = datetime.utcnow()
        for v in variants:
            # Aggressive sanitization - check every value
            barcode = v.get("barcode", "")
            smiles = v.get("smiles", "")
            score = v.get("score")
            status = v.get("status", "")
            parent_id = v.get("parent_id", "")
            
            # Check each value individually
            if isinstance(barcode, (pd.DataFrame, pd.Series)):
                logger.error(f"CRITICAL: DataFrame/Series in barcode: {type(barcode)}")
                barcode = ""
            if isinstance(smiles, (pd.DataFrame, pd.Series)):
                logger.error(f"CRITICAL: DataFrame/Series in smiles: {type(smiles)}")
                smiles = ""
            if isinstance(score, (pd.DataFrame, pd.Series)):
                logger.error(f"CRITICAL: DataFrame/Series in score: {type(score)}")
                score = None
            if isinstance(status, (pd.DataFrame, pd.Series)):
                logger.error(f"CRITICAL: DataFrame/Series in status: {type(status)}")
                status = ""
            if isinstance(parent_id, (pd.DataFrame, pd.Series)):
                logger.error(f"CRITICAL: DataFrame/Series in parent_id: {type(parent_id)}")
                parent_id = ""
            
            score_val = self._ensure_scalar(score, None)
            rows.append(
                (
                    str(self._ensure_scalar(barcode, "")),
                    str(self._ensure_scalar(smiles, "")),
                    float(score_val) if score_val is not None else None,
                    str(self._ensure_scalar(status, "")),
                    str(self._ensure_scalar(parent_id, "")),
                    now,
                )
            )
        if not rows:
            return
        
        # Final check - ensure no DataFrames/Series in rows
        cleaned_rows = []
        for row_idx, row in enumerate(rows):
            cleaned_row = []
            for col_idx, val in enumerate(row):
                if isinstance(val, (pd.DataFrame, pd.Series)):
                    logger.error(f"CRITICAL: DataFrame/Series found in variants row {row_idx}, col {col_idx}! Type: {type(val)}")
                    # Convert to None or empty string depending on column
                    if col_idx in [0, 1, 3, 4]:  # barcode, smiles, status, parent_id - should be strings
                        cleaned_row.append("")
                    else:
                        cleaned_row.append(None)
                else:
                    cleaned_row.append(val)
            cleaned_rows.append(tuple(cleaned_row))
        rows = cleaned_rows
        
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
        
        # Final check on the DataFrame itself - scan all cells
        for col in df.columns:
            for idx in df.index:
                val = df.at[idx, col]
                if isinstance(val, (pd.DataFrame, pd.Series)):
                    logger.error(f"CRITICAL: DataFrame/Series found in variants DataFrame at row {idx}, col '{col}'! Type: {type(val)}")
                    df.at[idx, col] = "" if col != "score" else None
        
        # Also check dtypes - if any column has object dtype with DataFrame/Series, convert
        for col in df.columns:
            if df[col].dtype == 'object':
                for idx in df.index:
                    val = df.at[idx, col]
                    if isinstance(val, (pd.DataFrame, pd.Series)):
                        logger.error(f"CRITICAL: DataFrame/Series in object column '{col}' at row {idx}")
                        df.at[idx, col] = "" if col != "score" else None
        
        # Convert DataFrame to native Python types before passing to DuckDB
        # This ensures no pandas objects remain - extract scalar from each cell
        df_converted = df.copy()
        for col in df_converted.columns:
            for idx in df_converted.index:
                val = df_converted.at[idx, col]
                # If it's a DataFrame/Series, convert to string representation
                if isinstance(val, pd.DataFrame):
                    logger.error(f"CRITICAL: DataFrame still present in '{col}' at row {idx} after all checks!")
                    df_converted.at[idx, col] = "" if col != "score" else None
                elif isinstance(val, pd.Series):
                    logger.error(f"CRITICAL: Series still present in '{col}' at row {idx} after all checks!")
                    df_converted.at[idx, col] = val.iloc[0] if len(val) > 0 else ("" if col != "score" else None)
                elif pd.isna(val):
                    df_converted.at[idx, col] = None
                else:
                    # Convert to native Python type
                    if isinstance(val, (pd.Timestamp, pd.Timedelta)):
                        df_converted.at[idx, col] = val.to_pydatetime() if hasattr(val, 'to_pydatetime') else str(val)
                    elif isinstance(val, (pd.Interval, pd.Period)):
                        df_converted.at[idx, col] = str(val)
                    else:
                        # Already a native type
                        df_converted.at[idx, col] = val
        
        with self._connect() as con:
            temp_view = "_variants_tmp_view"
            con.register(temp_view, df_converted)
            try:
                con.execute(
                    f"""
                    INSERT INTO variants AS t
                    SELECT * FROM {temp_view} s
                    ON CONFLICT (barcode) DO UPDATE SET
                        smiles = excluded.smiles,
                        score = excluded.score,
                        status = excluded.status,
                        parent_id = excluded.parent_id,
                        created_at = excluded.created_at
                    """
                )
            finally:
                unregister = getattr(con, "unregister", None)
                if callable(unregister):
                    unregister(temp_view)

    def upsert_medchem_results(self, barcode_to_result: Dict[str, Dict[str, Any]]) -> None:
        rows = []
        now = datetime.utcnow()
        for barcode, payload in barcode_to_result.items():
            # Ensure filter_flags_json and plots_json are JSON-serializable dicts, not DataFrames
            filter_flags = payload.get("filter_flags_json", {})
            if isinstance(filter_flags, pd.DataFrame):
                filter_flags = filter_flags.to_dict() if not filter_flags.empty else {}
            elif isinstance(filter_flags, pd.Series):
                filter_flags = filter_flags.to_dict() if len(filter_flags) > 0 else {}
            
            plots_json = payload.get("plots_json", {})
            if isinstance(plots_json, pd.DataFrame):
                plots_json = plots_json.to_dict() if not plots_json.empty else {}
            elif isinstance(plots_json, pd.Series):
                plots_json = plots_json.to_dict() if len(plots_json) > 0 else {}
            
            # Ensure list values are lists, not Series
            passed_rule_names = payload.get("passed_rule_names", [])
            if isinstance(passed_rule_names, pd.Series):
                passed_rule_names = passed_rule_names.tolist()
            elif not isinstance(passed_rule_names, list):
                passed_rule_names = []
            
            failed_rule_names = payload.get("failed_rule_names", [])
            if isinstance(failed_rule_names, pd.Series):
                failed_rule_names = failed_rule_names.tolist()
            elif not isinstance(failed_rule_names, list):
                failed_rule_names = []
            
            passed_structural_names = payload.get("passed_structural_names", [])
            if isinstance(passed_structural_names, pd.Series):
                passed_structural_names = passed_structural_names.tolist()
            elif not isinstance(passed_structural_names, list):
                passed_structural_names = []
            
            failed_structural_names = payload.get("failed_structural_names", [])
            if isinstance(failed_structural_names, pd.Series):
                failed_structural_names = failed_structural_names.tolist()
            elif not isinstance(failed_structural_names, list):
                failed_structural_names = []
            
            rows.append(
                (
                    str(self._ensure_scalar(barcode, "")),
                    self._ensure_scalar(payload.get("n_rules_pass"), None),
                    self._ensure_scalar(payload.get("n_structural_pass"), None),
                    self._ensure_scalar(payload.get("rule_threshold"), None),
                    self._ensure_scalar(payload.get("structural_threshold"), None),
                    json.dumps(filter_flags),
                    ",".join(passed_rule_names),
                    ",".join(failed_rule_names),
                    ",".join(passed_structural_names),
                    ",".join(failed_structural_names),
                    json.dumps(plots_json),
                    bool(self._ensure_scalar(payload.get("passed"), None)) if self._ensure_scalar(payload.get("passed"), None) is not None else None,
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
            temp_view = "_medchem_tmp_view"
            con.register(temp_view, df)
            try:
                con.execute(
                    f"""
                    INSERT INTO medchem_results AS t
                    SELECT * FROM {temp_view} s
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
                    """
                )
            finally:
                unregister = getattr(con, "unregister", None)
                if callable(unregister):
                    unregister(temp_view)

    def write_chemap_results(self, chemap_df: pd.DataFrame, smiles_to_barcode: Dict[str, str]) -> None:
        if chemap_df is None or chemap_df.empty:
            return
        now = datetime.utcnow()
        records = []
        for _, row in chemap_df.iterrows():
            smi = str(self._ensure_scalar(row.get("SMILES", ""), ""))
            barcode = self._ensure_scalar(smiles_to_barcode.get(smi, ""), "")
            pred = self._ensure_scalar(row.get("ChemAP_pred"), None)
            
            # Build row dict, ensuring all values are scalars
            row_dict = {}
            for k in chemap_df.columns:
                val = self._ensure_scalar(row.get(k), None)
                row_dict[k] = val
            
            records.append(
                (
                    str(barcode),
                    str(smi),
                    int(pred) if pd.notna(pred) else None,
                    json.dumps(row_dict),
                    now,
                )
            )
        df = pd.DataFrame(records, columns=["barcode", "smiles", "chemap_pred", "raw_json", "created_at"])
        with self._connect() as con:
            temp_view = "_chemap_tmp_view"
            con.register(temp_view, df)
            try:
                con.execute(
                    f"""
                    INSERT INTO chemap_results
                    SELECT * FROM {temp_view}
                    """
                )
            finally:
                unregister = getattr(con, "unregister", None)
                if callable(unregister):
                    unregister(temp_view)

    def upsert_boltz2_results(self, variants: Iterable[Dict[str, Any]]) -> None:
        rows = []
        now = datetime.utcnow()
        for v in variants:
            pocket_residues = v.get("pocket_residues")
            # Ensure pocket_residues is JSON-serializable
            if isinstance(pocket_residues, pd.DataFrame):
                pocket_residues = pocket_residues.to_dict() if not pocket_residues.empty else None
            elif isinstance(pocket_residues, pd.Series):
                pocket_residues = pocket_residues.tolist() if len(pocket_residues) > 0 else None
            
            rows.append(
                (
                    str(self._ensure_scalar(v.get("barcode", ""), "")),
                    self._ensure_scalar(v.get("affinity_pred_value"), None),
                    self._ensure_scalar(v.get("affinity_probability_binary"), None),
                    self._ensure_scalar(v.get("affinity_pred_value1"), None),
                    self._ensure_scalar(v.get("affinity_probability_binary1"), None),
                    self._ensure_scalar(v.get("affinity_pred_value2"), None),
                    self._ensure_scalar(v.get("affinity_probability_binary2"), None),
                    self._ensure_scalar(v.get("boltz2_score"), None),
                    json.dumps(pocket_residues) if pocket_residues is not None else None,
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
            temp_view = "_boltz_tmp_view"
            con.register(temp_view, df)
            try:
                con.execute(
                    f"""
                    INSERT INTO boltz2_results AS t
                    SELECT * FROM {temp_view} s
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
                    """
                )
            finally:
                unregister = getattr(con, "unregister", None)
                if callable(unregister):
                    unregister(temp_view)

    def upsert_docking_results(self, results: Dict[str, Dict[str, Any]], barcode_by_variant_id: Dict[str, str], search_mode: str) -> None:
        rows = []
        now = datetime.utcnow()
        for variant_id, payload in results.items():
            if not isinstance(payload, dict) or "error" in payload:
                continue
            barcode = self._ensure_scalar(barcode_by_variant_id.get(variant_id), None)
            if not barcode:
                continue
            
            # Ensure all_scores is a list, not DataFrame
            all_scores = payload.get("all_scores", [])
            if isinstance(all_scores, pd.DataFrame):
                all_scores = all_scores.values.flatten().tolist() if not all_scores.empty else []
            elif isinstance(all_scores, pd.Series):
                all_scores = all_scores.tolist()
            
            rows.append(
                (
                    str(barcode),
                    self._ensure_scalar(payload.get("docking_score"), None),
                    self._ensure_scalar(payload.get("pose_count"), None),
                    str(self._ensure_scalar(payload.get("result_file"), None)) if payload.get("result_file") else None,
                    json.dumps(all_scores) if all_scores is not None else None,
                    str(self._ensure_scalar(search_mode, "")),
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
            temp_view = "_dock_tmp_view"
            con.register(temp_view, df)
            try:
                con.execute(
                    f"""
                    INSERT INTO docking_results AS t
                    SELECT * FROM {temp_view} s
                    ON CONFLICT (barcode) DO UPDATE SET
                        best_score_kcal_mol = excluded.best_score_kcal_mol,
                        pose_count = excluded.pose_count,
                        result_file = excluded.result_file,
                        all_scores_json = excluded.all_scores_json,
                        search_mode = excluded.search_mode,
                        created_at = excluded.created_at
                    """
                )
            finally:
                unregister = getattr(con, "unregister", None)
                if callable(unregister):
                    unregister(temp_view)

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
            # Ensure all values are scalars (not DataFrames/Series)
            cleaned_row = {}
            for key, value in row.items():
                if isinstance(value, pd.DataFrame):
                    logger.warning(f"Found DataFrame in {key}, converting to None")
                    cleaned_row[key] = None
                elif isinstance(value, pd.Series):
                    # If it's a Series with one value, extract it
                    if len(value) == 1:
                        cleaned_row[key] = value.iloc[0]
                    else:
                        logger.warning(f"Found Series in {key}, converting to None")
                        cleaned_row[key] = None
                else:
                    cleaned_row[key] = value
            return cleaned_row

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

    # ------------- Job management methods -------------
    def create_job(self, job_id: str, output_dir: str, parameters: Dict[str, Any], 
                   status: str = "running", user_id: Optional[str] = None, 
                   job_name: Optional[str] = None) -> None:
        """Create a new job record with parameters."""
        now = datetime.utcnow()
        with self._connect() as con:
            con.execute(
                """
                INSERT INTO jobs (job_id, job_name, output_dir, parameters_json, status, created_at, user_id)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (job_id) DO UPDATE SET
                    job_name = excluded.job_name,
                    parameters_json = excluded.parameters_json,
                    status = excluded.status,
                    created_at = excluded.created_at
                """,
                [
                    job_id,
                    job_name,
                    output_dir,
                    json.dumps(parameters),
                    status,
                    now,
                    user_id
                ]
            )

    def update_job_status(self, job_id: str, status: str) -> None:
        """Update job status and optionally set completed_at timestamp."""
        now = datetime.utcnow()
        with self._connect() as con:
            if status in ["completed", "failed"]:
                con.execute(
                    """
                    UPDATE jobs 
                    SET status = ?, completed_at = ?
                    WHERE job_id = ?
                    """,
                    [status, now, job_id]
                )
            else:
                con.execute(
                    """
                    UPDATE jobs 
                    SET status = ?
                    WHERE job_id = ?
                    """,
                    [status, job_id]
                )

    def get_job_by_output_dir(self, output_dir: str) -> Optional[Dict[str, Any]]:
        """Get job record by output directory path."""
        with self._connect() as con:
            df = con.execute(
                """
                SELECT job_id, job_name, output_dir, parameters_json, status, created_at, completed_at, user_id
                FROM jobs
                WHERE output_dir = ?
                """,
                [output_dir]
            ).df()
            
            if df.empty:
                return None
            
            row = df.iloc[0].to_dict()
            # Parse JSON parameters
            if row.get("parameters_json"):
                try:
                    row["parameters"] = json.loads(row["parameters_json"])
                except json.JSONDecodeError:
                    row["parameters"] = {}
            else:
                row["parameters"] = {}
            return row

    def get_all_jobs(self, user_id: Optional[str] = None, limit: int = 100) -> pd.DataFrame:
        """Get all jobs, optionally filtered by user_id."""
        with self._connect() as con:
            if user_id:
                df = con.execute(
                    """
                    SELECT job_id, job_name, output_dir, parameters_json, status, created_at, completed_at, user_id
                    FROM jobs
                    WHERE user_id = ?
                    ORDER BY created_at DESC
                    LIMIT ?
                    """,
                    [user_id, limit]
                ).df()
            else:
                df = con.execute(
                    """
                    SELECT job_id, job_name, output_dir, parameters_json, status, created_at, completed_at, user_id
                    FROM jobs
                    ORDER BY created_at DESC
                    LIMIT ?
                    """,
                    [limit]
                ).df()
            
            if df.empty:
                return pd.DataFrame(columns=[
                    "job_id", "job_name", "output_dir", "parameters_json", "status", 
                    "created_at", "completed_at", "user_id"
                ])
            
            return df

