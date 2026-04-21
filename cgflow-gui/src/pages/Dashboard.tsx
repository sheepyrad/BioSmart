import { useState, useEffect, useCallback, useMemo, type PointerEvent as ReactPointerEvent } from 'react';
import { z } from 'zod';
import { useQuery } from 'convex/react';
import { api } from '../../convex/_generated/api';
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
import ParallelCoordinatesPanel from '@/components/ParallelCoordinatesPanel';
import SmilesCell from '@/components/SmilesCell';
import { computeBoltzMetrics } from '@shared/boltzMetrics';
import type { BoltzMetricInputRow, BoltzMetricSeries, RunInfo, MoleculeResult } from '@shared/types';
import {
  Atom,
  Beaker,
  CheckCircle2,
  Circle,
  CloudUpload,
  FileText,
  FolderOpen,
  History,
  PauseCircle,
  PlayCircle,
  RefreshCw,
  Square,
  Trash2,
  XCircle,
  FlaskConical,
  TrendingUp,
  Layers,
} from 'lucide-react';

interface DashboardProps {
  activeRun: RunInfo | null;
  onRunStatusChange: (run: RunInfo) => void;
}

const DASHBOARD_MOLECULE_LIMIT = 5000;
const TABLE_PAGE_SIZE = 50;
const SIDEBAR_MIN_WIDTH = 220;
const SIDEBAR_MAX_WIDTH = 520;
const SIDEBAR_DEFAULT_WIDTH = 256;
const HIDDEN_RUN_IDS_KEY = 'cgflow.hiddenRunIds';
const LOG_TAIL_LINES = 200;
const HiddenRunIdsSchema = z.array(z.string());

function getStatusIcon(status: string) {
  switch (status) {
    case 'running':
      return <PlayCircle className="h-4 w-4 text-primary" />;
    case 'completed':
      return <CheckCircle2 className="h-4 w-4 text-blue-400" />;
    case 'error':
      return <XCircle className="h-4 w-4 text-destructive" />;
    case 'paused':
      return <PauseCircle className="h-4 w-4 text-accent" />;
    default:
      return <Circle className="h-4 w-4 text-muted-foreground" />;
  }
}

function getRunOrigin(run: RunInfo): 'Cloud' | 'Synced' | 'Local' {
  if (run.source === 'convex') return 'Cloud';
  if (run.convexRunId) return 'Synced';
  return 'Local';
}

function computeBoltzScore(affinity: number, probability: number): number {
  return ((-affinity + 2) / 4) * probability;
}

function fmtBoltz(v: number | null | undefined): string {
  if (v == null || Number.isNaN(v)) return 'N/A';
  return v.toFixed(3);
}

function getStatusBadgeVariant(status: RunInfo['status']) {
  switch (status) {
    case 'running':
      return 'success';
    case 'error':
      return 'destructive';
    case 'paused':
      return 'warning';
    default:
      return 'secondary';
  }
}

function MetricTile({
  label,
  value,
  icon: Icon,
}: {
  label: string;
  value: React.ReactNode;
  icon?: React.ElementType;
}) {
  return (
    <div className="rounded-md border border-border bg-secondary/20 px-3 py-3">
      <div className="flex items-center gap-2">
        {Icon && <Icon className="h-3 w-3 text-muted-foreground" />}
        <p className="text-[10px] font-semibold uppercase tracking-[0.15em] text-muted-foreground">{label}</p>
      </div>
      <div className="mt-1 font-data text-base font-medium tabular-nums">{value}</div>
    </div>
  );
}

