import { useState, useEffect, useCallback } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { useConvexRuns } from '@/hooks/useConvex';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { ScrollArea } from '@/components/ui/scroll-area';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import { useIpcInvoke } from '@/hooks/useIpc';
import MolstarViewer from '@/components/MolstarViewer';
import MoleculeCard from '@/components/MoleculeCard';
import ReactionPathway from '@/components/ReactionPathway';
import type { RunInfo, MoleculeResult } from '@shared/types';
import { 
  Activity, 
  Clock, 
  Zap, 
  TrendingUp, 
  RefreshCw, 
  Beaker,
  Sparkles,
  BarChart3,
  Atom,
  History,
  ChevronRight,
  PlayCircle,
  CheckCircle2,
  XCircle,
  PauseCircle,
  Circle,
  FolderOpen,
} from 'lucide-react';

interface DashboardProps {
  activeRun: RunInfo | null;
  onRunStatusChange: (run: RunInfo) => void;
}

const kpiVariants = {
  hidden: { opacity: 0, y: 20, scale: 0.95 },
  visible: (i: number) => ({
    opacity: 1,
    y: 0,
    scale: 1,
    transition: {
      delay: i * 0.1,
      duration: 0.4,
      ease: [0.25, 0.1, 0.25, 1],
    },
  }),
};

function KPICard({ 
  title, 
  value, 
  icon: Icon, 
  color,
  index,
  suffix,
  isLoading,
}: { 
  title: string; 
  value: string | number; 
  icon: React.ElementType; 
  color: string;
  index: number;
  suffix?: string;
  isLoading?: boolean;
}) {
  return (
    <motion.div
      variants={kpiVariants}
      initial="hidden"
      animate="visible"
      custom={index}
    >
      <Card className="glass-card card-glow h-full overflow-hidden relative">
        <div className={`absolute inset-0 bg-gradient-to-br ${color} opacity-5`} />
        <CardContent className="pt-5 relative">
          <div className="flex items-start justify-between">
            <div className="space-y-1">
              <p className="text-xs font-medium text-muted-foreground uppercase tracking-wide">{title}</p>
              <div className="flex items-baseline gap-1">
                {isLoading ? (
                  <div className="h-8 w-16 skeleton rounded" />
                ) : (
                  <>
                    <motion.p 
                      className="text-2xl font-bold tabular-nums"
                      key={value}
                      initial={{ opacity: 0, y: 10 }}
                      animate={{ opacity: 1, y: 0 }}
                      transition={{ duration: 0.3 }}
                    >
                      {value}
                    </motion.p>
                    {suffix && (
                      <span className="text-sm text-muted-foreground">{suffix}</span>
                    )}
                  </>
                )}
              </div>
            </div>
            <div className={`p-2 rounded-lg bg-gradient-to-br ${color} bg-opacity-10`}>
              <Icon className="h-5 w-5 text-foreground/70" />
            </div>
          </div>
        </CardContent>
      </Card>
    </motion.div>
  );
}

function getStatusIcon(status: string) {
  switch (status) {
    case 'running':
      return <PlayCircle className="h-4 w-4 text-green-500" />;
    case 'completed':
      return <CheckCircle2 className="h-4 w-4 text-blue-500" />;
    case 'error':
      return <XCircle className="h-4 w-4 text-red-500" />;
    case 'paused':
      return <PauseCircle className="h-4 w-4 text-yellow-500" />;
    default:
      return <Circle className="h-4 w-4 text-gray-400" />;
  }
}

// Type for Convex run
interface ConvexRun {
  _id: string;
  configId: string;
  name: string;
  status: 'idle' | 'running' | 'paused' | 'completed' | 'error';
  currentStep: number;
  totalSteps: number;
  resultDir: string;
  checkpointPath: string | null;
  error: string | null;
  startedAt: number | null;
  completedAt: number | null;
  lastUpdatedAt: number;
}

