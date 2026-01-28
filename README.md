# CGFlow GUI

A modern Electron + React desktop application for molecular optimization using CGFlow with Boltz-2 co-folding.

## Features

- **Configuration Builder**: Visual interface to create and edit optimization configs
- **Mol* Protein Viewer**: Interactive 3D structure viewer with residue selection
- **Run Management**: Start, stop, pause, and resume training runs
- **Results Dashboard**: Real-time visualization of generated molecules and scores
- **Reaction Pathway Viewer**: Visual synthesis pathway with step-by-step actions
- **Cross-Machine Sync**: Convex backend for accessing runs from any device

## Prerequisites

- Node.js 18+
- Python 3.10+ with cgflow environment
- Convex account (optional, for cloud sync)

## Installation

```bash
# Install dependencies
npm install

# Initialize Convex (optional)
npx convex dev
```

## Development

```bash
# Start development server
npm run electron:dev

# Type checking
npm run typecheck
```

## Building

```bash
# Build for production
npm run build
```

## Project Structure

```
cgflow-gui/
├── electron/           # Electron main process
│   ├── main.ts        # Main process entry
│   ├── preload.ts     # Preload script with IPC bridge
│   └── convex-sync.ts # Convex sync service
├── src/               # React renderer
│   ├── components/    # UI components
│   │   └── ui/       # shadcn/ui components
│   ├── hooks/        # Custom React hooks
│   ├── lib/          # Utilities
│   └── pages/        # Main app pages
├── shared/           # Shared types (main + renderer)
│   └── types.ts      # Zod schemas and TypeScript types
└── convex/           # Convex backend
    ├── schema.ts     # Database schema
    ├── configs.ts    # Config mutations/queries
    ├── runs.ts       # Run management
    ├── molecules.ts  # Molecule storage
    ├── files.ts      # File uploads
    └── annotations.ts # User annotations
```

## Configuration

### Environment Variables

Create a `.env` file:

```env
VITE_CONVEX_URL=https://your-deployment.convex.cloud
```

### CGFlow Setup

Ensure the cgflow scripts are accessible at `../cgflow/` relative to this app.

## Usage

### 1. Configuration Tab

1. Load an existing config or create new
2. Upload a PDB file for the protein structure
3. Select target residues by clicking in the Mol* viewer
4. Configure Boltz-2 settings (base YAML, MSA path)
5. Set optimization parameters

### 2. Start Training

1. Click "Start Training" to begin optimization
2. Monitor progress in the Dashboard tab

### 3. Dashboard Tab

- View KPI metrics (status, progress, best scores)
- Browse generated molecules in the table
- Click a molecule to see details:
  - RDKit structure visualization
  - Boltz-2 scores (affinity, probability)
  - Reaction pathway steps
- View protein-ligand complex in Mol* viewer

### 4. Resume Training

If training was interrupted:
1. Select a checkpoint from the result directory
2. Click "Resume" to continue from that point

## Tech Stack

- **Electron**: Desktop app framework
- **React 18**: UI framework
- **TypeScript**: Type safety
- **Vite**: Build tool
- **Tailwind CSS + shadcn/ui**: Styling
- **Mol***: Molecular visualization
- **Convex**: Real-time backend (optional)
- **Zod**: Schema validation
- **better-sqlite3**: SQLite database access

## License

MIT
