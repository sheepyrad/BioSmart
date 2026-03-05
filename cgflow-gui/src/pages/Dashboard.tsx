import { useState, useEffect, useCallback, useMemo } from 'react';
import { useQuery } from 'convex/react';
import { api } from '../../convex/_generated/api';
import { motion, AnimatePresence } from 'framer-motion';
import { useConvexRuns, useConvexAvailable } from '@/hooks/useConvex';
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
import BoltzMetricsPanel from '@/components/BoltzMetricsPanel';
import { computeBoltzMetrics } from '@shared/boltzMetrics';
import type { BoltzMetricInputRow, BoltzMetricSeries, RunInfo, MoleculeResult } from '@shared/types';
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
  GripVertical,
  FileText,
  Trash2,
  Square,
} from 'lucide-react';

interface DashboardProps {
  activeRun: RunInfo | null;
  onRunStatusChange: (run: RunInfo) => void;
}

const DASHBOARD_MOLECULE_LIMIT = 5000;
const TABLE_PAGE_SIZE = 50;
const LOG_TAIL_LINES = 200;

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
  const isConvexAvailable = useConvexAvailable();
  const [runnerRuns, setRunnerRuns] = useState<RunInfo[]>([]);
  
  const [selectedRun, setSelectedRun] = useState<RunInfo | null>(activeRun);
  const [molecules, setMolecules] = useState<MoleculeResult[]>([]);
  const [selectedMolecule, setSelectedMolecule] = useState<MoleculeResult | null>(null);
  const [complexContent, setComplexContent] = useState<string | null>(null);
  const [localBoltzMetrics, setLocalBoltzMetrics] = useState<BoltzMetricSeries | null>(null);
  const [isBoltzMetricsLoading, setIsBoltzMetricsLoading] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const [isLogLoading, setIsLogLoading] = useState(false);
  const [tablePage, setTablePage] = useState(1);
  const [sidebarWidth, setSidebarWidth] = useState(280);
  const [runLogLines, setRunLogLines] = useState<string[]>([]);

  const convexMoleculeRows = useQuery(
    api.molecules.getByRun,
    isConvexAvailable && selectedRun?.source === 'convex'
      ? { runId: selectedRun.id as any, orderBy: 'reward' }
      : 'skip'
  );

  const convexMetricRows = useQuery(
    api.molecules.getByRun,
    isConvexAvailable && selectedRun?.source === 'convex'
      ? { runId: selectedRun.id as any, orderBy: 'iteration' }
      : 'skip'
  );

  const mappedConvexMolecules = useMemo<MoleculeResult[]>(() => {
    if (!convexMoleculeRows) return [];
    return convexMoleculeRows.map((row: any) => {
      let trajectory: any[] = [];
      try {
        trajectory = row.trajectory ? JSON.parse(row.trajectory) : [];
      } catch {
        trajectory = [];
      }
      const hasScores =
        row.affinityEnsemble !== null ||
        row.probabilityEnsemble !== null ||
        row.affinityModel1 !== null ||
        row.probabilityModel1 !== null ||
        row.affinityModel2 !== null ||
        row.probabilityModel2 !== null;

      return {
        smiles: row.smiles,
        reward: row.reward,
        trajectory,
        boltzScores: hasScores
          ? {
              iteration: row.iteration ?? 0,
              smiles: row.smiles,
              docking_score: 0,
              affinity_ensemble: row.affinityEnsemble ?? 0,
              probability_ensemble: row.probabilityEnsemble ?? 0,
              affinity_model1: row.affinityModel1 ?? 0,
              probability_model1: row.probabilityModel1 ?? 0,
              affinity_model2: row.affinityModel2 ?? 0,
              probability_model2: row.probabilityModel2 ?? 0,
            }
          : null,
        complexPath: null,
        oracleIdx: row.oracleIdx ?? null,
        molIdx: row.molIdx ?? null,
      } as MoleculeResult;
    });
  }, [convexMoleculeRows]);

  const convexMetricInputRows = useMemo<BoltzMetricInputRow[]>(() => {
    if (!convexMetricRows) return [];
    return convexMetricRows.map((row: any) => ({
      iteration: row.iteration ?? 0,
      smiles: row.smiles,
      affinityModel1: row.affinityModel1 ?? null,
      probabilityModel1: row.probabilityModel1 ?? null,
    }));
  }, [convexMetricRows]);

  const convexBoltzMetrics = useMemo<BoltzMetricSeries | null>(() => {
    if (convexMetricInputRows.length === 0) return null;
    return computeBoltzMetrics(convexMetricInputRows);
  }, [convexMetricInputRows]);

  const activeBoltzMetrics = selectedRun?.source === 'convex' ? convexBoltzMetrics : localBoltzMetrics;

  // Update selected run when activeRun changes
  useEffect(() => {
    if (activeRun) {
      setSelectedRun(activeRun);
    }
  }, [activeRun]);

  // Fetch local runner runs
  useEffect(() => {
    let mounted = true;

    const fetchRuns = async () => {
      try {
        const runs = await invoke('run:list');
        if (!mounted) return;
        setRunnerRuns((runs ?? []).map((run) => ({ ...run, source: 'local' })));
      } catch {
        if (!mounted) return;
        setRunnerRuns([]);
      }
    };

    fetchRuns();
    const interval = setInterval(fetchRuns, 5000);

    return () => {
      mounted = false;
      clearInterval(interval);
    };
  }, [invoke]);

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
    source: 'convex',
  });

  // Combine local runner runs with Convex runs (dedupe by convexRunId)
  const localRuns = [
    ...runnerRuns,
    ...(activeRun && !runnerRuns.find((r) => r.id === activeRun.id) ? [activeRun] : []),
  ].map((run) => ({ ...run, source: 'local' as const }));

  const convexRunList = convexRuns?.map(convertConvexRun) ?? [];
  const localConvexIds = new Set(
    localRuns.map((r) => r.convexRunId).filter((id): id is string => Boolean(id))
  );

  const allRuns: RunInfo[] = [
    ...localRuns,
    ...convexRunList.filter((run) => !localConvexIds.has(run.id)),
  ];

  useEffect(() => {
    if (!selectedRun) return;

    if (selectedRun.source === 'convex') {
      setMolecules(mappedConvexMolecules);
      if (mappedConvexMolecules.length > 0 && !selectedMolecule) {
        setSelectedMolecule(mappedConvexMolecules[0] ?? null);
      }
      return;
    }

    const fetchMolecules = async () => {
      try {
        const results = await invoke('db:get-top-molecules', selectedRun.id, DASHBOARD_MOLECULE_LIMIT);
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
  }, [selectedRun, invoke, selectedMolecule, mappedConvexMolecules]);

  useEffect(() => {
    if (!selectedRun) {
      setLocalBoltzMetrics(null);
      return;
    }

    if (selectedRun.source === 'convex') {
      setLocalBoltzMetrics(null);
      return;
    }

    let isMounted = true;
    setIsBoltzMetricsLoading(true);
    invoke('run:get-boltz-metrics', selectedRun.id)
      .then((metrics) => {
        if (!isMounted) return;
        setLocalBoltzMetrics(metrics);
      })
      .catch(() => {
        if (!isMounted) return;
        setLocalBoltzMetrics(null);
      })
      .finally(() => {
        if (!isMounted) return;
        setIsBoltzMetricsLoading(false);
      });

    return () => {
      isMounted = false;
    };
  }, [selectedRun, invoke]);

  useEffect(() => {
    if (!selectedMolecule || !selectedRun) {
      setComplexContent(null);
      return;
    }

    if (selectedRun.source === 'convex') {
      setComplexContent(null);
      return;
    }

    const oracleIdx = selectedMolecule.oracleIdx;
    const molIdx = selectedMolecule.molIdx;
    if (oracleIdx == null || molIdx == null) {
      setComplexContent(null);
      return;
    }

    const loadComplex = async () => {
      try {
        const content = await invoke('boltz:get-complex', selectedRun.id, oracleIdx, molIdx);
        setComplexContent(content);
      } catch {
        setComplexContent(null);
      }
    };

    loadComplex();
  }, [selectedMolecule, selectedRun, invoke]);

  useEffect(() => {
    if (!selectedRun) {
      setRunLogLines([]);
      return;
    }

    if (selectedRun.source === 'convex') {
      setRunLogLines([]);
      return;
    }

    let isMounted = true;
    const fetchLogs = async () => {
      setIsLogLoading(true);
      try {
        const lines = await invoke('run:get-output', selectedRun.id, LOG_TAIL_LINES);
        if (!isMounted) return;
        setRunLogLines(lines);
      } catch {
        if (!isMounted) return;
        setRunLogLines([]);
      } finally {
        if (isMounted) {
          setIsLogLoading(false);
        }
      }
    };

    void fetchLogs();
    const interval = setInterval(fetchLogs, 4000);
    return () => {
      isMounted = false;
      clearInterval(interval);
    };
  }, [selectedRun, invoke]);

  const handleRefresh = useCallback(async () => {
    if (!selectedRun) return;
    setIsLoading(true);
    try {
      if (selectedRun.source === 'convex') {
        setMolecules(mappedConvexMolecules);
        return;
      }
      const results = await invoke('db:get-top-molecules', selectedRun.id, DASHBOARD_MOLECULE_LIMIT);
      setMolecules(results);
      const metrics = await invoke('run:get-boltz-metrics', selectedRun.id);
      setLocalBoltzMetrics(metrics);
      const logs = await invoke('run:get-output', selectedRun.id, LOG_TAIL_LINES);
      setRunLogLines(logs);
    } finally {
      setIsLoading(false);
    }
  }, [selectedRun, invoke, mappedConvexMolecules]);

  const handleSelectRun = (run: RunInfo) => {
    setSelectedRun(run);
    setSelectedMolecule(null);
    setMolecules([]);
    setTablePage(1);
  };

  const handleStopRun = useCallback(async (run: RunInfo) => {
    if (run.source !== 'local' || run.status !== 'running') return;
    try {
      await invoke('run:stop', run.id);
    } catch (err) {
      console.error('Failed to stop run:', err);
    }
  }, [invoke]);

  const handleDeleteRun = useCallback(async (run: RunInfo) => {
    if (run.source !== 'local') return;
    if (run.status === 'running') {
      window.alert('Stop this run before deleting it.');
      return;
    }
    const confirmed = window.confirm(`Delete "${run.name}" from run history?`);
    if (!confirmed) return;

    try {
      await invoke('run:delete', run.id);
      setRunnerRuns((prev) => prev.filter((item) => item.id !== run.id));
      setSelectedRun((prev) => (prev?.id === run.id ? null : prev));
      setSelectedMolecule(null);
      setMolecules([]);
    } catch (err) {
      console.error('Failed to delete run:', err);
      window.alert(err instanceof Error ? err.message : 'Failed to delete run.');
    }
  }, [invoke]);

  const handleImportRun = useCallback(async () => {
    try {
      const dir = await invoke('file:select-directory');
      if (!dir) return;
      const importedRun = await invoke('run:import-existing', dir, null);
      setSelectedRun(importedRun);
      setSelectedMolecule(null);
      setMolecules([]);
      setTablePage(1);
    } catch (err) {
      console.error('Failed to import run:', err);
    }
  }, [invoke]);

  useEffect(() => {
    setTablePage(1);
  }, [selectedRun?.id]);

  const totalPages = Math.max(1, Math.ceil(molecules.length / TABLE_PAGE_SIZE));
  const safePage = Math.min(tablePage, totalPages);
  const pageStart = (safePage - 1) * TABLE_PAGE_SIZE;
  const pageEnd = Math.min(pageStart + TABLE_PAGE_SIZE, molecules.length);
  const pagedMolecules = useMemo(
    () => molecules.slice(pageStart, pageEnd),
    [molecules, pageStart, pageEnd]
  );

  useEffect(() => {
    if (tablePage !== safePage) {
      setTablePage(safePage);
    }
  }, [tablePage, safePage]);

  const affinityValues = molecules
    .filter((m) => m.boltzScores)
    .map((m) => m.boltzScores!.affinity_ensemble);
  const probabilityValues = molecules
    .filter((m) => m.boltzScores)
    .map((m) => m.boltzScores!.probability_ensemble);

  const bestAffinity = affinityValues.length > 0 ? Math.min(...affinityValues) : null;
  const bestProbability = probabilityValues.length > 0 ? Math.max(...probabilityValues) : null;

  // No runs at all - show empty state
  if (allRuns.length === 0) {
    return (
      <motion.div
        className="w-full p-6"
        initial={{ opacity: 0, scale: 0.97 }}
        animate={{ opacity: 1, scale: 1 }}
      >
        <div className="mx-auto w-full max-w-lg pt-8">
        <Card className="glass-card card-glow w-full">
          <CardHeader className="pb-2">
            <div className="flex items-center gap-2">
              <Beaker className="h-5 w-5 text-primary" />
              <CardTitle className="text-base">No runs found</CardTitle>
            </div>
          </CardHeader>
          <CardContent className="pt-2 space-y-3">
            <p className="text-sm text-muted-foreground">
              There are no previous runs yet. Start your first training run from the Configuration tab.
            </p>
            <div className="flex items-center gap-2 text-xs text-muted-foreground">
              <FolderOpen className="h-4 w-4" />
              <span>Completed runs will appear here automatically.</span>
            </div>
            <Button variant="outline" className="w-full gap-2" onClick={handleImportRun}>
              <FolderOpen className="h-4 w-4" />
              Import Existing Run Directory
            </Button>
          </CardContent>
        </Card>
        </div>
      </motion.div>
    );
  }

  return (
    <div className="min-h-full flex">
      {/* Left Sidebar: Runs List */}
      <motion.div 
        className="shrink-0 border-r border-border/50 flex flex-col bg-slate-50/50 relative"
        style={{ width: sidebarWidth }}
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
          <Button
            variant="outline"
            size="sm"
            className="mt-3 w-full justify-start gap-2"
            onClick={handleImportRun}
          >
            <FolderOpen className="h-3.5 w-3.5" />
            Import Existing Run
          </Button>
        </div>
        
        <ScrollArea className="flex-1">
          <div className="p-2 space-y-1">
            {allRuns.map((run, idx) => (
              <motion.div
                key={run.id}
                initial={{ opacity: 0, x: -10 }}
                animate={{ opacity: 1, x: 0 }}
                transition={{ delay: idx * 0.05 }}
                className={`w-full text-left p-3 rounded-lg transition-all duration-200 ${
                  selectedRun?.id === run.id
                    ? 'bg-primary/10 border border-primary/30'
                    : 'hover:bg-white border border-transparent hover:border-border/50'
                }`}
              >
                <div className="flex items-start justify-between gap-2">
                  <div className="flex-1 min-w-0">
                    <button className="w-full text-left" onClick={() => handleSelectRun(run)}>
                      <div className="flex items-center gap-2">
                        {getStatusIcon(run.status)}
                        <span className="text-sm font-medium truncate">{run.name}</span>
                      </div>
                      <div className="text-xs text-muted-foreground mt-1">
                        Step {run.currentStep}/{run.totalSteps}
                      </div>
                    </button>
                  </div>
                  <div className="flex items-center gap-1 shrink-0">
                    {run.source === 'local' && run.status === 'running' && (
                      <Button
                        variant="ghost"
                        size="icon"
                        className="h-7 w-7"
                        title="Stop run"
                        onClick={(event) => {
                          event.stopPropagation();
                          void handleStopRun(run);
                        }}
                      >
                        <Square className="h-3.5 w-3.5 text-amber-600" />
                      </Button>
                    )}
                    {run.source === 'local' && run.status !== 'running' && (
                      <Button
                        variant="ghost"
                        size="icon"
                        className="h-7 w-7"
                        title="Delete run from history"
                        onClick={(event) => {
                          event.stopPropagation();
                          void handleDeleteRun(run);
                        }}
                      >
                        <Trash2 className="h-3.5 w-3.5 text-red-600" />
                      </Button>
                    )}
                    {selectedRun?.id === run.id && (
                      <ChevronRight className="h-4 w-4 text-primary shrink-0 mt-0.5" />
                    )}
                  </div>
                </div>
              </motion.div>
            ))}
          </div>
        </ScrollArea>
        <div
          className="absolute top-0 right-0 h-full w-2 cursor-col-resize bg-transparent hover:bg-primary/20 transition-colors"
          onMouseDown={(event) => {
            event.preventDefault();
            const startX = event.clientX;
            const startWidth = sidebarWidth;
            const onMove = (moveEvent: MouseEvent) => {
              const nextWidth = startWidth + (moveEvent.clientX - startX);
              setSidebarWidth(Math.max(220, Math.min(480, nextWidth)));
            };
            const onUp = () => {
              window.removeEventListener('mousemove', onMove);
              window.removeEventListener('mouseup', onUp);
            };
            window.addEventListener('mousemove', onMove);
            window.addEventListener('mouseup', onUp);
          }}
          title="Drag to resize sidebar"
        >
          <div className="h-full flex items-center justify-center">
            <GripVertical className="h-4 w-4 text-muted-foreground/50" />
          </div>
        </div>
      </motion.div>

      {/* Main Content */}
      {selectedRun ? (
        <div className="flex-1 min-h-0 flex flex-col">
          {/* KPI Header */}
          <motion.div 
            className="shrink-0 p-4 border-b border-border/50 bg-white/80"
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

          <motion.div
            className="shrink-0 px-4 py-3 border-b border-border/50 bg-white/70"
            initial={{ opacity: 0, y: -8 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.3 }}
          >
            <BoltzMetricsPanel
              metrics={activeBoltzMetrics}
              isLoading={selectedRun.source === 'convex' ? convexMetricRows === undefined : isBoltzMetricsLoading}
            />
          </motion.div>

          <motion.div
            className="shrink-0 px-4 py-3 border-b border-border/50 bg-white/70"
            initial={{ opacity: 0, y: -8 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.3 }}
          >
            <Card className="glass-card">
              <CardHeader className="pb-2">
                <div className="flex items-center gap-2">
                  <FileText className="h-4 w-4 text-primary" />
                  <CardTitle className="text-base">Run Logs (Last {LOG_TAIL_LINES} Lines)</CardTitle>
                </div>
              </CardHeader>
              <CardContent>
                {selectedRun.source === 'convex' ? (
                  <p className="text-xs text-muted-foreground">Logs are only available for local runner runs.</p>
                ) : (
                  <div className="max-h-52 overflow-auto rounded-md border bg-background/40 p-2">
                    <pre className="whitespace-pre-wrap break-words text-[11px] leading-relaxed text-muted-foreground">
                      {runLogLines.length > 0
                        ? runLogLines.join('\n')
                        : isLogLoading
                        ? 'Loading logs...'
                        : 'No log output yet.'}
                    </pre>
                  </div>
                )}
              </CardContent>
            </Card>
          </motion.div>

          {/* Main Split View */}
          <div className="flex-1 min-h-0 flex overflow-hidden">
            {/* Left: Molecule Details */}
            <motion.div 
              className="w-1/2 min-h-0 border-r border-border/50 flex flex-col"
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
              className="w-1/2 min-h-0 flex flex-col bg-white"
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
            className="shrink-0 border-t border-border/50 bg-white/80"
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.5 }}
          >
            <div className="p-2 border-b border-border/50 flex items-center justify-between">
              <div className="flex items-center gap-2">
                <Beaker className="h-4 w-4 text-primary" />
                <h3 className="font-semibold text-sm">Generated Molecules</h3>
              </div>
              <div className="flex items-center gap-2">
                <Badge variant="outline" className="text-xs">
                  {molecules.length} total
                </Badge>
                <Badge variant="outline" className="text-xs">
                  Showing {molecules.length === 0 ? 0 : pageStart + 1}-{pageEnd}
                </Badge>
                <Badge variant="secondary" className="text-xs">
                  Page {safePage}/{totalPages}
                </Badge>
                <Button
                  variant="outline"
                  size="sm"
                  className="h-7 px-2 text-xs"
                  onClick={() => setTablePage((p) => Math.max(1, p - 1))}
                  disabled={safePage <= 1}
                >
                  Prev
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  className="h-7 px-2 text-xs"
                  onClick={() => setTablePage((p) => Math.min(totalPages, p + 1))}
                  disabled={safePage >= totalPages}
                >
                  Next
                </Button>
              </div>
            </div>
            <div className="overflow-x-auto">
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
                    {pagedMolecules.map((mol, idx) => (
                      <motion.tr
                        key={mol.smiles}
                        initial={{ opacity: 0, x: -10 }}
                        animate={{ opacity: 1, x: 0 }}
                        exit={{ opacity: 0, x: 10 }}
                        transition={{ delay: idx * 0.01 }}
                        className={`cursor-pointer transition-colors ${
                          selectedMolecule?.smiles === mol.smiles 
                            ? 'bg-primary/10 hover:bg-primary/15' 
                            : 'hover:bg-slate-50'
                        }`}
                        onClick={() => setSelectedMolecule(mol)}
                      >
                        <TableCell className="font-medium text-sm py-2">{pageStart + idx + 1}</TableCell>
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
            </div>
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
