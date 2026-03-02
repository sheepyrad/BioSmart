import { ConvexHttpClient } from 'convex/browser';
import initSqlJs, { Database as SqlJsDatabase } from 'sql.js';
import path from 'path';
import fs from 'fs/promises';
import type {
  BoltzScore,
  RewardCacheEntry,
} from '../shared/types';
import { api } from '../convex/_generated/api';

// Initialize SQL.js
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

/**
 * Service to sync local SQLite data to Convex for cross-machine access.
 * 
 * This runs in the Electron main process and periodically uploads
 * new molecules, scores, and run metadata to Convex.
 */
export class ConvexSyncService {
  private client: ConvexHttpClient | null = null;
  private syncIntervals = new Map<string, NodeJS.Timeout>();
  private lastSyncTimestamp = new Map<string, number>();

  constructor(convexUrl?: string) {
    if (convexUrl) {
      this.client = new ConvexHttpClient(convexUrl);
    }
  }

  /**
   * Start periodic sync for a run
   */
  startSync(runId: string, convexRunId: string, resultDir: string, intervalMs = 30000) {
    if (!this.client) {
      console.warn('Convex not configured, sync disabled');
      return;
    }

    // Stop any existing sync for this run
    this.stopSync(runId);

    // Initial sync
    this.syncRun(runId, convexRunId, resultDir);

    // Set up periodic sync
    const interval = setInterval(() => {
      this.syncRun(runId, convexRunId, resultDir);
    }, intervalMs);
    this.syncIntervals.set(runId, interval);
  }

  /**
   * Stop sync for a run
   */
  stopSync(runId: string) {
    const interval = this.syncIntervals.get(runId);
    if (interval) {
      clearInterval(interval);
      this.syncIntervals.delete(runId);
    }
  }

  /**
   * Sync a single run's data to Convex
   */
  async syncRun(runId: string, convexRunId: string, resultDir: string) {
    if (!this.client) return;

    try {
      // Sync molecules from reward cache
      await this.syncMolecules(convexRunId, resultDir);

      // Sync run status
      await this.syncRunStatus(convexRunId, resultDir);

      this.lastSyncTimestamp.set(runId, Date.now());
    } catch (err) {
      console.error(`Failed to sync run ${runId}:`, err);
    }
  }

  /**
   * Create a run record in Convex and return its id.
   */
  async createRun(configId: string, name: string, resultDir: string, totalSteps: number): Promise<string | null> {
    if (!this.client) return null;
    try {
      const runId = await this.client.mutation(api.runs.create, {
        configId: configId as any,
        name,
        resultDir,
        totalSteps,
      });
      // Mark as running immediately
      await this.client.mutation(api.runs.updateStatus, {
        id: runId as any,
        status: 'running',
      });
      return runId as any;
    } catch (err) {
      console.error('Failed to create Convex run:', err);
      return null;
    }
  }

  /**
   * Update run status in Convex
   */
  async updateRunStatus(
    convexRunId: string,
    status: 'idle' | 'running' | 'paused' | 'completed' | 'error',
    currentStep?: number,
    checkpointPath?: string | null,
    error?: string | null
  ): Promise<void> {
    if (!this.client) return;
    try {
      await this.client.mutation(api.runs.updateStatus, {
        id: convexRunId as any,
        status,
        currentStep,
        checkpointPath: checkpointPath ?? undefined,
        error: error ?? undefined,
      });
    } catch (err) {
      console.error('Failed to update Convex run status:', err);
    }
  }

