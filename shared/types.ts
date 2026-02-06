import { z } from 'zod';

// ============================================================================
// Config Schema (matches NS5_crop_boltz.yaml structure)
// ============================================================================

export const BoltzConfigSchema = z.object({
  base_yaml: z.string(),
  target_residues: z.array(z.string()),
  msa_path: z.string().nullable(),
  cache_dir: z.string().nullable(),
  use_msa_server: z.boolean(),
});

export const OptConfigSchema = z.object({
  result_dir: z.string(),
  env_dir: z.string(),
  max_atoms: z.number(),
  subsampling_ratio: z.number(),
  protein_path: z.string(),
  center: z.tuple([z.number(), z.number(), z.number()]).nullable(),
  ref_ligand_path: z.string().nullable(),
  size: z.tuple([z.number(), z.number(), z.number()]),
  num_steps: z.number(),
  num_sampling_per_step: z.number(),
  temperature: z.tuple([z.number(), z.number()]),
  seed: z.number(),
  pose_model: z.string(),
  pose_steps: z.number(),
  sampling_tau: z.number(),
  random_action_prob: z.number(),
  replay_warmup_step: z.number(),
  replay_capacity: z.number(),
  boltz: BoltzConfigSchema,
});

export type BoltzConfig = z.infer<typeof BoltzConfigSchema>;
export type OptConfig = z.infer<typeof OptConfigSchema>;

// ============================================================================
// Run Status and Management
// ============================================================================

export const RunStatusSchema = z.enum([
  'idle',
  'running',
  'paused',
  'completed',
  'error',
]);

export type RunStatus = z.infer<typeof RunStatusSchema>;

export const RunInfoSchema = z.object({
  id: z.string(),
  name: z.string(),
  configPath: z.string(),
  resultDir: z.string(),
  status: RunStatusSchema,
  currentStep: z.number(),
  totalSteps: z.number(),
  startedAt: z.string().nullable(),
  lastUpdatedAt: z.string().nullable(),
  checkpointPath: z.string().nullable(),
  error: z.string().nullable(),
  configId: z.string().nullable().optional(),
  convexRunId: z.string().nullable().optional(),
  source: z.enum(['local', 'convex']).optional(),
});

export type RunInfo = z.infer<typeof RunInfoSchema>;

// ============================================================================
// Database Schemas (from SQLite)
// ============================================================================

export const GeneratedObjectSchema = z.object({
  smi: z.string(),
  r: z.number(), // reward
  traj: z.string(), // JSON string of trajectory
});

export type GeneratedObject = z.infer<typeof GeneratedObjectSchema>;

export const BoltzScoreSchema = z.object({
  iteration: z.number(),
  smiles: z.string(),
  docking_score: z.number(),
  affinity_ensemble: z.number(),
  probability_ensemble: z.number(),
  affinity_model1: z.number(),
  probability_model1: z.number(),
  affinity_model2: z.number(),
  probability_model2: z.number(),
});

export type BoltzScore = z.infer<typeof BoltzScoreSchema>;

export const RewardCacheEntrySchema = z.object({
  smiles: z.string(),
  reward: z.number(),
  info: z.string().nullable(), // JSON with affinity scores
});

export type RewardCacheEntry = z.infer<typeof RewardCacheEntrySchema>;

// ============================================================================
// Trajectory / Reaction Pathway
// ============================================================================

export const TrajectoryStepSchema = z.object({
  step: z.number(),
  smiles: z.string(),
  action: z.tuple([z.string(), z.string(), z.string()]), // [rxn_name, block_id, fragment_smiles]
});

export type TrajectoryStep = z.infer<typeof TrajectoryStepSchema>;

// ============================================================================
// Molecule Result (for visualization)
// ============================================================================

export const MoleculeResultSchema = z.object({
  smiles: z.string(),
  reward: z.number(),
  trajectory: z.array(TrajectoryStepSchema),
  boltzScores: BoltzScoreSchema.nullable(),
  complexPath: z.string().nullable(), // Path to Boltz-2 predicted complex
  oracleIdx: z.number().nullable().optional(),
  molIdx: z.number().nullable().optional(),
});

export type MoleculeResult = z.infer<typeof MoleculeResultSchema>;

// ============================================================================
// IPC Channel Definitions
// ============================================================================

export interface IpcChannels {
  // File operations
  'file:select-pdb': () => Promise<string | null>;
  'file:select-yaml': () => Promise<string | null>;
  'file:select-directory': () => Promise<string | null>;
  'file:read-pdb': (path: string) => Promise<string>;
  'file:read-yaml': (path: string) => Promise<OptConfig>;
  'file:write-yaml': (path: string, config: OptConfig) => Promise<void>;
  'file:exists': (path: string) => Promise<boolean>;

  // Run management
  'run:start': (payload: {
    config: OptConfig;
    configPath?: string | null;
    configId?: string | null;
    name?: string | null;
  }) => Promise<RunInfo>;
  'run:stop': (runId: string) => Promise<void>;
  'run:resume': (runId: string, checkpointPath: string, oracleIdx?: number) => Promise<RunInfo>;
  'run:get-status': (runId: string) => Promise<RunInfo | null>;
  'run:list': () => Promise<RunInfo[]>;
  'run:get-checkpoints': (runId: string) => Promise<string[]>;

  // Database queries
  'db:get-generated-objects': (dbPath: string, limit?: number, offset?: number) => Promise<GeneratedObject[]>;
  'db:get-boltz-scores': (dbPath: string, limit?: number, offset?: number) => Promise<BoltzScore[]>;
  'db:get-reward-cache': (dbPath: string, limit?: number) => Promise<RewardCacheEntry[]>;
  'db:get-top-molecules': (runId: string, limit?: number) => Promise<MoleculeResult[]>;

  // Boltz complex files
  'boltz:get-complex': (runId: string, oracleIdx: number, molIdx: number) => Promise<string | null>;
}

// Type-safe IPC invoke helper type
export type IpcInvoke = <K extends keyof IpcChannels>(
  channel: K,
  ...args: Parameters<IpcChannels[K]>
) => ReturnType<IpcChannels[K]>;

// ============================================================================
// Events (main -> renderer)
// ============================================================================

export interface IpcEvents {
  'run:output': (runId: string, output: string) => void;
  'run:status-changed': (runInfo: RunInfo) => void;
  'run:checkpoint-saved': (runId: string, checkpointPath: string) => void;
  'run:error': (runId: string, error: string) => void;
}

export type IpcOn = <K extends keyof IpcEvents>(
  channel: K,
  callback: IpcEvents[K]
) => () => void;
