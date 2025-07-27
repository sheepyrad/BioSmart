# Drug Discovery Pipeline - Local Web Interface Specification

## Table of Contents
1. [Executive Summary](#executive-summary)
2. [Current System Analysis](#current-system-analysis)
3. [Technology Stack](#technology-stack)
4. [Database Schema](#database-schema)
5. [Application Architecture](#application-architecture)
6. [Page-by-Page Implementation](#page-by-page-implementation)
7. [Real-time Features](#real-time-features)
8. [File Management](#file-management)
9. [Migration Strategy](#migration-strategy)
10. [Local Deployment Architecture](#local-deployment-architecture)
11. [Summary: Fully Local Architecture](#summary-fully-local-architecture)

## Executive Summary

This document specifies the requirements and implementation plan for migrating the current stateless Streamlit-based drug discovery pipeline interface to a modern, stateful web application using Next.js frontend and SQLite backend - fully local deployment.

**Key Goals:**
- Persistent state management across sessions (local SQLite database)
- Simple local web interface without authentication complexity
- Real-time job monitoring and progress tracking
- Enhanced visualization capabilities
- Fully local deployment with no external dependencies

## Current System Analysis

### Existing Streamlit Pages (inside /pages directory)

#### 1. Configuration Page (`01_configuration.py` - 1,180 lines)
**Current Features:**
- Model selection (DiffSBDD vs Pocket2Mol)
- File upload handling (PDB files)
- Parameter configuration with validation
- 3D protein visualization with py3Dmol
- Box generation from residue lists
- Configuration export/import as JSON

**Key Components:**
- Model-specific parameter forms
- File upload with temporary storage
- Real-time 3D visualization
- Parameter validation and dependency management
- Automatic box calculation from protein residues

#### 2. Execution Page (`02_execution.py` - 373 lines)
**Current Features:**
- Pipeline start/stop controls
- Real-time progress tracking
- Live log streaming with syntax highlighting
- Multi-threaded execution management
- Auto-refresh capabilities

**Key Components:**
- Progress bars and status indicators
- Real-time log viewer with auto-scroll
- Thread management for pipeline execution
- Configuration summary display

#### 3. Results Page (`03_results.py` - 2,531 lines)
**Current Features:**
- Molecular structure rendering (2D/3D)
- Data table visualization
- Interactive charts and plots
- Export functionality
- Auto-refresh for active pipelines

**Key Components:**
- RDKit molecule rendering
- Plotly interactive charts
- Pandas dataframe display
- File download capabilities

#### 4. Visualize Results Page (`04_visualize_results.py` - 2,477 lines)
**Current Features:**
- Browse existing pipeline outputs
- Load results from directory structure
- 3D molecular visualization
- Pose analysis and comparison

**Key Components:**
- Directory browsing interface
- Multiple pose visualization
- Result comparison tools

#### 5. Similarity Search Page (`05_similarity_search.py` - 503 lines)
**Current Features:**
- Tanimoto similarity calculations
- CSV data loading
- Interactive similarity analysis
- Molecule filtering and ranking

**Key Components:**
- RDKit fingerprint calculations
- Similarity scoring algorithms
- Interactive result filtering

#### 6. Boltz Analysis Page (`06_boltz_analysis.py` - 936 lines)
**Current Features:**
- Boltz-1x model analysis
- CIF file processing
- Confidence scoring
- 3D structure visualization

**Key Components:**
- Boltz model integration
- CIF file parsing
- Confidence metrics display

### Pipeline Output Structure
Based on actual output at `/media/data/conrad_hku/NS5_350_150_boltz_newmedchem`:

```
pipeline_output/
├── round_1/
│   ├── ligand_generation/
│   │   ├── round_1_mols_gen.sdf
│   │   └── round_1_pocket2mol_output/
│   ├── docking_results/
│   ├── filter_results/
│   ├── retrosyn_results/
│   └── round_1_tracking_report.csv
├── round_2/
│   └── [same structure]
└── ...round_N/
```

**Example Tracking Report CSV Structure: (Non-exhaustive)**
```csv
compound_id,barcode,generation,round,smiles,parent_id,status,source,timestamp,variant_id,score,source_compound,source_smiles
round_1_mols_gen_mol_166,R1-GEN-0166,1,1,COC(=O)NC1=CCC(C(N)=O)=CC1=O,NONE,GENERATED,AI_GENERATION,2025-07-16T07:51:21.948987,,,,,,,,,,,,,,,,,,,,,
,R1-R1-GEN-0039-V-01,2,1,O=C(O)CNC(=O)c1cccc(C(=O)O)c1,round_1_mols_gen_mol_39_retrosyn,DOCKED,RETROSYNTHESIS,2025-07-16T08:29:13.819356,round_1_mols_gen_mol_39_retrosyn_variant_1_score1.000,1.0,round_1_mols_gen_mol_39,O=C(O)CNC(=O)c1cccc(C(=O)O)c1,0.8671890497207642,0.5420761108398438,2.347551822662353,0.5268909335136414,-0.6131736636161804,0.5572612881660461,0.94528067111969,0.8368666172027588,0.9238497018814088,0.9238497018814088,0.0,0.9506384134292604,0.906029999256134,-5.874,9.0,outputs/temp_docking/compound_round_1_mols_gen_mol_39_retrosyn_variant_1_score1.000/batch_docking_results/round_1_mols_gen_mol_39_retrosyn_variant_1_score1.000_out.sdf,"[-5.874, -5.818, -5.67, -5.658, -5.632, -5.621, -5.537, -5.516, -5.457]"
```

## Technology Stack

### Frontend
- **Framework**: Next.js with App Router
- **Language**: TypeScript
- **Styling**: Tailwind CSS (dark mode optimized)
- **UI Components**: Shadcn/UI
- **State Management**: React Query (TanStack Query) for API state
- **Visualization**: 
  - Recharts for charts
  - 3Dmol.js for molecular visualization
  - RDKit-JS for molecular rendering
- **Real-time**: WebSockets or Server-Sent Events for live updates

### Backend
- **Database**: SQLite3 (local file-based database)
- **ORM/Database Layer**: AsyncSQLDatabase with raw SQL queries
- **API Framework**: Next.js API routes (built-in backend)
- **File Storage**: Local file system (`/media/data/conrad_hku/`) but need to be configurable (maybe use system variable)
- **Pipeline Integration**: Direct Python subprocess execution

### External Dependencies
- **Database**: `sqlite3`, `aiosqlite` for async operations
- **Molecular Libraries**: RDKit, py3Dmol
- **Pipeline**: Existing Python codebase (unchanged)
- **Conda Environments**: Maintained as-is
- **File Watching**: `chokidar` for monitoring pipeline output files

## Database Schema

### SQLite Schema Definition

```sql
-- schema.sql
-- Create database tables for drug discovery pipeline

-- Jobs table - tracks pipeline runs
CREATE TABLE jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('queued', 'running', 'completed', 'failed', 'cancelled')),
    progress REAL DEFAULT 0.0 CHECK (progress >= 0 AND progress <= 100),
    current_stage TEXT,
    current_round INTEGER DEFAULT 0,
    total_rounds INTEGER DEFAULT 1,
    
    -- Configuration stored as JSON
    config TEXT NOT NULL, -- JSON string
    
    -- Timestamps
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    started_at DATETIME,
    completed_at DATETIME,
    error_message TEXT,
    
    -- File paths
    output_dir TEXT,
    pdb_file_path TEXT
);

-- Create indexes for better query performance
CREATE INDEX idx_jobs_status ON jobs(status);
CREATE INDEX idx_jobs_created_at ON jobs(created_at);

-- Compounds table - tracks generated/processed compounds
CREATE TABLE compounds (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id INTEGER NOT NULL,
    compound_id TEXT NOT NULL,
    barcode TEXT,
    smiles TEXT NOT NULL,
    generation TEXT,
    round INTEGER,
    parent_id TEXT,
    status TEXT, -- "GENERATED", "SYNTHETIZED", "FILTERED", "DOCKED"
    source TEXT, -- "AI_GENERATION", "RETROSYNTHESIS"
    score REAL,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
    variant_id TEXT,
    source_compound TEXT,
    source_smiles TEXT,
    
    FOREIGN KEY (job_id) REFERENCES jobs(id) ON DELETE CASCADE
);

-- Create indexes for compounds
CREATE INDEX idx_compounds_job_id ON compounds(job_id);
CREATE INDEX idx_compounds_barcode ON compounds(barcode);
CREATE INDEX idx_compounds_round ON compounds(job_id, round);

-- Job logs table - stores pipeline execution logs
CREATE TABLE job_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id INTEGER NOT NULL,
    level TEXT NOT NULL, -- "INFO", "WARNING", "ERROR", "DEBUG"
    message TEXT NOT NULL,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
    stage TEXT,
    round INTEGER,
    
    FOREIGN KEY (job_id) REFERENCES jobs(id) ON DELETE CASCADE
);

CREATE INDEX idx_logs_job_timestamp ON job_logs(job_id, timestamp);

-- Result files table - tracks output files
CREATE TABLE result_files (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id INTEGER NOT NULL,
    round INTEGER,
    file_type TEXT NOT NULL, -- "sdf", "pdbqt", "csv", "log", "json"
    file_name TEXT NOT NULL,
    file_path TEXT NOT NULL,
    description TEXT,
    file_size INTEGER,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    
    FOREIGN KEY (job_id) REFERENCES jobs(id) ON DELETE CASCADE
);

CREATE INDEX idx_results_job_id ON result_files(job_id);
CREATE INDEX idx_results_job_round ON result_files(job_id, round);

-- Similarity searches table - stores similarity search results
CREATE TABLE similarity_searches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    query_smiles TEXT NOT NULL,
    dataset_job_id INTEGER,
    results TEXT NOT NULL, -- JSON array of similarity results
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    
    FOREIGN KEY (dataset_job_id) REFERENCES jobs(id) ON DELETE SET NULL
);
```

### TypeScript Database Interface

```typescript
// lib/database.ts
import Database from 'better-sqlite3';
import { AsyncDatabase } from 'promised-sqlite3';

interface Job {
  id: number;
  name: string;
  status: 'queued' | 'running' | 'completed' | 'failed' | 'cancelled';
  progress: number;
  current_stage?: string;
  current_round: number;
  total_rounds: number;
  config: JobConfig; // JSON parsed
  created_at: string;
  started_at?: string;
  completed_at?: string;
  error_message?: string;
  output_dir?: string;
  pdb_file_path?: string;
}

interface Compound {
  id: number;
  job_id: number;
  compound_id: string;
  barcode?: string;
  smiles: string;
  generation?: string;
  round?: number;
  parent_id?: string;
  status?: string;
  source?: string;
  score?: number;
  timestamp: string;
  variant_id?: string;
  source_compound?: string;
  source_smiles?: string;
}

interface JobLog {
  id: number;
  job_id: number;
  level: string;
  message: string;
  timestamp: string;
  stage?: string;
  round?: number;
}

class DatabaseManager {
  private db: AsyncDatabase;
  
  constructor(dbPath: string = './pipeline.db') {
    this.db = new AsyncDatabase(dbPath);
    this.initializeSchema();
  }
  
  async initializeSchema() {
    // Execute schema.sql file
    const schema = await fs.readFile('./schema.sql', 'utf-8');
    await this.db.exec(schema);
  }
  
  // Job operations
  async createJob(job: Omit<Job, 'id' | 'created_at'>): Promise<number> {
    const result = await this.db.run(`
      INSERT INTO jobs (name, status, config, total_rounds, output_dir, pdb_file_path)
      VALUES (?, ?, ?, ?, ?, ?)
    `, [job.name, job.status, JSON.stringify(job.config), job.total_rounds, job.output_dir, job.pdb_file_path]);
    
    return result.lastID;
  }
  
  async getJob(id: number): Promise<Job | null> {
    const row = await this.db.get('SELECT * FROM jobs WHERE id = ?', [id]);
    return row ? { ...row, config: JSON.parse(row.config) } : null;
  }
  
  async getAllJobs(): Promise<Job[]> {
    const rows = await this.db.all('SELECT * FROM jobs ORDER BY created_at DESC');
    return rows.map(row => ({ ...row, config: JSON.parse(row.config) }));
  }
  
  async updateJobStatus(id: number, status: Job['status'], progress?: number, stage?: string) {
    await this.db.run(`
      UPDATE jobs 
      SET status = ?, progress = COALESCE(?, progress), current_stage = ?
      WHERE id = ?
    `, [status, progress, stage, id]);
  }
}

export const db = new DatabaseManager();
export type { Job, Compound, JobLog };
```

## Application Architecture

### Directory Structure
```
drug-pipeline-app/
├── app/
│   ├── api/
│   │   ├── jobs/
│   │   │   ├── route.ts
│   │   │   └── [id]/
│   │   │       ├── route.ts
│   │   │       ├── logs/route.ts
│   │   │       └── start/route.ts
│   │   ├── compounds/
│   │   │   └── route.ts
│   │   └── upload/
│   │       └── route.ts
│   ├── dashboard/
│   │   └── page.tsx
│   ├── jobs/
│   │   ├── new/
│   │   │   └── page.tsx
│   │   ├── [id]/
│   │   │   ├── page.tsx
│   │   │   ├── results/
│   │   │   ├── similarity/
│   │   │   └── boltz/
│   │   └── page.tsx
│   ├── results/
│   │   └── [jobId]/
│   └── layout.tsx
├── components/
│   ├── ui/ (shadcn components)
│   ├── job/
│   ├── molecular/
│   └── visualization/
├── lib/
│   ├── database.ts
│   ├── pipeline.ts
│   ├── utils.ts
│   ├── types.ts
│   └── molecular.ts
├── public/
├── schema.sql
└── pipeline.db (created at runtime)
```

### Core Components

#### 1. API Routes (Backend)
```typescript
// app/api/jobs/route.ts - REST API for job management
import { NextRequest, NextResponse } from 'next/server';
import { db } from '@/lib/database';

export async function GET() {
  const jobs = await db.getAllJobs();
  return NextResponse.json(jobs);
}

export async function POST(request: NextRequest) {
  const body = await request.json();
  const jobId = await db.createJob({
    name: body.name,
    status: 'queued',
    config: body.config,
    current_round: 0,
    total_rounds: body.config.numRounds,
    progress: 0,
    output_dir: body.config.outputDir,
    pdb_file_path: body.config.pdbPath,
  });
  
  return NextResponse.json({ id: jobId });
}
```

```typescript
// app/api/jobs/[id]/route.ts - Individual job operations
import { NextRequest, NextResponse } from 'next/server';
import { db } from '@/lib/database';

export async function GET(request: NextRequest, { params }: { params: { id: string } }) {
  const job = await db.getJob(parseInt(params.id));
  
  if (!job) {
    return NextResponse.json({ error: 'Job not found' }, { status: 404 });
  }
  
  return NextResponse.json(job);
}

export async function PATCH(request: NextRequest, { params }: { params: { id: string } }) {
  const body = await request.json();
  await db.updateJobStatus(parseInt(params.id), body.status, body.progress, body.stage);
  
  return NextResponse.json({ success: true });
}
```

```typescript
// app/api/jobs/[id]/start/route.ts - Start pipeline execution
import { NextRequest, NextResponse } from 'next/server';
import { db } from '@/lib/database';
import { startPipeline } from '@/lib/pipeline';

export async function POST(request: NextRequest, { params }: { params: { id: string } }) {
  const jobId = parseInt(params.id);
  const job = await db.getJob(jobId);
  
  if (!job) {
    return NextResponse.json({ error: 'Job not found' }, { status: 404 });
  }
  
  // Start pipeline execution in background
  startPipeline(jobId);
  
  return NextResponse.json({ message: 'Pipeline started' });
}
```

#### 2. Dashboard Overview
```typescript
// app/dashboard/page.tsx
import { useQuery } from '@tanstack/react-query';
import { Job } from '@/lib/database';

async function fetchJobs(): Promise<Job[]> {
  const response = await fetch('/api/jobs');
  if (!response.ok) throw new Error('Failed to fetch jobs');
  return response.json();
}

export default function Dashboard() {
  const { data: jobs, isLoading, error } = useQuery({
    queryKey: ['jobs'],
    queryFn: fetchJobs,
    refetchInterval: 5000, // Refresh every 5 seconds
  });
  
  if (isLoading) return <div>Loading...</div>;
  if (error) return <div>Error loading jobs</div>;
  
  const activeJobs = jobs?.filter(job => job.status === 'running') || [];
  const recentJobs = jobs?.slice(0, 5) || [];
  
  return (
    <DashboardLayout>
      <StatsGrid jobs={jobs} />
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-8">
        <ActiveJobsPanel jobs={activeJobs} />
        <RecentJobsPanel jobs={recentJobs} />
      </div>
    </DashboardLayout>
  );
}
```

```typescript
// app/layout.tsx - QueryClient setup
'use client';

import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { ReactQueryDevtools } from '@tanstack/react-query-devtools';
import { useState } from 'react';

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const [queryClient] = useState(() => new QueryClient({
    defaultOptions: {
      queries: {
        staleTime: 5 * 1000, // 5 seconds
        refetchInterval: 10 * 1000, // 10 seconds
      },
    },
  }));

  return (
    <html lang="en" className="dark">
      <body>
        <QueryClientProvider client={queryClient}>
          {children}
          <ReactQueryDevtools initialIsOpen={false} />
        </QueryClientProvider>
      </body>
    </html>
  );
}
```

## Page-by-Page Implementation

### 1. Job Configuration Page

**Route**: `/jobs/new`

**Components:**
- ModelSelectionCard
- FileUploadZone
- ParameterForm
- ProteinVisualization3D
- BoxCalculator
- ConfigurationSummary

**Key Features:**
```typescript
interface JobConfiguration {
  modelChoice: "diffsbdd" | "pocket2mol";
  pdbFile?: File;
  pdbPath?: string;
  nSamples: number;
  center: [number, number, number];
  boxSize: [number, number, number];
  exhaustiveness: "fast" | "balance" | "detail";
  // ... other parameters
}

const ConfigurationForm = () => {
  const [config, setConfig] = useState<JobConfiguration>();
  const createJob = useMutation(api.jobs.create);
  const router = useRouter();
  
  const handleSubmit = async () => {
    const jobId = await createJob({
      name: `Pipeline ${new Date().toISOString()}`,
      config
    });
    router.push(`/jobs/${jobId}`);
  };
};
```

**3D Visualization Integration:**
```typescript
const ProteinVisualization = ({ pdbData, config }) => {
  useEffect(() => {
    const viewer = $3Dmol.createViewer("protein-viewer", {
      defaultcolors: $3Dmol.rasmolElementColors
    });
    
    viewer.addModel(pdbData, "pdb");
    viewer.setStyle({}, { cartoon: { color: "spectrum" } });
    
    // Add docking box
    if (config.center && config.boxSize) {
      const box = new $3Dmol.Box({
        center: { x: config.center[0], y: config.center[1], z: config.center[2] },
        dimensions: { w: config.boxSize[0], h: config.boxSize[1], d: config.boxSize[2] }
      });
      viewer.addBox(box, { color: "blue", opacity: 0.3 });
    }
    
    viewer.render();
  }, [pdbData, config]);
};
```

### 2. Job Execution & Monitoring Page

**Route**: `/jobs/[id]`

**Components:**
- JobHeader
- ProgressTracker
- RealTimeLogViewer
- JobControls
- ConfigurationDisplay

**Real-time Updates:**
```typescript
const JobDetail = ({ params }: { params: { id: string } }) => {
  const job = useQuery(api.jobs.getById, { id: params.id });
  const logs = useQuery(api.logs.getByJob, { jobId: params.id });
  
  // Real-time subscriptions handled automatically by Convex
  
  return (
    <div className="space-y-6">
      <JobHeader job={job} />
      <ProgressSection job={job} />
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <LogViewer logs={logs} />
        <JobControls job={job} />
      </div>
    </div>
  );
};
```

**Log Viewer Component:**
```typescript
const LogViewer = ({ logs }) => {
  const logRef = useRef<HTMLDivElement>(null);
  
  useEffect(() => {
    // Auto-scroll to bottom
    logRef.current?.scrollTo({ top: logRef.current.scrollHeight });
  }, [logs]);
  
  return (
    <div 
      ref={logRef}
      className="h-96 overflow-y-auto bg-gray-900 p-4 rounded-lg font-mono text-sm"
    >
      {logs?.map((log, i) => (
        <LogLine key={i} log={log} />
      ))}
    </div>
  );
};
```

### 3. Results Visualization Page

**Route**: `/jobs/[id]/results`

**Components:**
- CompoundGrid
- MolecularRenderer
- InteractiveCharts
- DataTable
- ExportControls

**Molecular Rendering:**
```typescript
const MolecularRenderer = ({ smiles, pose3D }) => {
  return (
    <div className="molecular-viewer">
      {pose3D ? (
        <ThreeDMolViewer data={pose3D} />
      ) : (
        <TwoDMolViewer smiles={smiles} />
      )}
    </div>
  );
};

const CompoundGrid = ({ compounds }) => {
  return (
    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
      {compounds.map(compound => (
        <CompoundCard key={compound.compoundId} compound={compound} />
      ))}
    </div>
  );
};
```

### 4. Historical Results Browser

**Route**: `/results`

**Components:**
- JobBrowser
- ResultsFilter
- ComparisonTools
- DownloadManager

### 5. Similarity Search

**Route**: `/jobs/[id]/similarity`

**Components:**
- QueryMoleculeInput
- SimilarityResults
- TanimotoScoring
- ResultsComparison

### 6. Boltz Analysis

**Route**: `/jobs/[id]/boltz`

**Components:**
- BoltzResultsTable
- ConfidenceMetrics
- StructureComparison
- CIFViewer

## Real-time Features

### 1. Job Progress Tracking
```typescript
// convex/jobs.ts
export const updateProgress = internalMutation({
  args: {
    jobId: v.id("jobs"),
    progress: v.number(),
    currentStage: v.optional(v.string()),
    currentRound: v.optional(v.number()),
  },
  handler: async (ctx, args) => {
    await ctx.db.patch(args.jobId, {
      progress: args.progress,
      currentStage: args.currentStage,
      currentRound: args.currentRound,
    });
  },
});
```

### 2. Live Log Streaming
```typescript
// convex/logs.ts
export const addLog = internalMutation({
  args: {
    jobId: v.id("jobs"),
    level: v.string(),
    message: v.string(),
    stage: v.optional(v.string()),
  },
  handler: async (ctx, args) => {
    await ctx.db.insert("job_logs", {
      ...args,
      timestamp: Date.now(),
    });
  },
});
```

### 3. Local Pipeline Integration
```typescript
// lib/pipeline.ts - Local execution with SQLite logging
import { spawn } from 'child_process';
import fs from 'fs/promises';
import path from 'path';
import { db } from './database';
import chokidar from 'chokidar';

export async function startPipeline(jobId: number) {
  const job = await db.getJob(jobId);
  if (!job) throw new Error('Job not found');
  
  try {
    // Update status to running
    await db.updateJobStatus(jobId, 'running', 0, 'Initializing');
    
    // 1. Prepare local execution environment
    const workDir = path.join('/tmp', `pipeline-${jobId}`);
    await fs.mkdir(workDir, { recursive: true });
    
    // 2. Copy PDB file and prepare config
    if (job.pdb_file_path) {
      await fs.copyFile(job.pdb_file_path, path.join(workDir, 'input.pdb'));
    }
    
    const config = {
      ...job.config,
      pdbfile: path.join(workDir, 'input.pdb'),
      out_dir: path.join(workDir, 'results'),
    };
    await fs.writeFile(path.join(workDir, 'config.json'), JSON.stringify(config));
    
    // 3. Execute local Python pipeline
    const pipelineProcess = spawn('python', [
      'pipeline_quick_multiround.py',
      '--config', path.join(workDir, 'config.json'),
    ], {
      cwd: '/home/conrad_hku/Drug_pipeline',
      env: { 
        ...process.env, 
        CONDA_DEFAULT_ENV: 'drug_pipeline',
        PATH: '/home/conrad_hku/anaconda3/envs/drug_pipeline/bin:' + process.env.PATH
      }
    });
    
    // 4. Stream logs in real-time to SQLite
    pipelineProcess.stdout.on('data', async (data) => {
      const message = data.toString();
      await db.addLog(jobId, 'INFO', message);
      
      // Update progress based on log content
      updateProgressFromLog(jobId, message);
    });
    
    pipelineProcess.stderr.on('data', async (data) => {
      await db.addLog(jobId, 'ERROR', data.toString());
    });
    
    // 5. Monitor output directory for results
    const resultsDir = path.join(workDir, 'results');
    const watcher = chokidar.watch(resultsDir, { persistent: true });
    
    watcher.on('add', async (filePath) => {
      const fileName = path.basename(filePath);
      const stats = await fs.stat(filePath);
      
      await db.addResultFile({
        job_id: jobId,
        file_type: path.extname(fileName).slice(1),
        file_name: fileName,
        file_path: filePath,
        file_size: stats.size,
        description: `Pipeline output: ${fileName}`,
      });
    });
    
    // 6. Handle completion
    pipelineProcess.on('close', async (code) => {
      watcher.close();
      
      if (code === 0) {
        await parseAndStoreResults(jobId, workDir);
        await db.updateJobStatus(jobId, 'completed', 100, 'Completed');
      } else {
        await db.updateJobStatus(jobId, 'failed', undefined, 'Failed');
        await db.addLog(jobId, 'ERROR', `Pipeline failed with exit code ${code}`);
      }
    });
    
  } catch (error) {
    await db.updateJobStatus(jobId, 'failed', undefined, 'Error');
    await db.addLog(jobId, 'ERROR', error.message);
  }
}

// Helper function to update progress based on log content
async function updateProgressFromLog(jobId: number, message: string) {
  let progress = undefined;
  let stage = undefined;
  
  if (message.includes('Running ligand generation')) {
    progress = 20;
    stage = 'Ligand Generation';
  } else if (message.includes('Running retrosynthesis')) {
    progress = 40;
    stage = 'Retrosynthesis';
  } else if (message.includes('Starting batch filtering')) {
    progress = 60;
    stage = 'MedChem Filtering';
  } else if (message.includes('Starting docking')) {
    progress = 80;
    stage = 'Molecular Docking';
  } else if (message.includes('Pipeline completed successfully')) {
    progress = 100;
    stage = 'Completed';
  }
  
  if (progress !== undefined) {
    await db.updateJobStatus(jobId, 'running', progress, stage);
  }
}

// Helper function to parse tracking report and store compounds
async function parseAndStoreResults(jobId: number, workDir: string) {
  const trackingReportPath = path.join(workDir, 'results', 'tracking_report.csv');
  
  try {
    const csvContent = await fs.readFile(trackingReportPath, 'utf-8');
    const lines = csvContent.split('\n').slice(1); // Skip header
    
    for (const line of lines) {
      if (!line.trim()) continue;
      
      const [compound_id, barcode, generation, round, smiles, parent_id, status, source, timestamp] = line.split(',');
      
      await db.addCompound({
        job_id: jobId,
        compound_id,
        barcode,
        smiles,
        generation,
        round: parseInt(round),
        parent_id: parent_id === 'NONE' ? null : parent_id,
        status,
        source,
      });
    }
  } catch (error) {
    await db.addLog(jobId, 'WARNING', `Could not parse tracking report: ${error.message}`);
  }
}
```

## File Management

### 1. File Upload Handling
```typescript
// app/api/upload/route.ts - Local file upload
import { NextRequest, NextResponse } from 'next/server';
import fs from 'fs/promises';
import path from 'path';

export async function POST(request: NextRequest) {
  try {
    const formData = await request.formData();
    const file = formData.get('file') as File;
    
    if (!file) {
      return NextResponse.json({ error: 'No file provided' }, { status: 400 });
    }
    
    // Create uploads directory if it doesn't exist
    const uploadsDir = path.join(process.cwd(), 'uploads');
    await fs.mkdir(uploadsDir, { recursive: true });
    
    // Generate unique filename
    const fileName = `${Date.now()}-${file.name}`;
    const filePath = path.join(uploadsDir, fileName);
    
    // Save file to local filesystem
    const buffer = Buffer.from(await file.arrayBuffer());
    await fs.writeFile(filePath, buffer);
    
    return NextResponse.json({ 
      filePath,
      fileName,
      size: file.size,
      type: file.type 
    });
    
  } catch (error) {
    return NextResponse.json({ error: 'Upload failed' }, { status: 500 });
  }
}
```

```typescript
// Frontend file upload component
const FileUpload = ({ onUpload }: { onUpload: (filePath: string) => void }) => {
  const uploadFile = async (file: File) => {
    const formData = new FormData();
    formData.append('file', file);
    
    const response = await fetch('/api/upload', {
      method: 'POST',
      body: formData,
    });
    
    if (!response.ok) throw new Error('Upload failed');
    
    const result = await response.json();
    onUpload(result.filePath);
  };
  
  return (
    <input
      type="file"
      accept=".pdb,.pdbqt"
      onChange={async (e) => {
        const file = e.target.files?.[0];
        if (file) await uploadFile(file);
      }}
    />
  );
};
```

### 2. Result File Storage
```typescript
// Store pipeline output files
export const storeResultFile = internalMutation({
  args: {
    jobId: v.id("jobs"),
    round: v.number(),
    filePath: v.string(),
    type: v.string(),
  },
  handler: async (ctx, args) => {
    // Read file from pipeline output
    const fileContent = await readFile(args.filePath);
    
    // Store in Convex
    const fileId = await ctx.storage.store(
      new Blob([fileContent]),
      `${args.type}_round_${args.round}_${Date.now()}`
    );
    
    // Record in database
    await ctx.db.insert("results", {
      jobId: args.jobId,
      round: args.round,
      type: args.type,
      fileId,
      fileName: path.basename(args.filePath),
      filePath: args.filePath,
      description: `${args.type} file from round ${args.round}`,
      size: fileContent.length,
      createdAt: Date.now(),
    });
  },
});
```

## Migration Strategy

### Phase 1: Local Foundation Setup
1. Create Next.js project with TypeScript and Tailwind
2. Set up SQLite database with schema initialization
3. Create local file upload directory structure
4. Implement basic database connection and operations
5. Set up React Query for API state management

### Phase 2: Core Job Management
1. Implement job configuration page with local file uploads
2. Create REST API routes for job CRUD operations  
3. Add job creation workflow with SQLite storage
4. Build basic dashboard to display jobs
5. Set up local pipeline execution integration

### Phase 3: Real-time Pipeline Integration
1. Add Python subprocess execution with log streaming
2. Implement real-time progress tracking via React Query polling
3. Set up job control features (start/stop/cancel)
4. Create live log viewer with SQLite log storage
5. Add file system monitoring for pipeline outputs

### Phase 4: Data Visualization & Results
1. Integrate molecular rendering (RDKit-JS, 3Dmol.js)
2. Add 3D protein visualization for job configuration
3. Implement results parsing from pipeline output files
4. Create compound data visualization with interactive tables
5. Build molecular structure rendering components

### Phase 5: Advanced Features & Polish
1. Add similarity search functionality with Tanimoto scoring
2. Implement Boltz analysis integration
3. Add result comparison and filtering tools
4. Optimize performance and add error handling
5. Create export functionality for results

## Local Deployment Architecture

### Local Development Setup
- **Frontend**: Next.js development server (`npm run dev` on localhost:3000)
- **Backend**: Next.js API routes (built-in backend)
- **Database**: SQLite database file (`pipeline.db`)
- **File Storage**: Local file system (`uploads/`, existing pipeline outputs)
- **Pipeline**: Existing Python infrastructure (local execution)

### Development Workflow
1. **Single Command Start**: 
   ```bash
   npm run dev  # Starts both frontend and API
   ```
2. **Database Initialization**:
   ```bash
   sqlite3 pipeline.db < schema.sql
   ```
3. **Pipeline Integration**: Direct Python subprocess execution with real-time logging

### Environment Configuration

#### Local Development Environment
```env
# .env.local
DATABASE_PATH=./pipeline.db
UPLOAD_DIR=./uploads
PIPELINE_DIR=/home/conrad_hku/Drug_pipeline
CONDA_ENV=drug_pipeline
```

#### File System Integration
- **Database**: SQLite file in project root (`pipeline.db`)
- **File Uploads**: Local directory (`uploads/`)
- **Pipeline Outputs**: Existing structure (`/media/data/conrad_hku/`)
- **Fully Local Approach**: 
  - PDB files uploaded to local `uploads/` directory
  - Pipeline runs locally with direct file access
  - Results parsed and stored in SQLite database
  - All data remains on local machine

#### Simple Pipeline Execution
```typescript
// lib/pipeline.ts - Direct local execution
export async function startPipeline(jobId: number) {
  const job = await db.getJob(jobId);
  
  // 1. Prepare local workspace
  const workDir = `/tmp/pipeline-${jobId}`;
  await setupWorkspace(workDir, job);
  
  // 2. Execute Python pipeline directly
  const pipelineProcess = spawn('python', [
    'pipeline_quick_multiround.py',
    '--config', `${workDir}/config.json`
  ], {
    cwd: '/home/conrad_hku/Drug_pipeline',
    env: { ...process.env, CONDA_DEFAULT_ENV: 'drug_pipeline' }
  });
  
  // 3. Stream logs to SQLite in real-time
  pipelineProcess.stdout.on('data', async (data) => {
    await db.addLog(jobId, 'INFO', data.toString());
  });
  
  // 4. Parse results and update database
  pipelineProcess.on('close', async (code) => {
    if (code === 0) {
      await parseResults(jobId, workDir);
      await db.updateJobStatus(jobId, 'completed', 100);
    }
  });
}
```

### Development Dependencies

#### Required Software
- **Node.js 18+** for Next.js frontend and API
- **SQLite3** for database (usually pre-installed)
- **Existing Python environment** (conda, pip packages)

#### Setup Commands
```bash
# 1. Create Next.js project
npx create-next-app@latest drug-pipeline-app --typescript --tailwind --app
cd drug-pipeline-app

# 2. Install dependencies
npm install @tanstack/react-query better-sqlite3 promised-sqlite3 chokidar

# 3. Initialize database
sqlite3 pipeline.db < schema.sql

# 4. Start development (single command!)
npm run dev          # Frontend + API on localhost:3000
```

## Summary: Fully Local Architecture

This specification outlines a **fully local architecture** that provides modern web interface capabilities without external dependencies:

### 🏠 **Local Components**
- **Frontend**: Next.js dev server on localhost:3000
- **Backend**: Next.js API routes with SQLite database
- **Database**: Local SQLite file (`pipeline.db`)
- **File Storage**: Local file system (`uploads/`, `/media/data/conrad_hku/`)
- **Pipeline Execution**: Existing Python pipeline with conda environments
- **Real-time Updates**: React Query with polling + WebSockets

### 🎯 **Architecture Benefits**
1. **Zero External Dependencies**: No cloud services or accounts required
2. **Simple Setup**: Just Node.js and your existing Python environment
3. **Persistent State**: SQLite database survives restarts and crashes
4. **Real-time Monitoring**: Live job progress and log streaming
5. **No Authentication Complexity**: Direct access to pipeline interface
6. **Cost Free**: No ongoing subscription or usage costs
7. **Full Control**: All data stays on your local machine
8. **Fast Development**: Hot reload for frontend, instant API changes
```

### 📁 **File Structure**
```
drug-pipeline-app/
├── app/api/         # Backend API routes
├── app/dashboard/   # Frontend pages
├── lib/database.ts  # SQLite operations
├── lib/pipeline.ts  # Python pipeline integration
├── schema.sql       # Database schema
├── pipeline.db      # SQLite database (created at runtime)
└── uploads/         # File upload directory
```

### 🔄 **Data Flow**
1. **Upload PDB** → Local `uploads/` directory
2. **Configure Job** → Store in SQLite database
3. **Start Pipeline** → Python subprocess with log streaming
4. **Monitor Progress** → Real-time updates via React Query
5. **View Results** → Parse output files, store in database
6. **Visualize Data** → Molecular rendering with 3Dmol.js

This specification provides a comprehensive roadmap for implementing a modern, stateful web interface that maintains all existing functionality while adding persistent state management and real-time features through **fully local deployment with zero external dependencies**. 