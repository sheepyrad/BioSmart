import http from 'http';
import path from 'path';
import os from 'os';
import fs from 'fs/promises';
import { spawn, ChildProcess, type SpawnOptions } from 'child_process';
import { fileURLToPath } from 'url';
import YAML from 'yaml';
import initSqlJs, { Database as SqlJsDatabase } from 'sql.js';
import { ConvexHttpClient } from 'convex/browser';
import type {
  OptConfig,
  RunInfo,
  MoleculeResult,
  RewardCacheEntry,
  BoltzScore,
  TrajectoryStep,
} from '../shared/types';
import { getConvexSyncService } from './convex-sync';
import { api } from '../convex/_generated/api';

const __dirname = path.dirname(fileURLToPath(import.meta.url));

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

const DEFAULT_PORT = 45731;

interface RunnerOptions {
  dataDir?: string;
  convexUrl?: string;
  port?: number;
}

interface RunRecord extends RunInfo {
  pid: number | null;
  configId?: string | null;
  convexRunId?: string | null;
  source?: 'local';
  logPath?: string | null;
}

interface RunnerStartPayload {
  config?: OptConfig;
  configPath?: string | null;
  configId?: string | null;
  name?: string | null;
}

interface RunnerState {
  runs: Map<string, RunRecord>;
  outputs: Map<string, string[]>;
  processes: Map<string, ChildProcess>;
}

// ============================================================================
// SQL.js helpers
// ============================================================================

let SQL: Awaited<ReturnType<typeof initSqlJs>> | null = null;
async function initSQL() {
  if (!SQL) {
    SQL = await initSqlJs();
  }
  return SQL;
}

async function openDatabase(dbPath: string): Promise<SqlJsDatabase> {
  const sql = await initSQL();
  const buffer = await fs.readFile(dbPath);
  return new sql.Database(buffer);
}

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

// ============================================================================
// Runner utilities
// ============================================================================

function formatTimestamp(date = new Date()): string {
  const yy = String(date.getFullYear()).slice(-2);
  const mm = String(date.getMonth() + 1).padStart(2, '0');
  const dd = String(date.getDate()).padStart(2, '0');
  const hh = String(date.getHours()).padStart(2, '0');
  const mi = String(date.getMinutes()).padStart(2, '0');
  const ss = String(date.getSeconds()).padStart(2, '0');
  return `${yy}${mm}${dd}_${hh}${mi}${ss}`;
}

function generateRunId(): string {
  return `run_${Date.now()}_${Math.random().toString(36).substring(2, 9)}`;
}

function isConvexPath(value: string | null | undefined): boolean {
  return typeof value === 'string' && value.startsWith('convex://');
}

function parseConvexPath(value: string): { id: string; name?: string } | null {
  if (!value.startsWith('convex://')) return null;
  const parts = value.replace('convex://', '').split('::');
  return { id: parts[0]!, name: parts[1] };
}

async function readJson<T>(filePath: string, fallback: T): Promise<T> {
  try {
    const raw = await fs.readFile(filePath, 'utf-8');
    return JSON.parse(raw) as T;
  } catch {
    return fallback;
  }
}

async function writeJson(filePath: string, data: unknown) {
  await fs.writeFile(filePath, JSON.stringify(data, null, 2), 'utf-8');
}

function isProcessAlive(pid: number | null) {
  if (!pid) return false;
  try {
    process.kill(pid, 0);
    return true;
  } catch {
    return false;
  }
}

async function readTail(filePath: string, lines = 500): Promise<string[]> {
  try {
    const content = await fs.readFile(filePath, 'utf-8');
    const all = content.split('\n');
    return all.slice(-lines).filter((l) => l.length > 0);
  } catch {
    return [];
  }
}

async function ensureDir(dirPath: string) {
  await fs.mkdir(dirPath, { recursive: true });
}

