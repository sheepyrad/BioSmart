"""Engine-side Boltz-2 Scorer. Speaks JSON-lines to one persistent worker."""

from __future__ import annotations

import os
from pathlib import Path

from biosmart.scoring import Candidate, ScoreResult
from biosmart.worker import StdioWorker
from biosmart.spec import PocketSpec, TargetSpec
from biosmart.storage import flush_scorer_cache, read_scorer_cache

_LARGE_DISK_CACHES = (
    Path("/media/backup/p2-conrad/hf_cache"),
    Path("/media/data/conrad_hku/hf_cache"),
)
_LARGE_DISK_BOLTZ = Path("/media/backup/p2-conrad/boltz_cache")


def hf_cache_dir() -> Path:
    """Hugging Face cache on a large disk. Never the home-directory cache."""
    override = os.environ.get("HF_HUB_CACHE") or os.environ.get("HF_HOME")
    if override:
        path = Path(override).expanduser()
        path.mkdir(parents=True, exist_ok=True)
        return path
    for candidate in _LARGE_DISK_CACHES:
        if candidate.is_dir() or candidate.parent.is_dir():
            candidate.mkdir(parents=True, exist_ok=True)
            return candidate
    raise RuntimeError("Set HF_HUB_CACHE to a large-disk Hugging Face cache")


def boltz_weight_cache() -> Path:
    override = os.environ.get("BOLTZ_CACHE")
    if override:
        return Path(override).expanduser()
    if (_LARGE_DISK_BOLTZ / "boltz2_conf.ckpt").is_file():
        return _LARGE_DISK_BOLTZ
    raise RuntimeError("Set BOLTZ_CACHE to a large-disk Boltz-2 weight cache")


def default_boltz_python() -> Path:
    override = os.environ.get("BIOSMART_BOLTZ_PYTHON")
    if override:
        return Path(override)
    repo = Path(__file__).resolve().parents[3]
    return repo / ".pixi" / "envs" / "default" / "bin" / "python"


_CUDA_STUB_DIRS = (
    Path("/usr/local/cuda/lib64/stubs"),
    Path("/usr/local/cuda/targets/x86_64-linux/lib/stubs"),
)


def cuda_link_dir() -> Path | None:
    """Directory with unversioned libcuda.so so Triton can link `-lcuda`.

    The driver ships `libcuda.so.1`. GCC looks for `libcuda.so`, which on this
    host lives only in the CUDA stub directory.
    """
    for entry in os.environ.get("LIBRARY_PATH", "").split(os.pathsep):
        if entry and (Path(entry) / "libcuda.so").is_file():
            return Path(entry)
    for candidate in _CUDA_STUB_DIRS:
        if (candidate / "libcuda.so").is_file():
            return candidate
    return None


def worker_environment() -> dict[str, str]:
    """Environment for the persistent Boltz-2 worker process."""
    src = Path(__file__).resolve().parents[1]
    env = os.environ.copy()
    env["PYTHONPATH"] = str(src) + os.pathsep + env.get("PYTHONPATH", "")
    env["PYTHONUNBUFFERED"] = "1"
    env["BOLTZ_CACHE"] = str(boltz_weight_cache())
    hf_cache = str(hf_cache_dir())
    env["HF_HUB_CACHE"] = hf_cache
    env["HF_HOME"] = hf_cache
    env["HUGGINGFACE_HUB_CACHE"] = hf_cache
    env.setdefault("TMPDIR", "/media/backup/p2-conrad/tmp")
    env.setdefault("PYTORCH_CUDA_ALLOC_CONF", "max_split_size_mb:512")
    if env.get("CUDA_VISIBLE_DEVICES") == "":
        del env["CUDA_VISIBLE_DEVICES"]
    link_dir = cuda_link_dir()
    if link_dir is not None:
        current = env.get("LIBRARY_PATH", "")
        prefix = str(link_dir)
        if prefix not in current.split(os.pathsep):
            env["LIBRARY_PATH"] = prefix + (os.pathsep + current if current else "")
    tmp = Path(env["TMPDIR"])
    tmp.mkdir(parents=True, exist_ok=True)
    env.setdefault("TRITON_CACHE_DIR", str(tmp.parent / "triton_cache"))
    Path(env["TRITON_CACHE_DIR"]).mkdir(parents=True, exist_ok=True)
    return env


