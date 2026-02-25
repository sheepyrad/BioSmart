import { app, BrowserWindow, ipcMain, dialog, Tray, Menu, nativeImage } from 'electron';
import { fileURLToPath } from 'url';
import path from 'path';
import fs from 'fs/promises';
import { spawn, ChildProcess, type SpawnOptions } from 'child_process';
import YAML from 'yaml';
import initSqlJs, { Database as SqlJsDatabase } from 'sql.js';
import { startRunnerServer } from './runner';
import type {
  OptConfig,
  RunInfo,
  GeneratedObject,
  BoltzScore,
  RewardCacheEntry,
  MoleculeResult,
  TrajectoryStep,
} from '../shared/types';

const __dirname = path.dirname(fileURLToPath(import.meta.url));

// ============================================================================
// Globals
// ============================================================================

let mainWindow: BrowserWindow | null = null;
let SQL: Awaited<ReturnType<typeof initSqlJs>> | null = null;
const activeRuns = new Map<string, { process: ChildProcess; info: RunInfo }>();
let tray: Tray | null = null;
let isQuitting = false;

// Path to cgflow scripts
const CGFLOW_ROOT = path.resolve(__dirname, '../../cgflow');
const OPT_SCRIPT = path.join(CGFLOW_ROOT, 'scripts/opt/opt_boltz.py');
const CONDA_ENV_NAME = process.env.CGFLOW_CONDA_ENV?.trim() || 'cgflow';

function spawnCgflowPython(args: string[], options: SpawnOptions): ChildProcess {
  return spawn(
    'conda',
    ['run', '--no-capture-output', '-n', CONDA_ENV_NAME, 'python', ...args],
    options
  );
}

// Initialize SQL.js
async function initSQL() {
  if (!SQL) {
    SQL = await initSqlJs();
  }
  return SQL;
}

// Helper to open a SQLite database file
async function openDatabase(dbPath: string): Promise<SqlJsDatabase> {
  const sql = await initSQL();
  const buffer = await fs.readFile(dbPath);
  return new sql.Database(buffer);
}

// Helper to run a query and get results as objects
function queryAll<T>(db: SqlJsDatabase, sql: string, params: unknown[] = []): T[] {
  const stmt = db.prepare(sql);
  stmt.bind(params);
  const results: T[] = [];
  while (stmt.step()) {
    results.push(stmt.getAsObject() as T);
  }
  stmt.free();
  return results;
}

// ============================================================================
// Window Creation
// ============================================================================

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1600,
    height: 1000,
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
    },
  });

  if (process.env.VITE_DEV_SERVER_URL) {
    mainWindow.loadURL(process.env.VITE_DEV_SERVER_URL);
    mainWindow.webContents.openDevTools();
  } else {
    mainWindow.loadFile(path.join(__dirname, '../dist/index.html'));
  }

  mainWindow.on('close', (event) => {
    if (isQuitting) return;
    event.preventDefault();
    mainWindow?.hide();
  });
}

app.whenReady().then(async () => {
  await initSQL();
  await startRunnerServer({
    dataDir: path.join(app.getPath('userData'), 'runner'),
    convexUrl: process.env.VITE_CONVEX_URL ?? process.env.CONVEX_URL,
  });
  createWindow();

  // Create tray icon
  const trayIconPath = path.join(app.getPath('userData'), 'tray.png');
  try {
    await fs.access(trayIconPath);
  } catch {
    // Simple 16x16 PNG (blue dot) base64
    const base64 =
      'iVBORw0KGgoAAAANSUhEUgAAABAAAAAQCAYAAAAf8/9hAAAAPklEQVR4nGNgGAWMeGWr/v+Hs9sYsarFbgCyRnSAZhATXhcQATANwGc7FnkauIBiA3CENi55il1AcToYBgAArsYPEGSEkhYAAAAASUVORK5CYII=';
    const buffer = Buffer.from(base64, 'base64');
    await fs.writeFile(trayIconPath, buffer);
  }
  const trayImage = nativeImage.createFromPath(trayIconPath);
  tray = new Tray(trayImage);
  const contextMenu = Menu.buildFromTemplate([
    {
      label: 'Show CGFlow',
      click: () => {
        mainWindow?.show();
      },
    },
    {
      label: 'Hide CGFlow',
      click: () => {
        mainWindow?.hide();
      },
    },
    {
      label: 'Quit',
      click: () => {
        isQuitting = true;
        app.quit();
      },
    },
  ]);
  tray.setToolTip('CGFlow GUI');
  tray.setContextMenu(contextMenu);
});