const AMINO_ACID_3_TO_1: Record<string, string> = {
  ALA: 'A',
  ARG: 'R',
  ASN: 'N',
  ASP: 'D',
  CYS: 'C',
  GLN: 'Q',
  GLU: 'E',
  GLY: 'G',
  HIS: 'H',
  ILE: 'I',
  LEU: 'L',
  LYS: 'K',
  MET: 'M',
  PHE: 'F',
  PRO: 'P',
  SER: 'S',
  THR: 'T',
  TRP: 'W',
  TYR: 'Y',
  VAL: 'V',
  SEC: 'U',
  PYL: 'O',
  MSE: 'M',
};

interface ParsedProteinSequence {
  chainId: string;
  sequence: string;
}

function parseProteinSequencesFromPdb(pdbContent: string): ParsedProteinSequence[] {
  const chainResidues = new Map<string, { order: string[]; residues: Map<string, string> }>();

  for (const line of pdbContent.split(/\r?\n/)) {
    if (!line.startsWith('ATOM')) continue;
    if (line.length < 27) continue;

    const residueName = line.slice(17, 20).trim().toUpperCase();
    const chainRaw = line.slice(21, 22).trim();
    const chainId = chainRaw || 'A';
    const residueNumber = line.slice(22, 26).trim();
    const insertionCode = line.slice(26, 27).trim();
    const residueKey = `${residueNumber}:${insertionCode}`;

    const oneLetter = AMINO_ACID_3_TO_1[residueName];
    if (!oneLetter) continue;

    let chain = chainResidues.get(chainId);
    if (!chain) {
      chain = { order: [], residues: new Map<string, string>() };
      chainResidues.set(chainId, chain);
    }
    if (!chain.residues.has(residueKey)) {
      chain.order.push(residueKey);
      chain.residues.set(residueKey, oneLetter);
    }
  }

  const sequences: ParsedProteinSequence[] = [];
  for (const [chainId, chain] of chainResidues.entries()) {
    const sequence = chain.order.map((key) => chain.residues.get(key) ?? '').join('');
    if (sequence.length > 0) {
      sequences.push({ chainId, sequence });
    }
  }
  return sequences;
}

async function generateBoltzBaseYamlFromPdb(
  pdbPath: string,
  outputPath: string,
  msaPath?: string | null
): Promise<void> {
  const pdbContent = await fs.readFile(pdbPath, 'utf-8');
  const sequences = parseProteinSequencesFromPdb(pdbContent);
  if (sequences.length === 0) {
    throw new Error(`Could not extract protein sequence from PDB: ${pdbPath}`);
  }

  const yamlPayload = {
    version: 1,
    sequences: sequences.map((entry) => ({
      protein: {
        id: entry.chainId,
        sequence: entry.sequence,
        ...(msaPath ? { msa: msaPath } : {}),
      },
    })),
  };
  await fs.writeFile(outputPath, YAML.stringify(yamlPayload), 'utf-8');
}

// ============================================================================
// Runner core
// ============================================================================

