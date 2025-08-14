## Event-driven, DB-backed pipeline plan

### Objectives
- **Replace** the current mostly sequential, file-backed flow with an **event-driven**, SQL-backed pipeline.
- **Generate** molecules until a target number of unique compounds is reached (deduplicated at write-time).
- **Continuously queue and process** retrosynthesis from the DB rather than fixed ticks.
- **Batch** medchem filtering and Uni-Dock docking for throughput; Boltz-2 is pocket-conditioned and always proceeds to docking.
- **Persist** per-stage outcomes, per-filter decisions, and full lineage for auditability and analytics.

### Non-goals
- No tick-based scheduler. Workers should react to events (DB NOTIFY) and dequeue tasks with backpressure.

### Components
- **PostgreSQL** (system of record + event bus via LISTEN/NOTIFY).
- **Workers** (long-running processes): `generator`, `retrosyn_worker`, `medchem_worker`, `boltz2_worker`, `unidock_worker`, optional `leaderboard`.
- **CLI entrypoint** `pipeline_eventdriven.py` to run selected workers or run-all.
- **Conda envs** per tool via `utils/environment_manager.env_manager`.

### Backend tech stack
- **Language/runtime**: Python 3.10+ (Conda-managed; activate `drug_pipeline`).
- **Database**: PostgreSQL 14+ with `jsonb`, GIN indexes; optional RDKit cartridge if needed for chem-aware indexing (future).
- **DB access**: SQLAlchemy 2.x (ORM + Core) with psycopg2-binary; Alembic for migrations.
- **Eventing**: PostgreSQL `LISTEN/NOTIFY` via psycopg2 (async notification loop); durable queue in `tasks` table using `SELECT … FOR UPDATE SKIP LOCKED`.
- **Serialization/validation**: Pydantic 2.x for task payloads and event schemas.
- **Cheminformatics**: RDKit (SMILES canonicalization, InChIKey), Datamol; `medchem` library for filters.
- **ML/Tools integration**:
  - Synformer (retrosynthesis) via dedicated conda env `synformer-env`.
  - Boltz-2 via env `boltz-env`.
  - Uni-Dock and utilities via env `unidock-env`.
  - All invoked using `utils.environment_manager.env_manager` (ensure env names here align with the mappings in `utils/environment_manager.py`).
- **GPU and resources**: CUDA-capable machines; memory checks via `utils.gpu_memory_manager`.
- **Data processing**: pandas, numpy.
- **Logging/Observability**: Python `logging` + `utils.logging_utils` rotating handlers; optional Prometheus exporters (future); structured JSON logs optional.
- **Plotting (medchem artifacts)**: matplotlib, seaborn (Agg backend).
- **Filesystem layout**: results and artifacts under `outputs/` with per-stage subfolders; paths persisted in DB.

### Data model (initial schema)
- `molecules`:
  - `id` PK, `smiles` text, `inchikey` text UNIQUE, `generation` int, `barcode` text, `status` text, `source` text, `created_at` timestamptz
- `variants`:
  - `id` PK, `molecule_id` FK, `smiles` text, `barcode` text, `score` float, `status` text, `created_at` timestamptz
- `medchem_results`:
  - `variant_id` FK,
  - `n_rules_pass` int,
  - `n_structural_pass` int,
  - `rule_threshold` int,
  - `structural_threshold` int,
  - `filter_flags_json` jsonb,                 # map of each rule/alert/filter -> boolean pass/fail
  - `passed_rule_names` text[],
  - `failed_rule_names` text[],
  - `passed_structural_names` text[],
  - `failed_structural_names` text[],
  - `plots_json` jsonb,                        # file paths for heatmap and histograms
  - `passed` bool,
  - `created_at` timestamptz
- `boltz2_results`:
  - `variant_id` FK,
  - `affinity_pred_value` float,
  - `affinity_probability_binary` float,
  - `affinity_pred_value1` float,
  - `affinity_probability_binary1` float,
  - `affinity_pred_value2` float,
  - `affinity_probability_binary2` float,
  - `screening_score` float,                        # computed: max((−affinity_pred_value1 + 2)/4, 0) * affinity_probability_binary
  - `pocket_residues` int[],
  - `passed` bool,                                  # pocket-conditioned; always true by design
  - `created_at` timestamptz
