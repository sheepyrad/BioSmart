import { useState, useCallback, useEffect, useMemo } from 'react';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { ScrollArea } from '@/components/ui/scroll-area';
import { Badge } from '@/components/ui/badge';
import { useIpcInvoke, useIpcEvent, useRunOutput } from '@/hooks/useIpc';
import { useConvexConfigs } from '@/hooks/useConvexConfigs';
import MolstarViewer from '@/components/MolstarViewer';
import FileSelector from '@/components/FileSelector';
import type {
  OptConfig,
  RunInfo,
  BoltzConfig,
  FlashBindConfig,
  OptimizationEngine,
} from '@shared/types';
import { OptConfigSchema } from '@shared/types';
import { convexConfigToOpt, optConfigToConvex } from '@/lib/configMapping';
import YAML from 'yaml';
import {
  Clock,
  Cloud,
  FolderOpen,
  GripVertical,
  Loader2,
  Play,
  Plus,
  Save,
  Square,
  X,
  Microscope,
  Dna,
  SlidersHorizontal,
  Zap,
  FileText,
} from 'lucide-react';

interface ConfigBuilderProps {
  onConfigChange: (config: OptConfig | null) => void;
  onRunStarted: (run: RunInfo) => void;
  activeRun: RunInfo | null;
}

const defaultBoltzConfig: BoltzConfig = {
  base_yaml: '',
  target_residues: [],
  msa_path: null,
  cache_dir: null,
  use_msa_server: false,
  worker: 1,
};

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

const defaultConfig: OptConfig = {
  engine: 'boltz',
  result_dir: './result/opt/unidock_boltz/custom',
  env_dir: './data/envs/enamine_stock_new',
  max_atoms: 60,
  subsampling_ratio: 0.1,
  protein_path: '',
  center: null,
  ref_ligand_path: null,
  size: [16, 16, 16],
  num_steps: 2000,
  num_sampling_per_step: 32,
  temperature: [1, 64],
  seed: 481,
  pose_model: './weights/cgflow_crossdock.ckpt',
  pose_steps: 40,
  sampling_tau: 0.9,
  random_action_prob: 0.05,
  replay_warmup_step: 10,
  replay_capacity: 6400,
  boltz: defaultBoltzConfig,
  flashbind: defaultFlashBindConfig,
};

const normalizeBoltzWorker = (value: unknown): number => {
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) return 1;
  return Math.max(1, Math.floor(parsed));
};

const normalizeEngine = (value: unknown): OptimizationEngine => {
  return value === 'flashbind' ? 'flashbind' : 'boltz';
};

const normalizeFlashbindConfig = (value: unknown): FlashBindConfig => {
  const incoming = (value as Partial<FlashBindConfig> | null) ?? {};
  return {
    ...defaultFlashBindConfig,
    ...incoming,
    binary_checkpoints: Array.isArray(incoming.binary_checkpoints)
      ? incoming.binary_checkpoints.filter((v): v is string => typeof v === 'string')
      : defaultFlashBindConfig.binary_checkpoints,
    value_checkpoints: Array.isArray(incoming.value_checkpoints)
      ? incoming.value_checkpoints.filter((v): v is string => typeof v === 'string')
      : defaultFlashBindConfig.value_checkpoints,
  };
};

const getPathFilename = (input: string | null | undefined): string => {
  if (!input) return '';
  if (input.startsWith('convex://')) {
    const parts = input.split('::');
    return parts[1] ?? '';
  }
  // Normalize backslashes to forward slashes for cross-platform compatibility
  const normalized = input.replace(/\\/g, '/');
  return normalized.split('/').pop() ?? '';
};

const getFilenameStem = (filename: string): string => {
  const idx = filename.lastIndexOf('.');
  if (idx <= 0) return filename;
  return filename.slice(0, idx);
};

const isFlashbindSafeFilename = (filename: string): boolean => /^[A-Za-z0-9.-]+$/.test(filename);
const TARGET_RESIDUE_PATTERN = /^[A-Z]:\d+$/;

const hasUnsafeRelativePath = (value: string): boolean => value.includes('..');

const parseBoundedIntegerInput = (
  rawValue: string,
  currentValue: number,
  min: number,
  max: number
): number => {
  if (rawValue.trim() === '') return currentValue;
  const parsed = Number.parseInt(rawValue, 10);
  if (!Number.isFinite(parsed)) return currentValue;
  return Math.max(min, Math.min(max, parsed));
};