export async function startRunnerServer(options: RunnerOptions = {}) {
  const port = options.port ?? DEFAULT_PORT;
  const dataDir = options.dataDir ?? path.join(os.homedir(), '.cgflow-runner');
  const runsDir = path.join(dataDir, 'runs');
  const runsFile = path.join(dataDir, 'runs.json');
  const convexUrl = options.convexUrl ?? process.env.VITE_CONVEX_URL ?? process.env.CONVEX_URL;
  const convexClient = convexUrl ? new ConvexHttpClient(convexUrl) : null;
  const convexSync = getConvexSyncService(convexUrl);

  await ensureDir(runsDir);

  const state: RunnerState = {
    runs: new Map(),
    outputs: new Map(),
    processes: new Map(),
  };

  const sseClients = new Set<http.ServerResponse>();

  function broadcast(event: string, data: unknown) {
    const payload = `event: ${event}\ndata: ${JSON.stringify(data)}\n\n`;
    for (const res of sseClients) {
      res.write(payload);
    }
  }

  async function persistRuns() {
    const all = Array.from(state.runs.values());
    await writeJson(runsFile, { runs: all });
  }

  async function loadRuns() {
    const data = await readJson<{ runs: RunRecord[] }>(runsFile, { runs: [] });
    for (const run of data.runs) {
      const alive = isProcessAlive(run.pid);
      if (run.status === 'running' && !alive) {
        run.status = 'paused';
        run.error = 'Runner restarted; previous process not found.';
      }
      run.source = 'local';
      state.runs.set(run.id, run);
    }
  }

  await loadRuns();

  async function resolveConvexFile(convexPath: string, destDir: string): Promise<string> {
    if (!convexClient) {
      throw new Error('Convex not configured');
    }
    const parsed = parseConvexPath(convexPath);
    if (!parsed) throw new Error('Invalid Convex file path');
    const url = await convexClient.query(api.files.getUrl, { id: parsed.id as any });
    if (!url) throw new Error('Convex file URL not available');

    const res = await fetch(url);
    if (!res.ok) throw new Error(`Failed to download file: ${res.statusText}`);
    const buffer = Buffer.from(await res.arrayBuffer());

    const safeName = parsed.name ? parsed.name.replace(/[^a-zA-Z0-9._-]/g, '_') : 'file';
    const destPath = path.join(destDir, `${parsed.id}_${safeName}`);
    await fs.writeFile(destPath, buffer);
    return destPath;
  }

  async function resolveConfigPaths(config: OptConfig, inputsDir: string): Promise<OptConfig> {
    const resolved = JSON.parse(JSON.stringify(config)) as OptConfig;

    const resolveFile = async (value: string | null): Promise<string | null> => {
      if (!value) return null;
      if (isConvexPath(value)) {
        await ensureDir(inputsDir);
        return await resolveConvexFile(value, inputsDir);
      }
      return value;
    };

    resolved.protein_path = (await resolveFile(resolved.protein_path)) ?? '';
    resolved.ref_ligand_path = await resolveFile(resolved.ref_ligand_path);
    resolved.pose_model = (await resolveFile(resolved.pose_model)) ?? resolved.pose_model;
    resolved.boltz.msa_path = await resolveFile(resolved.boltz.msa_path);

    return resolved;
  }

  function convexConfigToOpt(config: any): OptConfig {
    return {
      result_dir: config.resultDir,
      env_dir: config.envDir,
      max_atoms: config.maxAtoms,
      subsampling_ratio: config.subsamplingRatio,
      protein_path: config.proteinPath,
      center: config.center ?? null,
      ref_ligand_path: config.refLigandPath ?? null,
      size: config.size as [number, number, number],
      num_steps: config.numSteps,
      num_sampling_per_step: config.numSamplingPerStep,
      temperature: [config.temperatureMin, config.temperatureMax],
      seed: config.seed,
      pose_model: config.poseModel,
      pose_steps: config.poseSteps,
      sampling_tau: config.samplingTau,
      random_action_prob: config.randomActionProb,
      replay_warmup_step: config.replayWarmupStep,
      replay_capacity: config.replayCapacity,
      boltz: {
        base_yaml: config.boltzBaseYaml,
        target_residues: config.boltzTargetResidues ?? [],
        msa_path: config.boltzMsaPath ?? null,
        cache_dir: config.boltzCacheDir ?? null,
        use_msa_server: config.boltzUseMsaServer ?? false,
        worker: Math.max(1, Math.floor(config.boltzWorker ?? 1)),
      },
    };
  }

  async function detectResultDir(baseDir: string, startedAt: number): Promise<string | null> {
    try {
      const entries = await fs.readdir(baseDir, { withFileTypes: true });
      const dirs = entries
        .filter((d) => d.isDirectory())
        .map((d) => d.name)
        .filter((name) => /^\d{6}_\d{6}$/.test(name))
        .map((name) => ({
          name,
          path: path.join(baseDir, name),
        }));

      let best: { name: string; path: string; mtimeMs: number } | null = null;
      for (const dir of dirs) {
        const stats = await fs.stat(dir.path);
        if (!best || stats.mtimeMs > best.mtimeMs) {
          best = { ...dir, mtimeMs: stats.mtimeMs };
        }
      }

      if (best && best.mtimeMs >= startedAt - 5000) {
        return best.path;
      }
    } catch {
      return null;
    }
    return null;
  }

  async function copyConfigToResultDir(configPath: string, resultDir: string) {
    try {
      await ensureDir(resultDir);
      const dest = path.join(resultDir, 'config.yaml');
      await fs.copyFile(configPath, dest);
    } catch {
      // ignore
    }
  }

  async function startRun(payload: RunnerStartPayload): Promise<RunRecord> {
    let config = payload.config;
    let configName = payload.name;
    if (!config) {
      if (!payload.configId || !convexClient) {
        throw new Error('Missing config payload and Convex is not available.');
      }
      const convexConfig = await convexClient.query(api.configs.get, { id: payload.configId as any });
      if (!convexConfig) {
        throw new Error('Config not found in Convex.');
      }
      config = convexConfigToOpt(convexConfig);
      configName = configName || convexConfig.name;
    }

    if (!config) {
      throw new Error('Config payload is required.');
    }

    const runId = generateRunId();
    const runStartedAt = Date.now();
    const timestamp = formatTimestamp(new Date(runStartedAt));
    const expectedResultDir = path.join(config.result_dir, timestamp);

    const runMetaDir = path.join(runsDir, runId);
    await ensureDir(runMetaDir);

    const inputsDir = path.join(runMetaDir, 'inputs');
    const resolvedConfig = await resolveConfigPaths(config, inputsDir);
    if (!resolvedConfig.protein_path) {
      throw new Error('protein_path is required to generate Boltz base YAML.');
    }
    await ensureDir(inputsDir);
    const generatedBoltzYamlPath = path.join(inputsDir, 'boltz_base.generated.yaml');
    await generateBoltzBaseYamlFromPdb(
      resolvedConfig.protein_path,
      generatedBoltzYamlPath,
      resolvedConfig.boltz.msa_path
    );
    resolvedConfig.boltz.base_yaml = generatedBoltzYamlPath;
    const resolvedConfigPath = path.join(runMetaDir, 'config.resolved.yaml');
    await fs.writeFile(resolvedConfigPath, YAML.stringify(resolvedConfig), 'utf-8');

    const logPath = path.join(runMetaDir, 'run.log');

    const runInfo: RunRecord = {
      id: runId,
      name: configName || `Run ${timestamp}`,
      configPath: payload.configPath ?? resolvedConfigPath,
      resultDir: expectedResultDir,
      status: 'running',
      currentStep: 0,
      totalSteps: config.num_steps,
      startedAt: new Date(runStartedAt).toISOString(),
      lastUpdatedAt: new Date(runStartedAt).toISOString(),
      checkpointPath: null,
      error: null,
      pid: null,
      configId: payload.configId ?? null,
      convexRunId: null,
      source: 'local',
      logPath,
    };

    state.runs.set(runId, runInfo);
    state.outputs.set(runId, []);
    await persistRuns();

    // Create Convex run if configured and configId provided
    if (payload.configId && convexUrl) {
      const convexRunId = await convexSync.createRun(
        payload.configId,
        runInfo.name,
        runInfo.resultDir,
        runInfo.totalSteps
      );
      if (convexRunId) {
        runInfo.convexRunId = convexRunId;
        await persistRuns();
      }
    }

    const args = [
      OPT_SCRIPT,
      '--config',
      resolvedConfigPath,
      '--result_dir',
      config.result_dir,
      '--env_dir',
      config.env_dir,
    ];

    const proc = spawnCgflowPython(args, {
      cwd: CGFLOW_ROOT,
      env: { ...process.env },
    });

    runInfo.pid = proc.pid ?? null;
    state.processes.set(runId, proc);

    let stdoutBuffer = '';

    const appendOutput = async (line: string) => {
      if (!line) return;
      const existing = state.outputs.get(runId) ?? [];
      existing.push(line);
      if (existing.length > 2000) {
        existing.splice(0, existing.length - 2000);
      }
      state.outputs.set(runId, existing);
      await fs.appendFile(logPath, `${line}\n`, 'utf-8');
      broadcast('run:output', { runId, output: line });
    };

    const handleChunk = async (chunk: Buffer, label?: string) => {
      const text = chunk.toString();
      const combined = stdoutBuffer + text;
      const lines = combined.split(/\r?\n/);
      stdoutBuffer = lines.pop() ?? '';
      for (const line of lines) {
        const outLine = label ? `${label} ${line}` : line;
        await appendOutput(outLine);
        const stepMatch = line.match(/iteration\s+(\d+)/i);
        if (stepMatch?.[1]) {
          runInfo.currentStep = parseInt(stepMatch[1], 10);
          runInfo.lastUpdatedAt = new Date().toISOString();
          void persistRuns();
          broadcast('run:status-changed', runInfo);
        }
        const checkpointMatch = line.match(/Saved checkpoint.*?(model_state_\d+\.pt)/);
        if (checkpointMatch?.[1]) {
          runInfo.checkpointPath = path.join(runInfo.resultDir, checkpointMatch[1]);
          void persistRuns();
          broadcast('run:checkpoint-saved', { runId, checkpointPath: runInfo.checkpointPath });
        }
      }
    };

    proc.stdout?.on('data', (data: Buffer) => {
      void handleChunk(data);
    });

    proc.stderr?.on('data', (data: Buffer) => {
      void handleChunk(data, '[stderr]');
    });

    proc.on('close', async (code) => {
      runInfo.status = code === 0 ? 'completed' : 'error';
      runInfo.error = code === 0 ? null : `Process exited with code ${code}`;
      runInfo.lastUpdatedAt = new Date().toISOString();
      state.processes.delete(runId);
      await persistRuns();
      broadcast('run:status-changed', runInfo);

      if (runInfo.convexRunId) {
        await convexSync.updateRunStatus(
          runInfo.convexRunId,
          runInfo.status,
          runInfo.currentStep,
          runInfo.checkpointPath,
          runInfo.error
        );
        convexSync.stopSync(runId);
      }
    });

    proc.on('error', async (err) => {
      runInfo.status = 'error';
      runInfo.error = err.message;
      runInfo.lastUpdatedAt = new Date().toISOString();
      state.processes.delete(runId);
      await persistRuns();
      broadcast('run:error', { runId, error: err.message });
      broadcast('run:status-changed', runInfo);

      if (runInfo.convexRunId) {
        await convexSync.updateRunStatus(
          runInfo.convexRunId,
          'error',
          runInfo.currentStep,
          runInfo.checkpointPath,
          runInfo.error
        );
        convexSync.stopSync(runId);
      }
    });

    // Try to detect actual result directory and copy config
    for (let attempt = 0; attempt < 5; attempt++) {
      const detected = await detectResultDir(config.result_dir, runStartedAt);
      if (detected) {
        runInfo.resultDir = detected;
        await copyConfigToResultDir(resolvedConfigPath, detected);
        await persistRuns();
        break;
      }
      await new Promise((resolve) => setTimeout(resolve, 1000));
    }

    // Start Convex sync if configured
    if (runInfo.convexRunId) {
      convexSync.startSync(runId, runInfo.convexRunId, runInfo.resultDir, 30000);
    }

    broadcast('run:status-changed', runInfo);

    return runInfo;
  }

  async function resumeRun(runId: string, checkpointPath: string, oracleIdx?: number): Promise<RunRecord> {
    const run = state.runs.get(runId);
    if (!run) {
      throw new Error(`Run ${runId} not found`);
    }

    const args = [OPT_SCRIPT, '--config', run.configPath, '--resume_from', checkpointPath];
    if (oracleIdx !== undefined) {
      args.push('--resume_oracle_idx', String(oracleIdx));
    }

    const proc = spawnCgflowPython(args, {
      cwd: CGFLOW_ROOT,
      env: { ...process.env },
    });

    run.status = 'running';
    run.lastUpdatedAt = new Date().toISOString();
    run.checkpointPath = checkpointPath;
    run.resultDir = path.dirname(checkpointPath);
    run.pid = proc.pid ?? null;
    state.processes.set(runId, proc);
    await persistRuns();

    let stdoutBuffer = '';

    const appendOutput = async (line: string) => {
      if (!line) return;
      const existing = state.outputs.get(runId) ?? [];
      existing.push(line);
      if (existing.length > 2000) {
        existing.splice(0, existing.length - 2000);
      }
      state.outputs.set(runId, existing);
      if (run.logPath) {
        await fs.appendFile(run.logPath, `${line}\n`, 'utf-8');
      }
      broadcast('run:output', { runId, output: line });
    };

    const handleChunk = async (chunk: Buffer, label?: string) => {
      const text = chunk.toString();
      const combined = stdoutBuffer + text;
      const lines = combined.split(/\r?\n/);
      stdoutBuffer = lines.pop() ?? '';
      for (const line of lines) {
        const outLine = label ? `${label} ${line}` : line;
        await appendOutput(outLine);
        const stepMatch = line.match(/iteration\s+(\d+)/i);
        if (stepMatch?.[1]) {
          run.currentStep = parseInt(stepMatch[1], 10);
          run.lastUpdatedAt = new Date().toISOString();
          void persistRuns();
          broadcast('run:status-changed', run);
        }
      }
    };

    proc.stdout?.on('data', (data: Buffer) => {
      void handleChunk(data);
    });

    proc.stderr?.on('data', (data: Buffer) => {
      void handleChunk(data, '[stderr]');
    });

    proc.on('close', async (code) => {
      run.status = code === 0 ? 'completed' : 'error';
      run.error = code === 0 ? null : `Process exited with code ${code}`;
      run.lastUpdatedAt = new Date().toISOString();
      state.processes.delete(runId);
      await persistRuns();
      broadcast('run:status-changed', run);

      if (run.convexRunId) {
        await convexSync.updateRunStatus(
          run.convexRunId,
          run.status,
          run.currentStep,
          run.checkpointPath,
          run.error
        );
        convexSync.stopSync(runId);
      }
    });

    proc.on('error', async (err) => {
      run.status = 'error';
      run.error = err.message;
      run.lastUpdatedAt = new Date().toISOString();
      state.processes.delete(runId);
      await persistRuns();
      broadcast('run:error', { runId, error: err.message });
      broadcast('run:status-changed', run);

      if (run.convexRunId) {
        await convexSync.updateRunStatus(
          run.convexRunId,
          'error',
          run.currentStep,
          run.checkpointPath,
          run.error
        );
        convexSync.stopSync(runId);
      }
    });

    if (run.convexRunId) {
      await convexSync.updateRunStatus(run.convexRunId, 'running', run.currentStep);
      convexSync.startSync(runId, run.convexRunId, run.resultDir, 30000);
    }

    broadcast('run:status-changed', run);

    return run;
  }

  async function loadTrajectoryMap(trainDir: string, smiles: string[]): Promise<Map<string, string>> {
    const trajMap = new Map<string, string>();
    if (smiles.length === 0) return trajMap;

    let files: string[] = [];
    try {
      files = await fs.readdir(trainDir);
    } catch {
      return trajMap;
    }

    const dbFiles = files.filter((f) => f.startsWith('generated_objs_') && f.endsWith('.db'));
    if (dbFiles.length === 0) return trajMap;

    const placeholders = smiles.map(() => '?').join(',');

    for (const dbFile of dbFiles) {
      const dbPath = path.join(trainDir, dbFile);
      try {
        const genDb = await openDatabase(dbPath);
        const trajRows = queryAll<{ smi: string; traj: string }>(
          genDb,
          `SELECT smi, traj FROM results WHERE smi IN (${placeholders})`,
          smiles
        );
        genDb.close();
        for (const row of trajRows) {
          if (!row.traj) continue;
          const existing = trajMap.get(row.smi);
          if (!existing) {
            trajMap.set(row.smi, row.traj);
            continue;
          }
          try {
            const currentLen = JSON.parse(existing).length ?? 0;
            const nextLen = JSON.parse(row.traj).length ?? 0;
            if (nextLen > currentLen) {
              trajMap.set(row.smi, row.traj);
            }
          } catch {
            // Keep existing on parse error
          }
        }
      } catch {
        // Ignore missing/corrupt DB files
      }
    }

    return trajMap;
  }

  async function getTopMolecules(runId: string, limit = 50): Promise<MoleculeResult[]> {
    const run = state.runs.get(runId);
    if (!run) return [];

    const rewardCachePath = path.join(run.resultDir, 'boltz_reward_cache.db');
    const trainDir = path.join(run.resultDir, 'train');

    const results: MoleculeResult[] = [];

    try {
      const rewardDb = await openDatabase(rewardCachePath);
      const topEntries = queryAll<RewardCacheEntry>(
        rewardDb,
        `SELECT smiles, reward, info FROM entries ORDER BY reward DESC LIMIT ?`,
        [limit]
      );
      rewardDb.close();

      if (topEntries.length === 0) return results;

      // Get trajectory info (scan all generated_objs_*.db)
      const trajMap = await loadTrajectoryMap(
        trainDir,
        topEntries.map((e) => e.smiles)
      );

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

      const indexMap = new Map<string, { oracleIdx: number | null; molIdx: number | null }>();
      for (const entry of topEntries) {
        if (!entry.info) continue;
        try {
          const parsed = JSON.parse(entry.info) as { oracle_idx?: number; mol_idx?: number };
          indexMap.set(entry.smiles, {
            oracleIdx: typeof parsed.oracle_idx === 'number' ? parsed.oracle_idx : null,
            molIdx: typeof parsed.mol_idx === 'number' ? parsed.mol_idx : null,
          });
        } catch {
          // ignore
        }
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

        const idx = indexMap.get(entry.smiles);

        results.push({
          smiles: entry.smiles,
          reward: entry.reward,
          trajectory,
          boltzScores: boltzMap.get(entry.smiles) ?? null,
          complexPath: null,
          oracleIdx: idx?.oracleIdx ?? null,
          molIdx: idx?.molIdx ?? null,
        });
      }
    } catch {
      return [];
    }

    return results;
  }

  async function getComplexContent(runId: string, oracleIdx: number, molIdx: number): Promise<string | null> {
    const run = state.runs.get(runId);
    if (!run) return null;
    const basePath = path.join(
      run.resultDir,
      'boltz_cofold',
      `oracle${oracleIdx}`,
      `mol_${molIdx}`,
      'boltz_output'
    );
    try {
      const files = await fs.readdir(basePath);
      const structureFile = files.find((f) => f.endsWith('.cif') || f.endsWith('.pdb'));
      if (structureFile) {
        return await fs.readFile(path.join(basePath, structureFile), 'utf-8');
      }
    } catch {
      return null;
    }
    return null;
  }

  // ========================================================================
  // HTTP server
  // ========================================================================

  const server = http.createServer(async (req, res) => {
    if (!req.url) {
      res.statusCode = 400;
      res.end('Bad Request');
      return;
    }

    // CORS
    res.setHeader('Access-Control-Allow-Origin', '*');
    res.setHeader('Access-Control-Allow-Methods', 'GET,POST,OPTIONS');
    res.setHeader('Access-Control-Allow-Headers', 'Content-Type');

    if (req.method === 'OPTIONS') {
      res.statusCode = 204;
      res.end();
      return;
    }

    const url = new URL(req.url, `http://${req.headers.host}`);
    const pathParts = url.pathname.split('/').filter(Boolean);

    const sendJson = (code: number, payload: unknown) => {
      res.statusCode = code;
      res.setHeader('Content-Type', 'application/json');
      res.end(JSON.stringify(payload));
    };

    const sendText = (code: number, payload: string) => {
      res.statusCode = code;
      res.setHeader('Content-Type', 'text/plain');
      res.end(payload);
    };

    const readBody = async () => {
      return await new Promise<string>((resolve) => {
        let body = '';
        req.on('data', (chunk) => {
          body += chunk.toString();
        });
        req.on('end', () => resolve(body));
      });
    };

    // Health
    if (req.method === 'GET' && url.pathname === '/health') {
      sendJson(200, {
        status: 'ok',
        version: '0.1.0',
        runs: state.runs.size,
      });
      return;
    }

    // SSE events
    if (req.method === 'GET' && url.pathname === '/events') {
      res.writeHead(200, {
        'Content-Type': 'text/event-stream',
        'Cache-Control': 'no-cache',
        Connection: 'keep-alive',
        'Access-Control-Allow-Origin': '*',
      });
      res.write('\n');
      sseClients.add(res);
      req.on('close', () => {
        sseClients.delete(res);
      });
      return;
    }

    // Runs
    if (req.method === 'GET' && url.pathname === '/runs') {
      sendJson(200, Array.from(state.runs.values()));
      return;
    }

    if (req.method === 'POST' && url.pathname === '/runs') {
      const body = await readBody();
      const payload = JSON.parse(body) as RunnerStartPayload;
      try {
        const run = await startRun(payload);
        sendJson(200, run);
      } catch (err) {
        sendText(500, err instanceof Error ? err.message : 'Failed to start run');
      }
      return;
    }

    if (pathParts[0] === 'runs' && pathParts[1]) {
      const runId = pathParts[1];

      if (req.method === 'GET' && pathParts.length === 2) {
        const run = state.runs.get(runId);
        if (!run) {
          sendJson(404, { error: 'Run not found' });
          return;
        }
        sendJson(200, run);
        return;
      }

      if (req.method === 'POST' && pathParts[2] === 'stop') {
        const run = state.runs.get(runId);
        if (!run) {
          sendJson(404, { error: 'Run not found' });
          return;
        }
        const proc = state.processes.get(runId);
        if (proc) {
          proc.kill('SIGINT');
          run.status = 'paused';
          run.lastUpdatedAt = new Date().toISOString();
          await persistRuns();
          broadcast('run:status-changed', run);
          if (run.convexRunId) {
            await convexSync.updateRunStatus(run.convexRunId, 'paused', run.currentStep, run.checkpointPath);
            convexSync.stopSync(runId);
          }
        }
        sendJson(200, { ok: true });
        return;
      }

      if (req.method === 'POST' && pathParts[2] === 'resume') {
        const body = await readBody();
        const data = JSON.parse(body) as { checkpointPath: string; oracleIdx?: number };
        try {
          const run = await resumeRun(runId, data.checkpointPath, data.oracleIdx);
          sendJson(200, run);
        } catch (err) {
          sendText(500, err instanceof Error ? err.message : 'Failed to resume run');
        }
        return;
      }

      if (req.method === 'GET' && pathParts[2] === 'checkpoints') {
        const run = state.runs.get(runId);
        if (!run) {
          sendJson(404, { error: 'Run not found' });
          return;
        }
        try {
          const files = await fs.readdir(run.resultDir);
          const checkpoints = files
            .filter((f) => f.startsWith('model_state_') && f.endsWith('.pt'))
            .map((f) => path.join(run.resultDir, f))
            .sort();
          sendJson(200, checkpoints);
        } catch {
          sendJson(200, []);
        }
        return;
      }

      if (req.method === 'GET' && pathParts[2] === 'output') {
        const run = state.runs.get(runId);
        if (!run) {
          sendJson(404, { error: 'Run not found' });
          return;
        }
        const tail = Number(url.searchParams.get('tail') ?? '500');
        const lines = run.logPath ? await readTail(run.logPath, tail) : [];
        sendJson(200, { lines });
        return;
      }

      if (req.method === 'GET' && pathParts[2] === 'molecules') {
        const limit = Number(url.searchParams.get('limit') ?? '50');
        const molecules = await getTopMolecules(runId, limit);
        sendJson(200, molecules);
        return;
      }

      if (req.method === 'GET' && pathParts[2] === 'complex') {
        const oracleIdx = Number(url.searchParams.get('oracleIdx'));
        const molIdx = Number(url.searchParams.get('molIdx'));
        if (Number.isNaN(oracleIdx) || Number.isNaN(molIdx)) {
          sendJson(400, { error: 'Missing oracleIdx or molIdx' });
          return;
        }
        const content = await getComplexContent(runId, oracleIdx, molIdx);
        if (!content) {
          sendJson(404, { error: 'Complex not found' });
          return;
        }
        sendText(200, content);
        return;
      }
    }

    sendJson(404, { error: 'Not found' });
  });

  server.listen(port, '127.0.0.1', () => {
    console.log(`CGFlow runner listening on http://127.0.0.1:${port}`);
  });
}

// CLI mode
const entry = fileURLToPath(import.meta.url);
if (process.argv[1] && path.resolve(process.argv[1]) === path.resolve(entry)) {
  void startRunnerServer().catch((err) => {
    console.error('Failed to start runner:', err);
    process.exit(1);
  });
}
