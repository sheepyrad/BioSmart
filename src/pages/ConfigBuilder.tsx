import { useState, useCallback, useEffect } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Separator } from '@/components/ui/separator';
import { ScrollArea } from '@/components/ui/scroll-area';
import { Badge } from '@/components/ui/badge';
import { useIpcInvoke } from '@/hooks/useIpc';
import MolstarViewer from '@/components/MolstarViewer';
import type { OptConfig, RunInfo, BoltzConfig } from '@shared/types';
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
  const [config, setConfig] = useState<OptConfig>(defaultConfig);
  const [configPath, setConfigPath] = useState<string | null>(null);
  const [pdbContent, setPdbContent] = useState<string | null>(null);
  const [selectedResidues, setSelectedResidues] = useState<string[]>([]);
  const [newResidue, setNewResidue] = useState('');
  const [isLoading, setIsLoading] = useState(false);

  useEffect(() => {
    onConfigChange(config);
  }, [config, onConfigChange]);

  useEffect(() => {
    setConfig((prev) => ({
      ...prev,
      boltz: {
        ...prev.boltz,
        target_residues: selectedResidues,
      },
    }));
  }, [selectedResidues]);

  const handleLoadConfig = useCallback(async () => {
    setIsLoading(true);
    try {
      const path = await invoke('file:select-yaml');
      if (path) {
        const loadedConfig = await invoke('file:read-yaml', path);
        setConfig(loadedConfig);
        setConfigPath(path);
        setSelectedResidues(loadedConfig.boltz.target_residues);
      }
    } finally {
      setIsLoading(false);
    }
  }, [invoke]);

  const handleSelectPdb = useCallback(async () => {
    setIsLoading(true);
    try {
      const path = await invoke('file:select-pdb');
      if (path) {
        const content = await invoke('file:read-pdb', path);
        setPdbContent(content);
        setConfig((prev) => ({ ...prev, protein_path: path }));
      }
    } finally {
      setIsLoading(false);
    }
  }, [invoke]);

  const handleSelectBoltzYaml = useCallback(async () => {
    const path = await invoke('file:select-yaml');
    if (path) {
      setConfig((prev) => ({
        ...prev,
        boltz: { ...prev.boltz, base_yaml: path },
      }));
    }
  }, [invoke]);

  const handleSelectMsa = useCallback(async () => {
    const path = await invoke('file:select-yaml');
    if (path) {
      setConfig((prev) => ({
        ...prev,
        boltz: { ...prev.boltz, msa_path: path },
      }));
    }
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

  const handleStartRun = useCallback(async () => {
    setIsLoading(true);
    try {
      if (!configPath) {
        const path = `./configs/opt/generated_${Date.now()}.yaml`;
        await invoke('file:write-yaml', path, config);
        setConfigPath(path);
      }
      const runInfo = await invoke('run:start', config, configPath!);
      onRunStarted(runInfo);
    } finally {
      setIsLoading(false);
    }
  }, [invoke, config, configPath, onRunStarted]);

  const handleStopRun = useCallback(async () => {
    if (activeRun) {
      await invoke('run:stop', activeRun.id);
    }
  }, [invoke, activeRun]);

  const isRunning = activeRun?.status === 'running';

  return (
    <div className="h-full flex">
      {/* Left: Config Form */}
      <div className="w-1/2 border-r border-border/50">
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
                  <div className="space-y-2">
                    <Label className="text-xs font-medium text-muted-foreground uppercase tracking-wide">Protein PDB</Label>
                    <div className="flex gap-2">
                      <Input
                        value={config.protein_path}
                        onChange={(e) =>
                          setConfig((prev) => ({ ...prev, protein_path: e.target.value }))
                        }
                        placeholder="Path to protein .pdb file"
                        className="bg-white"
                      />
                      <Button variant="outline" size="icon" onClick={handleSelectPdb} className="shrink-0 hover-lift">
                        <FileUp className="h-4 w-4" />
                      </Button>
                    </div>
                  </div>

                  <div className="space-y-2">
                    <Label className="text-xs font-medium text-muted-foreground uppercase tracking-wide">Boltz Base YAML</Label>
                    <div className="flex gap-2">
                      <Input
                        value={config.boltz.base_yaml}
                        onChange={(e) =>
                          setConfig((prev) => ({
                            ...prev,
                            boltz: { ...prev.boltz, base_yaml: e.target.value },
                          }))
                        }
                        placeholder="Path to Boltz base.yaml"
                        className="bg-white"
                      />
                      <Button variant="outline" size="icon" onClick={handleSelectBoltzYaml} className="shrink-0 hover-lift">
                        <FileUp className="h-4 w-4" />
                      </Button>
                    </div>
                  </div>

                  <div className="space-y-2">
                    <Label className="text-xs font-medium text-muted-foreground uppercase tracking-wide">MSA Path (optional)</Label>
                    <div className="flex gap-2">
                      <Input
                        value={config.boltz.msa_path ?? ''}
                        onChange={(e) =>
                          setConfig((prev) => ({
                            ...prev,
                            boltz: { ...prev.boltz, msa_path: e.target.value || null },
                          }))
                        }
                        placeholder="Path to MSA file"
                        className="bg-white"
                      />
                      <Button variant="outline" size="icon" onClick={handleSelectMsa} className="shrink-0 hover-lift">
                        <FileUp className="h-4 w-4" />
                      </Button>
                    </div>
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

                  <Separator className="bg-border/50" />

                  <div className="grid grid-cols-2 gap-4">
                    <div className="space-y-2">
                      <Label className="text-xs font-medium text-muted-foreground uppercase tracking-wide">Temp Min</Label>
                      <Input
                        type="number"
                        value={config.temperature[0]}
                        onChange={(e) =>
                          setConfig((prev) => ({
                            ...prev,
                            temperature: [parseInt(e.target.value) || 1, prev.temperature[1]],
                          }))
                        }
                        className="bg-background/50 tabular-nums"
                      />
                    </div>
                    <div className="space-y-2">
                      <Label className="text-xs font-medium text-muted-foreground uppercase tracking-wide">Temp Max</Label>
                      <Input
                        type="number"
                        value={config.temperature[1]}
                        onChange={(e) =>
                          setConfig((prev) => ({
                            ...prev,
                            temperature: [prev.temperature[0], parseInt(e.target.value) || 64],
                          }))
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
                      disabled={isRunning || isLoading || !config.protein_path || !config.boltz.base_yaml}
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
                      </motion.div>
                    )}
                  </AnimatePresence>
                </CardContent>
              </Card>
            </motion.div>
          </div>
        </ScrollArea>
      </div>

      {/* Right: Mol* Viewer */}
      <div className="w-1/2 flex flex-col bg-white">
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
