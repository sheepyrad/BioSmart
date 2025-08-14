"""
Lightweight PostgreSQL helper for the event-driven pipeline.

Responsibilities:
- Establish pooled connections
- Initialize minimal schema (tables + indexes)
- Enqueue/dequeue tasks with SKIP LOCKED
- Publish/subscribe using LISTEN/NOTIFY

Notes
- This module intentionally keeps dependencies minimal (psycopg2 only)
- SQLAlchemy can be layered on later if desired
"""

from __future__ import annotations

import json
import os
import select
import time
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Dict, Generator, Iterable, List, Optional, Tuple

import psycopg2
import psycopg2.extras


@dataclass
class DBConfig:
    dsn: str


class DB:
    """Small PostgreSQL utility.

    Usage:
        db = DB.from_env()
        db.init_schema()
        db.enqueue_task("retrosynthesis", {"molecule_id": 1})
        for notify in db.listen(["retrosynthesis"]):
            ...
    """

    def __init__(self, dsn: str) -> None:
        self.dsn = dsn
        self._conn = None

    @classmethod
    def from_env(cls) -> "DB":
        dsn = os.getenv("DB_URL", "")
        if not dsn:
            raise RuntimeError("DB_URL not set. Provide a PostgreSQL connection string.")
        return cls(dsn)

    @contextmanager
    def get_conn(self):
        conn = psycopg2.connect(self.dsn)
        try:
            yield conn
        finally:
            conn.close()

    def init_schema(self) -> None:
        """Create tables and indexes if they don't exist."""
        with self.get_conn() as conn:
            cur = conn.cursor()
            # Core tables
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS molecules (
                    id BIGSERIAL PRIMARY KEY,
                    smiles TEXT NOT NULL,
                    inchikey TEXT UNIQUE NOT NULL,
                    generation INT DEFAULT 1,
                    barcode TEXT,
                    status TEXT,
                    source TEXT,
                    created_at TIMESTAMPTZ DEFAULT NOW()
                );
                CREATE INDEX IF NOT EXISTS idx_molecules_inchikey ON molecules (inchikey);

                CREATE TABLE IF NOT EXISTS variants (
                    id BIGSERIAL PRIMARY KEY,
                    molecule_id BIGINT REFERENCES molecules(id) ON DELETE CASCADE,
                    smiles TEXT NOT NULL,
                    barcode TEXT,
                    score DOUBLE PRECISION,
                    status TEXT,
                    created_at TIMESTAMPTZ DEFAULT NOW()
                );
                CREATE INDEX IF NOT EXISTS idx_variants_molecule_id ON variants (molecule_id);

                CREATE TABLE IF NOT EXISTS medchem_results (
                    variant_id BIGINT PRIMARY KEY REFERENCES variants(id) ON DELETE CASCADE,
                    n_rules_pass INT,
                    n_structural_pass INT,
                    rule_threshold INT,
                    structural_threshold INT,
                    filter_flags_json JSONB,
                    passed_rule_names TEXT[],
                    failed_rule_names TEXT[],
                    passed_structural_names TEXT[],
                    failed_structural_names TEXT[],
                    plots_json JSONB,
                    passed BOOLEAN,
                    created_at TIMESTAMPTZ DEFAULT NOW()
                );

                CREATE TABLE IF NOT EXISTS boltz2_results (
                    variant_id BIGINT PRIMARY KEY REFERENCES variants(id) ON DELETE CASCADE,
                    affinity_pred_value DOUBLE PRECISION,
                    affinity_probability_binary DOUBLE PRECISION,
                    affinity_pred_value1 DOUBLE PRECISION,
                    affinity_probability_binary1 DOUBLE PRECISION,
                    affinity_pred_value2 DOUBLE PRECISION,
                    affinity_probability_binary2 DOUBLE PRECISION,
                    screening_score DOUBLE PRECISION,
                    pocket_residues INT[],
                    passed BOOLEAN,
                    created_at TIMESTAMPTZ DEFAULT NOW()
                );

                CREATE TABLE IF NOT EXISTS docking_results (
                    variant_id BIGINT PRIMARY KEY REFERENCES variants(id) ON DELETE CASCADE,
                    best_score_kcal_mol DOUBLE PRECISION,
                    pose_count INT,
                    result_file TEXT,
                    all_scores JSONB,
                    search_mode TEXT,
                    created_at TIMESTAMPTZ DEFAULT NOW()
                );

                CREATE TABLE IF NOT EXISTS tasks (
                    id BIGSERIAL PRIMARY KEY,
                    type TEXT NOT NULL,
                    payload JSONB NOT NULL,
                    status TEXT NOT NULL DEFAULT 'queued',
                    priority INT DEFAULT 0,
                    available_at TIMESTAMPTZ DEFAULT NOW(),
                    attempts INT DEFAULT 0,
                    error TEXT,
                    updated_at TIMESTAMPTZ DEFAULT NOW()
                );
                CREATE INDEX IF NOT EXISTS idx_tasks_lookup ON tasks (type, status, available_at);
                """
            )
            conn.commit()

    # ------------------------ Task Queue ------------------------
    def enqueue_task(self, task_type: str, payload: Dict[str, Any]) -> int:
        with self.get_conn() as conn:
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO tasks (type, payload) VALUES (%s, %s) RETURNING id",
                (task_type, json.dumps(payload)),
            )
            task_id = cur.fetchone()[0]
            conn.commit()
        self.notify(task_type)
        return task_id

    def notify(self, channel: str) -> None:
        with self.get_conn() as conn:
            cur = conn.cursor()
            cur.execute(f"NOTIFY {psycopg2.extensions.quote_ident(channel, cur)}, '1';")
            conn.commit()

    def dequeue(self, task_type: str, limit: int = 1) -> List[Tuple[int, Dict[str, Any]]]:
        """Atomically move tasks to running and return them (SKIP LOCKED)."""
        with self.get_conn() as conn:
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            cur.execute(
                """
                WITH picked AS (
                    SELECT id FROM tasks
                    WHERE type = %s AND status = 'queued' AND available_at <= NOW()
                    ORDER BY priority DESC, id
                    FOR UPDATE SKIP LOCKED
                    LIMIT %s
                )
                UPDATE tasks t
                SET status = 'running', attempts = t.attempts + 1, updated_at = NOW()
                FROM picked p
                WHERE t.id = p.id
                RETURNING t.id, t.payload;
                """,
                (task_type, limit),
            )
            rows = cur.fetchall()
            conn.commit()
        return [(int(r["id"]), r["payload"]) for r in rows]

    def complete_task(self, task_id: int) -> None:
        with self.get_conn() as conn:
            cur = conn.cursor()
            cur.execute(
                "UPDATE tasks SET status='done', updated_at=NOW() WHERE id=%s",
                (task_id,),
            )
            conn.commit()

    def fail_task(self, task_id: int, error: str) -> None:
        with self.get_conn() as conn:
            cur = conn.cursor()
            cur.execute(
                "UPDATE tasks SET status='failed', error=%s, updated_at=NOW() WHERE id=%s",
                (error, task_id),
            )
            conn.commit()

    # ------------------------ Pub/Sub ------------------------
    def listen(self, channels: Iterable[str]) -> Generator[str, None, None]:
        """Yield channel names as notifications arrive."""
        with psycopg2.connect(self.dsn) as conn:
            conn.set_isolation_level(psycopg2.extensions.ISOLATION_LEVEL_AUTOCOMMIT)
            cur = conn.cursor()
            for ch in channels:
                cur.execute(f"LISTEN {psycopg2.extensions.quote_ident(ch, cur)};")
            while True:
                if select.select([conn], [], [], 10) == ([], [], []):
                    # periodic heartbeat
                    yield "__timeout__"
                    continue
                conn.poll()
                while conn.notifies:
                    notify = conn.notifies.pop(0)
                    yield notify.channel

    # ------------------------ Molecule APIs ------------------------
    def upsert_molecule(self, smiles: str, inchikey: str, generation: int, barcode: str | None, source: str) -> Optional[int]:
        """Insert molecule if unique; return row id if inserted, else None."""
        with self.get_conn() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO molecules (smiles, inchikey, generation, barcode, status, source)
                VALUES (%s, %s, %s, %s, 'GENERATED', %s)
                ON CONFLICT (inchikey) DO NOTHING
                RETURNING id
                """,
                (smiles, inchikey, generation, barcode, source),
            )
            row = cur.fetchone()
            conn.commit()
            return int(row[0]) if row else None

    def count_unique_molecules(self) -> int:
        with self.get_conn() as conn:
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*) FROM molecules")
            (cnt,) = cur.fetchone()
            return int(cnt)

    # ------------------------ Variant APIs ------------------------
    def insert_variant(self, molecule_id: int, smiles: str, score: Optional[float], status: str, barcode: Optional[str]) -> int:
        with self.get_conn() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO variants (molecule_id, smiles, score, status, barcode)
                VALUES (%s, %s, %s, %s, %s)
                RETURNING id
                """,
                (molecule_id, smiles, score, status, barcode),
            )
            (vid,) = cur.fetchone()
            conn.commit()
            return int(vid)

    def get_molecule(self, molecule_id: int) -> Optional[Dict[str, Any]]:
        with self.get_conn() as conn:
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            cur.execute("SELECT * FROM molecules WHERE id=%s", (molecule_id,))
            row = cur.fetchone()
            return dict(row) if row else None

    def get_variants(self, variant_ids: List[int]) -> List[Dict[str, Any]]:
        if not variant_ids:
            return []
        with self.get_conn() as conn:
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            cur.execute(
                "SELECT * FROM variants WHERE id = ANY(%s)",
                (variant_ids,),
            )
            rows = cur.fetchall()
            return [dict(r) for r in rows]

    def update_variant_status(self, variant_id: int, status: str) -> None:
        with self.get_conn() as conn:
            cur = conn.cursor()
            cur.execute(
                "UPDATE variants SET status=%s, created_at=created_at WHERE id=%s",
                (status, variant_id),
            )
            conn.commit()

    # ------------------------ Results APIs ------------------------
    def upsert_medchem_results(self, variant_id: int, payload: Dict[str, Any]) -> None:
        with self.get_conn() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO medchem_results (
                    variant_id, n_rules_pass, n_structural_pass, rule_threshold, structural_threshold,
                    filter_flags_json, passed_rule_names, failed_rule_names, passed_structural_names,
                    failed_structural_names, plots_json, passed
                ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (variant_id) DO UPDATE SET
                    n_rules_pass=EXCLUDED.n_rules_pass,
                    n_structural_pass=EXCLUDED.n_structural_pass,
                    rule_threshold=EXCLUDED.rule_threshold,
                    structural_threshold=EXCLUDED.structural_threshold,
                    filter_flags_json=EXCLUDED.filter_flags_json,
                    passed_rule_names=EXCLUDED.passed_rule_names,
                    failed_rule_names=EXCLUDED.failed_rule_names,
                    passed_structural_names=EXCLUDED.passed_structural_names,
                    failed_structural_names=EXCLUDED.failed_structural_names,
                    plots_json=EXCLUDED.plots_json,
                    passed=EXCLUDED.passed,
                    created_at=NOW()
                """,
                (
                    variant_id,
                    payload.get("n_rules_pass"),
                    payload.get("n_structural_pass"),
                    payload.get("rule_threshold"),
                    payload.get("structural_threshold"),
                    json.dumps(payload.get("filter_flags_json", {})),
                    payload.get("passed_rule_names"),
                    payload.get("failed_rule_names"),
                    payload.get("passed_structural_names"),
                    payload.get("failed_structural_names"),
                    json.dumps(payload.get("plots_json", {})),
                    payload.get("passed"),
                ),
            )
            conn.commit()

    def upsert_boltz2_results(self, variant_id: int, payload: Dict[str, Any]) -> None:
        with self.get_conn() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO boltz2_results (
                    variant_id,
                    affinity_pred_value, affinity_probability_binary,
                    affinity_pred_value1, affinity_probability_binary1,
                    affinity_pred_value2, affinity_probability_binary2,
                    screening_score, pocket_residues, passed
                ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (variant_id) DO UPDATE SET
                    affinity_pred_value=EXCLUDED.affinity_pred_value,
                    affinity_probability_binary=EXCLUDED.affinity_probability_binary,
                    affinity_pred_value1=EXCLUDED.affinity_pred_value1,
                    affinity_probability_binary1=EXCLUDED.affinity_probability_binary1,
                    affinity_pred_value2=EXCLUDED.affinity_pred_value2,
                    affinity_probability_binary2=EXCLUDED.affinity_probability_binary2,
                    screening_score=EXCLUDED.screening_score,
                    pocket_residues=EXCLUDED.pocket_residues,
                    passed=EXCLUDED.passed,
                    created_at=NOW()
                """,
                (
                    variant_id,
                    payload.get("affinity_pred_value"),
                    payload.get("affinity_probability_binary"),
                    payload.get("affinity_pred_value1"),
                    payload.get("affinity_probability_binary1"),
                    payload.get("affinity_pred_value2"),
                    payload.get("affinity_probability_binary2"),
                    payload.get("screening_score"),
                    payload.get("pocket_residues"),
                    payload.get("passed", True),
                ),
            )
            conn.commit()

    def upsert_docking_results(self, variant_id: int, payload: Dict[str, Any]) -> None:
        with self.get_conn() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO docking_results (
                    variant_id, best_score_kcal_mol, pose_count, result_file, all_scores, search_mode
                ) VALUES (%s,%s,%s,%s,%s,%s)
                ON CONFLICT (variant_id) DO UPDATE SET
                    best_score_kcal_mol=EXCLUDED.best_score_kcal_mol,
                    pose_count=EXCLUDED.pose_count,
                    result_file=EXCLUDED.result_file,
                    all_scores=EXCLUDED.all_scores,
                    search_mode=EXCLUDED.search_mode,
                    created_at=NOW()
                """,
                (
                    variant_id,
                    payload.get("best_score_kcal_mol"),
                    payload.get("pose_count"),
                    payload.get("result_file"),
                    json.dumps(payload.get("all_scores", [])),
                    payload.get("search_mode"),
                ),
            )
            conn.commit()


