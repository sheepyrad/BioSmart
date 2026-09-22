# BioSmart Overhaul Plan

Status: **consensus reached 16 Sep 2026** after a five-round design review (Q1–Q47). Companion documents: `docs/biosmart-architecture-review.html` (evidence and diagrams), `CONTEXT.md` (glossary; terms below are used as defined there), `docs/adr/0001–0005` (architectural decisions).

Goal: a scientist on their own Linux GPU workstation goes from "nothing installed" to "first Run exported" without a terminal, YAML, or filesystem paths.

## Diagnosis in one paragraph

BioSmart is a research pipeline (`cgflow`) with a developer console (`cgflow-gui`) attached. The engine needs three mutually incompatible torch stacks (`cgflow` py3.11/torch 2.6–2.9, `flashaffinity` py3.11/torch 2.7.1, `fabind` py3.8/torch 1.12) bridged by `conda run`, weights from Google Drive and Hugging Face, a Building-block library that is not in the repo, and author-machine absolute paths in shipped configs. The GUI resolves `../../cgflow` via `__dirname`, spawns `conda run` on the host, re-implements the run contract in a 2,345-line `runner.ts` (regex on logs, BFS for CIFs, sql.js loading whole DBs), keeps a stale duplicate in `main.ts`, cannot be packaged, and has no readiness check, tests, lint or CI. The two halves are coupled where they should not be (filesystem) and uncoupled where they must be (schema, run state, events).

## Agreed decisions

| Topic | Decision |
|-------|----------|
| Topology | Solo Linux GPU workstation, always. Server binds `127.0.0.1` only; no token, no LAN mode. A shared-server topology is deferred and can be added without architectural change. |
| Distribution | One container image built from one `pixi.lock`; `pixi` host-native install from the same lockfile as fallback. `install.sh` checks for Docker + NVIDIA Container Toolkit and, with `--with-docker`, installs them on Ubuntu via sudo. |
| Hardware floor | Single GPU, 24 GB VRAM (RTX 3090 class). One Run executes at a time; others queue FIFO and can be cancelled. |
| Scorers | Two user-selectable Scorers: Boltz-2 and FlashBind. FABind+ is internal to FlashBind as its pose provider (pluggable seam; CGFlow-pose as alternative is lowest priority). UniDock/Vina code is retained for parity with upstream `tsa87/cgflow` but is not a product Scorer. Boltzina is deleted. |
| Building-block library | Built in-app from Enamine Catalog, Enamine Stock (different extraction scripts, user toggles which) or a plain `.smi`. Drug-like filter off by default, switchable. Several libraries coexist; newest is default; a Run records its library. Staleness reminder after a configurable 30 days, reminder only. No demo library ships; the Doctor's engine self-test is a `--dry-run`. |
| Pocket | v1: selected residues for Boltz-2, Reference ligand for FlashBind. Future: generator → Boltz-2 co-fold → use as Reference ligand. |
| Presets | Quick 100×16, Standard 1000×32, Thorough 2000×64. ETA derived from observed Scoring-round durations (`scoring_rounds` table), never hard-coded. Reference point: 64,000 Boltz-2 scorings ≈ 2 weeks on one RTX 3090 for a ~300 aa Target. |
| Inputs | Browser uploads plus a mounted `~/BioSmart/inputs` folder browsable in the UI. No arbitrary path access. |
| Outputs & retention | Nothing is deleted; all Scorer working files are retained. Runs root is user-configurable (may be a network drive). Exports: top-N SDF (route as SD tags) + CSV; archive Run as `.tar.zst`. |
| Network | Internet allowed for asset downloads (done once by the Doctor, never mid-Run). Boltz MSA server on by default, clearly labelled, switchable to uploaded `.a3m`. |
| Stop/Resume | For both Scorers: SIGTERM → checkpoint + Scorer cache flush → Paused; Resume is non-interactive. |
| Storage | Hybrid: engine-owned Run database per Run folder (source of truth) + rebuildable central Index in the registry (ADR-0003). Global Scorer cache keyed by context hash + canonical SMILES (ADR-0004). SQLite (WAL) throughout. |
| Provenance | Full: spec snapshot, seed, Library/Target/Pocket hashes, Pose-model hash, Scorer + FABind+ versions, exact Scorer command lines, MSA source with returned `.a3m` and hash, image digest, engine git SHA, GPU model, timings. |
| Legacy results | One-off importer for today's Boltz-2 result folders; low priority. |
| Process topology | One container; the server spawns the engine as a subprocess (one per Run) in the same container. Separate worker container deferred (compose change later, boundary kept clean). |
| Scorer workers | Persistent per-environment workers started at Run start, models loaded once, JSON-lines over stdin/stdout, die with the Run; Boltz-2 is a resident worker predicting in batches via its Python entry point; environments addressed by interpreter path, no `conda run` (ADR-0005). |
| Scorer interface | `Scorer.prepare(target, pocket) → context_hash`, `Scorer.score(round_no, candidates) → ScoreResult[]`, `Scorer.flush()`; FlashBind composes a `PoseProvider` (FABind+ default). UniDock/Vina do not implement it. |
| Server runtime | Fourth, torch-free `server` environment (FastAPI, RDKit, sqlite3) in the same image. Single uvicorn worker; supervisor and FIFO queue are in-process asyncio tasks with durable state in the registry. |
| Realtime transport | Server-Sent Events for server→browser events; REST for commands. |
| File ownership | Container runs as the invoking user (`--user uid:gid` set by `install.sh`). |
| Frontend | Keep React 18 + Vite + Tailwind/shadcn; port Mol*, ECharts, parallel coordinates, Candidates table into `features/*`; TS types generated from OpenAPI; hand-written wizard; small custom JSON-Schema renderer for Advanced; TanStack Query + small Zustand store; Node needed only at build time. |
| Day-to-day | Container starts at boot (`restart: unless-stopped`); installer drops a desktop launcher opening `http://127.0.0.1:8000`; `biosmart serve` also available. |
| Testing | `FakeScorer` (deterministic, CPU) so CI runs a whole Run through server → supervisor → engine → events → Index; recorded `events.jsonl` fixtures for ingest; UI tests against a mocked API; GPU integration as a manual pre-release checklist. |
| Repository | Submodule dissolved into the monorepo (no upstream sync). `experiments/`, `experimental/`, pretraining and multi-pocket scripts, Boltzina: tagged `research-archive` then removed from `main`. `wandb` removed from the product path. |
| Naming | `biosmart` for package, CLI, image and UI. CGFlow remains the method name; `cgflow`, `rxnflow`, `synthflow`, `gflownet` remain research-core package names. |
| Build | Solo developer. Phases ordered so each leaves the system usable; engine CLI and server are built together on the same spec/supervisor/event reader. UI last, generated from the schema. |