app.on('window-all-closed', () => {
  if (isQuitting) {
    app.quit();
  }
});

app.on('activate', () => {
  if (BrowserWindow.getAllWindows().length === 0) {
    createWindow();
  }
});

// ============================================================================
// File Operations
// ============================================================================

ipcMain.handle('file:select-pdb', async () => {
  const result = await dialog.showOpenDialog({
    properties: ['openFile'],
    filters: [{ name: 'PDB Files', extensions: ['pdb'] }],
  });
  return result.canceled ? null : result.filePaths[0] ?? null;
});

ipcMain.handle('file:select-yaml', async () => {
  const result = await dialog.showOpenDialog({
    properties: ['openFile'],
    filters: [{ name: 'YAML Files', extensions: ['yaml', 'yml'] }],
  });
  return result.canceled ? null : result.filePaths[0] ?? null;
});

ipcMain.handle('file:select-directory', async () => {
  const result = await dialog.showOpenDialog({
    properties: ['openDirectory'],
  });
  return result.canceled ? null : result.filePaths[0] ?? null;
});

ipcMain.handle('file:read-pdb', async (_event, filePath: string) => {
  return fs.readFile(filePath, 'utf-8');
});

ipcMain.handle('file:read-yaml', async (_event, filePath: string) => {
  const content = await fs.readFile(filePath, 'utf-8');
  return YAML.parse(content) as OptConfig;
});

ipcMain.handle('file:write-yaml', async (_event, filePath: string, config: OptConfig) => {
  const content = YAML.stringify(config);
  await fs.writeFile(filePath, content, 'utf-8');
});

ipcMain.handle('file:exists', async (_event, filePath: string) => {
  try {
    await fs.access(filePath);
    return true;
  } catch {
    return false;
  }
});

// ============================================================================
// Run Management
// ============================================================================

function generateRunId(): string {
  return `run_${Date.now()}_${Math.random().toString(36).substring(2, 9)}`;
}

function emitToRenderer(channel: string, ...args: unknown[]) {
  mainWindow?.webContents.send(channel, ...args);
}

ipcMain.handle('run:start', async (_event, payload: { config: OptConfig; configPath?: string | null; name?: string | null }) => {
  const config = payload.config;
  let configPath = payload.configPath ?? null;
  if (!configPath) {
    const path = `./configs/opt/generated_${Date.now()}.yaml`;
    const content = YAML.stringify(config);
    await fs.writeFile(path, content, 'utf-8');
    configPath = path;
  }
  const runId = generateRunId();
  const timestamp = new Date().toISOString().replace(/[:.]/g, '').substring(0, 15);
  const resultDir = path.join(config.result_dir, timestamp);

  const runInfo: RunInfo = {
    id: runId,
    name: payload.name || `Run ${timestamp}`,
    configPath,
    resultDir,
    status: 'running',
    currentStep: 0,
    totalSteps: config.num_steps,
    startedAt: new Date().toISOString(),
    lastUpdatedAt: new Date().toISOString(),
    checkpointPath: null,
    error: null,
  };

  const args = [
    OPT_SCRIPT,
    '--config', configPath,
    '--result_dir', config.result_dir,
    '--env_dir', config.env_dir,
  ];

  const proc = spawnCgflowPython(args, {
    cwd: CGFLOW_ROOT,
    env: { ...process.env },
  });

  proc.stdout?.on('data', (data: Buffer) => {
    const output = data.toString();
    emitToRenderer('run:output', runId, output);
    
    // Parse step from output
    const stepMatch = output.match(/iteration\s+(\d+)/i);
    if (stepMatch?.[1]) {
      runInfo.currentStep = parseInt(stepMatch[1], 10);
      runInfo.lastUpdatedAt = new Date().toISOString();
      emitToRenderer('run:status-changed', runInfo);
    }

    // Detect checkpoint
    const checkpointMatch = output.match(/Saved checkpoint.*?(model_state_\d+\.pt)/);
    if (checkpointMatch?.[1]) {
      runInfo.checkpointPath = path.join(resultDir, checkpointMatch[1]);
      emitToRenderer('run:checkpoint-saved', runId, runInfo.checkpointPath);
    }
  });

  proc.stderr?.on('data', (data: Buffer) => {
    const output = data.toString();
    emitToRenderer('run:output', runId, `[stderr] ${output}`);
  });

  proc.on('close', (code) => {
    runInfo.status = code === 0 ? 'completed' : 'error';
    if (code !== 0) {
      runInfo.error = `Process exited with code ${code}`;
    }
    runInfo.lastUpdatedAt = new Date().toISOString();
    activeRuns.delete(runId);
    emitToRenderer('run:status-changed', runInfo);
  });

  proc.on('error', (err) => {
    runInfo.status = 'error';
    runInfo.error = err.message;
    runInfo.lastUpdatedAt = new Date().toISOString();
    activeRuns.delete(runId);
    emitToRenderer('run:error', runId, err.message);
  });

  activeRuns.set(runId, { process: proc, info: runInfo });
  return runInfo;
});

