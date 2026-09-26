"""Rebuildable Index of Candidates, and the queries over it.

The Run database inside the Run folder is the source of truth. The Index in
the Registry is derived from that database. Deleting the Index and importing
the Run folder restores the same Candidates.
"""

from __future__ import annotations

import base64
import gzip
import json
import math
import pickle
import shutil
import sqlite3
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import rdkit
from rdkit import Chem, DataStructs, RDLogger
from rdkit.Chem import Descriptors, QED, RDConfig, rdFingerprintGenerator, rdMolDescriptors
from rdkit.Chem.FilterCatalog import FilterCatalog, FilterCatalogParams

from biosmart.storage import connect

RDLogger.DisableLog("rdApp.error")
RDLogger.DisableLog("rdApp.warning")

_RUN_ID_ALPHABET = "0123456789abcdef"
_STATUSES = frozenset({"scored", "failed", "filtered"})
_IMPORT_STATUSES = frozenset({"paused", "finished", "failed"})
_SORTS = frozenset({"candidate_id", "best_score", "mw", "logp"})
_MAX_LIMIT = 200
_DEFAULT_SIMILARITY = 0.5
_MORGAN = rdFingerprintGenerator.GetMorganGenerator(radius=2, fpSize=2048)

_PAINS: FilterCatalog | None = None
_FRAGMENT_SCORES: dict[int, float] | None = None


class IndexQueryError(ValueError):
    """A page or search query cannot be answered."""


class IndexNotFound(Exception):
    """No Run with this id is in the Registry or the Index."""

    def __init__(self, run_id: str) -> None:
        super().__init__(run_id)
        self.run_id = run_id


class RunFolderError(ValueError):
    """The Run folder cannot be imported."""


@dataclass(frozen=True)
class Described:
    inchikey: str | None
    mw: float
    logp: float
    hbd: int
    hba: int
    tpsa: float
    qed: float
    sa: float
    rings: int
    pains: bool
    morgan: bytes