## Target architecture

```
browser on the workstation ──http://127.0.0.1:8000──▶ one container `biosmart` (runs as the user, starts at boot)
                                                      ├─ FastAPI server (env `server`, 1 uvicorn worker): doctor · assets · libraries · inputs · runs · search · events (SSE) · static SPA
                                                      │    in-process supervisor + FIFO GPU queue; registry + Index (SQLite WAL)
                                                      ├─ engine subprocess `biosmart run <spec.json>` (env `default`) → JSONL events, Run folder
                                                      │    persistent Scorer workers: Boltz-2 (resident, batched) · fabind (Pose provider) · flashaffinity (FlashBind)
                                                      ├─ envs baked in via pixi.lock: server · default (cgflow+boltz) · flashaffinity · fabind
                                                      └─ mounts: <Runs root>  ·  /data/assets  ·  ~/BioSmart/inputs
```

## Storage model

**Registry** (`biosmart.sqlite`, server-owned): `runs`, `run_queue`, `libraries`, `targets`, `settings`, `doctor_results`, `scorer_cache`, and the **Index**: `candidate_index(run_id, candidate_id, canonical_smiles, inchikey, status, best_score, …)`, `candidate_props(mw, logp, hbd, hba, tpsa, qed, sa, rings, lilly, pains, …)`, `candidate_fp(morgan2048)`.

**Run database** (`run.sqlite`, engine-owned, one per Run folder): `meta(schema_version, …)`, `candidates(id, iteration, round_no, canonical_smiles, status ∈ {scored, filtered, failed}, failure_reason, reward, route_json, pose_ref, temperature)`, `scores(candidate_id, scorer, affinity_*, probability_*, raw_json)`, `scoring_rounds(round_no, scorer, n_sent, n_ok, n_failed, secs, gpu_mem_peak)`, `iterations(iteration, loss, reward_avg, top10, top100, top1000, temperature_lo, temperature_hi, n_valid, secs, …every key the trainer logs today)`, `artifacts(candidate_id, kind, path)`.