- `docking_results`:
  - `variant_id` FK,
  - `best_score_kcal_mol` float,                    # most negative energy among all poses
  - `pose_count` int,
  - `result_file` text,
  - `all_scores` jsonb,                             # list of all pose energies
  - `search_mode` text,
  - `created_at` timestamptz
- `tasks`:
  - `id` PK, `type` text, `payload` jsonb, `status` text, `priority` int, `available_at` timestamptz, `attempts` int, `error` text, `updated_at`
- Indices: `molecules(inchikey)`, `variants(molecule_id)`, `tasks(type,status,available_at)`, GIN on json fields.

### Events and channels
- Use a single `tasks` table for durable queueing and `NOTIFY <task_type>` for wake-ups.
- Event types (NOTIFY channels): `retrosynthesis`, `medchem`, `boltz2`, `docking`.
- Workers `LISTEN` channels and dequeue with `SELECT ... FOR UPDATE SKIP LOCKED`.

### End-to-end flow
1. **Generation (target unique loop)**
   - Generate molecules via chosen model (DiffSBDD/Pocket2Mol/CGFlow).
   - Normalize with RDKit, compute InChIKey, `UPSERT` into `molecules` (dedupe by InChIKey).
   - If insert was new, enqueue `retrosynthesis(molecule_id)` and `NOTIFY retrosynthesis`.
   - Stop when `COUNT(DISTINCT inchikey) >= TARGET_UNIQUE`.

2. **Retrosynthesis (continuous queue)**
   - Dequeue molecules; run Synformer via `env_manager`.
   - Create `variants` for outputs; filter by retrosynthesis score threshold, stores them to DB; set `status='PASSSCORE'` for survivors.
   - Enqueue `medchem` with a list of variant IDs (or per-variant) and `NOTIFY medchem`.

3. **Medchem (batched)**
   - Buffer variants until `batch_size` or `batch_timeout`.
   - Run `utils.medchem_filter.filter_by_pass_count` once for the batch.
   - Persist pass counts (`n_rules_pass`, `n_structural_pass`), thresholds, and per-filter booleans into `filter_flags_json`.
   - Populate name arrays for passed/failed rule and structural categories; save plot artifact paths in `plots_json`.
   - Set `passed` based on thresholds and mark variant `PASSFILTER`/`FAILFILTER`.
   - Enqueue all passed variants to `boltz2`; `NOTIFY boltz2`.

4. **Boltz-2 (pocket-conditioned)**
   - Run blind-docking filter; parse JSON output with multiple metrics:
     - `affinity_pred_value`, `affinity_probability_binary`, `affinity_pred_value1`, `affinity_probability_binary1`, `affinity_pred_value2`, `affinity_probability_binary2`.
   - Compute and persist the screening score: `screening_score = max((−affinity_pred_value1 + 2) / 4, 0) * affinity_probability_binary`.
   - Persist all metrics to `boltz2_results`, mark `passed=true` (pocket-conditioned), set variant status `BOLTZ2_DONE`.
   - Enqueue to `docking`; `NOTIFY docking`.

5. **Uni-Dock (batched docking)**
   - Batch docking already supported; run with chosen `search_mode`.
   - Parse outputs (SDF or PDBQT) and compute the best docking score as the **most negative** energy in kcal/mol across all poses.
   - Persist `best_score_kcal_mol`, `pose_count`, `all_scores`, and artifact paths to `docking_results`; set variant status `DOCKED`.

6. **Leaderboard / Top-N (optional)**
   - Leaderboard entries must include: `variant_id`, `smiles`, `boltz_screening_score`, and `unidock_docking_score_kcal_mol`.
   - Screening score formula: `max((−affinity_pred_value1 + 2)/4, 0) * affinity_probability_binary`.
   - Unidock score: use `docking_results.best_score_kcal_mol` (lower/more negative is better).
   - Implementation: SQL view joining `variants`, `boltz2_results`, `docking_results` (and `molecules` for SMILES if needed) with optional ordering.
   - Note: Existing Top-N helpers in `utils/retrosynformer.py` operate on CSV; this plan implements Top-N as SQL queries.