def rebuild_index(registry: Path, run_folder: Path) -> int:
    """Replace one Run's Index rows from its Run database."""
    if not isinstance(registry, Path):
        raise TypeError("registry must be a Path")
    if not isinstance(run_folder, Path):
        raise TypeError("run_folder must be a Path")
    if not run_folder.is_dir():
        raise ValueError("Run folder is missing")
    manifest = _read_manifest(run_folder / "run.json")
    run_id = manifest.get("run_id")
    if not isinstance(run_id, str) or not _valid_run_id(run_id):
        raise ValueError("Run manifest is missing its run id")
    database_path = run_folder / "run.sqlite"
    if not database_path.is_file():
        raise ValueError("Run folder is missing its Run database")

    with connect(database_path) as run_db:
        rows = run_db.execute(
            """
            SELECT id, canonical_smiles, status, failure_reason, reward
            FROM candidates
            ORDER BY id
            """
        ).fetchall()

    index_rows: list[tuple[Any, ...]] = []
    prop_rows: list[tuple[Any, ...]] = []
    fp_rows: list[tuple[Any, ...]] = []
    for candidate_id, smiles, status, failure_reason, reward in rows:
        described = describe(smiles) if isinstance(smiles, str) else None
        index_rows.append(
            (
                run_id,
                candidate_id,
                smiles,
                None if described is None else described.inchikey,
                status,
                reward,
                failure_reason,
            )
        )
        if described is None:
            prop_rows.append(
                (run_id, candidate_id, None, None, None, None, None, None, None, None, None)
            )
        else:
            prop_rows.append(
                (
                    run_id,
                    candidate_id,
                    described.mw,
                    described.logp,
                    described.hbd,
                    described.hba,
                    described.tpsa,
                    described.qed,
                    described.sa,
                    described.rings,
                    int(described.pains),
                )
            )
            fp_rows.append((run_id, candidate_id, described.morgan))

    registry.parent.mkdir(parents=True, exist_ok=True)
    with connect(registry) as connection:
        _ensure_schema(connection)
        connection.execute("DELETE FROM candidate_fp WHERE run_id = ?", (run_id,))
        connection.execute("DELETE FROM candidate_props WHERE run_id = ?", (run_id,))
        connection.execute("DELETE FROM candidate_index WHERE run_id = ?", (run_id,))
        connection.executemany(
            """
            INSERT INTO candidate_index (
                run_id, candidate_id, canonical_smiles, inchikey, status, best_score, failure_reason
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            index_rows,
        )
        connection.executemany(
            """
            INSERT INTO candidate_props (
                run_id, candidate_id, mw, logp, hbd, hba, tpsa, qed, sa, rings, pains
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            prop_rows,
        )
        connection.executemany(
            """
            INSERT INTO candidate_fp (run_id, candidate_id, morgan2048)
            VALUES (?, ?, ?)
            """,
            fp_rows,
        )
    with connect(registry) as connection:
        connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    return len(index_rows)


def import_run_folder(runs_root: Path, registry: Path, folder: Path) -> dict[str, Any]:
    """Copy a moved Run folder into the Runs root when needed, then rebuild its Index rows."""
    if not isinstance(runs_root, Path):
        raise TypeError("runs_root must be a Path")
    if not isinstance(registry, Path):
        raise TypeError("registry must be a Path")
    if not isinstance(folder, Path):
        raise TypeError("folder must be a Path")
    if not folder.is_dir():
        raise RunFolderError("Run folder is missing")
    manifest_path = folder / "run.json"
    database_path = folder / "run.sqlite"
    if not manifest_path.is_file() or not database_path.is_file():
        raise RunFolderError("Run folder is missing its manifest or Run database")
    manifest = _read_manifest(manifest_path)
    run_id = manifest.get("run_id")
    status = manifest.get("status")
    if not isinstance(run_id, str) or not _valid_run_id(run_id):
        raise RunFolderError("Run manifest is missing its run id")
    if status not in _IMPORT_STATUSES:
        raise RunFolderError("Import rebuilds a finished, failed, or Paused Run")
    if _registry_status(registry, run_id) == "running":
        raise RunFolderError("Import does not replace a running Run")

    runs_root.mkdir(parents=True, exist_ok=True)
    source = folder.resolve()
    destination = (runs_root / run_id).resolve()
    if source != destination:
        if destination.exists():
            shutil.rmtree(destination)
        shutil.copytree(source, destination)
    count = rebuild_index(registry, destination)
    return {
        "run_id": run_id,
        "status": str(status),
        "folder": str(destination),
        "candidates": count,
    }


def page_candidates(
    registry: Path,
    run_id: str,
    *,
    limit: int = 50,
    cursor: str | None = None,
    sort: str = "candidate_id",
    status: str | None = None,
    min_score: float | None = None,
    max_score: float | None = None,
    min_mw: float | None = None,
    max_mw: float | None = None,
    min_logp: float | None = None,
    max_logp: float | None = None,
) -> dict[str, Any]:
    """Page and filter one Run's Candidates from the Index."""
    if not isinstance(registry, Path):
        raise TypeError("registry must be a Path")
    if not isinstance(run_id, str) or not _valid_run_id(run_id):
        raise IndexNotFound(run_id)
    limit = _limit(limit)
    if sort not in _SORTS:
        raise IndexQueryError("sort must be candidate_id, best_score, mw, or logp")
    if status is not None and status not in _STATUSES:
        raise IndexQueryError("filter must be scored, failed, or filtered")
    min_score = _number("min_score", min_score)
    max_score = _number("max_score", max_score)
    min_mw = _number("min_mw", min_mw)
    max_mw = _number("max_mw", max_mw)
    min_logp = _number("min_logp", min_logp)
    max_logp = _number("max_logp", max_logp)
    decoded = _decode_cursor(cursor)
    if decoded is not None:
        if decoded.get("kind") != "page" or decoded.get("sort") != sort:
            raise IndexQueryError("cursor does not match this page")

    where = ["i.run_id = ?"]
    params: list[Any] = [run_id]
    if status is not None:
        where.append("i.status = ?")
        params.append(status)
    if min_score is not None:
        where.append("i.best_score >= ?")
        params.append(min_score)
    if max_score is not None:
        where.append("i.best_score <= ?")
        params.append(max_score)
    if min_mw is not None:
        where.append("p.mw >= ?")
        params.append(min_mw)
    if max_mw is not None:
        where.append("p.mw <= ?")
        params.append(max_mw)
    if min_logp is not None:
        where.append("p.logp >= ?")
        params.append(min_logp)
    if max_logp is not None:
        where.append("p.logp <= ?")
        params.append(max_logp)
    order_by = _page_order(sort)
    if decoded is not None:
        clause, cursor_params = _page_after(sort, decoded)
        where.append(clause)
        params.extend(cursor_params)

    sql = f"""
        SELECT
            i.run_id, i.candidate_id, i.canonical_smiles, i.inchikey, i.status,
            i.best_score, i.failure_reason,
            p.mw, p.logp, p.hbd, p.hba, p.tpsa, p.qed, p.sa, p.rings, p.pains
        FROM candidate_index AS i
        LEFT JOIN candidate_props AS p
            ON p.run_id = i.run_id AND p.candidate_id = i.candidate_id
        WHERE {' AND '.join(where)}
        ORDER BY {order_by}
        LIMIT ?
    """
    params.append(limit + 1)

    with _registry(registry) as connection:
        if not _run_known(connection, run_id):
            raise IndexNotFound(run_id)
        if not _table_exists(connection, "candidate_index"):
            return {"candidates": [], "next_cursor": None}
        rows = connection.execute(sql, params).fetchall()

    page = rows[:limit]
    next_cursor = None
    if len(rows) > limit and page:
        next_cursor = _encode_cursor(_page_cursor(sort, page[-1]))
    return {
        "candidates": [_candidate_payload(row) for row in page],
        "next_cursor": next_cursor,
    }


def search_candidates(
    registry: Path,
    *,
    smarts: str | None = None,
    similar_to: str | None = None,
    threshold: float | None = None,
    limit: int = 50,
    cursor: str | None = None,
) -> dict[str, Any]:
    """Substructure and similarity search across every Run in the Index."""
    if not isinstance(registry, Path):
        raise TypeError("registry must be a Path")
    limit = _limit(limit)
    if smarts is not None and not isinstance(smarts, str):
        raise TypeError("smarts must be a string")
    if similar_to is not None and not isinstance(similar_to, str):
        raise TypeError("similar_to must be a string")
    query_smarts = None if smarts is None or not smarts.strip() else smarts.strip()
    query_smiles = None if similar_to is None or not similar_to.strip() else similar_to.strip()
    if query_smarts is None and query_smiles is None:
        raise IndexQueryError("smarts or similar_to is required")
    if threshold is not None and query_smiles is None:
        raise IndexQueryError("threshold requires similar_to")
    pattern = None
    if query_smarts is not None:
        pattern = Chem.MolFromSmarts(query_smarts)
        if pattern is None:
            raise IndexQueryError("substructure query is not valid SMARTS")
    query_fp = None
    effective_threshold = None
    if query_smiles is not None:
        parsed = Chem.MolFromSmiles(query_smiles)
        if parsed is None:
            raise IndexQueryError("similarity query is not valid SMILES")
        query_fp = _MORGAN.GetFingerprint(parsed)
        effective_threshold = _DEFAULT_SIMILARITY if threshold is None else _number("threshold", threshold)
        if effective_threshold is None or effective_threshold < 0 or effective_threshold > 1:
            raise IndexQueryError("threshold must be between 0 and 1")

    decoded = _decode_cursor(cursor)
    if decoded is not None:
        if decoded.get("kind") != "search":
            raise IndexQueryError("cursor does not match this search")
        if decoded.get("smarts") != query_smarts or decoded.get("similar_to") != query_smiles:
            raise IndexQueryError("cursor does not match this search")
        if decoded.get("threshold") != effective_threshold:
            raise IndexQueryError("cursor does not match this search")

    matches: list[dict[str, Any]] = []
    with _registry(registry) as connection:
        if not _table_exists(connection, "candidate_index"):
            return {"candidates": [], "next_cursor": None}
        rows = connection.execute(
            """
            SELECT
                i.run_id, i.candidate_id, i.canonical_smiles, i.inchikey, i.status,
                i.best_score, i.failure_reason,
                p.mw, p.logp, p.hbd, p.hba, p.tpsa, p.qed, p.sa, p.rings, p.pains,
                f.morgan2048
            FROM candidate_index AS i
            LEFT JOIN candidate_props AS p
                ON p.run_id = i.run_id AND p.candidate_id = i.candidate_id
            LEFT JOIN candidate_fp AS f
                ON f.run_id = i.run_id AND f.candidate_id = i.candidate_id
            ORDER BY i.run_id, i.candidate_id
            """
        ).fetchall()

    for row in rows:
        similarity = None
        if pattern is not None:
            parsed = Chem.MolFromSmiles(row["canonical_smiles"])
            if parsed is None or not parsed.HasSubstructMatch(pattern):
                continue
        if query_fp is not None:
            blob = row["morgan2048"]
            if blob is None:
                continue
            if isinstance(blob, memoryview):
                blob = blob.tobytes()
            similarity = float(DataStructs.TanimotoSimilarity(query_fp, DataStructs.CreateFromBinaryText(blob)))
            if effective_threshold is None or similarity < effective_threshold:
                continue
        matches.append(_candidate_payload(row, similarity=similarity, include_similarity=True))

    matches.sort(key=_search_key)
    if decoded is not None:
        cursor_key = _search_key_from_cursor(decoded)
        matches = [item for item in matches if _search_key(item) > cursor_key]

    page = matches[:limit]
    next_cursor = None
    if len(matches) > limit and page:
        last = page[-1]
        next_cursor = _encode_cursor(
            {
                "kind": "search",
                "smarts": query_smarts,
                "similar_to": query_smiles,
                "threshold": effective_threshold,
                "similarity": last.get("similarity"),
                "run_id": last["run_id"],
                "candidate_id": last["candidate_id"],
            }
        )
    return {"candidates": page, "next_cursor": next_cursor}


def describe(smiles: str) -> Described | None:
    """Descriptors and a Morgan fingerprint for one Candidate. None when SMILES does not parse."""
    if not isinstance(smiles, str) or not smiles:
        return None
    parsed = Chem.MolFromSmiles(smiles)
    if parsed is None:
        return None
    inchikey: str | None
    try:
        inchikey = Chem.MolToInchiKey(parsed)
    except (ValueError, RuntimeError):
        inchikey = None
    if not inchikey:
        inchikey = None
    return Described(
        inchikey=inchikey,
        mw=float(Descriptors.MolWt(parsed)),
        logp=float(Descriptors.MolLogP(parsed)),
        hbd=int(Descriptors.NumHDonors(parsed)),
        hba=int(Descriptors.NumHAcceptors(parsed)),
        tpsa=float(Descriptors.TPSA(parsed)),
        qed=float(QED.qed(parsed)),
        sa=float(_synthetic_accessibility(parsed)),
        rings=int(rdMolDescriptors.CalcNumRings(parsed)),
        pains=bool(_pains_catalog().HasMatch(parsed)),
        morgan=DataStructs.BitVectToBinaryText(_MORGAN.GetFingerprint(parsed)),
    )


def _fragment_score_path() -> Path:
    candidates = (
        Path(RDConfig.RDContribDir) / "SA_Score" / "fpscores.pkl.gz",
        Path(rdkit.__file__).resolve().parent / "Contrib" / "SA_Score" / "fpscores.pkl.gz",
    )
    for path in candidates:
        if path.is_file():
            return path
    raise FileNotFoundError("SA fragment scores are missing")


def _fragment_scores() -> dict[int, float]:
    """Ertl fragment contributions shipped with RDKit."""
    global _FRAGMENT_SCORES
    if _FRAGMENT_SCORES is not None:
        return _FRAGMENT_SCORES
    with gzip.open(_fragment_score_path(), "rb") as handle:
        raw = pickle.load(handle)  # RDKit's fragment table is a pickle.
    if not isinstance(raw, list) or not raw:
        raise ValueError("SA fragment scores are unreadable")
    scores: dict[int, float] = {}
    for row in raw:
        if not isinstance(row, (list, tuple)) or len(row) < 2:
            raise ValueError("SA fragment scores are unreadable")
        value = float(row[0])
        for bit in row[1:]:
            scores[int(bit)] = value
    if not scores:
        raise ValueError("SA fragment scores are empty")
    _FRAGMENT_SCORES = scores
    return scores


def _synthetic_accessibility(parsed: Chem.Mol) -> float:
    """Ertl SA score using the RDKit fragment-score table."""
    scores = _fragment_scores()
    try:
        fingerprint = rdMolDescriptors.GetMorganFingerprint(parsed, 2)
    except RuntimeError:
        return 9.99
    counts = fingerprint.GetNonzeroElements()
    fragment_count = 0
    fragment_score = 0.0
    for bit_id, count in counts.items():
        fragment_count += count
        fragment_score += scores.get(int(bit_id), -4.0) * count
    if fragment_count == 0:
        return 9.99
    fragment_score /= fragment_count

    atom_count = parsed.GetNumAtoms()
    chiral_centers = len(Chem.FindMolChiralCenters(parsed, includeUnassigned=True))
    ring_info = parsed.GetRingInfo()
    spiro = rdMolDescriptors.CalcNumSpiroAtoms(parsed)
    bridgeheads = rdMolDescriptors.CalcNumBridgeheadAtoms(parsed)
    macrocycles = sum(1 for ring in ring_info.AtomRings() if len(ring) > 8)
    size_penalty = atom_count**1.005 - atom_count
    feature_score = 0.0 - size_penalty
    feature_score -= math.log10(chiral_centers + 1)
    feature_score -= math.log10(spiro + 1)
    feature_score -= math.log10(bridgeheads + 1)
    if macrocycles > 0:
        feature_score -= math.log10(2)
    density_score = 0.0
    if atom_count > len(counts):
        density_score = math.log(float(atom_count) / len(counts)) * 0.5
    raw = fragment_score + feature_score + density_score
    score = 11.0 - (raw - (-4.0) + 1) / (2.5 - (-4.0)) * 9.0
    if score > 8.0:
        score = 8.0 + math.log(score + 1.0 - 9.0)
    if score > 10.0:
        return 10.0
    if score < 1.0:
        return 1.0
    return score


def _pains_catalog() -> FilterCatalog:
    global _PAINS
    if _PAINS is None:
        params = FilterCatalogParams()
        params.AddCatalog(FilterCatalogParams.FilterCatalogs.PAINS)
        _PAINS = FilterCatalog(params)
    return _PAINS


def _ensure_schema(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS candidate_index (
            run_id TEXT NOT NULL,
            candidate_id TEXT NOT NULL,
            canonical_smiles TEXT NOT NULL,
            inchikey TEXT,
            status TEXT NOT NULL,
            best_score REAL,
            failure_reason TEXT,
            PRIMARY KEY (run_id, candidate_id)
        )
        """
    )
    columns = {row[1] for row in connection.execute("PRAGMA table_info(candidate_index)")}
    if "failure_reason" not in columns:
        connection.execute("ALTER TABLE candidate_index ADD COLUMN failure_reason TEXT")
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS candidate_props (
            run_id TEXT NOT NULL,
            candidate_id TEXT NOT NULL,
            mw REAL,
            logp REAL,
            hbd INTEGER,
            hba INTEGER,
            tpsa REAL,
            qed REAL,
            sa REAL,
            rings INTEGER,
            pains INTEGER,
            PRIMARY KEY (run_id, candidate_id),
            FOREIGN KEY (run_id, candidate_id)
                REFERENCES candidate_index (run_id, candidate_id)
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS candidate_fp (
            run_id TEXT NOT NULL,
            candidate_id TEXT NOT NULL,
            morgan2048 BLOB NOT NULL,
            PRIMARY KEY (run_id, candidate_id),
            FOREIGN KEY (run_id, candidate_id)
                REFERENCES candidate_index (run_id, candidate_id)
        )
        """
    )


@contextmanager
def _registry(registry: Path) -> Iterator[sqlite3.Connection]:
    connection = connect(registry)
    connection.row_factory = sqlite3.Row
    try:
        yield connection
    finally:
        connection.close()


def _table_exists(connection: sqlite3.Connection, name: str) -> bool:
    row = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (name,),
    ).fetchone()
    return row is not None


