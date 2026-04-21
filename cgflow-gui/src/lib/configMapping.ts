import type { FlashBindConfig, OptConfig, OptimizationEngine } from '@shared/types';

const defaultFlashBindConfig: FlashBindConfig = {
  root: './src/FlashBind',
  protein_id: '',
  pdb_dir: '',
  protein_repr: '',
  ligand_repr: '',
  prots_json: null,
  fabind_checkpoint: '',
  binary_checkpoints: [],
  value_checkpoints: [],
  fabind_conda_env: 'fabind',
  flashbind_conda_env: 'flashaffinity',
  fabind_num_threads: 8,
  fabind_batch_size: 4,
  fabind_post_optim: true,
  devices: 1,
  accelerator: 'gpu',
  num_workers: 16,
  distance_threshold: 20,
  repr_n_jobs: -1,
  auto_generate_protein_repr: true,
  auto_generate_ligand_repr: true,
  reward_cache_path: null,
  hf_cache: null,
};

export interface ConvexConfig {
  _id: string;
  name: string;
  resultDir: string;
  envDir: string;
  maxAtoms: number;
  subsamplingRatio: number;
  proteinPath: string;
  center: number[] | null;
  refLigandPath: string | null;
  size: number[];
  numSteps: number;
  numSamplingPerStep: number;
  temperatureMin: number;
  temperatureMax: number;
  seed: number;
  poseModel: string;
  poseSteps: number;
  samplingTau: number;
  randomActionProb: number;
  replayWarmupStep: number;
  replayCapacity: number;
  engine?: OptimizationEngine;
  boltzBaseYaml: string;
  boltzTargetResidues: string[];
  boltzMsaPath: string | null;
  boltzCacheDir: string | null;
  boltzUseMsaServer: boolean;
  boltzWorker: number;
  flashbindRoot?: string;
  flashbindProteinId?: string;
  flashbindPdbDir?: string;
  flashbindProteinRepr?: string;
  flashbindLigandRepr?: string;
  flashbindProtsJson?: string | null;
  flashbindFabindCheckpoint?: string;
  flashbindBinaryCheckpoints?: string[];
  flashbindValueCheckpoints?: string[];
  flashbindFabindCondaEnv?: string;
  flashbindFlashbindCondaEnv?: string;
  flashbindFabindNumThreads?: number;
  flashbindFabindBatchSize?: number;
  flashbindFabindPostOptim?: boolean;
  flashbindDevices?: number;
  flashbindAccelerator?: string;
  flashbindNumWorkers?: number;
  flashbindDistanceThreshold?: number;
  flashbindReprNJobs?: number;
  flashbindAutoGenerateProteinRepr?: boolean;
  flashbindAutoGenerateLigandRepr?: boolean;
  flashbindRewardCachePath?: string | null;
  flashbindHfCache?: string | null;
  createdAt: number;
  updatedAt: number;
  lastUsedAt: number | null;
}

export type ConvexConfigInput = Omit<ConvexConfig, '_id' | 'createdAt' | 'updatedAt' | 'lastUsedAt'>;

export function optConfigToConvex(name: string, config: OptConfig): ConvexConfigInput {
  const flashbind = config.flashbind ?? defaultFlashBindConfig;
  return {
    name,
    engine: config.engine ?? 'boltz',
    resultDir: config.result_dir,
    envDir: config.env_dir,
    maxAtoms: config.max_atoms,
    subsamplingRatio: config.subsampling_ratio,
    proteinPath: config.protein_path,
    center: config.center ? [...config.center] : null,
    refLigandPath: config.ref_ligand_path,
    size: [...config.size],
    numSteps: config.num_steps,
    numSamplingPerStep: config.num_sampling_per_step,
    temperatureMin: config.temperature[0],
    temperatureMax: config.temperature[1],
    seed: config.seed,
    poseModel: config.pose_model,
    poseSteps: config.pose_steps,
    samplingTau: config.sampling_tau,
    randomActionProb: config.random_action_prob,
    replayWarmupStep: config.replay_warmup_step,
    replayCapacity: config.replay_capacity,
    boltzBaseYaml: config.boltz.base_yaml,
    boltzTargetResidues: [...config.boltz.target_residues],
    boltzMsaPath: config.boltz.msa_path,
    boltzCacheDir: config.boltz.cache_dir,
    boltzUseMsaServer: config.boltz.use_msa_server,
    boltzWorker: Math.max(1, Math.floor(config.boltz.worker ?? 1)),
    flashbindRoot: flashbind.root,
    flashbindProteinId: flashbind.protein_id,
    flashbindPdbDir: flashbind.pdb_dir,
    flashbindProteinRepr: flashbind.protein_repr,
    flashbindLigandRepr: flashbind.ligand_repr,
    flashbindProtsJson: flashbind.prots_json,
    flashbindFabindCheckpoint: flashbind.fabind_checkpoint,
    flashbindBinaryCheckpoints: [...flashbind.binary_checkpoints],
    flashbindValueCheckpoints: [...flashbind.value_checkpoints],
    flashbindFabindCondaEnv: flashbind.fabind_conda_env,
    flashbindFlashbindCondaEnv: flashbind.flashbind_conda_env,
    flashbindFabindNumThreads: flashbind.fabind_num_threads,
    flashbindFabindBatchSize: flashbind.fabind_batch_size,
    flashbindFabindPostOptim: flashbind.fabind_post_optim,
    flashbindDevices: flashbind.devices,
    flashbindAccelerator: flashbind.accelerator,
    flashbindNumWorkers: flashbind.num_workers,
    flashbindDistanceThreshold: flashbind.distance_threshold,
    flashbindReprNJobs: flashbind.repr_n_jobs,
    flashbindAutoGenerateProteinRepr: flashbind.auto_generate_protein_repr,
    flashbindAutoGenerateLigandRepr: flashbind.auto_generate_ligand_repr,
    flashbindRewardCachePath: flashbind.reward_cache_path,
    flashbindHfCache: flashbind.hf_cache,
  };
}

