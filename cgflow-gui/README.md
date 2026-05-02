# CGFlow GUI

Desktop-first GUI for running and analyzing CGFlow + Boltz-2 optimization jobs.

The app provides:
- a visual config builder,
- local run orchestration,
- live monitoring and molecule analysis,
- optional Convex cloud sync for cross-machine access.

## What This App Does

CGFlow GUI is split across four layers:

1. **React Renderer (`src/`)** for config editing, dashboards, Mol* views, and molecule cards.
2. **Runner Service (`electron/runner.ts`)** that starts/stops/resumes CGFlow Python jobs and serves run data over HTTP/SSE.
3. **Electron Main (`electron/main.ts`)** for desktop shell, IPC, tray integration, and bootstrapping.
4. **Convex Backend (`convex/`)** for optional cloud persistence of runs, files, molecules, and annotations.

## Key Features

- **Configuration Builder**: Build/edit YAML-equivalent optimization configs.
- **Mol* Residue Selection**: Click residues in 3D protein view to set target residues.
- **Run Lifecycle Management**: Start, stop (pause), resume, and checkpoint-aware workflows.
- **Results Dashboard**: Inspect run progress, top molecules, Boltz scores, and trajectory pathways.
- **Protein-Ligand Complex Viewer**: Load predicted complex structures for selected molecules.
- **Cloud Sync (Optional)**: Persist files/runs/molecules with Convex.

## Prerequisites

- Bun
- Node.js 18+ available for Electron tooling
- Python 3.10+
- Conda env with CGFlow dependencies (default env name: `cgflow`)
- CGFlow repository available at `../cgflow` relative to this project
- Convex account (optional)

## Installation

From the repository root:

```bash
cd cgflow-gui
bun install
```

The desktop app starts CGFlow jobs through the local conda environment. By default it runs Python with:

```bash
conda run --no-capture-output -n cgflow python ...
```

Set `CGFLOW_CONDA_ENV` if your environment uses a different name.

### Optional Convex Setup

Convex is only needed for cloud sync. Local desktop runs and dashboards work without it.

```bash
bunx convex dev
```

If Convex is enabled, set `VITE_CONVEX_URL` or `CONVEX_URL` in `.env`.

## Running the App

### Desktop (recommended)

```bash
bun run electron:dev
```

This starts:
- Vite renderer dev server
- Electron main process
- local runner service (started by Electron on app boot)

### Web-only mode

```bash
bun run dev:web
```

This is useful for UI development, but training/run operations require the local runner service and local CGFlow setup.

### npm fallback

If Bun is unavailable, the same scripts can be run with npm:

```bash
npm install
npm run electron:dev
```

## Build

```bash
bun run build
```

Artifacts are generated in:
- `dist/` (renderer)
- `dist-electron/` (main/preload/runner)
- `release/` (packaged app)

## Environment Variables

Create `.env` in `cgflow-gui/` as needed:

```env
# Optional Convex deployment URL
VITE_CONVEX_URL=https://your-deployment.convex.cloud

# Optional toggle (default true)
VITE_CONVEX_ENABLED=true

# Optional runner URL override (default shown)
VITE_RUNNER_URL=http://127.0.0.1:45731

# Optional conda env override in main/runner process
CGFLOW_CONDA_ENV=cgflow
```

In PowerShell, you can also set the conda environment for the current terminal session before launching the app:

```powershell
$env:CGFLOW_CONDA_ENV="cgflow"
bun run electron:dev
```

## Typical Workflow

1. Open **Configuration** tab.
2. Load/create config and select files:
   - protein `.pdb`
   - optional MSA file (if provided, injected into generated Boltz base YAML)
3. Select target residues in Mol* (or enter manually as `CHAIN:RESID`, e.g. `A:123`).
4. Set optimization parameters and directories.
5. Start training.
6. Open **Dashboard** to monitor KPIs and inspect molecules.
7. Select a molecule to view:
   - RDKit 2D structure,
   - Boltz affinity/probability metrics,
   - reaction pathway,
   - predicted protein-ligand complex in Mol*.

## Project Structure

```text
cgflow-gui/
├── electron/
│   ├── main.ts          # Electron main process + IPC
│   ├── preload.ts       # Context bridge for renderer
│   ├── runner.ts        # Local HTTP/SSE runner service
│   └── convex-sync.ts   # SQLite -> Convex sync service
├── src/
│   ├── pages/           # ConfigBuilder + Dashboard
│   ├── components/      # MolstarViewer, FileSelector, MoleculeCard, etc.
│   ├── hooks/           # IPC, Convex, uploads, run state helpers
│   └── lib/             # Runner client, utilities
├── shared/
│   └── types.ts         # Shared zod schemas/types for app layers
└── convex/
    ├── schema.ts        # Convex schema
    ├── runs.ts          # Run records/status
    ├── molecules.ts     # Molecule upserts/queries
    ├── files.ts         # File storage metadata + upload URLs
    └── annotations.ts   # Molecule annotations
```

## Data and Output Expectations

CGFlow writes run outputs into the configured `result_dir`, including:
- checkpoint files (`model_state_*.pt`)
- logs
- SQLite databases used by the dashboard and sync (`boltz_reward_cache.db`, `boltz_scores_0.db`, `generated_objs_*.db`)
- Boltz complex output files (CIF/PDB) used for 3D viewing

## Troubleshooting

- **Runner unavailable / cannot start runs**
  - Ensure Electron app is running (desktop mode) or runner service is reachable at `VITE_RUNNER_URL`.
- **Python process fails immediately**
  - Verify `CGFLOW_CONDA_ENV` and that `opt_boltz.py` is available under `../cgflow/scripts/opt/`.
- **No molecules in dashboard yet**
  - Wait for CGFlow to emit SQLite outputs; early run stages may have no molecules.
- **Convex actions disabled**
  - Set a valid `VITE_CONVEX_URL` and run `bunx convex dev` (or deploy and point to a production URL).

## Tech Stack

- Electron
- React 18 + TypeScript
- Vite
- Tailwind CSS + shadcn/ui
- Framer Motion
- Mol*
- RDKit.js
- sql.js
- Convex (optional)
- Zod + YAML

## License

MIT