**Run folder**: `spec.json`, `run.json`, `provenance.json`, `events.jsonl`, `run.sqlite`, `target/` (copied Target file, Pocket definition), `library.json`, `checkpoints/`, `poses/round_{N}.sdf`, `scorer/round_{N}/…` (retained in full). "Import Run" rebuilds the Index from a folder; "Archive Run" produces one `.tar.zst`.

**Descriptors and search**: computed once by the server at ingest; v1 supports substructure (RDKit over one Run) and similarity (Morgan fingerprints in the Index); scaffold grouping later. Routes are JSON blobs in v1.

**Later verification**: whether per-Candidate Target/MSA processing under Boltz-2 can be computed once per Run and shared (would cut Scorer working files by most of their volume).

## Doctor checks (v1)

1. NVIDIA driver, GPU model, VRAM ≥ 24 GB, GPU idle. 2. GPU visible inside the container. 3. Runs root configured, writable, free space (warn < 200 GB). 4. Each environment imports its key packages. 5. Assets present with matching checksums (Pose model, FABind+, FlashBind, Boltz-2 weights + CCD pre-warmed, ESM3 with HF token via Fix button). 6. At least one Building-block library; staleness reminder. 7. HF and MSA server reachable (informational). 8. Engine self-test `biosmart run --dry-run`.
Blocking Start: 1–6.

## Event vocabulary (engine → server, JSONL)

`run.started`, `iteration`, `round.started`, `round.finished`, `candidate`, `checkpoint`, `warning`, `run.paused`, `run.finished`, `run.failed`.

## CLI

`biosmart doctor` · `biosmart assets sync|list` · `biosmart library build <file> --source catalog|stock|smiles [--druglike]` · `biosmart run <spec.json> [--dry-run]` · `biosmart runs list|import <folder>|archive <id>` · `biosmart serve` · `biosmart export-schema`.

## API (v1)

| Endpoint | Purpose |
|----------|---------|
| `GET /api/v1/doctor`, `POST /doctor/fix/{id}` | Readiness checks with automatable fixes |
| `GET /api/v1/schema/run-spec` | JSON Schema + Presets; UI renders Advanced from it |
| `POST /api/v1/inputs`, `GET /inputs`, `GET /inputs/{id}/residues` | Upload or browse `~/BioSmart/inputs`; server-side residue parse for Mol* |
| `GET/POST /api/v1/libraries`, `POST /libraries/build` | Library list, build job with progress, staleness |
| `POST /api/v1/runs`, `POST /runs/{id}/{stop,resume,cancel}`, `DELETE /runs/{id}` | Lifecycle; FIFO queue |
| `GET /api/v1/runs/{id}/candidates?sort&filter&limit&cursor` | Server-side pagination and filtering over the Index |
| `GET /api/v1/runs/{id}/artifacts/{kind}/{candidate}` | Resolved from `artifacts`, not BFS |
| `GET /api/v1/runs/{id}/export?format=sdf|csv&top=N`, `POST /runs/{id}/archive`, `POST /runs/import` | Outputs and portability |
| `GET /api/v1/search?smarts=|similar_to=` | Cross-Run search over the Index |
| `GET /api/v1/events` (SSE) | Multiplexed JSONL events |

## Proposed repository layout

```
biosmart/
├── engine/                      # Python package "biosmart"; pixi workspace
│   ├── pyproject.toml           # [project.scripts] biosmart = "biosmart.cli:app"
│   ├── pixi.toml / pixi.lock    # environments: server (torch-free), default (cgflow+boltz), fabind, flashaffinity
│   └── src/
│       ├── biosmart/            # cli, spec, presets, doctor/, assets/, libraries/, server/ (FastAPI, SSE, registry+Index), jobs/ (in-process supervisor, queue), events, storage/, scorers/ (interface, boltz2, flashbind, worker protocol), poses/ (interface, fabind, cgflow later)
│       └── {cgflow,rxnflow,synthflow,gflownet}/   # research core (UniDock/Vina retained, Boltzina removed)
├── third_party/flashbind/       # vendored minus inference_examples
├── web/                         # React 18 + Vite + Tailwind/shadcn SPA; generated API client; builds into server/static
├── deploy/                      # Dockerfile, compose.yaml (user, restart policy, mounts), install.sh [--with-docker], desktop launcher
├── docs/                        # review, this plan, adr/
└── .github/workflows/           # python, web, image, schema-drift
```