ipcMain.handle('run:stop', async (_event, runId: string) => {
  const run = activeRuns.get(runId);
  if (run) {
    run.process.kill('SIGINT');
    run.info.status = 'paused';
    run.info.lastUpdatedAt = new Date().toISOString();
    emitToRenderer('run:status-changed', run.info);
  }
});

ipcMain.handle('run:resume', async (_event, runId: string, checkpointPath: string, oracleIdx?: number) => {
  const run = activeRuns.get(runId);
  if (!run) {
    throw new Error(`Run ${runId} not found`);
  }

  const { info } = run;
  const args = [
    OPT_SCRIPT,
    '--config', info.configPath,
    '--resume_from', checkpointPath,
  ];

  if (oracleIdx !== undefined) {
    args.push('--resume_oracle_idx', oracleIdx.toString());
  }

  const proc = spawnCgflowPython(args, {
    cwd: CGFLOW_ROOT,
    env: { ...process.env },
  });

  info.status = 'running';
  info.lastUpdatedAt = new Date().toISOString();

  proc.stdout?.on('data', (data: Buffer) => {
    const output = data.toString();
    emitToRenderer('run:output', runId, output);
    
    const stepMatch = output.match(/iteration\s+(\d+)/i);
    if (stepMatch?.[1]) {
      info.currentStep = parseInt(stepMatch[1], 10);
      info.lastUpdatedAt = new Date().toISOString();
      emitToRenderer('run:status-changed', info);
    }
  });

  proc.stderr?.on('data', (data: Buffer) => {
    emitToRenderer('run:output', runId, `[stderr] ${data.toString()}`);
  });

  proc.on('close', (code) => {
    info.status = code === 0 ? 'completed' : 'error';
    info.lastUpdatedAt = new Date().toISOString();
    activeRuns.delete(runId);
    emitToRenderer('run:status-changed', info);
  });

  activeRuns.set(runId, { process: proc, info });
  emitToRenderer('run:status-changed', info);
  return info;
});

ipcMain.handle('run:get-status', async (_event, runId: string) => {
  const run = activeRuns.get(runId);
  return run?.info ?? null;
});

ipcMain.handle('run:list', async () => {
  return Array.from(activeRuns.values()).map((r) => r.info);
});

ipcMain.handle('run:get-checkpoints', async (_event, runIdOrDir: string) => {
  const run = activeRuns.get(runIdOrDir);
  const resultDir = run?.info.resultDir ?? runIdOrDir;
  try {
    const files = await fs.readdir(resultDir);
    return files
      .filter((f) => f.startsWith('model_state_') && f.endsWith('.pt'))
      .map((f) => path.join(resultDir, f))
      .sort();
  } catch {
    return [];
  }
});

// ============================================================================
// Database Queries
// ============================================================================

ipcMain.handle('db:get-generated-objects', async (_event, dbPath: string, limit = 100, offset = 0) => {
  const db = await openDatabase(dbPath);
  try {
    const rows = queryAll<GeneratedObject>(
      db,
      `SELECT smi, r, traj FROM results LIMIT ? OFFSET ?`,
      [limit, offset]
    );
    return rows;
  } finally {
    db.close();
  }
});

ipcMain.handle('db:get-boltz-scores', async (_event, dbPath: string, limit = 100, offset = 0) => {
  const db = await openDatabase(dbPath);
  try {
    const rows = queryAll<BoltzScore>(
      db,
      `SELECT iteration, smiles, docking_score, affinity_ensemble, probability_ensemble,
              affinity_model1, probability_model1, affinity_model2, probability_model2
       FROM results ORDER BY affinity_ensemble ASC LIMIT ? OFFSET ?`,
      [limit, offset]
    );
    return rows;
  } finally {
    db.close();
  }
});

ipcMain.handle('db:get-reward-cache', async (_event, dbPath: string, limit = 100) => {
  const db = await openDatabase(dbPath);
  try {
    const rows = queryAll<RewardCacheEntry>(
      db,
      `SELECT smiles, reward, info FROM entries ORDER BY reward DESC LIMIT ?`,
      [limit]
    );
    return rows;
  } finally {
    db.close();
  }
});

