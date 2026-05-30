import { useState, useEffect, useCallback, useMemo, useRef, type CSSProperties, type PointerEvent as ReactPointerEvent, type ReactNode, type UIEvent as ReactUIEvent } from 'react';
import { useQuery } from 'convex/react';
import { api } from '../../convex/_generated/api';
import { useConvexRuns, useConvexAvailable } from '@/hooks/useConvex';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { ScrollArea } from '@/components/ui/scroll-area';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { useIpcInvoke } from '@/hooks/useIpc';
import MolstarViewer from '@/components/MolstarViewer';
import BoltzMetricsPanel from '@/components/BoltzMetricsPanel';
import ParallelCoordinatesPanel from '@/components/ParallelCoordinatesPanel';
import CompoundImageCell from '@/components/CompoundImageCell';
import { computeBoltzMetrics } from '@shared/boltzMetrics';
import type { BoltzMetricInputRow, BoltzMetricSeries, RunInfo, MoleculeResult } from '@shared/types';
import {
  Beaker,
  CheckCircle2,
  Circle,
  CloudUpload,
  FileText,
  FolderOpen,
  History,
  PauseCircle,
  PanelLeftClose,
  PanelLeftOpen,
  PlayCircle,
  RefreshCw,
  Square,
  Trash2,
  XCircle,
  FlaskConical,
} from 'lucide-react';

interface DashboardProps {
  activeRun: RunInfo | null;
  onRunStatusChange: (run: RunInfo) => void;
}

const MOLECULE_ROW_HEIGHT = 120;
const MOLECULE_TABLE_MIN_VISIBLE_ROWS = 3;
const MOLECULE_TABLE_MAX_VISIBLE_ROWS = 10;
const MOLECULE_TABLE_HEADER_HEIGHT = 42;
const MOLECULE_ROW_OVERSCAN = 6;
const MOLECULE_SCROLL_IDLE_MS = 140;
const PARALLEL_COORDINATE_SAMPLE_LIMIT = 250;
const SIDEBAR_MIN_WIDTH = 220;
const SIDEBAR_MAX_WIDTH = 520;
const SIDEBAR_DEFAULT_WIDTH = 256;
const SIDEBAR_COLLAPSED_WIDTH = 64;
const VISUALIZATION_TABLE_MIN_WIDTH = 340;
const VISUALIZATION_TABLE_MAX_WIDTH = 760;
const VISUALIZATION_TABLE_DEFAULT_WIDTH = 370;
const VISUALIZATION_TOP_MIN_HEIGHT = 420;
const VISUALIZATION_TOP_MAX_HEIGHT = 760;
const VISUALIZATION_TOP_DEFAULT_HEIGHT = 560;
const RUN_INFO_CHART_MIN_HEIGHT = 160;
const RUN_INFO_CHART_MAX_HEIGHT = 320;
const RUN_INFO_CHART_DEFAULT_HEIGHT = 224;
const HIDDEN_RUN_IDS_KEY = 'cgflow.hiddenRunIds';
const LOG_TAIL_LINES = 200;