export default function Dashboard({ activeRun, onRunStatusChange: _onRunStatusChange }: DashboardProps) {
  const invoke = useIpcInvoke();
  
  // Fetch runs from Convex (returns null if Convex is not configured)
  const convexRuns = useConvexRuns();
  
  const [selectedRun, setSelectedRun] = useState<RunInfo | null>(activeRun);
  const [molecules, setMolecules] = useState<MoleculeResult[]>([]);
  const [selectedMolecule, setSelectedMolecule] = useState<MoleculeResult | null>(null);
  const [complexContent, setComplexContent] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(false);

  // Update selected run when activeRun changes
  useEffect(() => {
    if (activeRun) {
      setSelectedRun(activeRun);
    }
  }, [activeRun]);

  // Convert Convex run to RunInfo format
  const convertConvexRun = (run: ConvexRun): RunInfo => ({
    id: run._id,
    name: run.name,
    configPath: '', // Not stored in Convex run, use configId if needed
    resultDir: run.resultDir,
    status: run.status,
    currentStep: run.currentStep,
    totalSteps: run.totalSteps,
    startedAt: run.startedAt ? new Date(run.startedAt).toISOString() : null,
    lastUpdatedAt: run.lastUpdatedAt ? new Date(run.lastUpdatedAt).toISOString() : null,
    checkpointPath: run.checkpointPath,
    error: run.error,
  });

  // Combine local activeRun with Convex runs
  const allRuns: RunInfo[] = [
    ...(activeRun && !convexRuns?.find(r => r._id === activeRun.id) ? [activeRun] : []),
    ...(convexRuns?.map(convertConvexRun) ?? []),
  ];

  useEffect(() => {
    if (!selectedRun?.resultDir) return;

    const fetchMolecules = async () => {
      try {
        const results = await invoke('db:get-top-molecules', selectedRun.resultDir, 50);
        setMolecules(results);
        if (results.length > 0 && !selectedMolecule) {
          setSelectedMolecule(results[0] ?? null);
        }
      } catch (err) {
        console.error('Failed to fetch molecules:', err);
      }
    };

    fetchMolecules();
    const interval = setInterval(fetchMolecules, 5000);

    return () => clearInterval(interval);
  }, [selectedRun?.resultDir, invoke, selectedMolecule]);

  useEffect(() => {
    if (!selectedMolecule || !selectedRun?.resultDir) {
      setComplexContent(null);
      return;
    }

    const loadComplex = async () => {
      const complexPath = await invoke('boltz:get-complex-path', selectedRun.resultDir, 0, 0);
      if (complexPath) {
        const content = await invoke('boltz:read-complex', complexPath);
        setComplexContent(content);
      }
    };

    loadComplex();
  }, [selectedMolecule, selectedRun?.resultDir, invoke]);

  const handleRefresh = useCallback(async () => {
    if (!selectedRun?.resultDir) return;
    setIsLoading(true);
    try {
      const results = await invoke('db:get-top-molecules', selectedRun.resultDir, 50);
      setMolecules(results);
    } finally {
      setIsLoading(false);
    }
  }, [selectedRun?.resultDir, invoke]);

  const handleSelectRun = (run: RunInfo) => {
    setSelectedRun(run);
    setSelectedMolecule(null);
    setMolecules([]);
  };

  const bestAffinity = molecules.length > 0
    ? Math.min(...molecules.filter(m => m.boltzScores).map(m => m.boltzScores!.affinity_ensemble))
    : null;

  const bestProbability = molecules.length > 0
    ? Math.max(...molecules.filter(m => m.boltzScores).map(m => m.boltzScores!.probability_ensemble))
    : null;

  // No runs at all - show empty state
  if (allRuns.length === 0) {
    return (
      <motion.div 
        className="h-full flex items-center justify-center"
        initial={{ opacity: 0, scale: 0.95 }}
        animate={{ opacity: 1, scale: 1 }}
      >
        <div className="text-center space-y-6 max-w-md">
          <motion.div
            animate={{
              y: [0, -10, 0],
            }}
            transition={{
              duration: 2,
              repeat: Infinity,
              ease: 'easeInOut',
            }}
          >
            <Beaker className="h-20 w-20 mx-auto text-muted-foreground/40" />
          </motion.div>
          <div className="space-y-2">
            <h2 className="text-2xl font-semibold">No Runs Yet</h2>
            <p className="text-muted-foreground">
              Start your first training run from the Configuration tab to see results here.
            </p>
          </div>
          <div className="flex items-center justify-center gap-2 text-sm text-muted-foreground">
            <FolderOpen className="h-4 w-4" />
            <span>Your previous runs will appear in this dashboard</span>
          </div>
        </div>
      </motion.div>
    );
  }

  return (
    <div className="h-full flex">
      {/* Left Sidebar: Runs List */}
      <motion.div 
        className="w-64 border-r border-border/50 flex flex-col bg-slate-50/50"
        initial={{ opacity: 0, x: -20 }}
        animate={{ opacity: 1, x: 0 }}
      >
        <div className="p-4 border-b border-border/50">
          <div className="flex items-center gap-2">
            <History className="h-4 w-4 text-primary" />
            <h3 className="font-semibold text-sm">Run History</h3>
          </div>
          <p className="text-xs text-muted-foreground mt-1">
            {allRuns.length} run{allRuns.length !== 1 ? 's' : ''}
          </p>
        </div>
        
        <ScrollArea className="flex-1">
          <div className="p-2 space-y-1">
            {allRuns.map((run, idx) => (
              <motion.button
                key={run.id}
                initial={{ opacity: 0, x: -10 }}
                animate={{ opacity: 1, x: 0 }}
                transition={{ delay: idx * 0.05 }}
                onClick={() => handleSelectRun(run)}
                className={`w-full text-left p-3 rounded-lg transition-all duration-200 ${
                  selectedRun?.id === run.id
                    ? 'bg-primary/10 border border-primary/30'
                    : 'hover:bg-white border border-transparent hover:border-border/50'
                }`}
              >
                <div className="flex items-start justify-between gap-2">
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                      {getStatusIcon(run.status)}
                      <span className="text-sm font-medium truncate">{run.name}</span>
                    </div>
                    <div className="text-xs text-muted-foreground mt-1">
                      Step {run.currentStep}/{run.totalSteps}
                    </div>
                  </div>
                  {selectedRun?.id === run.id && (
                    <ChevronRight className="h-4 w-4 text-primary shrink-0 mt-0.5" />
                  )}
                </div>
              </motion.button>
            ))}
          </div>
        </ScrollArea>
      </motion.div>

      {/* Main Content */}
      {selectedRun ? (
        <div className="flex-1 flex flex-col">
          {/* KPI Header */}
          <motion.div 
            className="p-4 border-b border-border/50 bg-white/80"
            initial={{ opacity: 0, y: -20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.4 }}
          >
            <div className="grid grid-cols-5 gap-3">
              <KPICard
                title="Status"
                value={selectedRun.status}
                icon={Activity}
                color="from-green-500 to-emerald-500"
                index={0}
              />
              <KPICard
                title="Progress"
                value={`${selectedRun.currentStep}/${selectedRun.totalSteps}`}
                icon={Clock}
                color="from-blue-500 to-cyan-500"
                index={1}
              />
              <KPICard
                title="Best Affinity"
                value={bestAffinity?.toFixed(2) ?? 'N/A'}
                icon={Zap}
                color="from-yellow-500 to-orange-500"
                index={2}
              />
              <KPICard
                title="Best Probability"
                value={bestProbability?.toFixed(2) ?? 'N/A'}
                icon={TrendingUp}
                color="from-purple-500 to-pink-500"
                index={3}
              />
              <motion.div
                variants={kpiVariants}
                initial="hidden"
                animate="visible"
                custom={4}
              >
                <Card className="glass-card card-glow h-full overflow-hidden relative">
                  <div className="absolute inset-0 bg-gradient-to-br from-primary to-blue-500 opacity-5" />
                  <CardContent className="pt-5 relative">
                    <div className="flex items-start justify-between">
                      <div className="space-y-1">
                        <p className="text-xs font-medium text-muted-foreground uppercase tracking-wide">Molecules</p>
                        <motion.p 
                          className="text-2xl font-bold tabular-nums"
                          key={molecules.length}
                          initial={{ opacity: 0, y: 10 }}
                          animate={{ opacity: 1, y: 0 }}
                        >
                          {molecules.length}
                        </motion.p>
                      </div>
                      <Button 
                        variant="ghost" 
                        size="icon" 
                        onClick={handleRefresh} 
                        disabled={isLoading}
                        className="hover-lift h-8 w-8"
                      >
                        <RefreshCw className={`h-4 w-4 ${isLoading ? 'animate-spin' : ''}`} />
                      </Button>
                    </div>
                  </CardContent>
                </Card>
              </motion.div>
            </div>
          </motion.div>

          {/* Main Split View */}
          <div className="flex-1 flex overflow-hidden">
            {/* Left: Molecule Details */}
            <motion.div 
              className="w-1/2 border-r border-border/50 flex flex-col"
              initial={{ opacity: 0, x: -20 }}
              animate={{ opacity: 1, x: 0 }}
              transition={{ delay: 0.3 }}
            >
              <div className="p-3 border-b border-border/50 bg-white/80">
                <div className="flex items-center gap-2">
                  <Sparkles className="h-4 w-4 text-primary" />
                  <h3 className="font-semibold text-sm">Selected Molecule</h3>
                </div>
              </div>
              
              <AnimatePresence mode="wait">
                {selectedMolecule ? (
                  <ScrollArea className="flex-1">
                    <motion.div 
                      className="p-4 space-y-4"
                      initial={{ opacity: 0 }}
                      animate={{ opacity: 1 }}
                      exit={{ opacity: 0 }}
                      key={selectedMolecule.smiles}
                    >
                      <MoleculeCard molecule={selectedMolecule} />

                      {selectedMolecule.boltzScores && (
                        <motion.div
                          initial={{ opacity: 0, y: 10 }}
                          animate={{ opacity: 1, y: 0 }}
                          transition={{ delay: 0.1 }}
                        >
                          <Card className="glass-card">
                            <CardHeader className="pb-2">
                              <div className="flex items-center gap-2">
                                <BarChart3 className="h-4 w-4 text-blue-500" />
                                <CardTitle className="text-base">Boltz-2 Scores</CardTitle>
                              </div>
                            </CardHeader>
                            <CardContent>
                              <div className="grid grid-cols-3 gap-3">
                                {[
                                  { label: 'Ensemble', aff: selectedMolecule.boltzScores.affinity_ensemble, prob: selectedMolecule.boltzScores.probability_ensemble },
                                  { label: 'Model 1', aff: selectedMolecule.boltzScores.affinity_model1, prob: selectedMolecule.boltzScores.probability_model1 },
                                  { label: 'Model 2', aff: selectedMolecule.boltzScores.affinity_model2, prob: selectedMolecule.boltzScores.probability_model2 },
                                ].map((item, i) => (
                                  <motion.div
                                    key={item.label}
                                    initial={{ opacity: 0, y: 10 }}
                                    animate={{ opacity: 1, y: 0 }}
                                    transition={{ delay: 0.1 + i * 0.05 }}
                                    className="text-sm p-3 rounded-lg bg-slate-50"
                                  >
                                    <p className="text-xs text-muted-foreground font-medium mb-2">{item.label}</p>
                                    <div className="space-y-1">
                                      <div className="flex justify-between">
                                        <span className="text-muted-foreground">Affinity</span>
                                        <span className="font-mono font-medium">{item.aff.toFixed(3)}</span>
                                      </div>
                                      <div className="flex justify-between">
                                        <span className="text-muted-foreground">Probability</span>
                                        <span className="font-mono font-medium">{item.prob.toFixed(3)}</span>
                                      </div>
                                    </div>
                                  </motion.div>
                                ))}
                              </div>
                            </CardContent>
                          </Card>
                        </motion.div>
                      )}

                      {selectedMolecule.trajectory.length > 0 && (
                        <motion.div
                          initial={{ opacity: 0, y: 10 }}
                          animate={{ opacity: 1, y: 0 }}
                          transition={{ delay: 0.2 }}
                        >
                          <Card className="glass-card">
                            <CardHeader className="pb-2">
                              <div className="flex items-center gap-2">
                                <Atom className="h-4 w-4 text-purple-500" />
                                <CardTitle className="text-base">Reaction Pathway</CardTitle>
                              </div>
                            </CardHeader>
                            <CardContent>
                              <ReactionPathway trajectory={selectedMolecule.trajectory} />
                            </CardContent>
                          </Card>
                        </motion.div>
                      )}
                    </motion.div>
                  </ScrollArea>
                ) : (
                  <motion.div 
                    className="flex-1 flex items-center justify-center"
                    initial={{ opacity: 0 }}
                    animate={{ opacity: 1 }}
                  >
                    <p className="text-muted-foreground text-sm">Select a molecule from the table below</p>
                  </motion.div>
                )}
              </AnimatePresence>
            </motion.div>

            {/* Right: Mol* Viewer */}
            <motion.div 
              className="w-1/2 flex flex-col bg-white"
              initial={{ opacity: 0, x: 20 }}
              animate={{ opacity: 1, x: 0 }}
              transition={{ delay: 0.4 }}
            >
              <div className="p-3 border-b border-border/50 bg-white/80">
                <h3 className="font-semibold text-sm">Protein-Ligand Complex</h3>
                <p className="text-xs text-muted-foreground">
                  Boltz-2 predicted structure
                </p>
              </div>
              <div className="flex-1">
                <MolstarViewer
                  pdbContent={complexContent}
                  selectedResidues={[]}
                  onResidueSelect={() => {}}
                />
              </div>
            </motion.div>
          </div>

          {/* Bottom: Molecule Table */}
          <motion.div 
            className="h-56 border-t border-border/50 bg-white/80"
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.5 }}
          >
            <div className="p-2 border-b border-border/50 flex items-center justify-between">
              <div className="flex items-center gap-2">
                <Beaker className="h-4 w-4 text-primary" />
                <h3 className="font-semibold text-sm">Generated Molecules</h3>
              </div>
              <Badge variant="outline" className="text-xs">
                {molecules.length} total
              </Badge>
            </div>
            <ScrollArea className="h-[calc(100%-40px)]">
              <Table>
                <TableHeader>
                  <TableRow className="hover:bg-transparent">
                    <TableHead className="w-12 text-xs">#</TableHead>
                    <TableHead className="text-xs">SMILES</TableHead>
                    <TableHead className="w-20 text-xs">Reward</TableHead>
                    <TableHead className="w-20 text-xs">Aff</TableHead>
                    <TableHead className="w-20 text-xs">Prob</TableHead>
                    <TableHead className="w-16 text-xs">Steps</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  <AnimatePresence>
                    {molecules.map((mol, idx) => (
                      <motion.tr
                        key={mol.smiles}
                        initial={{ opacity: 0, x: -10 }}
                        animate={{ opacity: 1, x: 0 }}
                        exit={{ opacity: 0, x: 10 }}
                        transition={{ delay: idx * 0.02 }}
                        className={`cursor-pointer transition-colors ${
                          selectedMolecule?.smiles === mol.smiles 
                            ? 'bg-primary/10 hover:bg-primary/15' 
                            : 'hover:bg-slate-50'
                        }`}
                        onClick={() => setSelectedMolecule(mol)}
                      >
                        <TableCell className="font-medium text-sm py-2">{idx + 1}</TableCell>
                        <TableCell className="font-mono text-xs truncate max-w-xs py-2">
                          {mol.smiles}
                        </TableCell>
                        <TableCell className="font-mono text-sm py-2">{mol.reward.toFixed(3)}</TableCell>
                        <TableCell className="font-mono text-sm py-2">
                          {mol.boltzScores?.affinity_ensemble.toFixed(3) ?? 'N/A'}
                        </TableCell>
                        <TableCell className="font-mono text-sm py-2">
                          {mol.boltzScores?.probability_ensemble.toFixed(3) ?? 'N/A'}
                        </TableCell>
                        <TableCell className="text-sm py-2">
                          <Badge variant="secondary" className="text-xs">
                            {mol.trajectory.length}
                          </Badge>
                        </TableCell>
                      </motion.tr>
                    ))}
                  </AnimatePresence>
                </TableBody>
              </Table>
            </ScrollArea>
          </motion.div>
        </div>
      ) : (
        <motion.div 
          className="flex-1 flex items-center justify-center"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
        >
          <div className="text-center space-y-4">
            <ChevronRight className="h-12 w-12 mx-auto text-muted-foreground/40" />
            <p className="text-muted-foreground">Select a run from the sidebar to view details</p>
          </div>
        </motion.div>
      )}
    </div>
  );
}
