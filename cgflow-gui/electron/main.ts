import { app, BrowserWindow, ipcMain, dialog, Tray, Menu, nativeImage, session } from 'electron';
import { fileURLToPath } from 'url';
import path from 'path';
import fs from 'fs/promises';
import { spawn, ChildProcess, type SpawnOptions } from 'child_process';
import YAML from 'yaml';
import initSqlJs, { Database as SqlJsDatabase } from 'sql.js';
import { ConvexHttpClient } from 'convex/browser';
import { startRunnerServer } from './runner';
import { api } from '../convex/_generated/api';
import { OptConfigSchema } from '../shared/types';
import type {
  OptConfig,
  OptimizationEngine,
  RunInfo,
  GeneratedObject,
  BoltzScore,
  RewardCacheEntry,
  MoleculeResult,
  TrajectoryStep,
} from '../shared/types';
import { isPathContained, sanitizePath, validateFilePath } from './pathSecurity';

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
const OPT_BOLTZ_SCRIPT = path.join(CGFLOW_ROOT, 'scripts/opt/opt_boltz.py');
const OPT_FLASHBIND_SCRIPT = path.join(CGFLOW_ROOT, 'scripts/opt/opt_flashbind.py');
const CONDA_ENV_NAME = process.env.CGFLOW_CONDA_ENV?.trim() || 'cgflow';
const CONVEX_URL = process.env.VITE_CONVEX_URL ?? process.env.CONVEX_URL;
const convexClient = CONVEX_URL ? new ConvexHttpClient(CONVEX_URL) : null;
const GENERATED_CONFIG_DIR = path.join(CGFLOW_ROOT, 'configs', 'opt');
const SQLITE_EXTENSIONS = new Set(['.db', '.sqlite', '.sqlite3']);
const CONTENT_SECURITY_POLICY = [
  "default-src 'self'",
  "script-src 'self'",
  "style-src 'self' 'unsafe-inline'",
  "img-src 'self' data: blob:",
  "connect-src 'self' https://*.convex.cloud http://127.0.0.1:45731",
  "font-src 'self'",
].join('; ');

function normalizeEngine(engine: unknown): OptimizationEngine {
  return engine === 'flashbind' ? 'flashbind' : 'boltz';
}

function getOptScriptForEngine(engine: OptimizationEngine): string {
  return engine === 'flashbind' ? OPT_FLASHBIND_SCRIPT : OPT_BOLTZ_SCRIPT;
}

function spawnCgflowPython(args: string[], options: SpawnOptions): ChildProcess {
  return spawn(
    'conda',
    ['run', '--no-capture-output', '-n', CONDA_ENV_NAME, 'python', ...args],
    options
  );
}