def _run_known(connection: sqlite3.Connection, run_id: str) -> bool:
    if _table_exists(connection, "runs"):
        row = connection.execute("SELECT 1 FROM runs WHERE run_id = ?", (run_id,)).fetchone()
        if row is not None:
            return True
    if _table_exists(connection, "candidate_index"):
        row = connection.execute(
            "SELECT 1 FROM candidate_index WHERE run_id = ? LIMIT 1",
            (run_id,),
        ).fetchone()
        if row is not None:
            return True
    return False


def _registry_status(registry: Path, run_id: str) -> str | None:
    if not registry.is_file():
        return None
    with connect(registry) as connection:
        if not _table_exists(connection, "runs"):
            return None
        row = connection.execute("SELECT status FROM runs WHERE run_id = ?", (run_id,)).fetchone()
    if row is None:
        return None
    status = row[0]
    return status if isinstance(status, str) else None


def _read_manifest(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise ValueError("Run folder is missing its manifest")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Run manifest is not an object")
    return payload


def _valid_run_id(run_id: str) -> bool:
    return len(run_id) == 32 and all(character in _RUN_ID_ALPHABET for character in run_id)


def _limit(limit: int) -> int:
    if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1 or limit > _MAX_LIMIT:
        raise IndexQueryError("limit must be between 1 and 200")
    return limit


def _number(name: str, value: float | None) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise IndexQueryError(f"{name} must be a number")
    if isinstance(value, float) and not math.isfinite(value):
        raise IndexQueryError(f"{name} must be a number")
    return float(value)


def _page_order(sort: str) -> str:
    if sort == "candidate_id":
        return "i.candidate_id ASC"
    if sort == "best_score":
        return "i.best_score IS NULL, i.best_score DESC, i.candidate_id ASC"
    if sort == "mw":
        return "p.mw IS NULL, p.mw ASC, i.candidate_id ASC"
    return "p.logp IS NULL, p.logp ASC, i.candidate_id ASC"


def _page_after(sort: str, cursor: Mapping[str, Any]) -> tuple[str, list[Any]]:
    candidate_id = cursor.get("candidate_id")
    if not isinstance(candidate_id, str) or not candidate_id:
        raise IndexQueryError("cursor is invalid")
    if sort == "candidate_id":
        return "i.candidate_id > ?", [candidate_id]
    column = {"best_score": "i.best_score", "mw": "p.mw", "logp": "p.logp"}[sort]
    value = cursor.get(sort)
    if value is None:
        return f"{column} IS NULL AND i.candidate_id > ?", [candidate_id]
    number = _number(sort, value)
    return (
        f"({column} > ? OR ({column} = ? AND i.candidate_id > ?) OR {column} IS NULL)"
        if sort != "best_score"
        else f"({column} < ? OR ({column} = ? AND i.candidate_id > ?) OR {column} IS NULL)",
        [number, number, candidate_id],
    )


def _page_cursor(sort: str, row: sqlite3.Row) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "kind": "page",
        "sort": sort,
        "candidate_id": row["candidate_id"],
    }
    if sort == "best_score":
        payload["best_score"] = row["best_score"]
    elif sort == "mw":
        payload["mw"] = row["mw"]
    elif sort == "logp":
        payload["logp"] = row["logp"]
    return payload