### Configuration (flags @)
- Environment variables or CLI flags (wired into `pipeline_eventdriven.py`). YAML keys shown in backticks.
- Precedence: YAML < environment variables < CLI flags.

- Molecule generation (common)
  - @ `--target-unique` (env `TARGET_UNIQUE`, yaml `target_unique`): target number of unique compounds.
  - @ `--generator {diffsbdd|pocket2mol|cgflow}` (env `GENERATOR`, yaml `generator.name`).
  - @ `--n-samples` (env `GEN_N_SAMPLES`, yaml `generator.n_samples`).

- Generator: DiffSBDD
  - @ `--diffsbdd-checkpoint` (env `DIFFSBDD_CHECKPOINT`, yaml `generator.diffsbdd.checkpoint`).
  - @ `--resi-list "A:719 A:770 ..."` (env `DIFFSBDD_RESI_LIST`, yaml `generator.diffsbdd.resi_list[]`).
  - @ `--sanitize/--no-sanitize` (env `DIFFSBDD_SANITIZE`, yaml `generator.diffsbdd.sanitize`).
  - @ `--pdbfile` (env `TARGET_PDB`, yaml `generator.common.pdbfile`).

- Generator: Pocket2Mol
  - @ `--p2m-center x y z` (env `P2M_CENTER`, yaml `generator.pocket2mol.center`).
  - @ `--p2m-bbox-size` (env `P2M_BBOX_SIZE`, yaml `generator.pocket2mol.bbox_size`).
  - @ `--p2m-out-dir` (env `P2M_OUT_DIR`, yaml `generator.pocket2mol.out_dir`).
  - @ `--pdbfile` (env `TARGET_PDB`, yaml `generator.common.pdbfile`).

- Generator: CGFlow
  - @ `--cgflow-config` (env `CGFLOW_CONFIG`, yaml `generator.cgflow.config_path`).
  - @ `--cgflow-checkpoint` (env `CGFLOW_CHECKPOINT`, yaml `generator.cgflow.checkpoint_path`).
  - @ `--cgflow-out-dir` (env `CGFLOW_OUT_DIR`, yaml `generator.cgflow.out_dir`).

- Retrosynthesis
  - @ `--score-threshold` (env `SCORE_THRESHOLD`, yaml `thresholds.score_threshold`): minimum variant score to keep.
  - @ `--retro-timeout` seconds (env `RETRO_TIMEOUT`, yaml `timeouts.retrosynthesis_sec`).
  - @ `--retro-top-n` (env `RETRO_TOP_N`, yaml `retrosynthesis.top_n`): top-N variants per source to keep.

- Medchem filters
  - @ `--medchem-rule-threshold` (env `MEDCHEM_RULE_THRESHOLD`, yaml `thresholds.medchem_rule_threshold`).
  - @ `--medchem-structural-threshold` (env `MEDCHEM_STRUCTURAL_THRESHOLD`, yaml `thresholds.medchem_structural_threshold`).
  - @ `--medchem-batch-size` (env `BATCH_SIZE_MEDCHEM`, yaml `medchem.batch_size`).
  - @ `--medchem-batch-timeout` seconds (env `MEDCHEM_BATCH_TIMEOUT`, yaml `medchem.batch_timeout_sec`).

- Boltz-2
  - @ `--boltz-pocket-residues 156,158,202` (env `BOLTZ_POCKET_RESIDUES`, yaml `boltz.pocket_residues`).

- Uni-Dock
  - @ `--unidock-search-mode {fast|balance|detail}` (env `UNIDOCK_SEARCH_MODE`, yaml `unidock.search_mode`).
  - @ `--unidock-batch-size` (env `BATCH_SIZE_DOCKING`, yaml `unidock.batch_size`).
  - @ `--unidock-center x y z` (env `UNIDOCK_CENTER`, yaml `unidock.center`).
  - @ `--unidock-box-size x y z` (env `UNIDOCK_BOX_SIZE`, yaml `unidock.box_size`).

