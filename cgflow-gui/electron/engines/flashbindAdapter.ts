import path from 'path';
import fs from 'fs/promises';
import type { BoltzMetricInputRow, BoltzScore, MoleculeResult, TrajectoryStep } from '../../shared/types';

type OpenDatabase = (dbPath: string) => Promise<any>;
type QueryAll = <T>(db: any, sql: string, params?: any[]) => T[];
type PathExists = (targetPath: string) => Promise<boolean>;

type RewardCacheEntry = {
  smiles: string;
  reward: number;
  info: string | null;
};

export interface FlashbindAdapterDeps {
  openDatabase: OpenDatabase;
  queryAll: QueryAll;
  pathExists: PathExists;
}

function toFiniteOrNull(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null;
}

function normalizeReward(affinity: number | null, probability: number | null): number {
  if (affinity == null || probability == null) return 0;
  if (!Number.isFinite(affinity) || !Number.isFinite(probability)) return 0;
  return ((-affinity + 2.0) / 4.0) * probability;
}

function toBoltzScoreLike(params: {
  smiles: string;
  iteration: number;
  affinity: number | null;
  probability: number | null;
  affinity2?: number | null;
  probability2?: number | null;
}): BoltzScore | null {
  const affinity = params.affinity ?? 0;
  const probability = params.probability ?? 0;
  const affinity2 = params.affinity2 ?? 0;
  const probability2 = params.probability2 ?? 0;
  const hasAnyScore =
    params.affinity != null ||
    params.probability != null ||
    params.affinity2 != null ||
    params.probability2 != null;
  if (!hasAnyScore) return null;

  return {
    iteration: params.iteration,
    smiles: params.smiles,
    docking_score: 0,
    affinity_ensemble: affinity,
    probability_ensemble: probability,
    affinity_model1: affinity,
    probability_model1: probability,
    affinity_model2: affinity2,
    probability_model2: probability2,
  };
}

export async function getFlashbindMetricRowsFromRunDir(
  resultDir: string,
  deps: FlashbindAdapterDeps
): Promise<BoltzMetricInputRow[]> {
  const trainDir = path.join(resultDir, 'train');
  let files: string[] = [];
  try {
    files = await fs.readdir(trainDir);
  } catch {
    files = [];
  }
  const dbFiles = files
    .filter((name) => name.startsWith('flashbind_scores_') && name.endsWith('.db'))
    .sort();

  const rows: BoltzMetricInputRow[] = [];
  for (const dbFile of dbFiles) {
    const dbPath = path.join(trainDir, dbFile);
    try {
      let db: any = null;
      try {
        db = await deps.openDatabase(dbPath);
        const dbRows = deps.queryAll<{
          iteration: number;
          smiles: string;
          affinity_model1: number | null;
          probability_model1: number | null;
        }>(
          db,
          `SELECT iteration, smiles, affinity_model1, probability_model1
           FROM results
           ORDER BY iteration ASC, rowid ASC`
        );
        rows.push(
          ...dbRows.map((row) => ({
            iteration: Number(row.iteration ?? 0),
            smiles: row.smiles,
            affinityModel1: row.affinity_model1 ?? null,
            probabilityModel1: row.probability_model1 ?? null,
          }))
        );
      } finally {
        if (db && typeof db.close === 'function') {
          db.close();
        }
      }
    } catch {
      // Keep scanning while files are still being written.
    }
  }

  rows.sort((a, b) => a.iteration - b.iteration || a.smiles.localeCompare(b.smiles));
  return rows;
}