  /**
   * Sync molecules from local SQLite to Convex
   */
  private async syncMolecules(convexRunId: string, resultDir: string, limit = 1000) {
    if (!this.client) return;

    const rewardCachePath = path.join(resultDir, 'boltz_reward_cache.db');
    const trainDir = path.join(resultDir, 'train');

    // Check if reward cache exists
    try {
      await fs.access(rewardCachePath);
    } catch {
      return; // No data yet
    }

    // Read reward cache
    const rewardDb = await openDatabase(rewardCachePath);
    const entries = queryAll<RewardCacheEntry>(
      rewardDb,
      `SELECT smiles, reward, info FROM entries ORDER BY reward DESC LIMIT ?`,
      [limit]
    );
    rewardDb.close();

    if (entries.length === 0) return;

    // Get trajectory info (scan all generated_objs_*.db)
    const trajMap = await loadTrajectoryMap(
      trainDir,
      entries.map((e) => e.smiles)
    );

    // Get boltz scores
    let boltzMap = new Map<string, BoltzScore>();
    const boltzDbPath = path.join(trainDir, 'boltz_scores_0.db');
    
    try {
      const boltzDb = await openDatabase(boltzDbPath);
      const placeholders = entries.map(() => '?').join(',');
      const boltzRows = queryAll<BoltzScore>(
        boltzDb,
        `SELECT * FROM results WHERE smiles IN (${placeholders})`,
        entries.map((e) => e.smiles)
      );
      boltzDb.close();
      boltzMap = new Map(boltzRows.map((r) => [r.smiles, r]));
    } catch {
      // DB may not exist yet
    }

    // Extract oracle and molecule indices from reward cache info
    const indexMap = new Map<string, { oracleIdx: number | null; molIdx: number | null }>();
    for (const entry of entries) {
      if (!entry.info) continue;
      try {
        const parsed = JSON.parse(entry.info) as { oracle_idx?: number; mol_idx?: number };
        indexMap.set(entry.smiles, {
          oracleIdx: typeof parsed.oracle_idx === 'number' ? parsed.oracle_idx : null,
          molIdx: typeof parsed.mol_idx === 'number' ? parsed.mol_idx : null,
        });
      } catch {
        // Ignore malformed JSON
      }
    }

    // Prepare molecules for batch upsert
    const molecules = entries.map((entry) => {
      const boltz = boltzMap.get(entry.smiles);
      const idx = indexMap.get(entry.smiles);
      return {
        runId: convexRunId as any, // Type assertion needed for Convex ID
        smiles: entry.smiles,
        reward: entry.reward,
        trajectory: trajMap.get(entry.smiles) || '[]',
        affinityEnsemble: boltz?.affinity_ensemble ?? null,
        probabilityEnsemble: boltz?.probability_ensemble ?? null,
        affinityModel1: boltz?.affinity_model1 ?? null,
        probabilityModel1: boltz?.probability_model1 ?? null,
        affinityModel2: boltz?.affinity_model2 ?? null,
        probabilityModel2: boltz?.probability_model2 ?? null,
        oracleIdx: idx?.oracleIdx ?? null,
        molIdx: idx?.molIdx ?? null,
        complexFileId: null,
        iteration: boltz?.iteration ?? 0,
      };
    });

    if (molecules.length === 0) return;

    // Batch upsert to Convex
    await this.client.mutation(api.molecules.batchUpsert, { molecules: molecules as any });
  }

  /**
   * Sync run status from train.log
   */
  private async syncRunStatus(convexRunId: string, resultDir: string) {
    if (!this.client) return;

    const logPath = path.join(resultDir, 'train.log');
    
    try {
      const content = await fs.readFile(logPath, 'utf-8');
      const lines = content.split('\n');
      
      // Find last iteration
      let lastIteration = 0;
      for (const line of lines.reverse()) {
        const match = line.match(/iteration\s+(\d+)/i);
        if (match?.[1]) {
          lastIteration = parseInt(match[1], 10);
          break;
        }
      }

      // Update run status in Convex
      await this.client.mutation(api.runs.updateStatus, {
        id: convexRunId as any,
        status: 'running',
        currentStep: lastIteration,
      });
    } catch {
      // Log file may not exist yet
    }
  }

  /**
   * Upload a file to Convex storage
   */
  async uploadFile(
    filePath: string,
    fileType: 'pdb' | 'yaml' | 'msa' | 'db' | 'other',
    runId?: string
  ): Promise<string | null> {
    if (!this.client) return null;

    try {
      const content = await fs.readFile(filePath);
      const fileName = path.basename(filePath);

      // Get upload URL
      const uploadUrl = await this.client.mutation(api.files.generateUploadUrl, {});

      // Upload file
      const response = await fetch(uploadUrl, {
        method: 'POST',
        headers: { 'Content-Type': 'application/octet-stream' },
        body: content,
      });
      const { storageId } = await response.json();

      // Create file record
      const fileId = await this.client.mutation(api.files.create, {
        name: fileName,
        type: fileType,
        fieldType: 'other',
        storageId,
        size: content.length,
        runId: runId || null,
      });

      return fileId as any;
    } catch (err) {
      console.error('Failed to upload file:', err);
      return null;
    }
  }
}

// Singleton instance
let syncService: ConvexSyncService | null = null;

export function getConvexSyncService(convexUrl?: string): ConvexSyncService {
  if (!syncService) {
    syncService = new ConvexSyncService(convexUrl);
  }
  return syncService;
}