- Concurrency
  - @ `--generator-workers` (env `GENERATOR_WORKERS`, yaml `concurrency.generator_workers`).
  - @ `--retrosyn-workers` (env `RETROSYN_WORKERS`, yaml `concurrency.retrosyn_workers`).
  - @ `--medchem-workers` (env `MEDCHEM_WORKERS`, yaml `concurrency.medchem_workers`).
  - @ `--boltz-workers` (env `BOLTZ_WORKERS`, yaml `concurrency.boltz_workers`).
  - @ `--docking-workers` (env `DOCKING_WORKERS`, yaml `concurrency.docking_workers`).

- Leaderboard
  - @ `--leaderboard-top-n` (env `LEADERBOARD_TOP_N`, yaml `leaderboard.top_n`).

- Core
  - @ `--db-url` (env `DB_URL`, yaml `db_url`).
  - @ `--outputs-root` (env `OUTPUTS_ROOT`, yaml `outputs_root`).
  - @ `--config` path to YAML (env `PIPELINE_CONFIG`).

- YAML configuration file support:
  - Default path: `config/pipeline.yaml` (override via `--config` CLI or `PIPELINE_CONFIG` env var).
  - Validated with Pydantic; unknown keys warned but ignored.
  - Suggested keys:
    - `db_url`, `outputs_root`, `target_unique`
    - `thresholds`: `{ score_threshold, medchem_rule_threshold, medchem_structural_threshold }`
    - `boltz`: `{ pocket_residues: [156,158,202] }`
    - `unidock`: `{ search_mode: balance, batch_size: 1200, center: [114.817,75.602,82.416], box_size: [38,70,58] }`
    - `medchem`: `{ batch_size: 256, batch_timeout_sec: 5 }`
    - `timeouts`: `{ retrosynthesis_sec: 300 }`
    - `retrosynthesis`: `{ top_n: 5 }`
    - `generator`: `{ name: pocket2mol, n_samples: 200, diffsbdd: { checkpoint: ... , resi_list: [...] }, pocket2mol: { center: [...], bbox_size: 23.0 }, cgflow: { config_path: ..., checkpoint_path: ... } }`
    - `concurrency`: `{ generator_workers: 1, retrosyn_workers: 2, medchem_workers: 1, boltz_workers: 1, docking_workers: 1 }`
    - `leaderboard`: `{ top_n: 50 }`
- Example YAML:
```yaml
db_url: postgresql://user:pass@localhost:5432/drug_pipeline
outputs_root: outputs
target_unique: 2000
generator:
  name: diffsbdd
  n_samples: 200
  diffsbdd:
    checkpoint: src/DiffSBDD/checkpoints/crossdocked_fullatom_cond.ckpt
    resi_list: ["A:719", "A:770", "A:841", "A:856", "A:887", "A:888"]
    sanitize: true
  pocket2mol:
    center: [114.817, 75.602, 82.416]
    bbox_size: 23.0
    out_dir: outputs/p2m
  cgflow:
    config_path: src/cgflow/configs/opt/NS5.yaml
    checkpoint_path: path/to/model_state.pt
    out_dir: outputs/cgflow
thresholds:
  score_threshold: 0.7
  medchem_rule_threshold: 13
  medchem_structural_threshold: 27
boltz:
  pocket_residues: [156, 158, 202]
unidock:
  search_mode: balance
  batch_size: 1200
  center: [114.817, 75.602, 82.416]
  box_size: [38, 70, 58]
medchem:
  batch_size: 256
  batch_timeout_sec: 5
timeouts:
  retrosynthesis_sec: 300
retrosynthesis:
  top_n: 5
concurrency:
  generator_workers: 1
  retrosyn_workers: 2
  medchem_workers: 1
  boltz_workers: 1
  docking_workers: 1
leaderboard:
  top_n: 50
```