export async function getFlashbindTopMolecules(
  resultDir: string,
  limit: number,
  deps: FlashbindAdapterDeps
): Promise<MoleculeResult[]> {
  const rewardCachePath = path.join(resultDir, 'flashbind_reward_cache.db');
  const trainDir = path.join(resultDir, 'train');

  let entries: RewardCacheEntry[] = [];
  if (await deps.pathExists(rewardCachePath)) {
    try {
      const rewardDb = await deps.openDatabase(rewardCachePath);
      entries = deps.queryAll<RewardCacheEntry>(
        rewardDb,
        `SELECT smiles, reward, info FROM entries ORDER BY reward DESC LIMIT ?`,
        [limit]
      );
      if (typeof rewardDb.close === 'function') {
        rewardDb.close();
      }
    } catch {
      entries = [];
    }
  }

  const flashbindScoreMap = new Map<string, BoltzScore>();
  try {
    const files = await fs.readdir(trainDir);
    const scoreDbs = files
      .filter((name) => name.startsWith('flashbind_scores_') && name.endsWith('.db'))
      .sort();
    for (const scoreDb of scoreDbs) {
      const scoreDbPath = path.join(trainDir, scoreDb);
      let db: any = null;
      try {
        db = await deps.openDatabase(scoreDbPath);
        const rows = deps.queryAll<{
          iteration: number;
          smiles: string;
          affinity_model1: number | null;
          probability_model1: number | null;
          affinity_model2: number | null;
          probability_model2: number | null;
        }>(
          db,
          `SELECT iteration, smiles, affinity_model1, probability_model1, affinity_model2, probability_model2
           FROM results`
        );

        for (const row of rows) {
          const mapped = toBoltzScoreLike({
            smiles: row.smiles,
            iteration: Number(row.iteration ?? 0),
            affinity: row.affinity_model1,
            probability: row.probability_model1,
            affinity2: row.affinity_model2,
            probability2: row.probability_model2,
          });
          if (!mapped) continue;
          const existing = flashbindScoreMap.get(row.smiles);
          if (!existing || mapped.iteration >= existing.iteration) {
            flashbindScoreMap.set(row.smiles, mapped);
          }
        }
      } finally {
        if (db && typeof db.close === 'function') {
          db.close();
        }
      }
    }
  } catch {
    // Optional score DBs may not exist.
  }

  if (entries.length === 0 && flashbindScoreMap.size > 0) {
    const fallback = Array.from(flashbindScoreMap.values())
      .map((score, idx) => ({
        smiles: score.smiles,
        reward: normalizeReward(score.affinity_model1, score.probability_model1),
        trajectory: [] as TrajectoryStep[],
        boltzScores: score,
        normalizedScores: {
          affinity: score.affinity_model1,
          probability: score.probability_model1,
          score: normalizeReward(score.affinity_model1, score.probability_model1),
        },
        complexPath: null,
        engine: 'flashbind' as const,
        oracleIdx: score.iteration,
        molIdx: idx,
      }))
      .sort((a, b) => b.reward - a.reward);
    return fallback.slice(0, limit);
  }

  return entries.map((entry, idx) => {
    let parsedInfo: Record<string, unknown> = {};
    if (entry.info) {
      try {
        parsedInfo = JSON.parse(entry.info) as Record<string, unknown>;
      } catch {
        parsedInfo = {};
      }
    }

    const affinity = toFiniteOrNull(parsedInfo.flashbind_affinity);
    const binary = toFiniteOrNull(parsedInfo.flashbind_binary);
    const mappedReward = toFiniteOrNull(parsedInfo.flashbind_score) ?? normalizeReward(affinity, binary);
    const parsedIteration = toFiniteOrNull(parsedInfo.iteration);
    const iteration = parsedIteration == null ? idx : Math.max(0, Math.floor(parsedIteration));
    const scoreFromDb = flashbindScoreMap.get(entry.smiles);
    const boltzLikeScore =
      scoreFromDb ??
      toBoltzScoreLike({
        smiles: entry.smiles,
        iteration,
        affinity,
        probability: binary,
      });

    return {
      smiles: entry.smiles,
      reward: entry.reward ?? mappedReward,
      trajectory: [],
      boltzScores: boltzLikeScore,
      normalizedScores: {
        affinity: affinity ?? 0,
        probability: binary ?? 0,
        score: mappedReward ?? 0,
      },
      complexPath: null,
      engine: 'flashbind' as const,
      oracleIdx: iteration,
      molIdx: idx,
    } satisfies MoleculeResult;
  });
}

export async function getFlashbindComplexContent(
  resultDir: string,
  oracleIdx: number,
  molIdx: number
): Promise<string | null> {
  const candidateDirs = [
    path.join(resultDir, 'flashbind_oracle', `oracle${oracleIdx}`, 'fabind_output'),
    path.join(resultDir, 'flashbind_oracle', `oracle${oracleIdx}`),
  ];

  for (const candidateDir of candidateDirs) {
    try {
      const files = await fs.readdir(candidateDir);
      const structure = files.find(
        (name) =>
          name.includes(`mol_${molIdx}`) &&
          (name.endsWith('.sdf') || name.endsWith('.mol2') || name.endsWith('.pdb') || name.endsWith('.cif'))
      );
      if (!structure) continue;
      return await fs.readFile(path.join(candidateDir, structure), 'utf-8');
    } catch {
      // keep searching alternate locations
    }
  }

  return null;
}
