import type { OptConfig } from '@shared/types';

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
  boltzBaseYaml: string;
  boltzTargetResidues: string[];
  boltzMsaPath: string | null;
  boltzCacheDir: string | null;
  boltzUseMsaServer: boolean;
  createdAt: number;
  updatedAt: number;
  lastUsedAt: number | null;
}

export type ConvexConfigInput = Omit<ConvexConfig, '_id' | 'createdAt' | 'updatedAt' | 'lastUsedAt'>;

export function optConfigToConvex(name: string, config: OptConfig): ConvexConfigInput {
  return {
    name,
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
  };
}

export function convexConfigToOpt(config: ConvexConfig): OptConfig {
  return {
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
    },
  };
}
