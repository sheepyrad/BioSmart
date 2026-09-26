"""Run folder, Run database, event stream, and Index."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Mapping
from pathlib import Path
from typing import Any


def write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, allow_nan=False) + "\n")


def append_event(events_path: Path, event: Mapping[str, Any]) -> None:
    with events_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, allow_nan=False) + "\n")


def read_events(events_path: Path) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for line in events_path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            payload = json.loads(line)
            if not isinstance(payload, dict):
                raise ValueError(f"event is not an object: {line}")
            events.append(payload)
    return events


def spec_sha256(spec_path: Path) -> str:
    return hashlib.sha256(spec_path.read_bytes()).hexdigest()


def connect(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(path)
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA foreign_keys=ON")
    connection.execute("PRAGMA busy_timeout=5000")
    return connection


def init_run_database(path: Path) -> None:
    with connect(path) as connection:
        connection.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        connection.execute(
            """
            CREATE TABLE candidates (
                id TEXT PRIMARY KEY,
                iteration INTEGER NOT NULL,
                round_no INTEGER NOT NULL,
                canonical_smiles TEXT NOT NULL,
                status TEXT NOT NULL,
                failure_reason TEXT,
                reward REAL,
                route_json TEXT,
                pose_ref TEXT,
                temperature REAL
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE scores (
                candidate_id TEXT NOT NULL,
                scorer TEXT NOT NULL,
                reward REAL,
                raw_json TEXT,
                PRIMARY KEY (candidate_id, scorer)
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE scoring_rounds (
                round_no INTEGER PRIMARY KEY,
                scorer TEXT NOT NULL,
                n_sent INTEGER NOT NULL,
                n_ok INTEGER NOT NULL,
                n_failed INTEGER NOT NULL,
                secs REAL NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE iterations (
                iteration INTEGER PRIMARY KEY,
                reward_avg REAL,
                n_valid INTEGER NOT NULL,
                secs REAL NOT NULL
            )
            """
        )
        connection.execute(
            "INSERT INTO meta (key, value) VALUES ('schema_version', '1')"
        )


def insert_candidate(
    path: Path,
    *,
    candidate_id: str,
    iteration: int,
    round_no: int,
    canonical_smiles: str,
    status: str,
    reward: float | None,
    failure_reason: str | None,
    scorer: str,
    route_json: str | None,
    raw: Mapping[str, Any] | None = None,
) -> None:
    with connect(path) as connection:
        connection.execute(
            """
            INSERT INTO candidates (
                id, iteration, round_no, canonical_smiles, status,
                failure_reason, reward, route_json, pose_ref, temperature
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL)
            """,
            (
                candidate_id,
                iteration,
                round_no,
                canonical_smiles,
                status,
                failure_reason,
                reward,
                route_json,
            ),
        )
        connection.execute(
            """
            INSERT INTO scores (candidate_id, scorer, reward, raw_json)
            VALUES (?, ?, ?, ?)
            """,
            (
                candidate_id,
                scorer,
                reward,
                json.dumps(
                    {
                        "status": status,
                        "reward": reward,
                        "failure_reason": failure_reason,
                        **({"raw": raw} if raw else {}),
                    },
                    allow_nan=False,
                ),
            ),
        )


def insert_scoring_round(
    path: Path,
    *,
    round_no: int,
    scorer: str,
    n_sent: int,
    n_ok: int,
    n_failed: int,
    secs: float,
) -> None:
    with connect(path) as connection:
        connection.execute(
            """
            INSERT INTO scoring_rounds (round_no, scorer, n_sent, n_ok, n_failed, secs)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (round_no, scorer, n_sent, n_ok, n_failed, secs),
        )


def insert_iteration(
    path: Path,
    *,
    iteration: int,
    reward_avg: float | None,
    n_valid: int,
    secs: float,
) -> None:
    with connect(path) as connection:
        connection.execute(
            """
            INSERT INTO iterations (iteration, reward_avg, n_valid, secs)
            VALUES (?, ?, ?, ?)
            """,
            (iteration, reward_avg, n_valid, secs),
        )


def flush_scorer_cache(
    path: Path,
    *,
    scorer: str,
    scorer_version: str,
    context_hash: str,
    entries: list[tuple[str, float]],
) -> int:
    """Write staged Scorer cache entries and checkpoint the database."""
    if not isinstance(path, Path):
        raise TypeError("path must be a Path")
    if not scorer or not scorer_version or not context_hash:
        raise ValueError("Scorer cache key is incomplete")
    path.parent.mkdir(parents=True, exist_ok=True)
    with connect(path) as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS scorer_cache (
                scorer TEXT NOT NULL,
                scorer_version TEXT NOT NULL,
                context_hash TEXT NOT NULL,
                canonical_smiles TEXT NOT NULL,
                reward REAL NOT NULL,
                PRIMARY KEY (scorer, scorer_version, context_hash, canonical_smiles)
            )
            """
        )
        connection.executemany(
            """
            INSERT INTO scorer_cache (
                scorer, scorer_version, context_hash, canonical_smiles, reward
            ) VALUES (?, ?, ?, ?, ?)
            ON CONFLICT (scorer, scorer_version, context_hash, canonical_smiles)
            DO UPDATE SET reward = excluded.reward
            """,
            [
                (scorer, scorer_version, context_hash, smiles, reward)
                for smiles, reward in entries
            ],
        )
    with connect(path) as connection:
        connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    return len(entries)


def read_scorer_cache(
    path: Path,
    *,
    scorer: str,
    scorer_version: str,
    context_hash: str,
) -> dict[str, float]:
    """Scores already stored for this Scorer, version, and scoring context."""
    if not path.is_file():
        return {}
    with connect(path) as connection:
        table = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'scorer_cache'"
        ).fetchone()
        if table is None:
            return {}
        rows = connection.execute(
            """
            SELECT canonical_smiles, reward
            FROM scorer_cache
            WHERE scorer = ? AND scorer_version = ? AND context_hash = ?
            """,
            (scorer, scorer_version, context_hash),
        ).fetchall()
    return {smiles: float(reward) for smiles, reward in rows}