function getStatusIcon(status: string) {
  switch (status) {
    case 'running':
      return <PlayCircle className="h-4 w-4 text-primary" />;
    case 'completed':
      return <CheckCircle2 className="h-4 w-4 text-success" />;
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

function getStatusBadgeVariant(status: RunInfo['status']) {
  switch (status) {
    case 'running':
    case 'completed':
      return 'success';
    case 'error':
      return 'destructive';
    case 'paused':
      return 'warning';
    default:
      return 'secondary';
  }
}

interface ConvexRun {
  _id: string;
  name: string;
  engine?: 'boltz' | 'flashbind';
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

const LOG_LINE_PATTERN = /^(\d{2}\/\d{2}\/\d{4}\s+\d{2}:\d{2}:\d{2})\s+-\s+(\w+)\s+-\s+([^-]+)\s+-\s+(.*)$/;
const LOG_ITERATION_PATTERN = /^(iteration\s+)(\d+)(\s*:\s*)/;
const LOG_METRIC_PATTERN = /([A-Za-z_][\w]*):(-?\d+(?:\.\d+)?)/g;

function getLogMetricClass(metricName: string): string {
  if (metricName.includes('boltz')) return 'text-primary';
  if (metricName.includes('loss') || metricName.includes('invalid')) return 'text-destructive';
  if (metricName.includes('reward')) return 'text-success';
  return 'text-foreground';
}

function renderLogMetrics(text: string): ReactNode[] {
  const nodes: ReactNode[] = [];
  let lastIndex = 0;

  for (const match of text.matchAll(LOG_METRIC_PATTERN)) {
    const [token, key, value] = match;
    if (!key || !value) continue;
    const index = match.index ?? 0;
    if (index > lastIndex) nodes.push(text.slice(lastIndex, index));
    nodes.push(
      <span key={`${key}-${index}`} className="rounded bg-muted/60 px-1 py-0.5">
        <span className="text-muted-foreground">{key}:</span>
        <span className={`ml-0.5 font-semibold ${getLogMetricClass(key)}`}>{value}</span>
      </span>
    );
    lastIndex = index + token.length;
  }

  if (lastIndex < text.length) nodes.push(text.slice(lastIndex));
  return nodes;
}

function renderLogMessage(message: string): ReactNode[] {
  const iterationMatch = message.match(LOG_ITERATION_PATTERN);
  if (!iterationMatch) return renderLogMetrics(message);

  const [prefix, label, iteration, suffix] = iterationMatch;
  return [
    <span key="iteration" className="rounded bg-primary/10 px-1 py-0.5 font-semibold text-primary">
      {label}
      {iteration}
    </span>,
    suffix,
    ...renderLogMetrics(message.slice(prefix.length)),
  ];
}

function renderLogLine(line: string, index: number): ReactNode {
  const match = line.match(LOG_LINE_PATTERN);
  if (!match) {
    return (
      <div key={index} className="whitespace-pre-wrap break-words">
        {line}
      </div>
    );
  }

  const timestamp = match[1] ?? '';
  const level = match[2] ?? '';
  const logger = match[3] ?? '';
  const message = match[4] ?? '';
  return (
    <div key={index} className="whitespace-pre-wrap break-words">
      <span className="text-muted-foreground">{timestamp}</span>
      <span className="text-muted-foreground"> - </span>
      <span className="font-semibold text-primary">{level}</span>
      <span className="text-muted-foreground"> - </span>
      <span className="text-accent-foreground">{logger.trim()}</span>
      <span className="text-muted-foreground"> - </span>
      {renderLogMessage(message)}
    </div>
  );
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
  const [dashboardView, setDashboardView] = useState<'run-info' | 'visualization'>('visualization');
  const [plotFilteredSmiles, setPlotFilteredSmiles] = useState<Set<string> | null>(null);
  const [sidebarWidth, setSidebarWidth] = useState(SIDEBAR_DEFAULT_WIDTH);
  const [isRunSidebarCollapsed, setIsRunSidebarCollapsed] = useState(false);
  const [isResizingSidebar, setIsResizingSidebar] = useState(false);
  const [visualizationTableWidth, setVisualizationTableWidth] = useState(VISUALIZATION_TABLE_DEFAULT_WIDTH);
  const [visualizationTopHeight, setVisualizationTopHeight] = useState(VISUALIZATION_TOP_DEFAULT_HEIGHT);
  const [runInfoChartHeight, setRunInfoChartHeight] = useState(RUN_INFO_CHART_DEFAULT_HEIGHT);
  const [visualizationResizeMode, setVisualizationResizeMode] = useState<'columns' | 'rows' | null>(null);
  const moleculeTableRef = useRef<HTMLDivElement>(null);
  const moleculeTableScrollTimerRef = useRef<number | undefined>(undefined);
  const moleculeTableMeasureFrameRef = useRef<number | undefined>(undefined);
  const [moleculeTableScrollTop, setMoleculeTableScrollTop] = useState(0);
  const [moleculeTableViewportHeight, setMoleculeTableViewportHeight] = useState(VISUALIZATION_TOP_DEFAULT_HEIGHT);
  const [isMoleculeTableScrolling, setIsMoleculeTableScrolling] = useState(false);
  const [runLogLines, setRunLogLines] = useState<string[]>([]);
  const [hiddenRunIds, setHiddenRunIds] = useState<Set<string>>(() => {
    if (typeof window === 'undefined') return new Set();
    try {
      const raw = window.localStorage.getItem(HIDDEN_RUN_IDS_KEY);
      if (!raw) return new Set();
      const parsed = JSON.parse(raw) as string[];
      return new Set(Array.isArray(parsed) ? parsed : []);
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
        engine: row.engine ?? selectedRun?.engine ?? 'boltz',
        normalizedScores:
          row.normalizedAffinity != null &&
          row.normalizedProbability != null &&
          row.normalizedScore != null
            ? {
                affinity: row.normalizedAffinity,
                probability: row.normalizedProbability,
                score: row.normalizedScore,
              }
            : null,
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
  }, [convexMoleculeRows, selectedRun?.engine]);

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

  const selectedEngine = selectedRun?.engine ?? 'boltz';
  const selectedEngineLabel = selectedEngine === 'flashbind' ? 'FlashBind' : 'Boltz';

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
        const results = await invoke('db:get-top-molecules', selectedRun.id);
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
      const results = await invoke('db:get-top-molecules', selectedRun.id);
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

  const startVisualizationColumnResize = useCallback((event: ReactPointerEvent<HTMLDivElement>) => {
    event.preventDefault();
    const grid = event.currentTarget.parentElement;
    const rect = grid?.getBoundingClientRect();
    if (!rect) return;
    const startX = event.clientX;
    const startWidth = visualizationTableWidth;

    setVisualizationResizeMode('columns');

    const onMove = (moveEvent: PointerEvent) => {
      const nextWidth = Math.min(
        VISUALIZATION_TABLE_MAX_WIDTH,
        Math.max(VISUALIZATION_TABLE_MIN_WIDTH, startWidth + moveEvent.clientX - startX)
      );
      setVisualizationTableWidth(nextWidth);
    };

    const onUp = () => {
      setVisualizationResizeMode(null);
      window.removeEventListener('pointermove', onMove);
      window.removeEventListener('pointerup', onUp);
    };

    window.addEventListener('pointermove', onMove);
    window.addEventListener('pointerup', onUp, { once: true });
  }, [visualizationTableWidth]);

  const startVisualizationRowResize = useCallback((event: ReactPointerEvent<HTMLDivElement>) => {
    event.preventDefault();
    setVisualizationResizeMode('rows');
    const startY = event.clientY;
    const startHeight = visualizationTopHeight;

    const onMove = (moveEvent: PointerEvent) => {
      const nextHeight = Math.min(
        VISUALIZATION_TOP_MAX_HEIGHT,
        Math.max(VISUALIZATION_TOP_MIN_HEIGHT, startHeight + moveEvent.clientY - startY)
      );
      setVisualizationTopHeight(nextHeight);
    };

    const onUp = () => {
      setVisualizationResizeMode(null);
      window.removeEventListener('pointermove', onMove);
      window.removeEventListener('pointerup', onUp);
    };

    window.addEventListener('pointermove', onMove);
    window.addEventListener('pointerup', onUp, { once: true });
  }, [visualizationTopHeight]);

  const startRunInfoPlotResize = useCallback((event: ReactPointerEvent<HTMLDivElement>) => {
    event.preventDefault();
    setVisualizationResizeMode('rows');
    const startY = event.clientY;
    const startHeight = runInfoChartHeight;

    const onMove = (moveEvent: PointerEvent) => {
      const nextHeight = Math.min(
        RUN_INFO_CHART_MAX_HEIGHT,
        Math.max(RUN_INFO_CHART_MIN_HEIGHT, startHeight + moveEvent.clientY - startY)
      );
      setRunInfoChartHeight(nextHeight);
    };

    const onUp = () => {
      setVisualizationResizeMode(null);
      window.removeEventListener('pointermove', onMove);
      window.removeEventListener('pointerup', onUp);
    };

    window.addEventListener('pointermove', onMove);
    window.addEventListener('pointerup', onUp, { once: true });
  }, [runInfoChartHeight]);

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
    if (!visualizationResizeMode) return;
    const previousCursor = document.body.style.cursor;
    const previousUserSelect = document.body.style.userSelect;
    document.body.style.cursor = visualizationResizeMode === 'columns' ? 'col-resize' : 'row-resize';
    document.body.style.userSelect = 'none';
    return () => {
      document.body.style.cursor = previousCursor;
      document.body.style.userSelect = previousUserSelect;
    };
  }, [visualizationResizeMode]);

  useEffect(() => {
    setPlotFilteredSmiles(null);
  }, [selectedRun?.id]);

  const handleMoleculeTableScroll = useCallback((event: ReactUIEvent<HTMLDivElement>) => {
    setMoleculeTableScrollTop(event.currentTarget.scrollTop);
    setIsMoleculeTableScrolling(true);

    if (moleculeTableScrollTimerRef.current) {
      window.clearTimeout(moleculeTableScrollTimerRef.current);
    }

    moleculeTableScrollTimerRef.current = window.setTimeout(() => {
      setIsMoleculeTableScrolling(false);
    }, MOLECULE_SCROLL_IDLE_MS);
  }, []);

  const measureMoleculeTableViewport = useCallback(() => {
    if (dashboardView !== 'visualization') return;
    const table = moleculeTableRef.current;
    if (!table) return;

    const nextHeight = table.clientHeight;
    if (nextHeight < MOLECULE_TABLE_HEADER_HEIGHT + MOLECULE_ROW_HEIGHT) return;
    setMoleculeTableViewportHeight(nextHeight);
  }, [dashboardView]);

  useEffect(() => {
    const table = moleculeTableRef.current;
    if (!table) return;

    measureMoleculeTableViewport();
    const firstFrame = window.requestAnimationFrame(() => {
      const secondFrame = window.requestAnimationFrame(measureMoleculeTableViewport);
      moleculeTableMeasureFrameRef.current = secondFrame;
    });
    moleculeTableMeasureFrameRef.current = firstFrame;

    const observer = new ResizeObserver(measureMoleculeTableViewport);
    observer.observe(table);
    return () => {
      if (moleculeTableMeasureFrameRef.current) {
        window.cancelAnimationFrame(moleculeTableMeasureFrameRef.current);
      }
      moleculeTableMeasureFrameRef.current = undefined;
      observer.disconnect();
    };
  }, [dashboardView, measureMoleculeTableViewport, visualizationTopHeight]);

  useEffect(() => {
    const table = moleculeTableRef.current;
    if (table) table.scrollTop = 0;
    setMoleculeTableScrollTop(0);
    setIsMoleculeTableScrolling(false);
  }, [selectedRun?.id, plotFilteredSmiles]);

  useEffect(() => {
    return () => {
      if (moleculeTableScrollTimerRef.current) {
        window.clearTimeout(moleculeTableScrollTimerRef.current);
      }
      if (moleculeTableMeasureFrameRef.current) {
        window.cancelAnimationFrame(moleculeTableMeasureFrameRef.current);
      }
    };
  }, []);

  const displayedMolecules = useMemo(
    () => (plotFilteredSmiles ? molecules.filter((molecule) => plotFilteredSmiles.has(molecule.smiles)) : molecules),
    [molecules, plotFilteredSmiles]
  );

  const visibleMoleculeStart = Math.min(
    displayedMolecules.length,
    Math.max(0, Math.floor(moleculeTableScrollTop / MOLECULE_ROW_HEIGHT))
  );
  const moleculeTableRowsHeight = Math.max(0, moleculeTableViewportHeight - MOLECULE_TABLE_HEADER_HEIGHT);
  const visibleMoleculeCount = Math.max(1, Math.ceil(moleculeTableRowsHeight / MOLECULE_ROW_HEIGHT) + 1);
  const virtualMoleculeStart = Math.max(0, visibleMoleculeStart - MOLECULE_ROW_OVERSCAN);
  const virtualMoleculeEnd = Math.min(
    displayedMolecules.length,
    visibleMoleculeStart + visibleMoleculeCount + MOLECULE_ROW_OVERSCAN
  );
  const virtualMolecules = displayedMolecules.slice(virtualMoleculeStart, virtualMoleculeEnd);

  useEffect(() => {
    if (!selectedMolecule) return;
    if (displayedMolecules.some((molecule) => molecule.smiles === selectedMolecule.smiles)) return;
    setSelectedMolecule(displayedMolecules[0] ?? null);
  }, [displayedMolecules, selectedMolecule]);

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
      <div
        className="flex shrink-0 flex-col border-r border-border bg-card/75 transition-[width] duration-200"
        style={{ width: isRunSidebarCollapsed ? SIDEBAR_COLLAPSED_WIDTH : sidebarWidth }}
      >
        <div className={`border-b border-border p-3 ${isRunSidebarCollapsed ? 'space-y-2' : ''}`}>
          <div className={`flex items-center ${isRunSidebarCollapsed ? 'justify-center' : 'gap-2'}`}>
            <History className="h-4 w-4 text-primary" />
            {!isRunSidebarCollapsed ? <h3 className="font-display text-sm font-semibold">Run History</h3> : null}
            {!isRunSidebarCollapsed ? (
              <Button
                variant="ghost"
                size="icon"
                className="ml-auto h-7 w-7"
                title="Collapse run history"
                onClick={() => setIsRunSidebarCollapsed(true)}
              >
                <PanelLeftClose className="h-3.5 w-3.5" />
              </Button>
            ) : null}
          </div>
          {!isRunSidebarCollapsed ? (
          <p className="mt-1 font-data text-[10px] text-muted-foreground tabular-nums">
            {allRuns.length} run{allRuns.length !== 1 ? 's' : ''}
          </p>
          ) : null}
          {isRunSidebarCollapsed ? (
            <Button
              variant="ghost"
              size="icon"
              className="h-8 w-full"
              title="Expand run history"
              onClick={() => setIsRunSidebarCollapsed(false)}
            >
              <PanelLeftOpen className="h-4 w-4" />
            </Button>
          ) : null}
          <Button
            variant="outline"
            size={isRunSidebarCollapsed ? 'icon' : 'sm'}
            className={isRunSidebarCollapsed ? 'h-8 w-full' : 'mt-3 w-full justify-start gap-2'}
            onClick={handleImportRun}
            title="Import run"
          >
            <FolderOpen className="h-3.5 w-3.5" />
            {!isRunSidebarCollapsed ? 'Import Run' : null}
          </Button>
          {!isRunSidebarCollapsed ? (
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
          ) : null}
        </div>

        <ScrollArea className="flex-1">
          <div className={isRunSidebarCollapsed ? 'space-y-2 p-2' : 'space-y-1 p-2'}>
            {allRuns.map((run) => (
              <div
                key={run.id}
                onClick={() => handleSelectRun(run)}
                title={isRunSidebarCollapsed ? `${run.name} (${run.status})` : undefined}
                className={`w-full cursor-pointer rounded-md border text-left transition-all ${
                  isRunSidebarCollapsed ? 'flex h-10 items-center justify-center p-0' : 'p-3'
                } ${
                  selectedRun?.id === run.id
                    ? 'border-primary/30 bg-primary/10 shadow-sm'
                    : 'border-transparent hover:border-border hover:bg-secondary/30'
                }`}
              >
                {isRunSidebarCollapsed ? (
                  getStatusIcon(run.status)
                ) : (
                <>
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
                </>
                )}
              </div>
            ))}
          </div>
        </ScrollArea>
      </div>

      {/* Sidebar resize handle */}
      {!isRunSidebarCollapsed ? (
        <div
        role="separator"
        aria-orientation="vertical"
        aria-label="Resize run history sidebar"
        className="w-1 shrink-0 cursor-col-resize bg-border/40 transition-colors hover:bg-primary/30"
        onPointerDown={startSidebarResize}
      />
      ) : null}

      {/* Main Dashboard Content */}
      {selectedRun ? (
        <div className="flex min-h-0 min-w-0 flex-1 flex-col">
          {/* Dashboard header */}
          <div className="border-b border-border bg-card/50 px-4 py-3">
            <div className="flex items-start justify-between gap-4">
              <div>
                <div className="flex items-center gap-3">
                  <h2 className="font-display text-xl font-semibold">{selectedRun.name}</h2>
                  <Badge variant={getStatusBadgeVariant(selectedRun.status)}>{selectedRun.status}</Badge>
                  <Badge variant="outline" className="font-data text-[9px]">{selectedEngineLabel}</Badge>
                  <Badge variant="outline" className="font-data text-[9px]">{selectedRun.source}</Badge>
                </div>
                <p className="mt-0.5 font-data text-xs text-muted-foreground tabular-nums">
                  Iteration {selectedRun.currentStep} of {selectedRun.totalSteps}
                </p>
                <p className="mt-1 max-w-4xl truncate font-data text-[11px] text-muted-foreground" title={selectedRun.resultDir}>
                  Result directory: {selectedRun.resultDir}
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

          <Tabs value={dashboardView} onValueChange={(value) => setDashboardView(value as 'run-info' | 'visualization')} className="flex min-h-0 min-w-0 flex-1 flex-col">
            <div className="border-b border-border bg-background/60 px-4">
              <TabsList>
                <TabsTrigger value="run-info">Run Info</TabsTrigger>
                <TabsTrigger value="visualization">Visualization</TabsTrigger>
              </TabsList>
            </div>

            <TabsContent
              value="run-info"
              className="m-0 min-h-0 flex-1 overflow-auto p-4 data-[state=inactive]:hidden"
            >
              <div className="grid min-h-0 grid-rows-[auto_8px_auto] gap-3">
                <BoltzMetricsPanel
                  className="shrink-0"
                  metrics={activeBoltzMetrics}
                  isLoading={selectedRun.source === 'convex' ? convexMetricRows === undefined : isBoltzMetricsLoading}
                  chartHeight={runInfoChartHeight}
                />

                <div
                  className="h-2 cursor-row-resize rounded-full bg-border/40 transition-colors hover:bg-primary/40"
                  role="separator"
                  aria-label={`Resize ${selectedEngineLabel} score plots`}
                  aria-orientation="horizontal"
                  title={`Drag to resize ${selectedEngineLabel} score plots`}
                  onPointerDown={startRunInfoPlotResize}
                />

                <Card className="flex h-[clamp(180px,28vh,320px)] min-h-0 flex-col border-border/60 bg-card/80">
                  <CardHeader className="shrink-0 pb-3">
                    <div className="flex items-center gap-2">
                      <FileText className="h-4 w-4 text-muted-foreground" />
                      <CardTitle className="font-display text-base">Run Logs</CardTitle>
                    </div>
                  </CardHeader>
                  <CardContent className="min-h-0 flex-1">
                    {selectedRun.source === 'convex' ? (
                      <p className="text-sm text-muted-foreground">Logs are only available for local runs.</p>
                    ) : (
                      <div className="h-full overflow-auto rounded-md border border-border bg-background p-3">
                        <div className="space-y-1 font-data text-[10px] leading-relaxed text-foreground">
                          {runLogLines.length > 0
                            ? runLogLines.map(renderLogLine)
                            : isLogLoading
                              ? 'Loading logs...'
                              : 'No log output yet.'}
                        </div>
                      </div>
                    )}
                  </CardContent>
                </Card>
              </div>
            </TabsContent>

            <TabsContent value="visualization" className="m-0 overflow-x-hidden p-3">
              <div
                className="grid min-w-0 items-start gap-3 xl:grid-cols-[var(--visualization-table-width)_8px_minmax(0,1fr)] xl:gap-x-0"
                style={{ '--visualization-table-width': `${visualizationTableWidth}px` } as CSSProperties}
              >
                <Card className="flex min-w-0 flex-col overflow-hidden border-border/60 bg-card/80 xl:col-start-1">
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
                      </div>
                    </div>
                  </CardHeader>
                  <CardContent className="min-h-0 flex-1 p-0">
                    <div
                      ref={moleculeTableRef}
                      className="h-full overflow-auto"
                      style={{
                        height: `clamp(${MOLECULE_TABLE_HEADER_HEIGHT + MOLECULE_ROW_HEIGHT * MOLECULE_TABLE_MIN_VISIBLE_ROWS}px, calc(100vh - 245px), ${MOLECULE_TABLE_HEADER_HEIGHT + MOLECULE_ROW_HEIGHT * MOLECULE_TABLE_MAX_VISIBLE_ROWS}px)`,
                      }}
                      onScroll={handleMoleculeTableScroll}
                    >
                      <div className="sticky top-0 z-10 grid w-fit grid-cols-[2.25rem_180px_4.75rem] gap-x-3 border-b border-border bg-card px-4 py-3 font-data text-[10px] font-medium uppercase tracking-wide text-muted-foreground">
                        <div className="text-center">ID</div>
                        <div>Compound</div>
                        <div className="text-right">{selectedEngineLabel} Score</div>
                      </div>
                      <div className="relative" style={{ height: displayedMolecules.length * MOLECULE_ROW_HEIGHT }}>
                        {displayedMolecules.length === 0 ? (
                          <div className="absolute inset-x-0 top-0 px-4 py-6 text-sm text-muted-foreground">
                            No molecules to display.
                          </div>
                        ) : (
                          virtualMolecules.map((molecule, idx) => {
                            const moleculeIndex = virtualMoleculeStart + idx;
                            const isSelected = selectedMolecule?.smiles === molecule.smiles;

                            return (
                              <div
                                key={molecule.smiles}
                                className={`group absolute left-3 grid w-fit cursor-pointer grid-cols-[2.25rem_180px_4.75rem] items-start gap-x-3 rounded-md border px-3 py-2 transition-colors ${
                                  isSelected
                                    ? 'border-primary/30 bg-primary/10'
                                    : 'border-transparent bg-transparent hover:border-border/70 hover:bg-secondary/40'
                                }`}
                                style={{
                                  height: MOLECULE_ROW_HEIGHT - 8,
                                  transform: `translateY(${moleculeIndex * MOLECULE_ROW_HEIGHT}px)`,
                                }}
                                onClick={() => setSelectedMolecule(molecule)}
                              >
                                {isSelected ? <div className="absolute bottom-3 left-0 top-3 w-1 rounded-r-full bg-primary" /> : null}
                                <div className="pt-2 text-center font-data text-xs font-medium tabular-nums text-muted-foreground">
                                  {moleculeIndex + 1}
                                </div>
                                <CompoundImageCell
                                  smiles={molecule.smiles}
                                  renderImage={!isMoleculeTableScrolling || isSelected}
                                />
                                <div className="pt-2 text-right font-data text-xs font-medium tabular-nums text-foreground">
                                  {molecule.reward.toFixed(3)}
                                </div>
                              </div>
                            );
                          })
                        )}
                      </div>
                    </div>
                  </CardContent>
                </Card>

                <div
                  className="hidden self-stretch cursor-col-resize rounded-full bg-border/40 transition-colors hover:bg-primary/40 xl:col-start-2 xl:block"
                  role="separator"
                  aria-label="Resize table and visualization columns"
                  aria-orientation="vertical"
                  title="Drag to resize table and visualization columns"
                  onPointerDown={startVisualizationColumnResize}
                />

                <div className="min-w-0 space-y-3 xl:col-start-3">
                  <Card className="flex min-w-0 flex-col overflow-hidden border-border/60 bg-card/80">
                    <CardHeader className="px-3 py-2">
                      <CardTitle className="font-display text-sm">Protein-Ligand Complex</CardTitle>
                    </CardHeader>
                    <CardContent className="p-0" style={{ height: visualizationTopHeight }}>
                      <MolstarViewer
                        pdbContent={complexContent}
                        selectedResidues={[]}
                        onResidueSelect={() => {}}
                        compact
                      />
                    </CardContent>
                  </Card>

                  <div
                    className="hidden h-2 cursor-row-resize rounded-full bg-border/40 transition-colors hover:bg-primary/40 xl:block"
                    role="separator"
                    aria-label="Resize Mol* viewer height"
                    aria-orientation="horizontal"
                    title="Drag to resize the Mol* viewer"
                    onPointerDown={startVisualizationRowResize}
                  />

                  <ParallelCoordinatesPanel
                    molecules={molecules}
                    maxSamples={PARALLEL_COORDINATE_SAMPLE_LIMIT}
                    isFiltered={plotFilteredSmiles !== null}
                    onFilteredSmilesChange={(smiles) => {
                      setPlotFilteredSmiles(smiles ? new Set(smiles) : null);
                    }}
                  />
                </div>
              </div>
            </TabsContent>
          </Tabs>
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
