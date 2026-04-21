import { defineSchema, defineTable } from 'convex/server';
import { v } from 'convex/values';

export default defineSchema({
  // Run configurations
  configs: defineTable({
    name: v.string(),
    engine: v.union(v.literal('boltz'), v.literal('flashbind')),
    resultDir: v.string(),
    envDir: v.string(),
    maxAtoms: v.number(),
    subsamplingRatio: v.number(),
    proteinPath: v.string(),
    center: v.union(v.array(v.number()), v.null()),
    refLigandPath: v.union(v.string(), v.null()),
    size: v.array(v.number()),
    numSteps: v.number(),
    numSamplingPerStep: v.number(),
    temperatureMin: v.number(),
    temperatureMax: v.number(),
    seed: v.number(),
    poseModel: v.string(),
    poseSteps: v.number(),
    samplingTau: v.number(),
    randomActionProb: v.number(),
    replayWarmupStep: v.number(),
    replayCapacity: v.number(),
    // Boltz config
    boltzBaseYaml: v.string(),
    boltzTargetResidues: v.array(v.string()),
    boltzMsaPath: v.union(v.string(), v.null()),
    boltzCacheDir: v.union(v.string(), v.null()),
    boltzUseMsaServer: v.boolean(),
    boltzWorker: v.number(),
    // FlashBind config
    flashbindRoot: v.string(),
    flashbindProteinId: v.string(),
    flashbindPdbDir: v.string(),
    flashbindProteinRepr: v.string(),
    flashbindLigandRepr: v.string(),
    flashbindProtsJson: v.union(v.string(), v.null()),
    flashbindFabindCheckpoint: v.string(),
    flashbindBinaryCheckpoints: v.array(v.string()),
    flashbindValueCheckpoints: v.array(v.string()),
    flashbindFabindCondaEnv: v.string(),
    flashbindFlashbindCondaEnv: v.string(),
    flashbindFabindNumThreads: v.number(),
    flashbindFabindBatchSize: v.number(),
    flashbindFabindPostOptim: v.boolean(),
    flashbindDevices: v.number(),
    flashbindAccelerator: v.string(),
    flashbindNumWorkers: v.number(),
    flashbindDistanceThreshold: v.number(),
    flashbindReprNJobs: v.number(),
    flashbindAutoGenerateProteinRepr: v.boolean(),
    flashbindAutoGenerateLigandRepr: v.boolean(),
    flashbindRewardCachePath: v.union(v.string(), v.null()),
    flashbindHfCache: v.union(v.string(), v.null()),
    // Metadata
    createdAt: v.number(),
    updatedAt: v.number(),
    lastUsedAt: v.union(v.number(), v.null()),
  })
    .index('by_name', ['name'])
    .index('by_last_used', ['lastUsedAt']),

  // Training runs
  runs: defineTable({
    configId: v.id('configs'),
    name: v.string(),
    engine: v.union(v.literal('boltz'), v.literal('flashbind')),
    status: v.union(
      v.literal('idle'),
      v.literal('running'),
      v.literal('paused'),
      v.literal('completed'),
      v.literal('error')
    ),
    currentStep: v.number(),
    totalSteps: v.number(),
    resultDir: v.string(),
    checkpointPath: v.union(v.string(), v.null()),
    error: v.union(v.string(), v.null()),
    startedAt: v.union(v.number(), v.null()),
    completedAt: v.union(v.number(), v.null()),
    lastUpdatedAt: v.number(),
  })
    .index('by_status', ['status'])
    .index('by_config', ['configId']),

  // Uploaded files (PDB, YAML, etc.)
  files: defineTable({
    name: v.string(),
    type: v.union(v.literal('pdb'), v.literal('yaml'), v.literal('msa'), v.literal('db'), v.literal('other')),
    // Field type identifies which config field this file is used for
    fieldType: v.union(
      v.literal('protein_pdb'),
      v.literal('boltz_yaml'),
      v.literal('msa'),
      v.literal('other')
    ),
    storageId: v.id('_storage'),
    size: v.number(),
    runId: v.union(v.id('runs'), v.null()),
    createdAt: v.number(),
  })
    .index('by_run', ['runId'])
    .index('by_type', ['type'])
    .index('by_field_type', ['fieldType']),

  // Generated molecules (synced from SQLite)
  molecules: defineTable({
    runId: v.id('runs'),
    engine: v.union(v.literal('boltz'), v.literal('flashbind')),
    smiles: v.string(),
    reward: v.number(),
    normalizedAffinity: v.union(v.number(), v.null()),
    normalizedProbability: v.union(v.number(), v.null()),
    normalizedScore: v.union(v.number(), v.null()),
    trajectory: v.string(), // JSON string
    // Boltz scores
    affinityEnsemble: v.union(v.number(), v.null()),
    probabilityEnsemble: v.union(v.number(), v.null()),
    affinityModel1: v.union(v.number(), v.null()),
    probabilityModel1: v.union(v.number(), v.null()),
    affinityModel2: v.union(v.number(), v.null()),
    probabilityModel2: v.union(v.number(), v.null()),
    oracleIdx: v.union(v.number(), v.null()),
    molIdx: v.union(v.number(), v.null()),
    // Complex file reference
    complexFileId: v.union(v.id('files'), v.null()),
    iteration: v.number(),
    createdAt: v.number(),
  })
    .index('by_run', ['runId'])
    .index('by_run_reward', ['runId', 'reward'])
    .index('by_smiles', ['smiles']),

  // User annotations on molecules
  annotations: defineTable({
    moleculeId: v.id('molecules'),
    note: v.string(),
    starred: v.boolean(),
    tags: v.array(v.string()),
    createdAt: v.number(),
    updatedAt: v.number(),
  }).index('by_molecule', ['moleculeId']),
});