export function convexConfigToOpt(config: ConvexConfig): OptConfig {
  const flashbind: FlashBindConfig = {
    root: config.flashbindRoot ?? defaultFlashBindConfig.root,
    protein_id: config.flashbindProteinId ?? defaultFlashBindConfig.protein_id,
    pdb_dir: config.flashbindPdbDir ?? defaultFlashBindConfig.pdb_dir,
    protein_repr: config.flashbindProteinRepr ?? defaultFlashBindConfig.protein_repr,
    ligand_repr: config.flashbindLigandRepr ?? defaultFlashBindConfig.ligand_repr,
    prots_json: config.flashbindProtsJson ?? defaultFlashBindConfig.prots_json,
    fabind_checkpoint: config.flashbindFabindCheckpoint ?? defaultFlashBindConfig.fabind_checkpoint,
    binary_checkpoints: config.flashbindBinaryCheckpoints ?? defaultFlashBindConfig.binary_checkpoints,
    value_checkpoints: config.flashbindValueCheckpoints ?? defaultFlashBindConfig.value_checkpoints,
    fabind_conda_env: config.flashbindFabindCondaEnv ?? defaultFlashBindConfig.fabind_conda_env,
    flashbind_conda_env:
      config.flashbindFlashbindCondaEnv ?? defaultFlashBindConfig.flashbind_conda_env,
    fabind_num_threads:
      config.flashbindFabindNumThreads ?? defaultFlashBindConfig.fabind_num_threads,
    fabind_batch_size:
      config.flashbindFabindBatchSize ?? defaultFlashBindConfig.fabind_batch_size,
    fabind_post_optim:
      config.flashbindFabindPostOptim ?? defaultFlashBindConfig.fabind_post_optim,
    devices: config.flashbindDevices ?? defaultFlashBindConfig.devices,
    accelerator: config.flashbindAccelerator ?? defaultFlashBindConfig.accelerator,
    num_workers: config.flashbindNumWorkers ?? defaultFlashBindConfig.num_workers,
    distance_threshold:
      config.flashbindDistanceThreshold ?? defaultFlashBindConfig.distance_threshold,
    repr_n_jobs: config.flashbindReprNJobs ?? defaultFlashBindConfig.repr_n_jobs,
    auto_generate_protein_repr:
      config.flashbindAutoGenerateProteinRepr ??
      defaultFlashBindConfig.auto_generate_protein_repr,
    auto_generate_ligand_repr:
      config.flashbindAutoGenerateLigandRepr ??
      defaultFlashBindConfig.auto_generate_ligand_repr,
    reward_cache_path:
      config.flashbindRewardCachePath ?? defaultFlashBindConfig.reward_cache_path,
    hf_cache: config.flashbindHfCache ?? defaultFlashBindConfig.hf_cache,
  };

  return {
    engine: config.engine ?? 'boltz',
    result_dir: config.resultDir,
    env_dir: config.envDir,
    max_atoms: config.maxAtoms,
    subsampling_ratio: config.subsamplingRatio,
    protein_path: config.proteinPath,
    center: config.center ? (config.center as [number, number, number]) : null,
    ref_ligand_path: config.refLigandPath,
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
      target_residues: config.boltzTargetResidues,
      msa_path: config.boltzMsaPath,
      cache_dir: config.boltzCacheDir,
      use_msa_server: config.boltzUseMsaServer,
      worker: Math.max(1, Math.floor(config.boltzWorker ?? 1)),
    },
    flashbind,
  };
}
