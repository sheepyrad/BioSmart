# CGFlow GUI — Architecture & Feature Reference

A hybrid Electron / Web application for configuring, launching, and monitoring **CGFlow** molecular optimization runs powered by **Boltz-2**. The GUI spawns Python processes locally and reads their SQLite output databases for dashboards and 3D viewing.

---

## Table of Contents

1. [High-Level Architecture](#high-level-architecture)
2. [Project Structure](#project-structure)
3. [Running Modes](#running-modes)
4. [Pages & Features](#pages--features)
   - [Configuration Builder](#1-configuration-builder)
   - [Dashboard](#2-dashboard)
5. [Core Components](#core-components)
6. [How Python Processes Are Spawned](#how-python-processes-are-spawned)
   - [The Runner Server](#the-runner-server)
   - [Electron IPC (Legacy Path)](#electron-ipc-legacy-path)
   - [Process Lifecycle](#process-lifecycle)
7. [Data Flow End-to-End](#data-flow-end-to-end)
8. [Shared Types](#shared-types)
9. [Tech Stack](#tech-stack)

---

## High-Level Architecture

```
┌──────────────────────────────────────────────────────────────────────┐
│                          cgflow-gui                                  │
│                                                                      │
│  ┌──────────────┐     ┌────────────────┐     ┌───────────────────┐  │
│  │  React App   │────▶│  Runner Client │────▶│  Runner Server    │  │
│  │  (Renderer)  │     │  (HTTP client) │     │  (Node.js HTTP)   │  │
│  │              │     └────────────────┘     │  port 45731       │  │
│  │  - Config    │                            │                   │  │
│  │  - Dashboard │                            │  spawn('python',  │  │
│  │  - Mol*      │                            │   opt_boltz.py    │  │
│  │  - RDKit     │                            │   / opt_flashbind)│  │
│  └──────┬───────┘                            └────────┬──────────┘  │
│         │                                             │              │
│         │ IPC (Electron)                              │ stdout/err   │
│         ▼                                             ▼              │
│  ┌──────────────┐                            ┌───────────────────┐  │
│  │  Electron    │                            │  cgflow Python    │  │
│  │  Main Proc   │                            │  process          │  │
│  │  (optional)  │                            │                   │  │
│  └──────────────┘                            │  Writes to:       │  │
│                                              │  - train.log      │  │
│                                              │  - SQLite DBs     │  │
│                                              │  - checkpoints    │  │
│                                              │  - Boltz outputs  │  │
│                                              └───────────────────┘  │
│         │                                                            │
│         ▼                                                            │
│  ┌───────────────────────────────────────┐                           │
│  │  Local SQLite Databases               │                           │
│  │  - boltz_reward_cache.db              │                           │
│  │  - boltz_scores_0.db                  │                           │
│  │  - generated_objs_*.db                │                           │
│  └───────────────────────────────────────┘                           │
└──────────────────────────────────────────────────────────────────────┘
```

---

## Project Structure

```
cgflow-gui/
├── src/                           # Frontend (React + Vite)
│   ├── main.tsx                   #   Entry point
│   ├── App.tsx                    #   Tab navigation (Config / Dashboard)
│   ├── pages/
│   │   ├── ConfigBuilder.tsx      #   Configuration form + Mol* viewer
│   │   └── Dashboard.tsx          #   Run monitoring + molecule analysis
│   ├── components/
│   │   ├── FileSelector.tsx       #   Local file picker / path input
│   │   ├── MoleculeCard.tsx       #   2D molecule (RDKit SVG)
│   │   ├── MolstarViewer.tsx      #   3D protein viewer (Mol*)
│   │   ├── ReactionPathway.tsx    #   Reaction trajectory visualization
│   │   └── ui/                    #   shadcn/ui primitives
│   ├── hooks/
│   │   └── useIpc.ts              #   IPC / Runner client abstraction
│   └── lib/
│       ├── runnerClient.ts        #   HTTP client for runner server
│       ├── utils.ts               #   cn() helper
│       └── webFallback.ts         #   Web-mode IPC shims
│
├── electron/                      # Electron main process
│   ├── main.ts                    #   Window creation, IPC handlers
│   ├── preload.ts                 #   Context bridge
│   └── runner.ts                  #   Standalone HTTP runner server
│
├── shared/
│   └── types.ts                   #   Zod schemas shared across all layers
│
├── vite.config.ts                 #   Electron build (main + preload + runner)
├── vite.config.web.ts             #   Web-only build (no Electron)
└── package.json
```

---

## Running Modes

The app supports two deployment modes:

| Mode | Command | Electron | Runner Server |
|------|---------|----------|---------------|
| **Electron** | `npm run dev` / `bun run electron:dev` | Yes — full desktop app | Started automatically by Electron main process |
| **Web (full)** | `bun run dev:web` | No — browser-only | Started automatically alongside Vite |
| **Web (UI only)** | `bun run dev:web:ui` | No — browser-only | Must be started separately with `bun run dev:runner` |

In both Electron and web modes the React frontend communicates with the **Runner Server** over HTTP (`http://127.0.0.1:45731`). When Electron is present, IPC is available as a fallback.

In web mode, run-critical file/directory pickers are disabled. Users type runner-local paths for inputs and output directories. A runner status bar shows whether the local runner is ready, unavailable, or errored. Legacy `convex://` YAML paths are not resolved locally; reselect the corresponding local file or replace each value with a runner-readable path.

---

## Pages & Features

### 1. Configuration Builder

**Location:** `src/pages/ConfigBuilder.tsx`

A split-panel form for assembling a CGFlow optimization configuration.

| Section | Description |
|---------|-------------|
| **Load / Save** | Load YAML from disk, save YAML locally |
| **Input Files** | Select Protein PDB, Boltz Base YAML, MSA path — via local filesystem or typed runner-local paths |
| **Target Residues** | Click-to-select residues in the Mol* viewer or type manually (format `A:123`) |
| **Directories** | Result directory and environment directory paths |
| **Optimization Params** | Steps, Samples/Step, Max Atoms, Seed, Temperature range, Pose model, etc. |
| **Run Controls** | Start Training / Stop buttons, live status badge, progress bar |

**Right panel:** An interactive **Mol\*** 3D protein viewer that:
- Loads the selected PDB file
- Highlights selected target residues
- Supports click-to-select (multi-select mode) for defining binding sites

**Config format** matches the CGFlow YAML schema (`OptConfig` in `shared/types.ts`) with nested `boltz` sub-config.

### 2. Dashboard

**Location:** `src/pages/Dashboard.tsx`

A monitoring and analysis view for active and completed runs.

| Area | Description |
|------|-------------|
| **Left sidebar** | Scrollable run history — shows local runner runs with status icons and step progress. Click to select. Auto-refreshes every 5 seconds. |
| **KPI cards** (top) | 5 metric cards: Status, Progress, Best Affinity, Best Probability, Molecule Count |
| **Molecule detail** (left) | Selected molecule's 2D structure (RDKit), Boltz-2 scores (affinity/probability for ensemble + individual models), reaction trajectory pathway |
| **Mol\* viewer** (right) | 3D visualization of the Boltz-2 predicted protein-ligand complex for the selected molecule |
| **Molecule table** (bottom) | Top 50 molecules ranked by reward — columns: SMILES, Reward, Affinity, Probability, Steps. Click to select and inspect. |

**Data source:** the Dashboard lists local runs from the Runner Server (`GET /runs`) and polls SQLite-backed molecule, metric, log, and complex endpoints.

---

## Core Components

### `MolstarViewer` — 3D Protein Structure

- Embeds the [Mol\*](https://molstar.org/) WebGL viewer
- Loads PDB/MMCIF structures
- Interactive residue selection with highlighting
- Multi-select mode for binding site definition
- Used in both ConfigBuilder (residue selection) and Dashboard (complex viewing)

### `MoleculeCard` — 2D Molecule Rendering

- Renders SMILES via **RDKit.js** to SVG
- Shows reward score
- Copy-to-clipboard for SMILES strings

### `ReactionPathway` — Trajectory Visualization

- Displays the step-by-step build trajectory of a molecule
- Shows action names, fragment SMILES, and intermediate structures
- Animated timeline layout

### `FileSelector` — Local File Picker

- Local file selection via IPC dialog in Electron
- Typed runner-local paths in web mode
- Optional content callback for Mol* preview after a path is chosen

---

## How Python Processes Are Spawned

CGFlow's Python optimization script is invoked as a **child process** from Node.js. There are two code paths that can do this — both ultimately run the same command.

### The Runner Server

**Location:** `electron/runner.ts`

A standalone HTTP server (default port `45731`) that manages the full lifecycle of Python processes. It can run inside Electron or independently.

**Startup:**

```
server.listen(45731, '127.0.0.1')
```

**What it spawns:**

```
python  cgflow/scripts/opt/opt_boltz.py  \
  --config  <resolved_config.yaml>               \
  --result_dir  <result_dir>                      \
  --env_dir  <env_dir>
```

The script path is resolved relative to the runner:

```typescript
const CGFLOW_ROOT = path.resolve(__dirname, '../../cgflow');
const OPT_SCRIPT  = path.join(CGFLOW_ROOT, 'scripts/opt/opt_boltz.py');
```

**Resume runs** pass additional flags:

```
python  opt_boltz.py  --config <yaml>  --resume_from <checkpoint>  [--resume_oracle_idx N]
```

**Key REST endpoints:**

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/runs` | Start a new run — writes config YAML, spawns Python |
| `POST` | `/runs/:id/stop` | Send `SIGINT` to the Python process (graceful pause) |
| `POST` | `/runs/:id/resume` | Resume from a checkpoint |
| `GET`  | `/runs` | List all runs |
| `GET`  | `/runs/:id` | Get single run status |
| `GET`  | `/runs/:id/output` | Get process stdout/stderr |
| `GET`  | `/runs/:id/checkpoints` | List available checkpoints |
| `GET`  | `/runs/:id/molecules` | Query top molecules from SQLite |
| `GET`  | `/runs/:id/complex/:oracle/:mol` | Get Boltz complex structure file |
| `GET`  | `/events` | SSE stream for real-time status updates |
| `GET`  | `/health` | Health check |

### Electron IPC (Legacy Path)

**Location:** `electron/main.ts`

The Electron main process registers IPC handlers (`run:start`, `run:stop`, `run:resume`) that can also spawn the same Python script directly via `child_process.spawn()`. This path is used when the Runner Server is unavailable.

### Process Lifecycle

```
┌─────────┐   POST /runs    ┌───────────────┐   spawn()   ┌──────────────┐
│  React   │───────────────▶│ Runner Server │────────────▶│   Python     │
│  UI      │                │               │             │  opt_unidock │
└─────────┘                │               │◀────────────│  _boltz.py   │
                           │               │  stdout/err  └──────────────┘
     SSE /events           │               │                    │
◀──────────────────────────│  Broadcasts   │                    │
                           │  status via   │                    ▼
                           │  SSE events   │            ┌──────────────┐
                           │               │            │  SQLite DBs  │
                           └───────────────┘            │  train.log   │
                                  │                     │  checkpoints │
                                  │ reads SQLite        └──────────────┘
                                  │ on demand
                                  ▼
                           Returns molecules,
                           scores, complex files
```

1. **Start:** The frontend sends the `OptConfig` to `POST /runs`. The runner writes a temporary YAML config, spawns the Python process, and returns a `RunInfo` object with a unique `runId`.

2. **Monitor:** `stdout` and `stderr` are captured line-by-line. The runner parses output for progress markers (e.g., `[Step X/Y]`, `Saved checkpoint`). Status updates are broadcast over SSE to all connected clients.

3. **Stop:** `POST /runs/:id/stop` sends `SIGINT` to the child process. The process status is set to `paused`. The checkpoint path is preserved so the run can be resumed later.

4. **Resume:** `POST /runs/:id/resume` spawns a new Python process with `--resume_from <checkpoint>`.

5. **Complete:** When the process exits with code 0, the status is set to `completed`. Non-zero exit sets `error` status with the exit code.

6. **Data Access:** The runner reads SQLite databases written by the Python process to serve molecule data, Boltz scores, and complex structures on demand.

### State Management

The runner maintains in-memory state:

```typescript
interface RunnerState {
  runs:      Map<string, RunRecord>;     // Run metadata & status
  outputs:   Map<string, string[]>;      // Captured stdout/stderr lines
  processes: Map<string, ChildProcess>;  // Active Node.js child processes
}
```

Run metadata is persisted to a JSON file (`runs.json`) in the runner's data directory so runs survive server restarts.

---

## Data Flow End-to-End

### 1. Configure & Start a Run

```
User fills form in ConfigBuilder
        │
        ▼
OptConfig object assembled (Zod-validated)
        │
POST /runs → Runner Server
        │
        ├──▶ Write config to temp YAML file
        ├──▶ spawn('python', ['opt_boltz.py', ...])
        │
        ▼
Python process starts, writing to result_dir/
```

### 2. Monitor Progress

```
Python writes to stdout ──▶ Runner captures lines ──▶ SSE broadcast
Python writes train.log ──▶ Dashboard polls GET /runs/:id/output
Python writes SQLite DBs ──▶ Dashboard polls GET /runs/:id/molecules
```

### 3. View Results

```
Dashboard selects run
        │
        ├──▶ GET /runs/:id/molecules → reads SQLite on demand
        │
        ▼
Molecules displayed in table
        │
User clicks molecule
        │
        ├──▶ 2D structure rendered via RDKit.js
        ├──▶ Boltz scores displayed
        ├──▶ Reaction trajectory visualized
        └──▶ 3D complex loaded in Mol* (GET /runs/:id/complex)
```

---

## Shared Types

**Location:** `shared/types.ts`

All layers (frontend, Electron main, runner) share Zod-validated type definitions:

| Type | Description |
|------|-------------|
| `OptConfig` | Full optimization config (matches YAML schema) |
| `BoltzConfig` | Nested Boltz-2 sub-config |
| `RunInfo` | Run metadata (id, status, progress, paths) |
| `RunStatus` | `'idle' \| 'running' \| 'paused' \| 'completed' \| 'error'` |
| `MoleculeResult` | Molecule with scores, trajectory, and complex path |
| `BoltzScore` | Affinity/probability scores from Boltz-2 |
| `RewardCacheEntry` | SMILES + reward from the reward cache DB |
| `TrajectoryStep` | Single step in a molecule's build trajectory |
| `GeneratedObject` | Raw generated molecule from SQLite |
| `IpcChannels` | Type-safe IPC channel definitions |
| `IpcEvents` | Type-safe event definitions (main → renderer) |

---

## Tech Stack

| Layer | Technology |
|-------|------------|
| **Frontend** | React 18, TypeScript 5.7, Vite 5 |
| **UI** | Tailwind CSS, shadcn/ui (Radix primitives), Framer Motion |
| **3D Viewer** | Mol* (Molstar 4.5) |
| **2D Chemistry** | RDKit.js |
| **Desktop** | Electron 34 |
| **Process Mgmt** | Node.js `child_process.spawn` |
| **Local Data** | SQLite via sql.js |
| **Validation** | Zod 3.24 |
| **Config Format** | YAML (via `yaml` package) |
