import { ConvexHttpClient } from 'convex/browser';
import initSqlJs, { Database as SqlJsDatabase } from 'sql.js';
import path from 'path';
import fs from 'fs/promises';
import type {
  BoltzScore,
  RewardCacheEntry,
} from '../shared/types';

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

/**
 * Service to sync local SQLite data to Convex for cross-machine access.
 * 
 * This runs in the Electron main process and periodically uploads
 * new molecules, scores, and run metadata to Convex.
 */
export class ConvexSyncService {
  private client: ConvexHttpClient | null = null;
  private syncInterval: NodeJS.Timeout | null = null;
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
    this.syncInterval = setInterval(() => {
      this.syncRun(runId, convexRunId, resultDir);
    }, intervalMs);
  }

  /**
   * Stop sync for a run
   */
  stopSync(runId: string) {
    if (this.syncInterval) {
      clearInterval(this.syncInterval);
      this.syncInterval = null;
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
   * Sync molecules from local SQLite to Convex
   */
  private async syncMolecules(convexRunId: string, resultDir: string) {
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
      `SELECT smiles, reward, info FROM entries ORDER BY reward DESC LIMIT 100`,
      []
    );
    rewardDb.close();

    if (entries.length === 0) return;

    // Get trajectory info
    let trajMap = new Map<string, string>();
    const generatedDbPath = path.join(trainDir, 'generated_objs_0.db');
    
    try {
      const genDb = await openDatabase(generatedDbPath);
      const placeholders = entries.map(() => '?').join(',');
      const trajRows = queryAll<{ smi: string; traj: string }>(
        genDb,
        `SELECT smi, traj FROM results WHERE smi IN (${placeholders})`,
        entries.map((e) => e.smiles)
      );
      genDb.close();
      trajMap = new Map(trajRows.map((r) => [r.smi, r.traj]));
    } catch {
      // DB may not exist yet
    }

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

    // Prepare molecules for batch upsert
    const molecules = entries.map((entry) => {
      const boltz = boltzMap.get(entry.smiles);
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
        complexFileId: null,
        iteration: boltz?.iteration ?? 0,
      };
    });

    // Batch upsert to Convex
    // Note: In production, you'd import the api from convex/_generated/api
    // await this.client.mutation('molecules:batchUpsert', { molecules });
    console.log(`Would sync ${molecules.length} molecules to Convex`);
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
      // await this.client.mutation('runs:updateStatus', {
      //   id: convexRunId,
      //   currentStep: lastIteration,
      // });
      console.log(`Would update run step to ${lastIteration}`);
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
      // const uploadUrl = await this.client.mutation('files:generateUploadUrl', {});

      // Upload file
      // const response = await fetch(uploadUrl, {
      //   method: 'POST',
      //   headers: { 'Content-Type': 'application/octet-stream' },
      //   body: content,
      // });
      // const { storageId } = await response.json();

      // Create file record
      // const fileId = await this.client.mutation('files:create', {
      //   name: fileName,
      //   type: fileType,
      //   storageId,
      //   size: content.length,
      //   runId: runId || null,
      // });

      // return fileId;
      console.log(`Would upload file ${fileName} to Convex`);
      return null;
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