### Worker responsibilities
- Common:
  - Use `tasks` table transitions: `queued → running → done/failed` with `attempts` and backoff.
  - Idempotent writes (`UPSERT` on unique keys), store tool stdout/stderr paths, and timestamps.
- `generator`:
  - Maintain uniqueness target and publish retrosynthesis tasks for new molecules.
- `retrosyn_worker`:
  - Dequeue molecules; run Synformer; write variants; enforce score threshold; enqueue medchem.
- `medchem_worker`:
  - Batch-run filters; write `medchem_results` including `filter_flags_json`, name arrays, pass counts, thresholds, and plot artifact paths; enqueue Boltz-2 for all `passed`.
- `boltz2_worker`:
  - Parse all Boltz-2 affinity metrics; compute `screening_score` using the formula above; persist metrics; enqueue docking (always proceeds).
- `unidock_worker`:
  - Batch by `BATCH_SIZE_DOCKING`; manage GPU mem via `utils.gpu_memory_manager`; persist results (`best_score_kcal_mol`, `pose_count`, `all_scores`).

### Batching strategy
- Medchem: `batch_size=256`, `batch_timeout=5s` (flush on either).
- Docking: `batch_size` configurable; split and retry on OOM.
- Retrosynthesis: single-item per task but worker can run K tasks concurrently via a process/thread pool.

### Fault tolerance and backpressure
- `SKIP LOCKED` dequeues prevent contention; stale `running` tasks get reclaimed after a heartbeat timeout.
- Backpressure knobs: max outstanding tasks per stage, worker concurrency limits, and generation pause when queue depth exceeds thresholds.

### Observability
- Reuse `utils.logging_utils` for rotating logs.
- Minimal `pipeline_stats` table for counters (processed, failed, avg latency per stage).
- Optional: small Streamlit page to visualize live status from DB.

### Artifacts and lineage
- Store paths to result SDF/JSON in `docking_results.result_file` and a `artifacts_root` config.
- Maintain lineage: `molecule -> variants -> medchem -> boltz2 -> docking` via FKs.

### Integration notes vs current code
- Current `pipeline_quick_multiround.py` uses CSV tracking and mostly sequential steps; this plan moves all state to SQL and reactive workers.
- Current Top-N utilities exist in `utils/retrosynformer.py` but are not wired in the main pipeline; here, implement Top-N via SQL queries.
- Boltz-2: pocket-conditioned, so all medchem-passed variants proceed to docking by design.

### Milestones (implementation order)
1. DB layer and schema
   - Create tables/migrations and `utils/db.py` wrapper (enqueue/dequeue/notify/listen helpers).
   - Smoke test: produce/consume a dummy task.
2. Generator worker
   - SDF→SMILES ingest, RDKit normalization, InChIKey dedupe, enqueue retrosynthesis; stop at `TARGET_UNIQUE`.
3. Retrosynthesis worker
   - Run Synformer via `env_manager`, persist variants, enforce score threshold, enqueue medchem.
4. Medchem worker (batched)
   - Batch filter with `filter_by_pass_count`, persist detailed outputs, enqueue boltz-2.
5. Boltz-2 worker
   - Pocket-conditioned run; persist metrics + screening score; enqueue docking.
6. Uni-Dock worker (batched)
   - GPU-aware batching, result parsing, persist artifacts and scores.
7. Leaderboard / Top-N
   - SQL query + optional view/table; optional Streamlit read-only page.
8. CLI and ops
   - `pipeline_eventdriven.py` to run selected workers; graceful shutdown, health logs, backoff.

### Acceptance criteria
- Unique count gating on generation works and is durable.
- Workers react to NOTIFY events (no polling loops), using `SKIP LOCKED` dequeues.
- Medchem persists detailed per-filter outcomes (`filter_flags_json`), name arrays, counts, thresholds, and plot paths; Boltz-2 persists full metrics and computed screening score; Uni-Dock persists `best_score_kcal_mol` as the most negative energy per variant that passes the medchem threshold.
- Leaderboard exposes `smiles`, `boltz_screening_score`, and `unidock_docking_score_kcal_mol`.
- Full lineage queryable; restart-safe without duplications; configurable thresholds respected.
