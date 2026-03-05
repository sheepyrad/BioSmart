import { useState, useCallback, useEffect, useMemo } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
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
import type { OptConfig, RunInfo, BoltzConfig } from '@shared/types';
import { convexConfigToOpt, optConfigToConvex } from '@/lib/configMapping';
import YAML from 'yaml';
import {
  FolderOpen,
  FileUp,
  Play,
  Square,
  Plus,
  X,
  Save,
  Upload,
  Target,
  Folder,
  Sliders,
  Rocket,
  Loader2,
  CheckCircle2,
  XCircle,
  Cloud,
  Clock,
  GripVertical,
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

const defaultConfig: OptConfig = {
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
};

const normalizeBoltzWorker = (value: unknown): number => {
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) return 1;
  return Math.max(1, Math.floor(parsed));
};

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

const cardVariants = {
  hidden: { opacity: 0, y: 20 },
  visible: (i: number) => ({
    opacity: 1,
    y: 0,
    transition: {
      delay: i * 0.1,
      duration: 0.4,
      ease: [0.25, 0.1, 0.25, 1],
    },
  }),
};

const badgeVariants = {
  initial: { scale: 0, opacity: 0 },
  animate: { scale: 1, opacity: 1 },
  exit: { scale: 0, opacity: 0 },
};

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
  const [selectedResidues, setSelectedResidues] = useState<string[]>([]);
  const [newResidue, setNewResidue] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [startError, setStartError] = useState<string | null>(null);
  const [leftPanelWidth, setLeftPanelWidth] = useState(50);

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
    setConfig((prev) => ({
      ...prev,
      boltz: {
        ...prev.boltz,
        target_residues: selectedResidues,
      },
    }));
  }, [selectedResidues]);

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
        // Protein path may be unavailable in current environment (e.g. cloud path)
      }
    };

    void maybeLoadPdbContent();
    return () => {
      cancelled = true;
    };
  }, [config.protein_path, pdbContent, loadedPdbPath, invoke]);

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

  const highlightedYamlLines = useMemo(() => {
    if (!generatedBoltzYamlResult.yaml) return [];
    return generatedBoltzYamlResult.yaml.split('\n').map((line, index) => {
      const keyValueMatch = line.match(/^(\s*)(-\s*)?([A-Za-z_][A-Za-z0-9_-]*):(.*)$/);
      if (keyValueMatch) {
        const indent = keyValueMatch[1] ?? '';
        const listPrefix = keyValueMatch[2] ?? '';
        const prefix = `${indent}${listPrefix}`;
        const key = keyValueMatch[3];
        const rawValue = keyValueMatch[4] ?? '';
        const hasValue = rawValue.trim().length > 0;
        const keyClass =
          key === 'id' || key === 'sequence' || key === 'msa'
            ? 'text-violet-700 dark:text-violet-400'
            : 'text-blue-700 dark:text-blue-400';
        return (
          <span key={`yaml-line-${index}`} className="block">
            <span className="text-muted-foreground">{prefix}</span>
            <span className={keyClass}>{key}</span>
            <span className="text-muted-foreground">:</span>
            {hasValue ? (
              <>
                <span> </span>
                <span className="text-orange-700 dark:text-orange-400">{rawValue.trimStart()}</span>
              </>
            ) : null}
          </span>
        );
      }

      const looksLikeSequenceContinuation = /^\s*[A-Z]+\s*$/.test(line);
      return (
        <span
          key={`yaml-line-${index}`} 
          className={`block ${looksLikeSequenceContinuation ? 'text-orange-700 dark:text-orange-400' : ''}`}
        >
          {line.length > 0 ? line : ' '}
        </span>
      );
    });
  }, [generatedBoltzYamlResult.yaml]);

  const handleLoadConfig = useCallback(async () => {
    setIsLoading(true);
    try {
      const path = await invoke('file:select-yaml');
      if (path) {
        const loadedConfig = await invoke('file:read-yaml', path);
        const normalizedConfig: OptConfig = {
          ...loadedConfig,
          boltz: {
            ...loadedConfig.boltz,
            worker: normalizeBoltzWorker(
              (loadedConfig.boltz as unknown as { worker?: unknown; boltz_worker?: unknown })?.worker ??
                (loadedConfig.boltz as unknown as { worker?: unknown; boltz_worker?: unknown })?.boltz_worker
            ),
          },
        };
        setConfig(normalizedConfig);
        setConfigPath(path);
        setSelectedResidues(normalizedConfig.boltz.target_residues);
        setSavedConfigId(null);
      }
    } finally {
      setIsLoading(false);
    }
  }, [invoke]);

  // File selection handlers - return path for FileSelector
  const handleSelectPdb = useCallback(async (): Promise<string | null> => {
    setIsLoading(true);
    try {
      const path = await invoke('file:select-pdb');
      if (path) {
        // Also load the PDB content for the viewer
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

  const handleSelectResultDir = useCallback(async () => {
    const path = await invoke('file:select-directory');
    if (path) {
      setConfig((prev) => ({ ...prev, result_dir: path }));
    }
  }, [invoke]);

  const handleSelectEnvDir = useCallback(async () => {
    const path = await invoke('file:select-directory');
    if (path) {
      setConfig((prev) => ({ ...prev, env_dir: path }));
    }
  }, [invoke]);

  const handleResidueSelect = useCallback((residues: string[]) => {
    setSelectedResidues(residues);
  }, []);

  const handleAddResidue = useCallback(() => {
    if (newResidue && !selectedResidues.includes(newResidue)) {
      setSelectedResidues((prev) => [...prev, newResidue]);
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
        boltz: {
          ...loaded.boltz,
          worker: normalizeBoltzWorker(
            (loaded.boltz as unknown as { worker?: unknown; boltz_worker?: unknown })?.worker ??
              (loaded.boltz as unknown as { worker?: unknown; boltz_worker?: unknown })?.boltz_worker
          ),
        },
      };
      setConfig(normalizedLoaded);
      setConfigName(convexConfig.name);
      setSavedConfigId(convexConfig._id);
      setConfigPath(null);
      setSelectedResidues(normalizedLoaded.boltz.target_residues);
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
    setIsLoading(true);
    setStartError(null);
    try {
      if (savedConfigId && isConvexAvailable) {
        await updateConfig(savedConfigId as any, { lastUsedAt: Date.now() });
      }
      const runInfo = await invoke('run:start', {
        config,
        configPath,
        configId: savedConfigId,
        name: configName.trim() || undefined,
      });
      onRunStarted(runInfo);
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Failed to start run.';
      setStartError(message);
    } finally {
      setIsLoading(false);
    }
  }, [invoke, config, configPath, onRunStarted, savedConfigId, isConvexAvailable, updateConfig, configName]);

  const handleStopRun = useCallback(async () => {
    if (activeRun) {
      await invoke('run:stop', activeRun.id);
    }
  }, [invoke, activeRun]);

  const isRunning = activeRun?.status === 'running';

  return (
    <div className="h-full flex">
      {/* Left: Config Form */}
      <div className="relative border-r border-border/50 shrink-0" style={{ width: `${leftPanelWidth}%` }}>
        <ScrollArea className="h-full">
          <div className="p-6 space-y-5">
            {/* Load/Save Config */}
            <motion.div
              variants={cardVariants}
              initial="hidden"
              animate="visible"
              custom={0}
            >
              <Card className="glass-card card-glow overflow-hidden">
                <CardHeader className="pb-3">
                  <div className="flex items-center gap-2">
                    <div className="p-2 rounded-lg bg-primary/10">
                      <Upload className="h-4 w-4 text-primary" />
                    </div>
                    <div>
                      <CardTitle className="text-base">Configuration</CardTitle>
                      <CardDescription className="text-xs">Load or create optimization config</CardDescription>
                    </div>
                  </div>
                </CardHeader>
                <CardContent className="space-y-4">
                  <div className="flex gap-2">
                    <Button 
                      variant="outline" 
                      onClick={handleLoadConfig}
                      disabled={isLoading}
                      className="flex-1 hover-lift"
                    >
                      {isLoading ? (
                        <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                      ) : (
                        <FolderOpen className="mr-2 h-4 w-4" />
                      )}
                      Load Config
                    </Button>
                    <Button 
                      variant="outline" 
                      onClick={handleSaveConfig}
                      className="flex-1 hover-lift"
                    >
                      <Save className="mr-2 h-4 w-4" />
                      Save Config
                    </Button>
                  </div>
                  <div className="space-y-2">
                    <Label className="text-xs font-medium text-muted-foreground uppercase tracking-wide">
                      Config Name
                    </Label>
                    <Input
                      value={configName}
                      onChange={(e) => setConfigName(e.target.value)}
                      placeholder="Name this configuration"
                      className="bg-white"
                    />
                  </div>
                  {isConvexAvailable && (
                    <div className="space-y-2">
                      <div className="flex gap-2">
                        <Button
                          variant="default"
                          onClick={handleSaveToConvex}
                          disabled={isLoading}
                          className="flex-1 hover-lift"
                        >
                          <Cloud className="mr-2 h-4 w-4" />
                          Save to Cloud
                        </Button>
                        <Button
                          variant="outline"
                          onClick={handleLoadLastUsed}
                          className="flex-1 hover-lift"
                          disabled={!configs || configs.length === 0}
                        >
                          <Clock className="mr-2 h-4 w-4" />
                          Load Last Used
                        </Button>
                      </div>
                      {configs && configs.length > 0 && (
                        <div className="rounded-lg border border-border bg-muted/30 p-2 space-y-2">
                          <p className="text-xs text-muted-foreground">Recent configs</p>
                          <div className="space-y-1 max-h-32 overflow-auto">
                            {configs.map((cfg) => (
                              <button
                                key={cfg._id}
                                onClick={() => handleLoadConvexConfig(cfg)}
                                className={`w-full text-left text-xs px-2 py-1 rounded hover:bg-white transition-colors ${
                                  savedConfigId === cfg._id ? 'bg-white border border-primary/30' : ''
                                }`}
                              >
                                <span className="font-medium">{cfg.name}</span>
                                {cfg.lastUsedAt && (
                                  <span className="text-muted-foreground ml-2">
                                    {new Date(cfg.lastUsedAt).toLocaleDateString()}
                                  </span>
                                )}
                              </button>
                            ))}
                          </div>
                        </div>
                      )}
                    </div>
                  )}
                  <AnimatePresence>
                    {configPath && (
                      <motion.p 
                        initial={{ opacity: 0, height: 0 }}
                        animate={{ opacity: 1, height: 'auto' }}
                        exit={{ opacity: 0, height: 0 }}
                        className="text-xs text-muted-foreground truncate px-2 py-1 rounded bg-muted/50"
                      >
                        {configPath}
                      </motion.p>
                    )}
                  </AnimatePresence>
                </CardContent>
              </Card>
            </motion.div>

            {/* Files */}
            <motion.div
              variants={cardVariants}
              initial="hidden"
              animate="visible"
              custom={1}
            >
              <Card className="glass-card card-glow">
                <CardHeader className="pb-3">
                  <div className="flex items-center gap-2">
                    <div className="p-2 rounded-lg bg-blue-500/10">
                      <FileUp className="h-4 w-4 text-blue-500" />
                    </div>
                    <CardTitle className="text-base">Input Files</CardTitle>
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

                  <p className="text-xs text-muted-foreground">
                    Boltz base YAML is auto-generated from the selected protein PDB at run start.
                  </p>

                  <div className="space-y-2">
                    <Label className="text-xs font-medium text-muted-foreground uppercase tracking-wide">
                      Generated Boltz YAML Preview
                    </Label>
                    <div className="rounded-md border bg-muted/20 p-3">
                      {generatedBoltzYamlResult.error ? (
                        <p className="text-xs text-destructive">{generatedBoltzYamlResult.error}</p>
                      ) : generatedBoltzYamlResult.yaml ? (
                        <pre className="max-h-48 overflow-auto rounded bg-background/50 p-2 text-xs leading-relaxed">
                          <code className="block whitespace-pre-wrap break-all font-mono">{highlightedYamlLines}</code>
                        </pre>
                      ) : (
                        <p className="text-xs text-muted-foreground">
                          Upload/select a protein PDB to preview the generated YAML.
                        </p>
                      )}
                    </div>
                  </div>

                  <FileSelector
                    label="MSA Path"
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

                  <div className="space-y-2">
                    <Label className="text-xs font-medium text-muted-foreground uppercase tracking-wide">
                      Boltz Workers
                    </Label>
                    <Input
                      type="number"
                      min={1}
                      value={config.boltz.worker}
                      onChange={(e) =>
                        setConfig((prev) => ({
                          ...prev,
                          boltz: {
                            ...prev.boltz,
                            worker: normalizeBoltzWorker(e.target.value),
                          },
                        }))
                      }
                      className="bg-background/50 tabular-nums"
                    />
                  </div>
                </CardContent>
              </Card>
            </motion.div>

            {/* Target Residues */}
            <motion.div
              variants={cardVariants}
              initial="hidden"
              animate="visible"
              custom={2}
            >
              <Card className="glass-card card-glow">
                <CardHeader className="pb-3">
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      <div className="p-2 rounded-lg bg-green-500/10">
                        <Target className="h-4 w-4 text-green-500" />
                      </div>
                      <div>
                        <CardTitle className="text-base">Target Residues</CardTitle>
                        <CardDescription className="text-xs">
                          Click residues in viewer to toggle
                        </CardDescription>
                      </div>
                    </div>
                    <AnimatePresence>
                      {selectedResidues.length > 0 && (
                        <motion.div
                          variants={badgeVariants}
                          initial="initial"
                          animate="animate"
                          exit="exit"
                        >
                          <Badge variant="secondary" className="bg-green-500/10 text-green-500 border-green-500/20">
                            {selectedResidues.length} selected
                          </Badge>
                        </motion.div>
                      )}
                    </AnimatePresence>
                  </div>
                </CardHeader>
                <CardContent className="space-y-4">
                  <AnimatePresence mode="popLayout">
                    {selectedResidues.length > 0 ? (
                      <motion.div 
                        className="flex flex-wrap gap-2"
                        layout
                      >
                        {selectedResidues.map((residue) => (
                          <motion.div
                            key={residue}
                            layout
                            variants={badgeVariants}
                            initial="initial"
                            animate="animate"
                            exit="exit"
                          >
                            <Badge variant="secondary" className="gap-1 pr-1 hover:bg-secondary/80 transition-colors">
                              {residue}
                              <button
                                onClick={() => handleRemoveResidue(residue)}
                                className="ml-1 p-0.5 rounded-full hover:bg-destructive/20 hover:text-destructive transition-colors"
                              >
                                <X className="h-3 w-3" />
                              </button>
                            </Badge>
                          </motion.div>
                        ))}
                      </motion.div>
                    ) : (
                      <motion.p 
                        initial={{ opacity: 0 }}
                        animate={{ opacity: 1 }}
                        className="text-sm text-muted-foreground italic text-center py-4 border border-dashed rounded-lg"
                      >
                        Click on protein structure to select binding site
                      </motion.p>
                    )}
                  </AnimatePresence>
                  <div className="flex gap-2">
                    <Input
                      value={newResidue}
                      onChange={(e) => setNewResidue(e.target.value)}
                      placeholder="A:123"
                      onKeyDown={(e) => e.key === 'Enter' && handleAddResidue()}
                      className="bg-white"
                    />
                    <Button variant="outline" size="icon" onClick={handleAddResidue} className="shrink-0 hover-lift">
                      <Plus className="h-4 w-4" />
                    </Button>
                    {selectedResidues.length > 0 && (
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => setSelectedResidues([])}
                        className="text-muted-foreground hover:text-destructive"
                      >
                        Clear
                      </Button>
                    )}
                  </div>
                </CardContent>
              </Card>
            </motion.div>

            {/* Directories */}
            <motion.div
              variants={cardVariants}
              initial="hidden"
              animate="visible"
              custom={3}
            >
              <Card className="glass-card card-glow">
                <CardHeader className="pb-3">
                  <div className="flex items-center gap-2">
                    <div className="p-2 rounded-lg bg-orange-500/10">
                      <Folder className="h-4 w-4 text-orange-500" />
                    </div>
                    <CardTitle className="text-base">Directories</CardTitle>
                  </div>
                </CardHeader>
                <CardContent className="space-y-4">
                  <div className="space-y-2">
                    <Label className="text-xs font-medium text-muted-foreground uppercase tracking-wide">Result Directory</Label>
                    <div className="flex gap-2">
                      <Input
                        value={config.result_dir}
                        onChange={(e) =>
                          setConfig((prev) => ({ ...prev, result_dir: e.target.value }))
                        }
                        className="bg-white"
                      />
                      <Button variant="outline" size="icon" onClick={handleSelectResultDir} className="shrink-0 hover-lift">
                        <FolderOpen className="h-4 w-4" />
                      </Button>
                    </div>
                  </div>

                  <div className="space-y-2">
                    <Label className="text-xs font-medium text-muted-foreground uppercase tracking-wide">Environment Directory</Label>
                    <div className="flex gap-2">
                      <Input
                        value={config.env_dir}
                        onChange={(e) =>
                          setConfig((prev) => ({ ...prev, env_dir: e.target.value }))
                        }
                        className="bg-white"
                      />
                      <Button variant="outline" size="icon" onClick={handleSelectEnvDir} className="shrink-0 hover-lift">
                        <FolderOpen className="h-4 w-4" />
                      </Button>
                    </div>
                  </div>
                </CardContent>
              </Card>
            </motion.div>

            {/* Optimization Parameters */}
            <motion.div
              variants={cardVariants}
              initial="hidden"
              animate="visible"
              custom={4}
            >
              <Card className="glass-card card-glow">
                <CardHeader className="pb-3">
                  <div className="flex items-center gap-2">
                    <div className="p-2 rounded-lg bg-purple-500/10">
                      <Sliders className="h-4 w-4 text-purple-500" />
                    </div>
                    <CardTitle className="text-base">Optimization Parameters</CardTitle>
                  </div>
                </CardHeader>
                <CardContent className="space-y-4">
                  <div className="grid grid-cols-2 gap-4">
                    <div className="space-y-2">
                      <Label className="text-xs font-medium text-muted-foreground uppercase tracking-wide">Steps</Label>
                      <Input
                        type="number"
                        value={config.num_steps}
                        onChange={(e) =>
                          setConfig((prev) => ({ ...prev, num_steps: parseInt(e.target.value) || 0 }))
                        }
                        className="bg-background/50 tabular-nums"
                      />
                    </div>
                    <div className="space-y-2">
                      <Label className="text-xs font-medium text-muted-foreground uppercase tracking-wide">Samples/Step</Label>
                      <Input
                        type="number"
                        value={config.num_sampling_per_step}
                        onChange={(e) =>
                          setConfig((prev) => ({
                            ...prev,
                            num_sampling_per_step: parseInt(e.target.value) || 0,
                          }))
                        }
                        className="bg-background/50 tabular-nums"
                      />
                    </div>
                    <div className="space-y-2">
                      <Label className="text-xs font-medium text-muted-foreground uppercase tracking-wide">Max Atoms</Label>
                      <Input
                        type="number"
                        value={config.max_atoms}
                        onChange={(e) =>
                          setConfig((prev) => ({ ...prev, max_atoms: parseInt(e.target.value) || 0 }))
                        }
                        className="bg-background/50 tabular-nums"
                      />
                    </div>
                    <div className="space-y-2">
                      <Label className="text-xs font-medium text-muted-foreground uppercase tracking-wide">Seed</Label>
                      <Input
                        type="number"
                        value={config.seed}
                        onChange={(e) =>
                          setConfig((prev) => ({ ...prev, seed: parseInt(e.target.value) || 0 }))
                        }
                        className="bg-background/50 tabular-nums"
                      />
                    </div>
                  </div>

                </CardContent>
              </Card>
            </motion.div>

            {/* Run Controls */}
            <motion.div
              variants={cardVariants}
              initial="hidden"
              animate="visible"
              custom={5}
            >
              <Card className={`glass-card overflow-hidden ${isRunning ? 'animated-border' : 'card-glow'}`}>
                <CardHeader className="pb-3">
                  <div className="flex items-center gap-2">
                    <div className={`p-2 rounded-lg ${isRunning ? 'bg-green-500/20' : 'bg-primary/10'}`}>
                      <Rocket className={`h-4 w-4 ${isRunning ? 'text-green-500' : 'text-primary'}`} />
                    </div>
                    <CardTitle className="text-base">Run Controls</CardTitle>
                  </div>
                </CardHeader>
                <CardContent className="space-y-4">
                  <div className="flex gap-2">
                    <Button
                      onClick={handleStartRun}
                      disabled={isRunning || isLoading || !config.protein_path}
                      className="flex-1 bg-gradient-to-r from-primary to-blue-600 hover:from-primary/90 hover:to-blue-600/90 shadow-lg shadow-primary/25 transition-all duration-300"
                    >
                      {isLoading ? (
                        <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                      ) : (
                        <Play className="mr-2 h-4 w-4" />
                      )}
                      Start Training
                    </Button>
                    <Button
                      variant="destructive"
                      onClick={handleStopRun}
                      disabled={!isRunning}
                      className="hover-lift"
                    >
                      <Square className="mr-2 h-4 w-4" />
                      Stop
                    </Button>
                  </div>
                  
                  <AnimatePresence>
                    {activeRun && (
                      <motion.div
                        initial={{ opacity: 0, height: 0 }}
                        animate={{ opacity: 1, height: 'auto' }}
                        exit={{ opacity: 0, height: 0 }}
                        className="rounded-lg bg-muted/30 p-4 space-y-3"
                      >
                        <div className="flex items-center justify-between">
                          <span className="text-sm text-muted-foreground">Status</span>
                          <Badge
                            className={`${
                              activeRun.status === 'running'
                                ? 'bg-green-500/20 text-green-500 border-green-500/30'
                                : activeRun.status === 'completed'
                                ? 'bg-blue-500/20 text-blue-500 border-blue-500/30'
                                : activeRun.status === 'error'
                                ? 'bg-red-500/20 text-red-500 border-red-500/30'
                                : 'bg-yellow-500/20 text-yellow-500 border-yellow-500/30'
                            }`}
                          >
                            {activeRun.status === 'running' && (
                              <Loader2 className="mr-1 h-3 w-3 animate-spin" />
                            )}
                            {activeRun.status === 'completed' && (
                              <CheckCircle2 className="mr-1 h-3 w-3" />
                            )}
                            {activeRun.status === 'error' && (
                              <XCircle className="mr-1 h-3 w-3" />
                            )}
                            {activeRun.status}
                          </Badge>
                        </div>
                        
                        <div className="space-y-1">
                          <div className="flex justify-between text-sm">
                            <span className="text-muted-foreground">Progress</span>
                            <span className="font-mono">{activeRun.currentStep} / {activeRun.totalSteps}</span>
                          </div>
                          <div className="h-2 bg-background rounded-full overflow-hidden">
                            <motion.div
                              className="h-full bg-gradient-to-r from-primary to-blue-500"
                              initial={{ width: 0 }}
                              animate={{ 
                                width: `${(activeRun.currentStep / activeRun.totalSteps) * 100}%` 
                              }}
                              transition={{ duration: 0.5 }}
                            />
                          </div>
                        </div>

                        {(activeRun.error || startError) && (
                          <div className="rounded-md border border-destructive/30 bg-destructive/10 p-2">
                            <p className="text-xs text-destructive break-words">
                              {activeRun.error ?? startError}
                            </p>
                          </div>
                        )}

                        <div className="space-y-1">
                          <span className="text-xs text-muted-foreground uppercase tracking-wide">
                            Recent Logs
                          </span>
                          <div className="max-h-40 overflow-auto rounded-md border bg-background/40 p-2">
                            <pre className="whitespace-pre-wrap break-words text-[11px] leading-relaxed text-muted-foreground">
                              {runOutput.length > 0
                                ? runOutput.slice(-60).join('\n')
                                : 'No output yet.'}
                            </pre>
                          </div>
                        </div>
                      </motion.div>
                    )}
                  </AnimatePresence>
                </CardContent>
              </Card>
            </motion.div>
          </div>
        </ScrollArea>
        <div
          className="absolute top-0 right-0 h-full w-2 cursor-col-resize bg-transparent hover:bg-primary/20 transition-colors"
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
          <div className="h-full flex items-center justify-center">
            <GripVertical className="h-4 w-4 text-muted-foreground/50" />
          </div>
        </div>
      </div>

      {/* Right: Mol* Viewer */}
      <div className="flex-1 min-w-0 flex flex-col bg-white">
        <motion.div 
          className="p-4 border-b border-border/50 glass"
          initial={{ opacity: 0, y: -10 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.3 }}
        >
          <div className="flex items-center justify-between">
            <div>
              <h2 className="font-semibold">Protein Structure</h2>
              <p className="text-xs text-muted-foreground">
                Click to select/deselect binding site residues
              </p>
            </div>
            <AnimatePresence>
              {selectedResidues.length > 0 && (
                <motion.div
                  variants={badgeVariants}
                  initial="initial"
                  animate="animate"
                  exit="exit"
                >
                  <Badge className="bg-green-500/20 text-green-500 border-green-500/30">
                    {selectedResidues.length} residues
                  </Badge>
                </motion.div>
              )}
            </AnimatePresence>
          </div>
        </motion.div>
        <motion.div 
          className="flex-1"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ delay: 0.4 }}
        >
          <MolstarViewer
            pdbContent={pdbContent}
            selectedResidues={selectedResidues}
            onResidueSelect={handleResidueSelect}
            multiSelectMode={true}
          />
        </motion.div>
      </div>
    </div>
  );
}