ipcMain.handle('db:get-top-molecules', async (_event, runIdOrDir: string, limit = 50) => {
  const run = activeRuns.get(runIdOrDir);
  const resultDir = run?.info.resultDir ?? runIdOrDir;
  const rewardCachePath = path.join(resultDir, 'boltz_reward_cache.db');
  const trainDir = path.join(resultDir, 'train');

  const results: MoleculeResult[] = [];

  // Get top molecules from reward cache
  try {
    const rewardDb = await openDatabase(rewardCachePath);
    const topEntries = queryAll<RewardCacheEntry>(
      rewardDb,
      `SELECT smiles, reward, info FROM entries ORDER BY reward DESC LIMIT ?`,
      [limit]
    );
    rewardDb.close();

    // Get trajectory info from generated_objs
    const generatedDbPath = path.join(trainDir, 'generated_objs_0.db');
    let trajMap = new Map<string, string>();
    
    try {
      const genDb = await openDatabase(generatedDbPath);
      const placeholders = topEntries.map(() => '?').join(',');
      const trajRows = queryAll<{ smi: string; traj: string }>(
        genDb,
        `SELECT smi, traj FROM results WHERE smi IN (${placeholders})`,
        topEntries.map((e) => e.smiles)
      );
      genDb.close();
      trajMap = new Map(trajRows.map((r) => [r.smi, r.traj]));
    } catch {
      // Generated objects DB may not exist yet
    }

    // Get boltz scores
    const boltzDbPath = path.join(trainDir, 'boltz_scores_0.db');
    let boltzMap = new Map<string, BoltzScore>();
    
    try {
      const boltzDb = await openDatabase(boltzDbPath);
      const placeholders = topEntries.map(() => '?').join(',');
      const boltzRows = queryAll<BoltzScore>(
        boltzDb,
        `SELECT * FROM results WHERE smiles IN (${placeholders})`,
        topEntries.map((e) => e.smiles)
      );
      boltzDb.close();
      boltzMap = new Map(boltzRows.map((r) => [r.smiles, r]));
    } catch {
      // Boltz scores DB may not exist yet
    }

    for (const entry of topEntries) {
      const trajStr = trajMap.get(entry.smiles);
      let trajectory: TrajectoryStep[] = [];
      
      if (trajStr) {
        try {
          trajectory = JSON.parse(trajStr) as TrajectoryStep[];
        } catch {
          // Invalid trajectory JSON
        }
      }

      results.push({
        smiles: entry.smiles,
        reward: entry.reward,
        trajectory,
        boltzScores: boltzMap.get(entry.smiles) ?? null,
        complexPath: null, // Will be populated separately
      });
    }
  } catch {
    // Reward cache DB may not exist yet
  }

  return results;
});

// ============================================================================
// Boltz Complex Files
// ============================================================================

ipcMain.handle('boltz:get-complex-path', async (_event, resultDir: string, oracleIdx: number, molIdx: number) => {
  const basePath = path.join(resultDir, 'boltz_cofold', `oracle${oracleIdx}`, `mol_${molIdx}`, 'boltz_output');
  
  try {
    const files = await fs.readdir(basePath);
    // Look for the combined structure file (usually ends with _combined.cif or similar)
    const structureFile = files.find((f) => f.endsWith('.cif') || f.endsWith('.pdb'));
    if (structureFile) {
      return path.join(basePath, structureFile);
    }
  } catch {
    // Directory may not exist
  }
  
  return null;
});

ipcMain.handle('boltz:read-complex', async (_event, complexPath: string) => {
  return fs.readFile(complexPath, 'utf-8');
});

// Convenience: get complex content directly by runId or resultDir
ipcMain.handle('boltz:get-complex', async (_event, runIdOrDir: string, oracleIdx: number, molIdx: number) => {
  const run = activeRuns.get(runIdOrDir);
  const resultDir = run?.info.resultDir ?? runIdOrDir;
  const basePath = path.join(resultDir, 'boltz_cofold', `oracle${oracleIdx}`, `mol_${molIdx}`, 'boltz_output');

  try {
    const files = await fs.readdir(basePath);
    const structureFile = files.find((f) => f.endsWith('.cif') || f.endsWith('.pdb'));
    if (structureFile) {
      return fs.readFile(path.join(basePath, structureFile), 'utf-8');
    }
  } catch {
    // Directory may not exist
  }

  return null;
});