interface ConvexRun {
  _id: string;
  configId: string;
  name: string;
  engine: 'boltz' | 'flashbind';
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
  const [isSyncingCloud, setIsSyncingCloud] = useState(false);
  const [deletingRunId, setDeletingRunId] = useState<string | null>(null);
  const [isLogLoading, setIsLogLoading] = useState(false);
  const [tablePage, setTablePage] = useState(1);
  const [plotFilteredSmiles, setPlotFilteredSmiles] = useState<Set<string> | null>(null);
  const [sidebarWidth, setSidebarWidth] = useState(SIDEBAR_DEFAULT_WIDTH);
  const [isResizingSidebar, setIsResizingSidebar] = useState(false);
  const [runLogLines, setRunLogLines] = useState<string[]>([]);
  const [hiddenRunIds, setHiddenRunIds] = useState<Set<string>>(() => {
    if (typeof window === 'undefined') return new Set();
    try {
      const raw = window.localStorage.getItem(HIDDEN_RUN_IDS_KEY);
      if (!raw) return new Set();
      const parsed = HiddenRunIdsSchema.safeParse(JSON.parse(raw));
      if (!parsed.success) {
        return new Set();
      }
      return new Set(parsed.data);
    } catch {
      return new Set();
    }
  });

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
        normalizedScores:
          row.normalizedAffinity !== null ||
          row.normalizedProbability !== null ||
          row.normalizedScore !== null
            ? {
                affinity: row.normalizedAffinity ?? 0,
                probability: row.normalizedProbability ?? 0,
                score: row.normalizedScore ?? row.reward,
              }
            : undefined,
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
        engine: row.engine ?? selectedRun?.engine ?? 'boltz',
        oracleIdx: row.oracleIdx ?? null,
        molIdx: row.molIdx ?? null,
      } as MoleculeResult;
    });
  }, [convexMoleculeRows, selectedRun?.engine]);

  const convexMetricInputRows = useMemo<BoltzMetricInputRow[]>(() => {
    if (!convexMetricRows) return [];
    return convexMetricRows.map((row: any) => ({
      iteration: row.iteration ?? 0,
      smiles: row.smiles,
      affinityModel1: row.affinityModel1 ?? row.normalizedAffinity ?? null,
      probabilityModel1: row.probabilityModel1 ?? row.normalizedProbability ?? null,
    }));
  }, [convexMetricRows]);

  const convexBoltzMetrics = useMemo<BoltzMetricSeries | null>(() => {
    if (convexMetricInputRows.length === 0) return null;
    return computeBoltzMetrics(convexMetricInputRows);
  }, [convexMetricInputRows]);

  const activeBoltzMetrics = selectedRun?.source === 'convex' ? convexBoltzMetrics : localBoltzMetrics;

  useEffect(() => {
    if (activeRun) {
      setSelectedRun(activeRun);
    }
  }, [activeRun]);

  const persistHiddenRunIds = useCallback((next: Set<string>) => {
    if (typeof window === 'undefined') return;
    try {
      window.localStorage.setItem(HIDDEN_RUN_IDS_KEY, JSON.stringify(Array.from(next)));
    } catch {
      // Ignore storage errors.
    }
  }, []);

  const hideRunFromSidebar = useCallback(
    (runId: string) => {
      setHiddenRunIds((prev) => {
        const next = new Set(prev);
        next.add(runId);
        persistHiddenRunIds(next);
        return next;
      });
      setRunnerRuns((prev) => prev.filter((run) => run.id !== runId));
      if (selectedRun?.id === runId) {
        setSelectedRun(null);
        setSelectedMolecule(null);
        setMolecules([]);
        setPlotFilteredSmiles(null);
        setTablePage(1);
      }
    },
    [persistHiddenRunIds, selectedRun]
  );

  useEffect(() => {
    let mounted = true;

    const fetchRuns = async () => {
      try {
        const runs = await invoke('run:list');
        if (!mounted) return;
        setRunnerRuns(
          (runs ?? [])
            .map((run) => ({ ...run, source: 'local' as const }))
            .filter((run) => !hiddenRunIds.has(run.id))
        );
      } catch {
        if (!mounted) return;
        setRunnerRuns([]);
      }
    };

    void fetchRuns();
    const interval = setInterval(fetchRuns, 5000);

    return () => {
      mounted = false;
      clearInterval(interval);
    };
  }, [hiddenRunIds, invoke]);

  const convertConvexRun = (run: ConvexRun): RunInfo => ({
    id: run._id,
    name: run.name,
    configPath: '',
    resultDir: run.resultDir,
    status: run.status,
    currentStep: run.currentStep,
    totalSteps: run.totalSteps,
    startedAt: run.startedAt ? new Date(run.startedAt).toISOString() : null,
    lastUpdatedAt: run.lastUpdatedAt ? new Date(run.lastUpdatedAt).toISOString() : null,
    checkpointPath: run.checkpointPath,
    error: run.error,
  engine: run.engine,
    source: 'convex',
  });

  const localRuns = [
    ...runnerRuns.filter((run) => !hiddenRunIds.has(run.id)),
    ...(activeRun && !hiddenRunIds.has(activeRun.id) && !runnerRuns.find((run) => run.id === activeRun.id)
      ? [activeRun]
      : []),
  ].map((run) => ({ ...run, source: 'local' as const }));

  const convexRunList = convexRuns?.map(convertConvexRun) ?? [];
  const localConvexIds = new Set(
    localRuns.map((run) => run.convexRunId).filter((id): id is string => Boolean(id))
  );

  const allRuns: RunInfo[] = [
    ...localRuns,
    ...convexRunList.filter((run) => !localConvexIds.has(run.id)),
  ];
  const selectedEngine = selectedRun?.engine ?? 'boltz';
  const selectedEngineLabel = selectedEngine === 'flashbind' ? 'FlashBind' : 'Boltz';

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

    void fetchMolecules();
    const interval = setInterval(fetchMolecules, 5000);
    return () => clearInterval(interval);
  }, [invoke, mappedConvexMolecules, selectedMolecule, selectedRun]);

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
  }, [invoke, selectedRun]);

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

    void loadComplex();
  }, [invoke, selectedMolecule, selectedRun]);

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
  }, [invoke, selectedRun]);

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
  }, [invoke, mappedConvexMolecules, selectedRun]);

  const handleSelectRun = useCallback((run: RunInfo) => {
    setSelectedRun(run);
    setSelectedMolecule(null);
    setMolecules([]);
      setPlotFilteredSmiles(null);
    setTablePage(1);
  }, []);

  const handleStopRun = useCallback(async (run: RunInfo) => {
    if (run.source !== 'local' || run.status !== 'running') return;
    try {
      await invoke('run:stop', run.id);
    } catch (err) {
      console.error('Failed to stop run:', err);
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
      setPlotFilteredSmiles(null);
      setTablePage(1);
    } catch (err) {
      console.error('Failed to import run:', err);
    }
  }, [invoke]);

  const handleSyncSelectedRunToCloud = useCallback(async () => {
    if (!selectedRun || selectedRun.source === 'convex') return;
    setIsSyncingCloud(true);
    try {
      const synced = await invoke('run:sync-to-cloud', selectedRun.id);
      setSelectedRun(synced);
      setRunnerRuns((prev) => prev.map((run) => (run.id === synced.id ? { ...synced, source: 'local' } : run)));
    } catch (err) {
      console.error('Failed to sync run to cloud:', err);
    } finally {
      setIsSyncingCloud(false);
    }
  }, [invoke, selectedRun]);

  const handleDeleteRun = useCallback(async (run: RunInfo) => {
    if (run.source === 'convex') return;
    if (run.status === 'running') {
      window.alert('Stop this run before deleting it.');
      return;
    }
    const confirmed = window.confirm(`Delete run "${run.name}" from sidebar history?`);
    if (!confirmed) return;

    setDeletingRunId(run.id);
    try {
      await invoke('run:delete', run.id);
      hideRunFromSidebar(run.id);
    } catch (err) {
      console.error('Failed to delete run:', err);
      window.alert(err instanceof Error ? err.message : 'Failed to delete run.');
    } finally {
      setDeletingRunId(null);
    }
  }, [hideRunFromSidebar, invoke]);

  const startSidebarResize = useCallback((event: ReactPointerEvent<HTMLDivElement>) => {
    event.preventDefault();
    setIsResizingSidebar(true);
    const startX = event.clientX;
    const startWidth = sidebarWidth;

    const onMove = (moveEvent: PointerEvent) => {
      const deltaX = moveEvent.clientX - startX;
      const nextWidth = Math.min(SIDEBAR_MAX_WIDTH, Math.max(SIDEBAR_MIN_WIDTH, startWidth + deltaX));
      setSidebarWidth(nextWidth);
    };

    const onUp = () => {
      setIsResizingSidebar(false);
      window.removeEventListener('pointermove', onMove);
      window.removeEventListener('pointerup', onUp);
    };

    window.addEventListener('pointermove', onMove);
    window.addEventListener('pointerup', onUp, { once: true });
  }, [sidebarWidth]);

  useEffect(() => {
    if (!isResizingSidebar) return;
    const previousCursor = document.body.style.cursor;
    const previousUserSelect = document.body.style.userSelect;
    document.body.style.cursor = 'col-resize';
    document.body.style.userSelect = 'none';
    return () => {
      document.body.style.cursor = previousCursor;
      document.body.style.userSelect = previousUserSelect;
    };
  }, [isResizingSidebar]);

  useEffect(() => {
    setTablePage(1);
    setPlotFilteredSmiles(null);
  }, [selectedRun?.id]);

  const displayedMolecules = useMemo(
    () => (plotFilteredSmiles ? molecules.filter((molecule) => plotFilteredSmiles.has(molecule.smiles)) : molecules),
    [molecules, plotFilteredSmiles]
  );

  const totalPages = Math.max(1, Math.ceil(displayedMolecules.length / TABLE_PAGE_SIZE));
  const safePage = Math.min(tablePage, totalPages);
  const pageStart = (safePage - 1) * TABLE_PAGE_SIZE;
  const pageEnd = Math.min(pageStart + TABLE_PAGE_SIZE, displayedMolecules.length);
  const pagedMolecules = useMemo(
    () => displayedMolecules.slice(pageStart, pageEnd),
    [displayedMolecules, pageStart, pageEnd]
  );

  useEffect(() => {
    if (tablePage !== safePage) {
      setTablePage(safePage);
    }
  }, [safePage, tablePage]);

  useEffect(() => {
    if (!selectedMolecule) return;
    if (displayedMolecules.some((molecule) => molecule.smiles === selectedMolecule.smiles)) return;
    setSelectedMolecule(displayedMolecules[0] ?? null);
  }, [displayedMolecules, selectedMolecule]);

  const affinityValues = molecules
    .filter((molecule) => molecule.boltzScores)
    .map((molecule) => molecule.boltzScores!.affinity_ensemble);
  const probabilityValues = molecules
    .filter((molecule) => molecule.boltzScores)
    .map((molecule) => molecule.boltzScores!.probability_ensemble);

  const bestAffinity = affinityValues.length > 0 ? Math.min(...affinityValues) : null;
  const bestProbability = probabilityValues.length > 0 ? Math.max(...probabilityValues) : null;

  if (allRuns.length === 0) {
    return (
      <div className="flex h-full w-full items-center justify-center p-6">
        <div className="mx-auto w-full max-w-md">
          <Card className="border-border/60 bg-card/80">
            <CardHeader className="pb-3">
              <div className="flex items-center gap-3">
                <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-primary/10">
                  <FlaskConical className="h-5 w-5 text-primary" />
                </div>
                <CardTitle className="font-display text-lg">No Runs Found</CardTitle>
              </div>
            </CardHeader>
            <CardContent className="space-y-4 pt-2">
              <p className="text-sm text-muted-foreground">
                Start a run from Configuration, or import an existing result directory.
              </p>
              <Button variant="outline" className="w-full gap-2" onClick={handleImportRun}>
                <FolderOpen className="h-4 w-4" />
                Import Existing Run
              </Button>
            </CardContent>
          </Card>
        </div>
      </div>
    );
  }

  return (
    <div className="flex min-h-full">
      {/* Run History Sidebar */}
      <div className="flex shrink-0 flex-col border-r border-border bg-card/50" style={{ width: sidebarWidth }}>
        <div className="border-b border-border p-4">
          <div className="flex items-center gap-2">
            <History className="h-4 w-4 text-primary" />
            <h3 className="font-display text-sm font-semibold">Run History</h3>
          </div>
          <p className="mt-1 font-data text-[10px] text-muted-foreground tabular-nums">
            {allRuns.length} run{allRuns.length !== 1 ? 's' : ''}
          </p>
          <Button
            variant="outline"
            size="sm"
            className="mt-3 w-full justify-start gap-2"
            onClick={handleImportRun}
          >
            <FolderOpen className="h-3.5 w-3.5" />
            Import Run
          </Button>
          <Button
            variant="outline"
            size="sm"
            className="mt-2 w-full justify-start gap-2"
            onClick={handleSyncSelectedRunToCloud}
            disabled={!selectedRun || selectedRun.source === 'convex' || isSyncingCloud}
          >
            <CloudUpload className="h-3.5 w-3.5" />
            {isSyncingCloud ? 'Syncing...' : 'Sync to Cloud'}
          </Button>
        </div>

        <ScrollArea className="flex-1">
          <div className="space-y-1 p-2">
            {allRuns.map((run) => (
              <div
                key={run.id}
                onClick={() => handleSelectRun(run)}
                className={`w-full cursor-pointer rounded-md border p-3 text-left transition-all ${
                  selectedRun?.id === run.id
                    ? 'border-primary/30 bg-primary/5 glow-subtle'
                    : 'border-transparent hover:border-border hover:bg-secondary/30'
                }`}
              >
                <div className="flex items-start justify-between gap-2">
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2">
                      {getStatusIcon(run.status)}
                      <span className="truncate text-sm font-medium">{run.name}</span>
                    </div>
                    <div className="mt-1.5 flex items-center gap-2">
                      <Badge variant="outline" className="h-5 px-1.5 font-data text-[9px] font-medium">
                        {getRunOrigin(run)}
                      </Badge>
                      <span className="font-data text-[10px] text-muted-foreground tabular-nums">
                        {run.currentStep}/{run.totalSteps}
                      </span>
                    </div>
                  </div>
                  <div className="mt-0.5 flex shrink-0 items-center gap-1">
                    {run.source === 'local' && run.status === 'running' ? (
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
                        <Square className="h-3.5 w-3.5 text-accent" />
                      </Button>
                    ) : null}
                    <Button
                      variant="ghost"
                      size="icon"
                      className="h-7 w-7"
                      disabled={run.source !== 'local' || deletingRunId === run.id || run.status === 'running'}
                      title={run.source === 'convex' ? 'Cloud run cannot be deleted here' : 'Delete run'}
                      onClick={(event) => {
                        event.stopPropagation();
                        void handleDeleteRun(run);
                      }}
                    >
                      <Trash2 className="h-3.5 w-3.5 text-destructive/70" />
                    </Button>
                  </div>
                </div>
              </div>
            ))}
          </div>
        </ScrollArea>
      </div>

      {/* Sidebar resize handle */}
      <div
        role="separator"
        aria-orientation="vertical"
        aria-label="Resize run history sidebar"
        className="w-1 shrink-0 cursor-col-resize bg-border/40 transition-colors hover:bg-primary/30"
        onPointerDown={startSidebarResize}
      />

      {/* Main Dashboard Content */}
      {selectedRun ? (
        <div className="flex min-h-0 flex-1 flex-col">
          {/* Dashboard header */}
          <div className="border-b border-border bg-card/50 px-5 py-4">
            <div className="flex items-start justify-between gap-4">
              <div>
                <div className="flex items-center gap-3">
                  <h2 className="font-display text-xl font-semibold">{selectedRun.name}</h2>
                  <Badge variant={getStatusBadgeVariant(selectedRun.status)}>{selectedRun.status}</Badge>
                  <Badge variant="outline" className="font-data text-[9px]">{selectedRun.source}</Badge>
                  <Badge variant="secondary" className="font-data text-[9px]">{selectedEngineLabel}</Badge>
                </div>
                <p className="mt-0.5 font-data text-xs text-muted-foreground tabular-nums">
                  Step {selectedRun.currentStep} of {selectedRun.totalSteps}
                </p>
              </div>
              <div className="flex items-center gap-2">
                <Button variant="outline" size="sm" onClick={handleRefresh} disabled={isLoading}>
                  <RefreshCw className={`mr-2 h-3.5 w-3.5 ${isLoading ? 'animate-spin' : ''}`} />
                  Refresh
                </Button>
                {selectedRun.source === 'local' && selectedRun.status === 'running' ? (
                  <Button variant="destructive" size="sm" onClick={() => void handleStopRun(selectedRun)}>
                    <Square className="mr-2 h-3.5 w-3.5" />
                    Stop
                  </Button>
                ) : null}
              </div>
            </div>
          </div>

          <div className="space-y-4 p-5">
            {/* Metrics row */}
            <div className="stats-grid">
              <MetricTile
                label="Progress"
                value={<span>{selectedRun.currentStep} / {selectedRun.totalSteps}</span>}
                icon={TrendingUp}
              />
              <MetricTile
                label="Molecules"
                value={molecules.length}
                icon={FlaskConical}
              />
              <MetricTile
                label="Best Affinity"
                value={bestAffinity?.toFixed(3) ?? 'N/A'}
                icon={Atom}
              />
              <MetricTile
                label="Best Probability"
                value={bestProbability?.toFixed(3) ?? 'N/A'}
                icon={Layers}
              />
            </div>

            {/* Paths */}
            <div className="grid gap-3 xl:grid-cols-2">
              <div className="rounded-md border border-border bg-secondary/15 px-3 py-2.5">
                <p className="text-[10px] font-semibold uppercase tracking-[0.15em] text-muted-foreground">Result Directory</p>
                <p className="mt-1 break-all font-data text-[11px] text-foreground/70">{selectedRun.resultDir}</p>
              </div>
              <div className="rounded-md border border-border bg-secondary/15 px-3 py-2.5">
                <p className="text-[10px] font-semibold uppercase tracking-[0.15em] text-muted-foreground">Checkpoint</p>
                <p className="mt-1 break-all font-data text-[11px] text-foreground/70">
                  {selectedRun.checkpointPath ?? 'No checkpoint recorded'}
                </p>
              </div>
            </div>

            {/* Boltz metrics */}
            <BoltzMetricsPanel
              metrics={activeBoltzMetrics}
              isLoading={selectedRun.source === 'convex' ? convexMetricRows === undefined : isBoltzMetricsLoading}
              title={`${selectedEngineLabel} Score Trends`}
              emptyMessage={`No ${selectedEngineLabel} metric data available yet.`}
            />

            {/* Logs */}
            <Card className="border-border/60 bg-card/80">
              <CardHeader className="pb-3">
                <div className="flex items-center gap-2">
                  <FileText className="h-4 w-4 text-muted-foreground" />
                  <CardTitle className="font-display text-base">Run Logs</CardTitle>
                </div>
              </CardHeader>
              <CardContent>
                {selectedRun.source === 'convex' ? (
                  <p className="text-sm text-muted-foreground">Logs are only available for local runs.</p>
                ) : (
                  <div className="max-h-52 overflow-auto rounded-md border border-border bg-background p-3">
                    <pre className="whitespace-pre-wrap break-words font-data text-[10px] leading-relaxed text-muted-foreground">
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

            {/* Molecule details + 3D viewer */}
            <div className="grid gap-4 xl:grid-cols-[minmax(360px,420px)_minmax(0,1fr)]">
              <div className="space-y-4">
                {selectedMolecule ? (
                  <MoleculeCard molecule={selectedMolecule} />
                ) : (
                  <Card className="border-border/60 bg-card/80">
                    <CardContent className="py-8">
                      <p className="text-center text-sm text-muted-foreground">Select a molecule from the table to inspect it.</p>
                    </CardContent>
                  </Card>
                )}

                {selectedMolecule?.boltzScores ? (
                  <Card className="border-border/60 bg-card/80">
                    <CardHeader className="pb-3">
                      <CardTitle className="font-display text-base">{selectedEngineLabel} Scores</CardTitle>
                    </CardHeader>
                    <CardContent className="grid gap-3 md:grid-cols-3">
                      {[
                        {
                          label: 'Ensemble',
                          aff: selectedMolecule.boltzScores.affinity_ensemble,
                          prob: selectedMolecule.boltzScores.probability_ensemble,
                        },
                        {
                          label: 'Model 1',
                          aff: selectedMolecule.boltzScores.affinity_model1,
                          prob: selectedMolecule.boltzScores.probability_model1,
                        },
                        {
                          label: 'Model 2',
                          aff: selectedMolecule.boltzScores.affinity_model2,
                          prob: selectedMolecule.boltzScores.probability_model2,
                        },
                      ].map((item) => (
                        <div key={item.label} className="rounded-md border border-border bg-secondary/20 p-3 text-sm">
                          <p className="mb-2 text-xs font-semibold text-muted-foreground">{item.label}</p>
                          <div className="space-y-1.5 text-muted-foreground">
                            <div className="flex justify-between">
                              <span className="text-xs">Affinity</span>
                              <span className="font-data text-xs text-foreground tabular-nums">{item.aff.toFixed(3)}</span>
                            </div>
                            <div className="flex justify-between">
                              <span className="text-xs">Probability</span>
                              <span className="font-data text-xs text-foreground tabular-nums">{item.prob.toFixed(3)}</span>
                            </div>
                            <div className="h-px bg-border/40" />
                            <div className="flex justify-between">
                              <span className="text-xs font-medium text-primary/80">Score</span>
                              <span className="font-data text-xs font-medium text-primary tabular-nums">
                                {computeBoltzScore(item.aff, item.prob).toFixed(3)}
                              </span>
                            </div>
                          </div>
                        </div>
                      ))}
                    </CardContent>
                  </Card>
                ) : null}

                {selectedMolecule && selectedMolecule.trajectory.length > 0 ? (
                  <Card className="border-border/60 bg-card/80">
                    <CardHeader className="pb-3">
                      <div className="flex items-center gap-2">
                        <Atom className="h-4 w-4 text-primary" />
                        <CardTitle className="font-display text-base">Reaction Pathway</CardTitle>
                      </div>
                    </CardHeader>
                    <CardContent>
                      <ReactionPathway trajectory={selectedMolecule.trajectory} />
                    </CardContent>
                  </Card>
                ) : null}
              </div>

              <Card className="min-h-[420px] overflow-hidden border-border/60 bg-card/80">
                <CardHeader className="pb-3">
                  <CardTitle className="font-display text-base">Protein–Ligand Complex</CardTitle>
                </CardHeader>
                <CardContent className="h-[520px] p-0">
                  <MolstarViewer
                    pdbContent={complexContent}
                    selectedResidues={[]}
                    onResidueSelect={() => {}}
                  />
                </CardContent>
              </Card>
            </div>

            <ParallelCoordinatesPanel
              molecules={molecules}
              isFiltered={plotFilteredSmiles !== null}
              onFilteredSmilesChange={(smiles) => {
                setPlotFilteredSmiles(smiles ? new Set(smiles) : null);
                setTablePage(1);
              }}
            />

            {/* Molecule table */}
            <Card className="border-border/60 bg-card/80">
              <CardHeader className="pb-3">
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <div className="flex items-center gap-2">
                    <Beaker className="h-4 w-4 text-primary" />
                    <CardTitle className="font-display text-base">Generated Molecules</CardTitle>
                  </div>
                  <div className="flex flex-wrap items-center gap-2">
                    <Badge variant="outline" className="font-data text-[10px]">
                      {plotFilteredSmiles ? `${displayedMolecules.length} filtered` : `${molecules.length} total`}
                    </Badge>
                    {plotFilteredSmiles ? (
                      <Badge variant="outline" className="font-data text-[10px]">
                        {molecules.length} total
                      </Badge>
                    ) : null}
                    <Badge variant="outline" className="font-data text-[10px]">
                      {displayedMolecules.length === 0 ? 0 : pageStart + 1}–{pageEnd}
                    </Badge>
                    <Badge variant="secondary" className="font-data text-[10px]">{safePage}/{totalPages}</Badge>
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => setTablePage((page) => Math.max(1, page - 1))}
                      disabled={safePage <= 1}
                    >
                      Prev
                    </Button>
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => setTablePage((page) => Math.min(totalPages, page + 1))}
                      disabled={safePage >= totalPages}
                    >
                      Next
                    </Button>
                  </div>
                </div>
              </CardHeader>
              <CardContent className="p-0">
                <div className="overflow-x-auto">
                  <Table>
                    <TableHeader>
                      <TableRow className="hover:bg-transparent">
                        <TableHead className="w-10 font-data text-[10px]">#</TableHead>
                        <TableHead className="min-w-[200px] font-data text-[10px]">SMILES</TableHead>
                        <TableHead className="w-[4.5rem] font-data text-[10px]">Reward</TableHead>
                        <TableHead className="w-[4.5rem] font-data text-[10px]" title="Ensemble affinity">
                          Ens A
                        </TableHead>
                        <TableHead className="w-[4.5rem] font-data text-[10px]" title="Ensemble probability">
                          Ens P
                        </TableHead>
                        <TableHead className="w-[4.5rem] font-data text-[10px]" title="Model 1 affinity">
                          M1 A
                        </TableHead>
                        <TableHead className="w-[4.5rem] font-data text-[10px]" title="Model 1 probability">
                          M1 P
                        </TableHead>
                        <TableHead className="w-[4.5rem] font-data text-[10px]" title="Model 2 affinity">
                          M2 A
                        </TableHead>
                        <TableHead className="w-[4.5rem] font-data text-[10px]" title="Model 2 probability">
                          M2 P
                        </TableHead>
                        <TableHead className="w-16 font-data text-[10px]">Steps</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {pagedMolecules.map((molecule, idx) => (
                        <TableRow
                          key={molecule.smiles}
                          className={`cursor-pointer transition-colors ${selectedMolecule?.smiles === molecule.smiles ? 'bg-primary/5' : 'hover:bg-secondary/30'}`}
                          onClick={() => setSelectedMolecule(molecule)}
                        >
                          <TableCell className="align-top py-2 font-data text-xs font-medium tabular-nums">
                            {pageStart + idx + 1}
                          </TableCell>
                          <TableCell className="min-w-[12rem] max-w-none py-2 align-top">
                            <SmilesCell smiles={molecule.smiles} />
                          </TableCell>
                          <TableCell className="py-2 align-top font-data text-xs tabular-nums">
                            {molecule.reward.toFixed(3)}
                          </TableCell>
                          <TableCell className="py-2 align-top font-data text-xs tabular-nums">
                            {molecule.boltzScores ? fmtBoltz(molecule.boltzScores.affinity_ensemble) : 'N/A'}
                          </TableCell>
                          <TableCell className="py-2 align-top font-data text-xs tabular-nums">
                            {molecule.boltzScores ? fmtBoltz(molecule.boltzScores.probability_ensemble) : 'N/A'}
                          </TableCell>
                          <TableCell className="py-2 align-top font-data text-xs tabular-nums">
                            {molecule.boltzScores ? fmtBoltz(molecule.boltzScores.affinity_model1) : 'N/A'}
                          </TableCell>
                          <TableCell className="py-2 align-top font-data text-xs tabular-nums">
                            {molecule.boltzScores ? fmtBoltz(molecule.boltzScores.probability_model1) : 'N/A'}
                          </TableCell>
                          <TableCell className="py-2 align-top font-data text-xs tabular-nums">
                            {molecule.boltzScores ? fmtBoltz(molecule.boltzScores.affinity_model2) : 'N/A'}
                          </TableCell>
                          <TableCell className="py-2 align-top font-data text-xs tabular-nums">
                            {molecule.boltzScores ? fmtBoltz(molecule.boltzScores.probability_model2) : 'N/A'}
                          </TableCell>
                          <TableCell className="py-2 align-top">
                            <Badge variant="secondary" className="font-data text-[10px]">
                              {molecule.trajectory.length}
                            </Badge>
                          </TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </div>
              </CardContent>
            </Card>
          </div>
        </div>
      ) : (
        <div className="flex flex-1 items-center justify-center">
          <div className="space-y-3 text-center">
            <History className="mx-auto h-10 w-10 text-muted-foreground/30" />
            <p className="text-sm text-muted-foreground">Select a run from the sidebar.</p>
          </div>
        </div>
      )}
    </div>
  );
}