function shellQuote(value: string): string {
  return `'${value.replace(/'/g, `'\\''`)}'`;
}

function formatCondaCommand(args: string[]): string {
  const full = ['conda', 'run', '--no-capture-output', '-n', CONDA_ENV_NAME, 'python', ...args];
  return full.map(shellQuote).join(' ');
}

function summarizeFailureLines(lines: string[], maxLines = 20): string[] {
  const stderrLines = lines.filter((line) => line.includes('[stderr]'));
  let tracebackStart = -1;
  for (let i = lines.length - 1; i >= 0; i -= 1) {
    if (/Traceback \(most recent call last\):/i.test(lines[i] ?? '')) {
      tracebackStart = i;
      break;
    }
  }

  if (tracebackStart >= 0) return lines.slice(tracebackStart).slice(-maxLines);
  if (stderrLines.length > 0) return stderrLines.slice(-maxLines);
  return lines.slice(-maxLines);
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
function queryAll<T>(db: SqlJsDatabase, sql: string, params: any[] = []): T[] {
  const stmt = db.prepare(sql);
  stmt.bind(params);
  const results: T[] = [];
  while (stmt.step()) {
    results.push(stmt.getAsObject() as T);
  }
  stmt.free();
  return results;
}

function isConvexPath(value: string | null | undefined): boolean {
  return typeof value === 'string' && value.startsWith('convex://');
}

function parseConvexPath(value: string): { id: string; name?: string } | null {
  if (!value.startsWith('convex://')) return null;
  const parts = value.replace('convex://', '').split('::');
  return { id: parts[0]!, name: parts[1] };
}

async function readConvexFileText(convexPath: string): Promise<string> {
  if (!convexClient) {
    throw new Error('Convex is not configured. Set VITE_CONVEX_URL or CONVEX_URL.');
  }
  const parsed = parseConvexPath(convexPath);
  if (!parsed) {
    throw new Error(`Invalid Convex file path: ${convexPath}`);
  }
  const url = await convexClient.query(api.files.getUrl, { id: parsed.id as any });
  if (!url) {
    throw new Error(`Convex file URL not available for: ${parsed.id}`);
  }
  const res = await fetch(url);
  if (!res.ok) {
    throw new Error(`Failed to download Convex file (${res.status}): ${res.statusText}`);
  }
  return await res.text();
}

async function resolveConvexFileToLocalPath(convexPath: string, destDir: string): Promise<string> {
  if (!convexClient) {
    throw new Error('Convex is not configured. Set VITE_CONVEX_URL or CONVEX_URL.');
  }
  const parsed = parseConvexPath(convexPath);
  if (!parsed) {
    throw new Error(`Invalid Convex file path: ${convexPath}`);
  }
  const url = await convexClient.query(api.files.getUrl, { id: parsed.id as any });
  if (!url) {
    throw new Error(`Convex file URL not available for: ${parsed.id}`);
  }
  const res = await fetch(url);
  if (!res.ok) {
    throw new Error(`Failed to download Convex file (${res.status}): ${res.statusText}`);
  }
  const buffer = Buffer.from(await res.arrayBuffer());
  const safeName = parsed.name ? parsed.name.replace(/[^a-zA-Z0-9._-]/g, '_') : 'file';
  await fs.mkdir(destDir, { recursive: true });
  const destPath = path.join(destDir, `${parsed.id}_${safeName}`);
  await fs.writeFile(destPath, buffer);
  return destPath;
}

async function resolveConfigConvexPaths(config: OptConfig, destDir: string): Promise<OptConfig> {
  const resolved = JSON.parse(JSON.stringify(config)) as OptConfig;
  const resolveOne = async (value: string | null): Promise<string | null> => {
    if (!value) return null;
    if (!isConvexPath(value)) return value;
    return await resolveConvexFileToLocalPath(value, destDir);
  };

  resolved.protein_path = (await resolveOne(resolved.protein_path)) ?? '';
  resolved.ref_ligand_path = await resolveOne(resolved.ref_ligand_path);
  resolved.pose_model = (await resolveOne(resolved.pose_model)) ?? resolved.pose_model;
  resolved.boltz.msa_path = await resolveOne(resolved.boltz.msa_path);
  return resolved;
}

function configHasConvexPaths(config: OptConfig): boolean {
  return [
    config.protein_path,
    config.ref_ligand_path,
    config.pose_model,
    config.boltz.msa_path,
  ].some((value) => isConvexPath(value ?? null));
}

function getAllowedConfigWriteDirs(): string[] {
  return [
    path.join(CGFLOW_ROOT, 'configs'),
    GENERATED_CONFIG_DIR,
    path.join(app.getPath('userData'), 'configs'),
  ].map((baseDir) => sanitizePath(baseDir));
}

function resolveAndValidatePath(filePath: string, operation: 'read' | 'write'): string {
  validateFilePath(filePath, operation);
  return sanitizePath(filePath);
}

function resolveRunResultDir(runIdOrDir: string): string {
  const run = activeRuns.get(runIdOrDir);
  const candidate = run?.info.resultDir ?? runIdOrDir;
  return resolveAndValidatePath(candidate, 'read');
}

function resolveAndValidateDbPath(dbPath: string): string {
  const resolved = resolveAndValidatePath(dbPath, 'read');
  const extension = path.extname(resolved).toLowerCase();
  if (!SQLITE_EXTENSIONS.has(extension)) {
    throw new Error(`Unsupported database file extension: ${extension || '(none)'}`);
  }

  const activeRunDirs = Array.from(activeRuns.values()).map(({ info }) => info.resultDir);
  const allowedDbBaseDirs = [CGFLOW_ROOT, app.getPath('userData'), ...activeRunDirs];
  if (!isPathContained(resolved, allowedDbBaseDirs)) {
    throw new Error(`Database path is outside allowed directories: ${resolved}`);
  }
  return resolved;
}

function configureContentSecurityPolicy() {
  session.defaultSession.webRequest.onHeadersReceived((details, callback) => {
    callback({
      responseHeaders: {
        ...details.responseHeaders,
        'Content-Security-Policy': [CONTENT_SECURITY_POLICY],
      },
    });
  });
}

// ============================================================================
// Window Creation
// ============================================================================

function createWindow() {
  const preloadPath = app.isPackaged
    ? path.join(__dirname, 'preload.js')
    : path.join(__dirname, '../electron/preload.cjs');

  mainWindow = new BrowserWindow({
    width: 1600,
    height: 1000,
    webPreferences: {
      preload: preloadPath,
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
    },
  });

  const devServerUrl =
    process.env.VITE_DEV_SERVER_URL ||
    process.env.ELECTRON_RENDERER_URL ||
    (!app.isPackaged ? 'http://localhost:5173' : '');

  if (devServerUrl) {
    mainWindow.loadURL(devServerUrl);
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
  configureContentSecurityPolicy();
  await initSQL();
  const parsedRunnerPort = Number.parseInt(
    process.env.CGFLOW_RUNNER_PORT ?? process.env.VITE_RUNNER_PORT ?? '',
    10
  );
  await startRunnerServer({
    dataDir: path.join(app.getPath('userData'), 'runner'),
    convexUrl: process.env.VITE_CONVEX_URL ?? process.env.CONVEX_URL,
    port: Number.isFinite(parsedRunnerPort) ? parsedRunnerPort : undefined,
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

ipcMain.handle('file:select-ligand', async () => {
  const result = await dialog.showOpenDialog({
    properties: ['openFile'],
    filters: [
      { name: 'Ligand Files', extensions: ['mol2', 'sdf', 'mol', 'pdb', 'cif', 'mmcif'] },
      { name: 'All Files', extensions: ['*'] },
    ],
  });
  return result.canceled ? null : result.filePaths[0] ?? null;
});

ipcMain.handle('file:select-json', async () => {
  const result = await dialog.showOpenDialog({
    properties: ['openFile'],
    filters: [{ name: 'JSON Files', extensions: ['json'] }],
  });
  return result.canceled ? null : result.filePaths[0] ?? null;
});

ipcMain.handle('file:select-msa', async () => {
  const result = await dialog.showOpenDialog({
    properties: ['openFile'],
    filters: [{ name: 'A3M Files', extensions: ['a3m'] }],
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
  if (isConvexPath(filePath)) {
    return await readConvexFileText(filePath);
  }
  const safeFilePath = resolveAndValidatePath(filePath, 'read');
  return fs.readFile(safeFilePath, 'utf-8');
});

ipcMain.handle('file:read-text', async (_event, filePath: string) => {
  if (isConvexPath(filePath)) {
    return await readConvexFileText(filePath);
  }
  const safeFilePath = resolveAndValidatePath(filePath, 'read');
  return await fs.readFile(safeFilePath, 'utf-8');
});

ipcMain.handle('file:read-yaml', async (_event, filePath: string) => {
  const safeFilePath = resolveAndValidatePath(filePath, 'read');
  const content = await fs.readFile(safeFilePath, 'utf-8');
  return YAML.parse(content) as OptConfig;
});

ipcMain.handle('file:write-yaml', async (_event, filePath: string, config: OptConfig) => {
  const safeFilePath = resolveAndValidatePath(filePath, 'write');
  const allowedConfigDirs = getAllowedConfigWriteDirs();
  if (!isPathContained(safeFilePath, allowedConfigDirs)) {
    throw new Error(`YAML writes are restricted to config directories: ${allowedConfigDirs.join(', ')}`);
  }
  const content = YAML.stringify(config);
  await fs.mkdir(path.dirname(safeFilePath), { recursive: true });
  await fs.writeFile(safeFilePath, content, 'utf-8');
});

ipcMain.handle('file:exists', async (_event, filePath: string) => {
  if (isConvexPath(filePath)) {
    try {
      const parsed = parseConvexPath(filePath);
      if (!parsed || !convexClient) return false;
      const url = await convexClient.query(api.files.getUrl, { id: parsed.id as any });
      return Boolean(url);
    } catch {
      return false;
    }
  }
  try {
    const safeFilePath = resolveAndValidatePath(filePath, 'read');
    await fs.access(safeFilePath);
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
  const runId = generateRunId();
  const resolvedInputsDir = path.join(app.getPath('userData'), 'inputs', runId);
  const hasConvexPaths = configHasConvexPaths(payload.config);
  const parsedConfig = OptConfigSchema.safeParse(
    hasConvexPaths ? await resolveConfigConvexPaths(payload.config, resolvedInputsDir) : payload.config
  );
  if (!parsedConfig.success) {
    throw new Error(`Invalid optimization config: ${parsedConfig.error.message}`);
  }
  const config = parsedConfig.data;
  resolveAndValidatePath(config.result_dir, 'write');
  resolveAndValidatePath(config.env_dir, 'write');

  let configPath = payload.configPath ?? null;
  if (configPath) {
    if (isConvexPath(configPath)) {
      throw new Error('Convex config paths are not supported for local process execution');
    }
    configPath = resolveAndValidatePath(configPath, 'read');
  }

  if (!configPath || hasConvexPaths) {
    await fs.mkdir(GENERATED_CONFIG_DIR, { recursive: true });
    const generatedConfigPath = path.join(GENERATED_CONFIG_DIR, `generated_${Date.now()}.yaml`);
    const allowedConfigDirs = getAllowedConfigWriteDirs();
    if (!isPathContained(generatedConfigPath, allowedConfigDirs)) {
      throw new Error(`Generated config path is outside allowed config directories: ${generatedConfigPath}`);
    }
    const content = YAML.stringify(config);
    await fs.writeFile(generatedConfigPath, content, 'utf-8');
    configPath = generatedConfigPath;
  }
  if (!configPath) {
    throw new Error('Failed to resolve config path');
  }
  const safeConfigPath = configPath;
  const timestamp = new Date().toISOString().replace(/[:.]/g, '').substring(0, 15);
  const resultDir = path.join(config.result_dir, timestamp);

  const runInfo: RunInfo = {
    id: runId,
    name: payload.name || `Run ${timestamp}`,
    configPath: safeConfigPath,
    resultDir,
    status: 'running',
    currentStep: 0,
    totalSteps: config.num_steps,
    startedAt: new Date().toISOString(),
    lastUpdatedAt: new Date().toISOString(),
    checkpointPath: null,
    error: null,
    engine: normalizeEngine(config.engine),
  };

  const args = [
    getOptScriptForEngine(runInfo.engine ?? 'boltz'),
    '--config', safeConfigPath,
    '--result_dir', config.result_dir,
    '--env_dir', config.env_dir,
  ];

  const proc = spawnCgflowPython(args, {
    cwd: CGFLOW_ROOT,
    env: { ...process.env },
  });
  const commandString = formatCondaCommand(args);
  const outputBuffer: string[] = [];
  const pushOutput = (line: string) => {
    outputBuffer.push(line);
    if (outputBuffer.length > 2000) {
      outputBuffer.splice(0, outputBuffer.length - 2000);
    }
  };
  const launchLine = `[runner] Launching command: ${commandString}`;
  pushOutput(launchLine);
  emitToRenderer('run:output', runId, launchLine);

  proc.stdout?.on('data', (data: Buffer) => {
    const output = data.toString();
    output.split(/\r?\n/).forEach((line) => {
      if (line.trim().length > 0) pushOutput(line);
    });
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
    output.split(/\r?\n/).forEach((line) => {
      if (line.trim().length > 0) pushOutput(`[stderr] ${line}`);
    });
    emitToRenderer('run:output', runId, `[stderr] ${output}`);
  });

  proc.on('close', (code, signal) => {
    runInfo.status = code === 0 ? 'completed' : 'error';
    if (code !== 0) {
      const snippet = summarizeFailureLines(outputBuffer);
      runInfo.error = [
        `Training process failed (${code !== null ? `exit code ${code}` : `signal ${signal ?? 'unknown'}`}).`,
        `Command: ${commandString}`,
        ...(snippet.length > 0 ? ['Recent output:', ...snippet] : []),
      ].join('\n');
      emitToRenderer('run:error', runId, runInfo.error);
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
  const safeConfigPath = resolveAndValidatePath(info.configPath, 'read');
  const safeCheckpointPath = resolveAndValidatePath(checkpointPath, 'read');
  const allowedCheckpointDirs = [info.resultDir];
  if (info.checkpointPath) {
    allowedCheckpointDirs.push(path.dirname(info.checkpointPath));
  }
  if (!isPathContained(safeCheckpointPath, allowedCheckpointDirs)) {
    throw new Error('Checkpoint path is outside allowed checkpoint directories');
  }

  const args = [
    getOptScriptForEngine(normalizeEngine(info.engine)),
    '--config', safeConfigPath,
    '--resume_from', safeCheckpointPath,
  ];

  if (oracleIdx !== undefined) {
    args.push('--resume_oracle_idx', oracleIdx.toString());
  }

  const proc = spawnCgflowPython(args, {
    cwd: CGFLOW_ROOT,
    env: { ...process.env },
  });
  const commandString = formatCondaCommand(args);
  const outputBuffer: string[] = [];
  const pushOutput = (line: string) => {
    outputBuffer.push(line);
    if (outputBuffer.length > 2000) {
      outputBuffer.splice(0, outputBuffer.length - 2000);
    }
  };
  const launchLine = `[runner] Launching command: ${commandString}`;
  pushOutput(launchLine);
  emitToRenderer('run:output', runId, launchLine);

  info.status = 'running';
  info.lastUpdatedAt = new Date().toISOString();

  proc.stdout?.on('data', (data: Buffer) => {
    const output = data.toString();
    output.split(/\r?\n/).forEach((line) => {
      if (line.trim().length > 0) pushOutput(line);
    });
    emitToRenderer('run:output', runId, output);
    
    const stepMatch = output.match(/iteration\s+(\d+)/i);
    if (stepMatch?.[1]) {
      info.currentStep = parseInt(stepMatch[1], 10);
      info.lastUpdatedAt = new Date().toISOString();
      emitToRenderer('run:status-changed', info);
    }
  });

  proc.stderr?.on('data', (data: Buffer) => {
    const output = data.toString();
    output.split(/\r?\n/).forEach((line) => {
      if (line.trim().length > 0) pushOutput(`[stderr] ${line}`);
    });
    emitToRenderer('run:output', runId, `[stderr] ${output}`);
  });

  proc.on('close', (code, signal) => {
    info.status = code === 0 ? 'completed' : 'error';
    if (code !== 0) {
      const snippet = summarizeFailureLines(outputBuffer);
      info.error = [
        `Training process failed (${code !== null ? `exit code ${code}` : `signal ${signal ?? 'unknown'}`}).`,
        `Command: ${commandString}`,
        ...(snippet.length > 0 ? ['Recent output:', ...snippet] : []),
      ].join('\n');
      emitToRenderer('run:error', runId, info.error);
    } else {
      info.error = null;
    }
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

ipcMain.handle('run:delete', async (_event, runId: string) => {
  const run = activeRuns.get(runId);
  if (run?.info.status === 'running') {
    throw new Error('Cannot delete an active run. Stop it first.');
  }
  activeRuns.delete(runId);
});

ipcMain.handle('run:get-checkpoints', async (_event, runIdOrDir: string) => {
  const resultDir = resolveRunResultDir(runIdOrDir);
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

ipcMain.handle('run:get-output', async (_event, runIdOrDir: string, tail = 200) => {
  const resultDir = resolveRunResultDir(runIdOrDir);
  const candidatePaths = [
    path.join(resultDir, 'train.log'),
    path.join(resultDir, 'run.log'),
  ];

  for (const logPath of candidatePaths) {
    try {
      const content = await fs.readFile(logPath, 'utf-8');
      const all = content.split(/\r?\n/).filter((line) => line.length > 0);
      return all.slice(-Math.max(1, tail));
    } catch {
      // Try next candidate path
    }
  }

  return [];
});

// ============================================================================
// Database Queries
// ============================================================================

ipcMain.handle('db:get-generated-objects', async (_event, dbPath: string, limit = 100, offset = 0) => {
  const safeDbPath = resolveAndValidateDbPath(dbPath);
  const db = await openDatabase(safeDbPath);
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
  const safeDbPath = resolveAndValidateDbPath(dbPath);
  const db = await openDatabase(safeDbPath);
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
  const safeDbPath = resolveAndValidateDbPath(dbPath);
  const db = await openDatabase(safeDbPath);
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
  const resultDir = resolveRunResultDir(runIdOrDir);
  const rewardCachePath = path.join(resultDir, 'boltz_reward_cache.db');
  const trainDir = path.join(resultDir, 'train');
  if (!isPathContained(rewardCachePath, [resultDir]) || !isPathContained(trainDir, [resultDir])) {
    throw new Error('Derived database paths must remain within result directory');
  }

  const results: MoleculeResult[] = [];

  // Get top molecules from reward cache
  try {
    const rewardDb = await openDatabase(resolveAndValidateDbPath(rewardCachePath));
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
      if (!isPathContained(generatedDbPath, [resultDir])) {
        throw new Error('Generated object DB path escaped result directory');
      }
      const genDb = await openDatabase(resolveAndValidateDbPath(generatedDbPath));
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
      if (!isPathContained(boltzDbPath, [resultDir])) {
        throw new Error('Boltz score DB path escaped result directory');
      }
      const boltzDb = await openDatabase(resolveAndValidateDbPath(boltzDbPath));
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
  const safeResultDir = resolveAndValidatePath(resultDir, 'read');
  const basePath = path.join(safeResultDir, 'boltz_cofold', `oracle${oracleIdx}`, `mol_${molIdx}`, 'boltz_output');
  if (!isPathContained(basePath, [safeResultDir])) {
    throw new Error('Complex path escaped result directory');
  }
  
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
  const safeComplexPath = resolveAndValidatePath(complexPath, 'read');
  return fs.readFile(safeComplexPath, 'utf-8');
});

// Convenience: get complex content directly by runId or resultDir
ipcMain.handle('boltz:get-complex', async (_event, runIdOrDir: string, oracleIdx: number, molIdx: number) => {
  const resultDir = resolveRunResultDir(runIdOrDir);
  const basePath = path.join(resultDir, 'boltz_cofold', `oracle${oracleIdx}`, `mol_${molIdx}`, 'boltz_output');
  if (!isPathContained(basePath, [resultDir])) {
    throw new Error('Complex path escaped result directory');
  }

  try {
    const files = await fs.readdir(basePath);
    const structureFile = files.find((f) => f.endsWith('.cif') || f.endsWith('.pdb'));
    if (structureFile) {
      const structurePath = path.join(basePath, structureFile);
      if (!isPathContained(structurePath, [resultDir])) {
        throw new Error('Resolved complex file escaped result directory');
      }
      const safeStructurePath = resolveAndValidatePath(structurePath, 'read');
      return fs.readFile(safeStructurePath, 'utf-8');
    }
  } catch {
    // Directory may not exist
  }

  return null;
});
