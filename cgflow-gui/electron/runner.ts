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
  BoltzMetricInputRow,
  BoltzMetricSeries,
  OptConfig,
  RunInfo,
  MoleculeResult,
  RewardCacheEntry,
  BoltzScore,
  TrajectoryStep,
} from '../shared/types';
import { computeBoltzMetrics } from '../shared/boltzMetrics';
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
const RESULT_DIR_INITIAL_DETECTION_ATTEMPTS = 30;
const RESULT_DIR_INITIAL_DETECTION_INTERVAL_MS = 1000;
const RESULT_DIR_REFRESH_INTERVAL_MS = 10000;

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

function shellQuote(value: string): string {
  return `'${value.replace(/'/g, `'\\''`)}'`;
}

function formatCondaCommand(args: string[]): string {
  const full = ['conda', 'run', '--no-capture-output', '-n', CONDA_ENV_NAME, 'python', ...args];
  return full.map(shellQuote).join(' ');
}

function summarizeFailureFromOutput(
  outputLines: string[],
  maxLines = 20
): string[] {
  if (outputLines.length === 0) return [];
  const stderrLines = outputLines.filter((line) => line.includes('[stderr]'));
  let tracebackStart = -1;
  for (let i = outputLines.length - 1; i >= 0; i -= 1) {
    if (/Traceback \(most recent call last\):/i.test(outputLines[i] ?? '')) {
      tracebackStart = i;
      break;
    }
  }

  if (tracebackStart >= 0) {
    return outputLines.slice(tracebackStart).slice(-maxLines);
  }
  if (stderrLines.length > 0) {
    return stderrLines.slice(-maxLines);
  }
  return outputLines.slice(-maxLines);
}

function buildFailureMessage(params: {
  code: number | null;
  signal: NodeJS.Signals | null;
  outputLines: string[];
  logPath: string | null | undefined;
  command: string;
}): string {
  const parts: string[] = [];
  const statusCore =
    params.code !== null
      ? `exit code ${params.code}`
      : `signal ${params.signal ?? 'unknown'}`;
  parts.push(`Training process failed (${statusCore}).`);
  if (params.logPath) {
    parts.push(`Log: ${params.logPath}`);
  }
  parts.push(`Command: ${params.command}`);

  const snippet = summarizeFailureFromOutput(params.outputLines);
  if (snippet.length > 0) {
    parts.push('Recent output:');
    parts.push(...snippet);
  }
  return parts.join('\n');
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

async function pathExists(targetPath: string): Promise<boolean> {
  try {
    await fs.access(targetPath);
    return true;
  } catch {
    return false;
  }
}

async function listSubdirectories(parentDir: string): Promise<string[]> {
  try {
    const entries = await fs.readdir(parentDir, { withFileTypes: true });
    return entries.filter((entry) => entry.isDirectory()).map((entry) => entry.name);
  } catch {
    return [];
  }
}

async function findFirstMatchingFile(
  rootDir: string,
  predicate: (name: string) => boolean,
  maxDepth = 5
): Promise<string | null> {
  const queue: Array<{ dir: string; depth: number }> = [{ dir: rootDir, depth: 0 }];

  while (queue.length > 0) {
    const item = queue.shift();
    if (!item) break;
    let entries: any[];
    try {
      entries = await fs.readdir(item.dir, { withFileTypes: true });
    } catch {
      continue;
    }

    for (const entry of entries) {
      const fullPath = path.join(item.dir, entry.name);
      if (entry.isFile() && predicate(entry.name)) {
        return fullPath;
      }
      if (entry.isDirectory() && item.depth < maxDepth) {
        queue.push({ dir: fullPath, depth: item.depth + 1 });
      }
    }
  }

  return null;
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

interface ArtifactMolecule {
  smiles: string;
  reward: number;
  oracleIdx: number;
  molIdx: number;
  boltzScores: BoltzScore | null;
}

function normalizeReward(affinity: number | null, probability: number | null): number {
  if (affinity == null || probability == null) return 0;
  if (!Number.isFinite(affinity) || !Number.isFinite(probability)) return 0;
  return ((-affinity + 2.0) / 4.0) * probability;
}

function toFiniteOrNull(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null;
}

async function getBoltzMetricRowsFromRunDir(resultDir: string): Promise<BoltzMetricInputRow[]> {
  const trainDir = path.join(resultDir, 'train');
  let boltzFiles: string[] = [];
  try {
    const entries = await fs.readdir(trainDir);
    boltzFiles = entries
      .filter((name) => name.startsWith('boltz_scores_') && name.endsWith('.db'))
      .sort();
  } catch {
    boltzFiles = [];
  }

  const metricRows: BoltzMetricInputRow[] = [];
  for (const boltzFile of boltzFiles) {
    const boltzDbPath = path.join(trainDir, boltzFile);
    try {
      const boltzDb = await openDatabase(boltzDbPath);
      const rows = queryAll<{
        iteration: number;
        smiles: string;
        affinity_model1: number | null;
        probability_model1: number | null;
      }>(
        boltzDb,
        `SELECT iteration, smiles, affinity_model1, probability_model1
         FROM results
         ORDER BY iteration ASC, rowid ASC`
      );
      boltzDb.close();
      metricRows.push(
        ...rows.map((row) => ({
          iteration: Number(row.iteration ?? 0),
          smiles: row.smiles,
          affinityModel1: row.affinity_model1 ?? null,
          probabilityModel1: row.probability_model1 ?? null,
        }))
      );
    } catch {
      // Continue scanning other shards while files are being written.
    }
  }

  if (metricRows.length > 0) {
    metricRows.sort((a, b) => a.iteration - b.iteration || a.smiles.localeCompare(b.smiles));
    return metricRows;
  }

  const artifactRows = await loadMoleculesFromArtifacts(resultDir, Number.MAX_SAFE_INTEGER);
  return artifactRows
    .map((row) => ({
      iteration: row.boltzScores?.iteration ?? row.oracleIdx ?? 0,
      smiles: row.smiles,
      affinityModel1: row.boltzScores?.affinity_model1 ?? null,
      probabilityModel1: row.boltzScores?.probability_model1 ?? null,
    }))
    .sort((a, b) => a.iteration - b.iteration || a.smiles.localeCompare(b.smiles));
}

async function readRunProgressFromLog(resultDir: string): Promise<{ currentStep: number; totalSteps: number }> {
  const logPath = path.join(resultDir, 'train.log');
  try {
    const content = await fs.readFile(logPath, 'utf-8');
    const matches = content.matchAll(/iteration\s+(\d+)/gi);
    let maxIteration = 0;
    for (const match of matches) {
      const parsed = Number.parseInt(match[1] ?? '0', 10);
      if (parsed > maxIteration) maxIteration = parsed;
    }
    return { currentStep: maxIteration, totalSteps: maxIteration };
  } catch {
    return { currentStep: 0, totalSteps: 0 };
  }
}

async function getLatestCheckpoint(resultDir: string): Promise<string | null> {
  try {
    const files = await fs.readdir(resultDir);
    const checkpoints = files
      .filter((file) => file.startsWith('model_state_') && file.endsWith('.pt'))
      .sort();
    if (checkpoints.length === 0) return null;
    const latest = checkpoints[checkpoints.length - 1];
    return latest ? path.join(resultDir, latest) : null;
  } catch {
    return null;
  }
}

async function loadMoleculesFromArtifacts(resultDir: string, limit: number): Promise<MoleculeResult[]> {
  const boltzRoot = path.join(resultDir, 'boltz_cofold');
  const oracleDirs = await listSubdirectories(boltzRoot);
  if (oracleDirs.length === 0) return [];

  const parsedRows: ArtifactMolecule[] = [];

  for (const oracleDir of oracleDirs) {
    const oracleMatch = oracleDir.match(/^oracle(\d+)$/);
    if (!oracleMatch?.[1]) continue;
    const oracleIdx = Number.parseInt(oracleMatch[1], 10);
    if (!Number.isFinite(oracleIdx)) continue;

    const oraclePath = path.join(boltzRoot, oracleDir);
    const molDirs = await listSubdirectories(oraclePath);
    for (const molDir of molDirs) {
      const molMatch = molDir.match(/^mol_(\d+)$/);
      if (!molMatch?.[1]) continue;
      const molIdx = Number.parseInt(molMatch[1], 10);
      if (!Number.isFinite(molIdx)) continue;

      const molPath = path.join(oraclePath, molDir);
      const yamlPath = path.join(molPath, `mol_${molIdx}.yaml`);
      let smiles = '';
      if (await pathExists(yamlPath)) {
        try {
          const yamlContent = await fs.readFile(yamlPath, 'utf-8');
          const parsedYaml = YAML.parse(yamlContent) as any;
          const sequences = Array.isArray(parsedYaml?.sequences) ? parsedYaml.sequences : [];
          const ligandEntry = sequences.find(
            (entry: any) => entry && typeof entry === 'object' && entry.ligand?.smiles
          );
          smiles = ligandEntry?.ligand?.smiles ?? '';
        } catch {
          smiles = '';
        }
      }
      if (!smiles) continue;

      const predictionBase = path.join(
        molPath,
        'boltz_output',
        `boltz_results_mol_${molIdx}`,
        'predictions',
        `mol_${molIdx}`
      );
      const affinityPath = path.join(predictionBase, `affinity_mol_${molIdx}.json`);

      let affinityModel1: number | null = null;
      let probabilityModel1: number | null = null;
      let affinityEnsemble: number | null = null;
      let probabilityEnsemble: number | null = null;
      let affinityModel2: number | null = null;
      let probabilityModel2: number | null = null;
      if (await pathExists(affinityPath)) {
        try {
          const affinityRaw = await fs.readFile(affinityPath, 'utf-8');
          const affinity = JSON.parse(affinityRaw) as Record<string, unknown>;
          affinityEnsemble = toFiniteOrNull(affinity.affinity_pred_value);
          probabilityEnsemble = toFiniteOrNull(affinity.affinity_probability_binary);
          affinityModel1 = toFiniteOrNull(affinity.affinity_pred_value1) ?? affinityEnsemble;
          probabilityModel1 = toFiniteOrNull(affinity.affinity_probability_binary1) ?? probabilityEnsemble;
          affinityModel2 = toFiniteOrNull(affinity.affinity_pred_value2);
          probabilityModel2 = toFiniteOrNull(affinity.affinity_probability_binary2);
        } catch {
          // Keep nulls
        }
      }

      const reward = normalizeReward(affinityModel1, probabilityModel1);
      parsedRows.push({
        smiles,
        reward,
        oracleIdx,
        molIdx,
        boltzScores:
          affinityModel1 != null || probabilityModel1 != null
            ? {
                iteration: oracleIdx,
                smiles,
                docking_score: 0,
                affinity_ensemble: affinityEnsemble ?? 0,
                probability_ensemble: probabilityEnsemble ?? 0,
                affinity_model1: affinityModel1 ?? 0,
                probability_model1: probabilityModel1 ?? 0,
                affinity_model2: affinityModel2 ?? 0,
                probability_model2: probabilityModel2 ?? 0,
              }
            : null,
      });
    }
  }

  parsedRows.sort((a, b) => b.reward - a.reward);
  return parsedRows.slice(0, limit).map((row) => ({
    smiles: row.smiles,
    reward: row.reward,
    trajectory: [],
    boltzScores: row.boltzScores,
    complexPath: null,
    oracleIdx: row.oracleIdx,
    molIdx: row.molIdx,
  }));
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
  const artifactMapCache = new Map<string, Map<string, MoleculeResult>>();
  const resultDirRefreshTimers = new Map<string, NodeJS.Timeout>();
  const resultDirRefreshInFlight = new Set<string>();

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

  async function syncRunResultDir(
    runId: string,
    nextResultDir: string,
    sourceConfigPath?: string
  ): Promise<boolean> {
    const run = state.runs.get(runId);
    if (!run || !nextResultDir || run.resultDir === nextResultDir) {
      return false;
    }

    const oldResultDir = run.resultDir;
    run.resultDir = nextResultDir;
    run.lastUpdatedAt = new Date().toISOString();

    if (run.checkpointPath) {
      const checkpointName = path.basename(run.checkpointPath);
      if (checkpointName.startsWith('model_state_') && checkpointName.endsWith('.pt')) {
        run.checkpointPath = path.join(nextResultDir, checkpointName);
      }
    }

    artifactMapCache.delete(oldResultDir);
    artifactMapCache.delete(nextResultDir);
    if (sourceConfigPath) {
      await copyConfigToResultDir(sourceConfigPath, nextResultDir);
    }

    await persistRuns();
    broadcast('run:status-changed', run);
    if (run.convexRunId) {
      convexSync.stopSync(runId);
      convexSync.startSync(runId, run.convexRunId, nextResultDir, 30000);
    }
    return true;
  }

  async function maybeRefreshRunResultDir(
    runId: string,
    baseDir: string,
    startedAt: number,
    sourceConfigPath?: string
  ): Promise<boolean> {
    const run = state.runs.get(runId);
    if (!run || run.status !== 'running') {
      return false;
    }
    const detected = await detectResultDir(baseDir, startedAt);
    if (!detected) {
      return false;
    }
    return await syncRunResultDir(runId, detected, sourceConfigPath);
  }

  function stopResultDirRefresh(runId: string) {
    const timer = resultDirRefreshTimers.get(runId);
    if (timer) {
      clearInterval(timer);
      resultDirRefreshTimers.delete(runId);
    }
    resultDirRefreshInFlight.delete(runId);
  }

  function startResultDirRefresh(
    runId: string,
    baseDir: string,
    startedAt: number,
    sourceConfigPath?: string
  ) {
    stopResultDirRefresh(runId);

    const tick = async () => {
      const run = state.runs.get(runId);
      if (!run || run.status !== 'running') {
        stopResultDirRefresh(runId);
        return;
      }
      if (resultDirRefreshInFlight.has(runId)) return;
      resultDirRefreshInFlight.add(runId);
      try {
        await maybeRefreshRunResultDir(runId, baseDir, startedAt, sourceConfigPath);
      } finally {
        resultDirRefreshInFlight.delete(runId);
      }
    };

    const timer = setInterval(() => {
      void tick();
    }, RESULT_DIR_REFRESH_INTERVAL_MS);
    resultDirRefreshTimers.set(runId, timer);
    void tick();
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
    const commandString = formatCondaCommand(args);

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

    await appendOutput(`[runner] Launching command: ${commandString}`);

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

    proc.on('close', async (code, signal) => {
      stopResultDirRefresh(runId);
      runInfo.status = code === 0 ? 'completed' : 'error';
      runInfo.error =
        code === 0
          ? null
          : buildFailureMessage({
              code,
              signal,
              outputLines: state.outputs.get(runId) ?? [],
              logPath: runInfo.logPath,
              command: commandString,
            });
      runInfo.lastUpdatedAt = new Date().toISOString();
      state.processes.delete(runId);
      await persistRuns();
      if (code !== 0) {
        broadcast('run:error', { runId, error: runInfo.error ?? `Process exited with code ${code}` });
      }
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
      stopResultDirRefresh(runId);
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

    // Try to detect actual result directory and keep revalidating while running.
    for (let attempt = 0; attempt < RESULT_DIR_INITIAL_DETECTION_ATTEMPTS; attempt++) {
      const refreshed = await maybeRefreshRunResultDir(
        runId,
        config.result_dir,
        runStartedAt,
        resolvedConfigPath
      );
      if (refreshed) {
        break;
      }
      await new Promise((resolve) => setTimeout(resolve, RESULT_DIR_INITIAL_DETECTION_INTERVAL_MS));
    }
    startResultDirRefresh(runId, config.result_dir, runStartedAt, resolvedConfigPath);

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
    const commandString = formatCondaCommand(args);

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

    await appendOutput(`[runner] Launching command: ${commandString}`);

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

    proc.on('close', async (code, signal) => {
      stopResultDirRefresh(runId);
      run.status = code === 0 ? 'completed' : 'error';
      run.error =
        code === 0
          ? null
          : buildFailureMessage({
              code,
              signal,
              outputLines: state.outputs.get(runId) ?? [],
              logPath: run.logPath,
              command: commandString,
            });
      run.lastUpdatedAt = new Date().toISOString();
      state.processes.delete(runId);
      await persistRuns();
      if (code !== 0) {
        broadcast('run:error', { runId, error: run.error ?? `Process exited with code ${code}` });
      }
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
      stopResultDirRefresh(runId);
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

  async function importExistingRun(resultDir: string, name?: string | null): Promise<RunRecord> {
    const stats = await fs.stat(resultDir).catch(() => null);
    if (!stats?.isDirectory()) {
      throw new Error(`Result directory does not exist: ${resultDir}`);
    }

    const runId = generateRunId();
    const progress = await readRunProgressFromLog(resultDir);
    const checkpointPath = await getLatestCheckpoint(resultDir);
    const startedAt = new Date(stats.mtimeMs).toISOString();
    const configPathCandidate = path.join(resultDir, 'config.yaml');

    const run: RunRecord = {
      id: runId,
      name: name?.trim() || `Imported ${path.basename(resultDir)}`,
      configPath: (await pathExists(configPathCandidate)) ? configPathCandidate : resultDir,
      resultDir,
      status: 'completed',
      currentStep: progress.currentStep,
      totalSteps: progress.totalSteps,
      startedAt,
      lastUpdatedAt: new Date().toISOString(),
      checkpointPath,
      error: null,
      pid: null,
      source: 'local',
      logPath: path.join(resultDir, 'train.log'),
    };

    state.runs.set(run.id, run);
    await persistRuns();
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

      if (topEntries.length === 0) {
        return await loadMoleculesFromArtifacts(run.resultDir, limit);
      }

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
      return await loadMoleculesFromArtifacts(run.resultDir, limit);
    }

    if (results.length === 0) {
      return await loadMoleculesFromArtifacts(run.resultDir, limit);
    }

    const needsArtifactLookup = results.some(
      (row) => row.oracleIdx == null || row.molIdx == null || row.boltzScores == null
    );
    if (needsArtifactLookup) {
      const shouldUseArtifactCache = run.status !== 'running';
      let artifactMap = shouldUseArtifactCache ? artifactMapCache.get(run.resultDir) : undefined;
      if (!artifactMap) {
        const artifactRows = await loadMoleculesFromArtifacts(run.resultDir, Number.MAX_SAFE_INTEGER);
        artifactMap = new Map(artifactRows.map((row) => [row.smiles, row]));
        if (shouldUseArtifactCache) {
          artifactMapCache.set(run.resultDir, artifactMap);
        }
      }

      for (const row of results) {
        const artifact = artifactMap.get(row.smiles);
        if (!artifact) continue;
        if (row.oracleIdx == null && artifact.oracleIdx != null) {
          row.oracleIdx = artifact.oracleIdx;
        }
        if (row.molIdx == null && artifact.molIdx != null) {
          row.molIdx = artifact.molIdx;
        }
        if (row.boltzScores == null && artifact.boltzScores) {
          row.boltzScores = artifact.boltzScores;
          if (!Number.isFinite(row.reward) || row.reward === 0) {
            row.reward = artifact.reward;
          }
        }
      }
    }
    return results;
  }

  async function getBoltzMetrics(runId: string): Promise<BoltzMetricSeries | null> {
    const run = state.runs.get(runId);
    if (!run) return null;

    const rows = await getBoltzMetricRowsFromRunDir(run.resultDir);
    if (rows.length === 0) return null;
    return computeBoltzMetrics(rows);
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
      const structurePath = await findFirstMatchingFile(
        basePath,
        (name) => name.endsWith('.cif') || name.endsWith('.pdb'),
        6
      );
      if (structurePath) {
        return await fs.readFile(structurePath, 'utf-8');
      }
    } catch {
      return null;
    }
    return null;
  }

  async function deleteRun(runId: string): Promise<void> {
    const run = state.runs.get(runId);
    if (!run) {
      throw new Error('Run not found');
    }
    if (run.status === 'running' && state.processes.has(runId)) {
      throw new Error('Cannot delete an active run. Stop it first.');
    }

    state.runs.delete(runId);
    state.outputs.delete(runId);
    stopResultDirRefresh(runId);
    artifactMapCache.delete(run.resultDir);
    if (run.convexRunId) {
      convexSync.stopSync(runId);
    }

    await fs.rm(path.join(runsDir, runId), { recursive: true, force: true }).catch(() => undefined);
    await persistRuns();
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
    res.setHeader('Access-Control-Allow-Methods', 'GET,POST,DELETE,OPTIONS');
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

    if (req.method === 'POST' && url.pathname === '/runs/import') {
      const body = await readBody();
      const payload = JSON.parse(body) as { resultDir: string; name?: string | null };
      try {
        const run = await importExistingRun(payload.resultDir, payload.name);
        sendJson(200, run);
      } catch (err) {
        sendText(500, err instanceof Error ? err.message : 'Failed to import run');
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

      if (req.method === 'DELETE' && pathParts.length === 2) {
        try {
          await deleteRun(runId);
          sendJson(200, { ok: true });
        } catch (err) {
          sendText(400, err instanceof Error ? err.message : 'Failed to delete run');
        }
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
          stopResultDirRefresh(runId);
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

      if (req.method === 'GET' && pathParts[2] === 'boltz-metrics') {
        const metrics = await getBoltzMetrics(runId);
        if (!metrics) {
          sendJson(404, { error: 'Boltz metrics not found' });
          return;
        }
        sendJson(200, metrics);
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