def _candidate_payload(
    row: sqlite3.Row,
    *,
    similarity: float | None = None,
    include_similarity: bool = False,
) -> dict[str, Any]:
    pains = row["pains"]
    payload: dict[str, Any] = {
        "run_id": row["run_id"],
        "candidate_id": row["candidate_id"],
        "canonical_smiles": row["canonical_smiles"],
        "inchikey": row["inchikey"],
        "status": row["status"],
        "best_score": row["best_score"],
        "failure_reason": row["failure_reason"],
        "mw": row["mw"],
        "logp": row["logp"],
        "hbd": row["hbd"],
        "hba": row["hba"],
        "tpsa": row["tpsa"],
        "qed": row["qed"],
        "sa": row["sa"],
        "rings": row["rings"],
        "pains": None if pains is None else bool(pains),
    }
    if include_similarity:
        payload["similarity"] = similarity
    return payload


def _search_key(item: Mapping[str, Any]) -> tuple[float, str, str]:
    similarity = item.get("similarity")
    rank = -(float(similarity) if isinstance(similarity, (int, float)) else -1.0)
    return (rank, str(item["run_id"]), str(item["candidate_id"]))


def _search_key_from_cursor(cursor: Mapping[str, Any]) -> tuple[float, str, str]:
    run_id = cursor.get("run_id")
    candidate_id = cursor.get("candidate_id")
    if not isinstance(run_id, str) or not isinstance(candidate_id, str):
        raise IndexQueryError("cursor is invalid")
    similarity = cursor.get("similarity")
    if similarity is not None and not isinstance(similarity, (int, float)):
        raise IndexQueryError("cursor is invalid")
    return _search_key(
        {"similarity": similarity, "run_id": run_id, "candidate_id": candidate_id}
    )


def _encode_cursor(payload: Mapping[str, Any]) -> str:
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True, allow_nan=False).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _decode_cursor(cursor: str | None) -> dict[str, Any] | None:
    if cursor is None:
        return None
    if not isinstance(cursor, str) or not cursor:
        raise IndexQueryError("cursor is invalid")
    padded = cursor + "=" * (-len(cursor) % 4)
    try:
        payload = json.loads(base64.urlsafe_b64decode(padded.encode()))
    except (ValueError, json.JSONDecodeError):
        raise IndexQueryError("cursor is invalid") from None
    if not isinstance(payload, dict):
        raise IndexQueryError("cursor is invalid")
    return payload