const AMINO_ACID_3_TO_1: Record<string, string> = {
  ALA: 'A', ARG: 'R', ASN: 'N', ASP: 'D', CYS: 'C',
  GLN: 'Q', GLU: 'E', GLY: 'G', HIS: 'H', ILE: 'I',
  LEU: 'L', LYS: 'K', MET: 'M', PHE: 'F', PRO: 'P',
  SER: 'S', THR: 'T', TRP: 'W', TYR: 'Y', VAL: 'V',
  SEC: 'U', PYL: 'O', MSE: 'M',
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

function SectionIcon({ icon: Icon }: { icon: React.ElementType }) {
  return (
    <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md bg-primary/10">
      <Icon className="h-3.5 w-3.5 text-primary" />
    </div>
  );
}

export default function ConfigBuilder({
  onConfigChange,
  onRunStarted,
  activeRun,
}: ConfigBuilderProps) {
  const invoke = useIpcInvoke();
  const runOutput = useRunOutput(activeRun?.id ?? null);
  const { configs, createConfig, updateConfig, isAvailable: isConvexAvailable } = useConvexConfigs(10);
  const [config, setConfig] = useState<OptConfig>(defaultConfig);
  const [configPath, setConfigPath] = useState<string | null>(null);
  const [configName, setConfigName] = useState<string>('New Config');
  const [savedConfigId, setSavedConfigId] = useState<string | null>(null);
  const [pdbContent, setPdbContent] = useState<string | null>(null);
  const [loadedPdbPath, setLoadedPdbPath] = useState<string | null>(null);
  const [ligandContent, setLigandContent] = useState<string | null>(null);
  const [loadedLigandPath, setLoadedLigandPath] = useState<string | null>(null);
  const [selectedResidues, setSelectedResidues] = useState<string[]>([]);
  const [newResidue, setNewResidue] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [startError, setStartError] = useState<string | null>(null);
  const [validationErrors, setValidationErrors] = useState<string[]>([]);
  const [leftPanelWidth, setLeftPanelWidth] = useState(50);
  const isFlashBindEngine = config.engine === 'flashbind';

  useEffect(() => {
    onConfigChange(config);
  }, [config, onConfigChange]);

  useIpcEvent(
    'run:status-changed',
    useCallback(
      (runInfo: RunInfo) => {
        if (activeRun && runInfo.id === activeRun.id) {
          onRunStarted(runInfo);
        }
      },
      [activeRun, onRunStarted]
    )
  );

  useIpcEvent(
    'run:error',
    useCallback(
      (runId: string, error: string) => {
        if (!activeRun || runId !== activeRun.id) return;
        onRunStarted({
          ...activeRun,
          status: 'error',
          error,
          lastUpdatedAt: new Date().toISOString(),
        });
      },
      [activeRun, onRunStarted]
    )
  );

  useEffect(() => {
    if (isFlashBindEngine) return;
    setConfig((prev) => ({
      ...prev,
      boltz: {
        ...prev.boltz,
        target_residues: selectedResidues,
      },
    }));
  }, [isFlashBindEngine, selectedResidues]);

  useEffect(() => {
    if (!isFlashBindEngine) return;
    if (selectedResidues.length === 0) return;
    setSelectedResidues([]);
  }, [isFlashBindEngine, selectedResidues.length]);

  useEffect(() => {
    let cancelled = false;

    const maybeLoadPdbContent = async () => {
      if (!config.protein_path) {
        if (!cancelled) {
          setPdbContent(null);
          setLoadedPdbPath(null);
        }
        return;
      }
      if (pdbContent && loadedPdbPath === config.protein_path) return;
      try {
        const content = await invoke('file:read-pdb', config.protein_path);
        if (!cancelled) {
          setPdbContent(content);
          setLoadedPdbPath(config.protein_path);
        }
      } catch {
        // Protein path may be unavailable in current environment
      }
    };

    void maybeLoadPdbContent();
    return () => {
      cancelled = true;
    };
  }, [config.protein_path, pdbContent, loadedPdbPath, invoke]);

  useEffect(() => {
    let cancelled = false;

    const maybeLoadLigandContent = async () => {
      if (!config.ref_ligand_path) {
        if (!cancelled) {
          setLigandContent(null);
          setLoadedLigandPath(null);
        }
        return;
      }
      if (ligandContent && loadedLigandPath === config.ref_ligand_path) return;
      try {
        const content = await invoke('file:read-text', config.ref_ligand_path);
        if (!cancelled) {
          setLigandContent(content);
          setLoadedLigandPath(config.ref_ligand_path);
        }
      } catch {
        // Ligand path may be unavailable in current environment
      }
    };

    void maybeLoadLigandContent();
    return () => {
      cancelled = true;
    };
  }, [config.ref_ligand_path, ligandContent, loadedLigandPath, invoke]);

  const generatedBoltzYamlResult = useMemo(() => {
    if (!pdbContent) {
      return { yaml: '', error: null as string | null };
    }
    const sequences = parseProteinSequencesFromPdb(pdbContent);
    if (sequences.length === 0) {
      return { yaml: '', error: 'Could not extract protein sequence from current PDB.' };
    }
    const yaml = YAML.stringify({
      version: 1,
      sequences: sequences.map((entry) => ({
        protein: {
          id: entry.chainId,
          sequence: entry.sequence,
          ...(config.boltz.msa_path ? { msa: config.boltz.msa_path } : {}),
        },
      })),
    });
    return { yaml, error: null as string | null };
  }, [pdbContent, config.boltz.msa_path]);

  const handleLoadConfig = useCallback(async () => {
    setIsLoading(true);
    try {
      const path = await invoke('file:select-yaml');
      if (path) {
        const loadedConfig = await invoke('file:read-yaml', path);
        const normalizedConfig: OptConfig = {
          ...loadedConfig,
          engine: normalizeEngine((loadedConfig as Partial<OptConfig>).engine),
          boltz: {
            ...loadedConfig.boltz,
            worker: normalizeBoltzWorker(
              (loadedConfig.boltz as unknown as { worker?: unknown; boltz_worker?: unknown })?.worker ??
                (loadedConfig.boltz as unknown as { worker?: unknown; boltz_worker?: unknown })?.boltz_worker
            ),
          },
          flashbind: normalizeFlashbindConfig((loadedConfig as Partial<OptConfig>).flashbind),
        };
        setConfig(normalizedConfig);
        setConfigPath(path);
        setSelectedResidues(
          normalizedConfig.engine === 'boltz' ? normalizedConfig.boltz.target_residues : []
        );
        setSavedConfigId(null);
      }
    } finally {
      setIsLoading(false);
    }
  }, [invoke]);

  const handleSelectPdb = useCallback(async (): Promise<string | null> => {
    setIsLoading(true);
    try {
      const path = await invoke('file:select-pdb');
      if (path) {
        const content = await invoke('file:read-pdb', path);
        setPdbContent(content);
        setLoadedPdbPath(path);
      }
      return path;
    } finally {
      setIsLoading(false);
    }
  }, [invoke]);

  const handleSelectMsa = useCallback(async (): Promise<string | null> => {
    return await invoke('file:select-msa');
  }, [invoke]);

  const handleSelectProtsJson = useCallback(async (): Promise<string | null> => {
    return await invoke('file:select-json');
  }, [invoke]);

  const handleSelectLigand = useCallback(async (): Promise<string | null> => {
    setIsLoading(true);
    try {
      const path = await invoke('file:select-ligand');
      if (path) {
        const content = await invoke('file:read-text', path);
        setLigandContent(content);
        setLoadedLigandPath(path);
      }
      return path;
    } finally {
      setIsLoading(false);
    }
  }, [invoke]);

  const handleSelectResultDir = useCallback(async () => {
    const path = await invoke('file:select-directory');
    if (path) {
      if (hasUnsafeRelativePath(path)) {
        setStartError('Result directory cannot contain ".." path traversal sequences.');
        return;
      }
      setStartError(null);
      setConfig((prev) => ({ ...prev, result_dir: path }));
    }
  }, [invoke]);

  const handleSelectEnvDir = useCallback(async () => {
    const path = await invoke('file:select-directory');
    if (path) {
      if (hasUnsafeRelativePath(path)) {
        setStartError('Environment directory cannot contain ".." path traversal sequences.');
        return;
      }
      setStartError(null);
      setConfig((prev) => ({ ...prev, env_dir: path }));
    }
  }, [invoke]);

  const handleResidueSelect = useCallback((residues: string[]) => {
    setSelectedResidues(residues);
  }, []);

  const handleAddResidue = useCallback(() => {
    const normalized = newResidue.trim().toUpperCase();
    if (!normalized) return;
    if (!TARGET_RESIDUE_PATTERN.test(normalized)) {
      setStartError('Residue must match CHAIN:RESID (for example A:123).');
      return;
    }
    setStartError(null);
    if (!selectedResidues.includes(normalized)) {
      setSelectedResidues((prev) => [...prev, normalized]);
      setNewResidue('');
    }
  }, [newResidue, selectedResidues]);

  const handleRemoveResidue = useCallback((residue: string) => {
    setSelectedResidues((prev) => prev.filter((r) => r !== residue));
  }, []);

  const handleSaveConfig = useCallback(async () => {
    const path = await invoke('file:select-yaml');
    if (path) {
      await invoke('file:write-yaml', path, config);
      setConfigPath(path);
    }
  }, [invoke, config]);

  const handleSaveToConvex = useCallback(async () => {
    if (!isConvexAvailable) return;
    setIsLoading(true);
    try {
      const payload = optConfigToConvex(configName.trim() || 'Untitled Config', config);
      if (savedConfigId) {
        await updateConfig(savedConfigId as any, payload);
      } else {
        const id = await createConfig(payload);
        if (id) setSavedConfigId(id);
      }
    } finally {
      setIsLoading(false);
    }
  }, [isConvexAvailable, config, configName, savedConfigId, createConfig, updateConfig]);

  const handleLoadConvexConfig = useCallback(
    (convexConfig: any) => {
      const loaded = convexConfigToOpt(convexConfig);
      const normalizedLoaded: OptConfig = {
        ...loaded,
        engine: normalizeEngine((loaded as Partial<OptConfig>).engine),
        boltz: {
          ...loaded.boltz,
          worker: normalizeBoltzWorker(
            (loaded.boltz as unknown as { worker?: unknown; boltz_worker?: unknown })?.worker ??
              (loaded.boltz as unknown as { worker?: unknown; boltz_worker?: unknown })?.boltz_worker
          ),
        },
        flashbind: normalizeFlashbindConfig((loaded as Partial<OptConfig>).flashbind),
      };
      setConfig(normalizedLoaded);
      setConfigName(convexConfig.name);
      setSavedConfigId(convexConfig._id);
      setConfigPath(null);
      setSelectedResidues(
        normalizedLoaded.engine === 'boltz' ? normalizedLoaded.boltz.target_residues : []
      );
    },
    []
  );

  const handleLoadLastUsed = useCallback(() => {
    if (!configs || configs.length === 0) return;
    const latest = configs[0];
    if (!latest) return;
    handleLoadConvexConfig(latest);
  }, [configs, handleLoadConvexConfig]);

  const handleStartRun = useCallback(async () => {
    if (isFlashBindEngine) {
      const proteinId = config.flashbind?.protein_id?.trim() ?? '';
      if (!proteinId) {
        setStartError('FlashBind requires `protein_id`.');
        return;
      }
      const protsJsonPath = config.flashbind?.prots_json;
      if (!protsJsonPath) {
        setStartError('FlashBind requires `prots_json`.');
        return;
      }

      const proteinFilename = getPathFilename(config.protein_path);
      const protsJsonFilename = getPathFilename(protsJsonPath);
      const filenamesToCheck = [
        { label: 'protein file', value: proteinFilename },
        { label: 'prots_json file', value: protsJsonFilename },
      ];
      for (const item of filenamesToCheck) {
        if (!item.value) {
          setStartError(`FlashBind requires a valid ${item.label} name.`);
          return;
        }
        if (!isFlashbindSafeFilename(item.value) || item.value.includes('_')) {
          setStartError(
            `FlashBind ${item.label} "${item.value}" is invalid. Use only letters/numbers/dot/hyphen; no spaces, symbols, or underscores (_).`
          );
          return;
        }
      }

      const proteinStem = getFilenameStem(proteinFilename);
      if (proteinStem !== proteinId) {
        setStartError(
          `FlashBind requires protein_id (${proteinId}) to match protein filename stem (${proteinStem}).`
        );
        return;
      }
    }

    const trimmedConfigName = configName.trim();
    if (trimmedConfigName.length > 255) {
      setStartError('Configuration name must be 255 characters or fewer.');
      return;
    }
    if (hasUnsafeRelativePath(config.result_dir) || hasUnsafeRelativePath(config.env_dir)) {
      setStartError('Directory paths cannot contain ".." path traversal sequences.');
      return;
    }

    const parsedConfig = OptConfigSchema.safeParse(config);
    if (!parsedConfig.success) {
      setValidationErrors(
        parsedConfig.error.issues.map((issue) => `${issue.path.join('.') || 'config'}: ${issue.message}`)
      );
      setStartError('Configuration validation failed. Fix the errors below.');
      return;
    }

    setIsLoading(true);
    setStartError(null);
    setValidationErrors([]);
    try {
      if (savedConfigId && isConvexAvailable) {
        await updateConfig(savedConfigId as any, { lastUsedAt: Date.now() });
      }
      const runInfo = await invoke('run:start', {
        config: parsedConfig.data,
        configPath,
        configId: savedConfigId,
        name: trimmedConfigName || undefined,
      });
      onRunStarted(runInfo);
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Failed to start run.';
      setStartError(message);
    } finally {
      setIsLoading(false);
    }
  }, [
    config,
    configName,
    configPath,
    invoke,
    isConvexAvailable,
    isFlashBindEngine,
    onRunStarted,
    savedConfigId,
    updateConfig,
  ]);

  const handleStopRun = useCallback(async () => {
    if (activeRun) {
      await invoke('run:stop', activeRun.id);
    }
  }, [invoke, activeRun]);

  const isRunning = activeRun?.status === 'running';
  const runStatusVariant =
    activeRun?.status === 'running'
      ? 'success'
      : activeRun?.status === 'error'
        ? 'destructive'
        : activeRun?.status === 'paused'
          ? 'warning'
          : 'secondary';

  return (
    <div className="flex h-full min-h-0">
      {/* Left panel - Config form */}
      <div
        className="relative shrink-0 border-r border-border bg-background"
        style={{ width: `${leftPanelWidth}%` }}
      >
        <ScrollArea className="h-full">
          <div className="space-y-4 p-5">
            {/* Page header */}
            <div className="mb-6">
              <h2 className="font-display text-2xl font-semibold tracking-tight">
                Run Configuration
              </h2>
              <p className="mt-1 text-sm text-muted-foreground">
                Prepare and launch molecular optimization jobs with {isFlashBindEngine ? 'FlashBind' : 'Boltz-2'}.
              </p>
            </div>

            <Card className="border-border/60 bg-card/80">
              <CardHeader className="pb-3">
                <CardTitle className="font-display text-base">Optimization Engine</CardTitle>
                <CardDescription>Choose the scoring backend for this run.</CardDescription>
              </CardHeader>
              <CardContent>
                <div className="grid grid-cols-2 gap-2">
                  <Button
                    variant={config.engine === 'boltz' ? 'default' : 'outline'}
                    onClick={() =>
                      setConfig((prev) => ({
                        ...prev,
                        engine: 'boltz',
                        boltz: {
                          ...prev.boltz,
                          target_residues:
                            selectedResidues.length > 0
                              ? selectedResidues
                              : prev.boltz.target_residues,
                        },
                      }))
                    }
                  >
                    Boltz
                  </Button>
                  <Button
                    variant={config.engine === 'flashbind' ? 'default' : 'outline'}
                    onClick={() =>
                      setConfig((prev) => ({
                        ...prev,
                        engine: 'flashbind',
                        flashbind: prev.flashbind ?? defaultFlashBindConfig,
                        boltz: { ...prev.boltz, target_residues: [] },
                      }))
                    }
                  >
                    FlashBind
                  </Button>
                </div>
              </CardContent>
            </Card>

            {/* Config management */}
            <Card className="border-border/60 bg-card/80">
              <CardHeader className="pb-4">
                <div className="flex items-center gap-3">
                  <SectionIcon icon={FileText} />
                  <div>
                    <CardTitle className="font-display text-base">Configuration</CardTitle>
                    <CardDescription>Load an existing setup or prepare a new run.</CardDescription>
                  </div>
                </div>
              </CardHeader>
              <CardContent className="space-y-4">
                <div className="flex gap-2">
                  <Button
                    variant="outline"
                    onClick={handleLoadConfig}
                    disabled={isLoading}
                    className="flex-1"
                  >
                    {isLoading ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <FolderOpen className="mr-2 h-4 w-4" />}
                    Load
                  </Button>
                  <Button variant="outline" onClick={handleSaveConfig} className="flex-1">
                    <Save className="mr-2 h-4 w-4" />
                    Save
                  </Button>
                </div>

                <div className="space-y-2">
                  <Label htmlFor="config-name" className="text-xs font-medium text-muted-foreground">Config name</Label>
                  <Input
                    id="config-name"
                    value={configName}
                    maxLength={255}
                    onChange={(e) => setConfigName(e.target.value.slice(0, 255))}
                    placeholder="Name this configuration"
                  />
                </div>

                {isConvexAvailable ? (
                  <div className="space-y-3 rounded-md border border-primary/10 bg-primary/[0.03] p-3">
                    <div className="flex gap-2">
                      <Button
                        variant="default"
                        onClick={handleSaveToConvex}
                        disabled={isLoading}
                        className="flex-1"
                      >
                        <Cloud className="mr-2 h-4 w-4" />
                        Cloud Save
                      </Button>
                      <Button
                        variant="outline"
                        onClick={handleLoadLastUsed}
                        className="flex-1"
                        disabled={!configs || configs.length === 0}
                      >
                        <Clock className="mr-2 h-4 w-4" />
                        Last Used
                      </Button>
                    </div>

                    {configs && configs.length > 0 ? (
                      <div className="space-y-2">
                        <p className="text-[10px] font-semibold uppercase tracking-[0.15em] text-muted-foreground">
                          Recent
                        </p>
                        <div className="space-y-1">
                          {configs.map((cfg) => (
                            <button
                              key={cfg._id}
                              onClick={() => handleLoadConvexConfig(cfg)}
                              className={`flex w-full items-center justify-between rounded-md border px-3 py-2 text-left text-sm transition-all ${
                                savedConfigId === cfg._id
                                  ? 'border-primary/30 bg-primary/5'
                                  : 'border-transparent hover:border-border hover:bg-secondary/40'
                              }`}
                            >
                              <span className="truncate font-medium">{cfg.name}</span>
                              <span className="ml-3 shrink-0 font-data text-[10px] text-muted-foreground">
                                {cfg.lastUsedAt ? new Date(cfg.lastUsedAt).toLocaleDateString() : 'Saved'}
                              </span>
                            </button>
                          ))}
                        </div>
                      </div>
                    ) : null}
                  </div>
                ) : null}

                {configPath ? (
                  <div className="rounded-md border border-border bg-secondary/30 px-3 py-2 font-data text-[11px] text-muted-foreground">
                    {configPath}
                  </div>
                ) : null}
              </CardContent>
            </Card>

            {/* Input files */}
            <Card className="border-border/60 bg-card/80">
              <CardHeader className="pb-4">
                <div className="flex items-center gap-3">
                  <SectionIcon icon={Microscope} />
                  <div>
                    <CardTitle className="font-display text-base">Input Files</CardTitle>
                    <CardDescription>
                      Protein and reference ligand inputs for {isFlashBindEngine ? 'FlashBind' : 'Boltz'}.
                    </CardDescription>
                  </div>
                </div>
              </CardHeader>
              <CardContent className="space-y-4">
                <FileSelector
                  label="Protein PDB"
                  value={config.protein_path}
                  onChange={(path) => setConfig((prev) => ({ ...prev, protein_path: path }))}
                  onContentLoaded={(content) => setPdbContent(content)}
                  fieldType="protein_pdb"
                  fileType="pdb"
                  accept=".pdb"
                  placeholder="Select protein .pdb file"
                  onSelectLocal={handleSelectPdb}
                  onReadLocalContent={async (path) => await invoke('file:read-pdb', path)}
                />

                <FileSelector
                  label="Reference ligand"
                  value={config.ref_ligand_path ?? ''}
                  onChange={(path) =>
                    setConfig((prev) => ({
                      ...prev,
                      ref_ligand_path: path || null,
                    }))
                  }
                  onContentLoaded={(content) => setLigandContent(content)}
                  fieldType="other"
                  fileType="other"
                  accept=".mol2,.sdf,.mol,.pdb,.cif,.mmcif"
                  placeholder="Select reference ligand file"
                  optional
                  onSelectLocal={handleSelectLigand}
                  onReadLocalContent={async (path) => await invoke('file:read-text', path)}
                />

                {isFlashBindEngine ? (
                  <div className="space-y-2 rounded-md border border-amber-500/30 bg-amber-500/10 p-3">
                    <p className="text-xs font-semibold uppercase tracking-[0.12em] text-amber-200">
                      FlashBind Naming Constraint
                    </p>
                    <p className="text-xs text-amber-100/90">
                      Protein and prots_json filenames must not contain spaces, special symbols, or underscores (`_`).
                      Also ensure `protein_id` exactly matches the protein filename stem.
                    </p>
                  </div>
                ) : null}

                {isFlashBindEngine ? (
                  <div className="space-y-2">
                    <Label htmlFor="flashbind-protein-id" className="text-xs font-medium text-muted-foreground">
                      FlashBind protein_id
                    </Label>
                    <Input
                      id="flashbind-protein-id"
                      value={config.flashbind?.protein_id ?? ''}
                      onChange={(e) =>
                        setConfig((prev) => ({
                          ...prev,
                          flashbind: {
                            ...(prev.flashbind ?? defaultFlashBindConfig),
                            protein_id: e.target.value.trim(),
                          },
                        }))
                      }
                      placeholder="Must match protein filename stem (e.g. NS5)"
                      className="font-data"
                    />
                  </div>
                ) : null}

                {isFlashBindEngine ? (
                  <FileSelector
                    label="FlashBind prots_json"
                    value={config.flashbind?.prots_json ?? ''}
                    onChange={(path) =>
                      setConfig((prev) => ({
                        ...prev,
                        flashbind: {
                          ...(prev.flashbind ?? defaultFlashBindConfig),
                          prots_json: path || null,
                        },
                      }))
                    }
                    fieldType="other"
                    fileType="other"
                    accept=".json"
                    placeholder="Select FlashBind prots.json"
                    onSelectLocal={handleSelectProtsJson}
                    onReadLocalContent={async (path) => await invoke('file:read-text', path)}
                    optional={false}
                  />
                ) : null}

                {!isFlashBindEngine ? (
                  <div className="space-y-2">
                    <Label className="text-xs font-medium text-muted-foreground">Boltz YAML preview</Label>
                    <div className="rounded-md border border-border bg-secondary/20 p-3">
                      {generatedBoltzYamlResult.error ? (
                        <p className="text-sm text-destructive">{generatedBoltzYamlResult.error}</p>
                      ) : generatedBoltzYamlResult.yaml ? (
                        <pre className="max-h-56 overflow-auto whitespace-pre-wrap break-all font-data text-[11px] leading-5 text-foreground/80">
                          {generatedBoltzYamlResult.yaml}
                        </pre>
                      ) : (
                        <p className="text-sm text-muted-foreground">
                          Choose a protein PDB to preview.
                        </p>
                      )}
                    </div>
                  </div>
                ) : null}

                {!isFlashBindEngine ? (
                  <FileSelector
                    label="MSA file"
                    value={config.boltz.msa_path ?? ''}
                    onChange={(path) =>
                      setConfig((prev) => ({
                        ...prev,
                        boltz: { ...prev.boltz, msa_path: path || null },
                      }))
                    }
                    fieldType="msa"
                    fileType="msa"
                    accept=".a3m"
                    placeholder="Select MSA file"
                    optional
                    onSelectLocal={handleSelectMsa}
                  />
                ) : null}

                {!isFlashBindEngine ? (
                  <div className="space-y-2">
                    <Label htmlFor="boltz-workers" className="text-xs font-medium text-muted-foreground">Boltz workers</Label>
                    <Input
                      id="boltz-workers"
                      type="number"
                      min={1}
                      max={1024}
                      value={config.boltz.worker}
                      onChange={(e) =>
                        setConfig((prev) => ({
                          ...prev,
                          boltz: {
                            ...prev.boltz,
                            worker: parseBoundedIntegerInput(
                              e.target.value,
                              normalizeBoltzWorker(prev.boltz.worker),
                              1,
                              1024
                            ),
                          },
                        }))
                      }
                      className="font-data tabular-nums"
                    />
                  </div>
                ) : null}
              </CardContent>
            </Card>

            {/* Target residues */}
            {!isFlashBindEngine ? (
              <Card className="border-border/60 bg-card/80">
                <CardHeader className="pb-4">
                  <div className="flex items-center gap-3">
                    <SectionIcon icon={Dna} />
                    <div>
                      <CardTitle className="font-display text-base">Target Residues</CardTitle>
                      <CardDescription>Pick residues in the viewer or enter as CHAIN:RESID.</CardDescription>
                    </div>
                  </div>
                </CardHeader>
                <CardContent className="space-y-4">
                  <div className="flex items-center justify-between gap-2">
                    <span className="text-[10px] font-semibold uppercase tracking-[0.15em] text-muted-foreground">Selected</span>
                    <Badge variant="outline" className="font-data text-[10px]">{selectedResidues.length}</Badge>
                  </div>

                  {selectedResidues.length > 0 ? (
                    <div className="flex flex-wrap gap-1.5">
                      {selectedResidues.map((residue) => (
                        <Badge key={residue} variant="secondary" className="gap-1 pr-1 font-data text-[11px]">
                          {residue}
                          <button
                            onClick={() => handleRemoveResidue(residue)}
                            className="rounded-sm p-0.5 text-muted-foreground hover:bg-muted hover:text-foreground"
                          >
                            <X className="h-3 w-3" />
                          </button>
                        </Badge>
                      ))}
                    </div>
                  ) : (
                    <div className="rounded-md border border-dashed border-border bg-secondary/20 px-3 py-4 text-center text-sm text-muted-foreground">
                      No residues selected yet.
                    </div>
                  )}

                  <div className="flex gap-2">
                    <Input
                      value={newResidue}
                      onChange={(e) => setNewResidue(e.target.value.toUpperCase())}
                      placeholder="A:123"
                      className="font-data"
                      onKeyDown={(e) => e.key === 'Enter' && handleAddResidue()}
                    />
                    <Button variant="outline" size="icon" onClick={handleAddResidue}>
                      <Plus className="h-4 w-4" />
                    </Button>
                    {selectedResidues.length > 0 ? (
                      <Button variant="ghost" size="sm" onClick={() => setSelectedResidues([])}>
                        Clear
                      </Button>
                    ) : null}
                  </div>
                </CardContent>
              </Card>
            ) : null}

            {/* Directories */}
            <Card className="border-border/60 bg-card/80">
              <CardHeader className="pb-4">
                <div className="flex items-center gap-3">
                  <SectionIcon icon={FolderOpen} />
                  <div>
                    <CardTitle className="font-display text-base">Directories</CardTitle>
                    <CardDescription>Output and environment file locations.</CardDescription>
                  </div>
                </div>
              </CardHeader>
              <CardContent className="space-y-4">
                <div className="space-y-2">
                  <Label htmlFor="result-dir" className="text-xs font-medium text-muted-foreground">Result directory</Label>
                  <div className="flex gap-2">
                    <Input
                      id="result-dir"
                      value={config.result_dir}
                      onChange={(e) => {
                        const next = e.target.value;
                        if (hasUnsafeRelativePath(next)) {
                          setStartError('Result directory cannot contain ".." path traversal sequences.');
                          return;
                        }
                        setStartError(null);
                        setConfig((prev) => ({ ...prev, result_dir: next }));
                      }}
                      className="font-data text-xs"
                    />
                    <Button variant="outline" size="icon" onClick={handleSelectResultDir}>
                      <FolderOpen className="h-4 w-4" />
                    </Button>
                  </div>
                </div>

                <div className="space-y-2">
                  <Label htmlFor="env-dir" className="text-xs font-medium text-muted-foreground">Environment directory</Label>
                  <div className="flex gap-2">
                    <Input
                      id="env-dir"
                      value={config.env_dir}
                      onChange={(e) => {
                        const next = e.target.value;
                        if (hasUnsafeRelativePath(next)) {
                          setStartError('Environment directory cannot contain ".." path traversal sequences.');
                          return;
                        }
                        setStartError(null);
                        setConfig((prev) => ({ ...prev, env_dir: next }));
                      }}
                      className="font-data text-xs"
                    />
                    <Button variant="outline" size="icon" onClick={handleSelectEnvDir}>
                      <FolderOpen className="h-4 w-4" />
                    </Button>
                  </div>
                </div>
              </CardContent>
            </Card>

            {/* Optimization parameters */}
            <Card className="border-border/60 bg-card/80">
              <CardHeader className="pb-4">
                <div className="flex items-center gap-3">
                  <SectionIcon icon={SlidersHorizontal} />
                  <div>
                    <CardTitle className="font-display text-base">Optimization Parameters</CardTitle>
                    <CardDescription>Core sampling controls.</CardDescription>
                  </div>
                </div>
              </CardHeader>
              <CardContent className="field-grid">
                <div className="space-y-2">
                  <Label htmlFor="num-steps" className="text-xs font-medium text-muted-foreground">Steps</Label>
                  <Input
                    id="num-steps"
                    type="number"
                    min={1}
                    max={100000}
                    value={config.num_steps}
                    onChange={(e) =>
                      setConfig((prev) => ({
                        ...prev,
                        num_steps: parseBoundedIntegerInput(e.target.value, prev.num_steps, 1, 100000),
                      }))
                    }
                    className="font-data tabular-nums"
                  />
                </div>

                <div className="space-y-2">
                  <Label htmlFor="samples-per-step" className="text-xs font-medium text-muted-foreground">Samples/step</Label>
                  <Input
                    id="samples-per-step"
                    type="number"
                    min={1}
                    max={100000}
                    value={config.num_sampling_per_step}
                    onChange={(e) =>
                      setConfig((prev) => ({
                        ...prev,
                        num_sampling_per_step: parseBoundedIntegerInput(
                          e.target.value,
                          prev.num_sampling_per_step,
                          1,
                          100000
                        ),
                      }))
                    }
                    className="font-data tabular-nums"
                  />
                </div>

                <div className="space-y-2">
                  <Label htmlFor="max-atoms" className="text-xs font-medium text-muted-foreground">Max atoms</Label>
                  <Input
                    id="max-atoms"
                    type="number"
                    min={1}
                    max={100000}
                    value={config.max_atoms}
                    onChange={(e) =>
                      setConfig((prev) => ({
                        ...prev,
                        max_atoms: parseBoundedIntegerInput(e.target.value, prev.max_atoms, 1, 100000),
                      }))
                    }
                    className="font-data tabular-nums"
                  />
                </div>

                <div className="space-y-2">
                  <Label htmlFor="seed" className="text-xs font-medium text-muted-foreground">Seed</Label>
                  <Input
                    id="seed"
                    type="number"
                    min={0}
                    max={2147483647}
                    value={config.seed}
                    onChange={(e) =>
                      setConfig((prev) => ({
                        ...prev,
                        seed: parseBoundedIntegerInput(e.target.value, prev.seed, 0, 2147483647),
                      }))
                    }
                    className="font-data tabular-nums"
                  />
                </div>
              </CardContent>
            </Card>

            {/* Run controls */}
            <Card className="border-border/60 bg-card/80">
              <CardHeader className="pb-4">
                <div className="flex items-center gap-3">
                  <SectionIcon icon={Zap} />
                  <div>
                    <CardTitle className="font-display text-base">Run Controls</CardTitle>
                    <CardDescription>Launch or stop optimization.</CardDescription>
                  </div>
                </div>
              </CardHeader>
              <CardContent className="space-y-4">
                <div className="flex gap-2">
                  <Button
                    onClick={handleStartRun}
                    disabled={isRunning || isLoading || !config.protein_path}
                    className="flex-1 glow-primary"
                  >
                    {isLoading ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Play className="mr-2 h-4 w-4" />}
                    Start Training
                  </Button>
                  <Button variant="destructive" onClick={handleStopRun} disabled={!isRunning}>
                    <Square className="mr-2 h-4 w-4" />
                    Stop
                  </Button>
                </div>

                {activeRun ? (
                  <div className="space-y-3 rounded-md border border-primary/15 bg-primary/[0.03] p-3 animate-fade-in">
                    <div className="flex items-center justify-between gap-3">
                      <div>
                        <p className="text-sm font-medium">{activeRun.name}</p>
                        <p className="font-data text-[11px] text-muted-foreground tabular-nums">
                          {activeRun.currentStep} of {activeRun.totalSteps} steps
                        </p>
                      </div>
                      <Badge variant={runStatusVariant}>{activeRun.status}</Badge>
                    </div>

                    <div className="space-y-1">
                      <div className="flex justify-between font-data text-[10px] text-muted-foreground">
                        <span>Progress</span>
                        <span className="tabular-nums">
                          {activeRun.currentStep} / {activeRun.totalSteps}
                        </span>
                      </div>
                      <div className="h-1.5 overflow-hidden rounded-full bg-secondary">
                        <div
                          className="h-full rounded-full bg-primary transition-all duration-500"
                          style={{
                            width: `${Math.min(
                              100,
                              activeRun.totalSteps > 0
                                ? (activeRun.currentStep / activeRun.totalSteps) * 100
                                : 0
                            )}%`,
                          }}
                        />
                      </div>
                    </div>

                    {(activeRun.error || startError) ? (
                      <div className="rounded-md border border-destructive/25 bg-destructive/10 px-3 py-2 text-sm text-destructive">
                        {activeRun.error ?? startError}
                      </div>
                    ) : null}

                    <div className="space-y-2">
                      <p className="text-[10px] font-semibold uppercase tracking-[0.15em] text-muted-foreground">
                        Recent Logs
                      </p>
                      <div className="max-h-40 overflow-auto rounded-md border border-border bg-background p-3">
                        <pre className="whitespace-pre-wrap break-words font-data text-[10px] leading-relaxed text-muted-foreground">
                          {runOutput.length > 0 ? runOutput.slice(-60).join('\n') : 'No output yet.'}
                        </pre>
                      </div>
                    </div>
                  </div>
                ) : startError ? (
                  <div className="rounded-md border border-destructive/25 bg-destructive/10 px-3 py-2 text-sm text-destructive">
                    {startError}
                  </div>
                ) : null}
                {validationErrors.length > 0 ? (
                  <div className="rounded-md border border-destructive/25 bg-destructive/10 px-3 py-2 text-sm text-destructive">
                    {validationErrors.join(' | ')}
                  </div>
                ) : null}
              </CardContent>
            </Card>
          </div>
        </ScrollArea>

        {/* Resize handle */}
        <div
          className="absolute right-0 top-0 h-full w-1.5 cursor-col-resize bg-transparent transition-colors hover:bg-primary/20"
          onMouseDown={(event) => {
            event.preventDefault();
            const startX = event.clientX;
            const startPercent = leftPanelWidth;
            const container = (event.currentTarget as HTMLDivElement).parentElement?.parentElement;
            const containerWidth = container?.clientWidth ?? 1;
            const onMove = (moveEvent: MouseEvent) => {
              const deltaPercent = ((moveEvent.clientX - startX) / containerWidth) * 100;
              const nextPercent = startPercent + deltaPercent;
              setLeftPanelWidth(Math.max(30, Math.min(70, nextPercent)));
            };
            const onUp = () => {
              window.removeEventListener('mousemove', onMove);
              window.removeEventListener('mouseup', onUp);
            };
            window.addEventListener('mousemove', onMove);
            window.addEventListener('mouseup', onUp);
          }}
          title="Drag to resize panel"
        >
          <div className="flex h-full items-center justify-center">
            <GripVertical className="h-4 w-4 text-muted-foreground/30" />
          </div>
        </div>
      </div>

      {/* Right panel - 3D Viewer */}
      <div className="flex min-w-0 flex-1 flex-col">
        <div className="border-b border-border bg-card/50 px-5 py-4">
          <div className="flex items-start justify-between gap-4">
            <div>
              <h2 className="font-display text-lg font-semibold">Protein Structure</h2>
              <p className="mt-0.5 text-xs text-muted-foreground">
                {isFlashBindEngine
                  ? 'Preview uploaded protein and reference ligand for FlashBind.'
                  : 'Click residues in the viewer to update the target list.'}
              </p>
            </div>
            <div className="flex items-center gap-2">
              {!isFlashBindEngine ? (
                <Badge variant="outline" className="font-data text-[10px]">{selectedResidues.length} residues</Badge>
              ) : null}
              {config.protein_path ? (
                <Badge variant="secondary" className="max-w-[280px] truncate font-data text-[10px]">
                  {config.protein_path.split('/').pop()}
                </Badge>
              ) : null}
              {config.ref_ligand_path ? (
                <Badge variant="secondary" className="max-w-[240px] truncate font-data text-[10px]">
                  Ligand: {config.ref_ligand_path.split('/').pop()}
                </Badge>
              ) : null}
            </div>
          </div>
        </div>

        <div className="flex-1 bg-background">
          <MolstarViewer
            pdbContent={pdbContent}
            ligandContent={ligandContent}
            ligandLabel={config.ref_ligand_path}
            selectedResidues={isFlashBindEngine ? [] : selectedResidues}
            onResidueSelect={isFlashBindEngine ? () => {} : handleResidueSelect}
            multiSelectMode={!isFlashBindEngine}
          />
        </div>
      </div>
    </div>
  );
}