## Roadmap

| Phase | Scope | Effort | Definition of done |
|-------|-------|--------|--------------------|
| 0 Hygiene | Dissolve submodule; tag `research-archive`; remove Boltzina, experiments, experimental, scratch blobs, wandb; declare `medchem`; pin git deps; fix `rxnflow` packaging; strip absolute paths; ruff/pytest/tsc/eslint CI; `pixi.toml` with four envs and a lockfile; replace `conda run` with interpreter paths | ~1 wk | Fresh clone → `pixi install` → NS5 Boltz-2 config runs headless |
| 1 Engine + server core | pydantic `RunSpec` + Presets; `biosmart` CLI; JSONL events; Run folder + Run database; SIGTERM checkpoint/resume for both Scorers; Scorer/PoseProvider interface with persistent workers (fabind, flashaffinity, resident batched Boltz-2); global Scorer cache; provenance; `FakeScorer`; Doctor; assets registry + sync (pose ckpt mirrored to HF); Library build job; FastAPI server in `server` env with registry, FIFO queue, in-process supervisor with reattach, Index ingest with descriptors/fingerprints, SSE, static SPA | ~4–5 wk | `biosmart doctor` green on the lab box; a Run started from the API streams events, survives server restart, resumes after Stop; CPU end-to-end test with `FakeScorer` passes in CI |
| 2 Image + installer | Dockerfile from lockfile; compose (runs as user, restart policy, mounts); `install.sh [--with-docker]`; desktop launcher; GHCR publish | ~1–2 wk | Clean Ubuntu 22.04 + GPU: `install.sh` → Doctor green → Quick Run completes with no editor |
| 3 UI | Doctor screen; Library screen (build, list, staleness); New Run wizard (Target → Pocket → Preset/Scorer → Start; Advanced from schema); Runs (queue, live progress, ETA, paginated Candidates, parallel coordinates, Mol* complex, search, export, archive); bundle RDKit locally; TanStack Query + small store; vitest + Playwright smoke; delete `cgflow-gui/electron/` | ~3–4 wk | A scientist with no terminal experience completes a Quick Run upload → exported SDF |
| 4 Low priority | Legacy Boltz-2 folder importer; Scorer working-file dedup verification; CGFlow-pose provider for FlashBind; scaffold grouping; relational route analytics | ongoing | — |

## Key evidence (paths in the current tree)

- Conda bridging and iJIT shim: `cgflow/src/synthflow/utils/conda_env.py`
- Env recipes: `README.md`, `cgflow/README.md` (conflicting torch pins), `cgflow/src/FlashBind/env.yaml`, `cgflow/src/FlashBind/FABind_plus/README.md`
- Undeclared dep `medchem`: `cgflow/scripts/opt/tasks/{boltz,flashbind}.py`
- Absolute paths: `cgflow/configs/opt/NS5_*.yaml` (`result_dir`, `hf_cache`), `cgflow/data/examples/NS5_crop_renum.yaml` (msa), `cgflow-gui/electron/runner.ts` FlashBind defaults
- Runner coupling: `cgflow-gui/electron/runner.ts` L37–83 (paths, spawn), L996–1007 and L1414–1425 (regexes), L1185–1311 (result-dir polling), L1170–1177 (orphans), L1875–1901 (BFS)
- Duplicate IPC path: `cgflow-gui/electron/main.ts` L322–524, L582–749
- Packaging gap: `cgflow-gui/package.json` `build.files`
- CDN RDKit: `cgflow-gui/index.html`
- Current result-dir contract: `cgflow/src/gflownet/utils/sqlite_log.py`, `cgflow/src/rxnflow/base/gflownet/sqlite_log.py` (`results`), `cgflow/src/synthflow/utils/boltz_reward_cache.py` (`entries`), `cgflow/scripts/opt/tasks/{boltz,flashbind}.py` (`*_scores_*` columns); Boltz-2 invoked per Candidate with `--output_format pdb --use_potentials` (`boltz.py` L571–605)
- Library build: `cgflow/data/scripts/{a_catalog_to_smi,a_stock_to_smi,a_refine_smi,b_druglike_filter,c_create_env}.py`; no demo library exists (`data/template/real/` is two YAML templates)