class Boltz2WorkerScorer:
    """Boltz-2 Scorer backed by one worker process for the Run."""

    name = "boltz2"

    def __init__(
        self,
        *,
        work_dir: Path,
        cache_path: Path,
        msa: Path | None,
        seed: int,
        python: Path | None = None,
    ) -> None:
        self._work_dir = work_dir
        self._cache_path = cache_path
        self._msa = msa
        self._seed = seed
        self._python = python or default_boltz_python()
        self._worker: StdioWorker | None = None
        self._context_hash: str | None = None
        self._pending: list[tuple[str, float]] = []
        self.version = "0"
        self.gpu: str | None = None
        self.model_loads = 0
        self.prediction_calls = 0
        self.interpreter = str(self._python)

    def prepare(self, target: TargetSpec, pocket: PocketSpec) -> str:
        if not target.sequence or not target.sequence.strip():
            raise ValueError("Boltz-2 Target needs a sequence")
        if not pocket.residues:
            raise ValueError("Boltz-2 Pocket is selected residues")
        worker = self._ensure_worker()
        response = worker.call(
            {
                "op": "prepare",
                "scorer": "boltz2",
                "seed": self._seed,
                "ordinal": 0,
                "target": {
                    "name": target.name,
                    "sequence": target.sequence.strip(),
                    "msa": str(self._msa) if self._msa is not None else None,
                },
                "pocket": {"residues": list(pocket.residues)},
                "cache_dir": str(boltz_weight_cache()),
                "work_dir": str(self._work_dir),
            }
        )
        self._context_hash = str(response["context_hash"])
        self.version = str(response["version"])
        self.gpu = response.get("gpu") if isinstance(response.get("gpu"), str) else None
        self.model_loads = int(response["model_loads"])
        self.prediction_calls = int(response["prediction_calls"])
        return self._context_hash

    def score(self, round_no: int, candidates: list[Candidate]) -> list[ScoreResult]:
        if self._context_hash is None:
            raise RuntimeError("Boltz-2 prepare must run before score")
        cached = read_scorer_cache(
            self._cache_path,
            scorer=self.name,
            scorer_version=self.version,
            context_hash=self._context_hash,
        )
        misses = [candidate for candidate in candidates if candidate.canonical_smiles not in cached]
        fresh: dict[str, ScoreResult] = {}
        if misses:
            response = self._ensure_worker().call(
                {
                    "op": "score",
                    "round_no": round_no,
                    "candidates": [
                        {
                            "candidate_id": candidate.candidate_id,
                            "canonical_smiles": candidate.canonical_smiles,
                            "iteration": candidate.iteration,
                            "round_no": candidate.round_no,
                        }
                        for candidate in misses
                    ],
                }
            )
            self.model_loads = int(response["model_loads"])
            self.prediction_calls = int(response["prediction_calls"])
            for item in response["results"]:
                raw = item.get("raw")
                result = ScoreResult(
                    candidate_id=str(item["candidate_id"]),
                    canonical_smiles=str(item["canonical_smiles"]),
                    status=str(item["status"]),
                    reward=None if item["reward"] is None else float(item["reward"]),
                    failure_reason=None if item.get("failure_reason") is None else str(item["failure_reason"]),
                    raw=raw if isinstance(raw, dict) else None,
                )
                fresh[result.canonical_smiles] = result
                if result.status == "scored" and result.reward is not None:
                    self._pending.append((result.canonical_smiles, result.reward))
        results: list[ScoreResult] = []
        for candidate in candidates:
            if candidate.canonical_smiles in cached:
                reward = cached[candidate.canonical_smiles]
                results.append(
                    ScoreResult(
                        candidate_id=candidate.candidate_id,
                        canonical_smiles=candidate.canonical_smiles,
                        status="scored",
                        reward=reward,
                    )
                )
                continue
            found = fresh.get(candidate.canonical_smiles)
            if found is None:
                results.append(
                    ScoreResult(
                        candidate_id=candidate.candidate_id,
                        canonical_smiles=candidate.canonical_smiles,
                        status="failed",
                        reward=None,
                        failure_reason="Boltz-2 did not return a score",
                    )
                )
                continue
            results.append(
                ScoreResult(
                    candidate_id=candidate.candidate_id,
                    canonical_smiles=candidate.canonical_smiles,
                    status=found.status,
                    reward=found.reward,
                    failure_reason=found.failure_reason,
                    raw=found.raw,
                )
            )
        return results

    def flush(self) -> int:
        if self._context_hash is None:
            raise ValueError("prepare before flush")
        response = self._ensure_worker().call({"op": "flush"})
        self.model_loads = int(response["model_loads"])
        self.prediction_calls = int(response["prediction_calls"])
        gpu = response.get("gpu")
        if isinstance(gpu, str):
            self.gpu = gpu
        raw_cache = response.get("cache")
        written = response.get("entries")
        if isinstance(written, bool) or not isinstance(written, int) or written < 0:
            raise ValueError("worker flush did not return an entry count")
        if not isinstance(raw_cache, list) or len(raw_cache) != written:
            raise ValueError("worker flush did not return the cache entries")
        entries: list[tuple[str, float]] = []
        for item in raw_cache:
            if not isinstance(item, dict):
                raise ValueError("worker flush cache entry is invalid")
            smiles = item.get("canonical_smiles")
            reward = item.get("reward")
            if not isinstance(smiles, str) or isinstance(reward, bool) or not isinstance(reward, (int, float)):
                raise ValueError("worker flush cache entry is invalid")
            entries.append((smiles, float(reward)))
        recorded = flush_scorer_cache(
            self._cache_path,
            scorer=self.name,
            scorer_version=self.version,
            context_hash=self._context_hash,
            entries=entries,
        )
        self._pending.clear()
        self.close()
        return recorded

    def close(self) -> None:
        if self._worker is not None:
            self._worker.close()
            self._worker = None

    def _worker_alive(self) -> bool:
        return self._worker is not None and self._worker.running()

    def _ensure_worker(self) -> StdioWorker:
        if self._worker is not None and self._worker_alive():
            return self._worker
        python = self._python
        if not python.is_file():
            raise FileNotFoundError(
                "pixi default interpreter is missing at "
                f"{python}. Install it with `pixi install -e default`."
            )
        env = worker_environment()
        self._worker = StdioWorker(
            [str(python), "-u", "-m", "biosmart", "worker", "--stdio"],
            env=env,
            log_path=self._work_dir / "worker.log",
        )
        return self._worker
