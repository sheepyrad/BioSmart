import { useCallback, useMemo, useRef } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Activity } from 'lucide-react';
import type { MoleculeResult } from '@shared/types';
import EChart from '@/components/EChart';
import type { EChartsOption, EChartsType } from 'echarts';
import { useChartTheme } from '@/lib/chartTheme';

interface ParallelCoordinatesPanelProps {
  molecules: MoleculeResult[];
  maxSamples?: number;
  onFilteredSmilesChange?: (smiles: string[] | null) => void;
  isFiltered?: boolean;
}

type ParallelRow = {
  molecule: MoleculeResult;
  smiles: string;
  reward: number;
  ensAffinity: number;
  ensProb: number;
  m1Affinity: number;
  m1Prob: number;
  m2Affinity: number;
  m2Prob: number;
  steps: number;
};

function hashString(value: string): number {
  let hash = 2166136261;
  for (let index = 0; index < value.length; index += 1) {
    hash ^= value.charCodeAt(index);
    hash = Math.imul(hash, 16777619);
  }
  return hash >>> 0;
}

const REQUIRED_TOP_ROW_COUNT = 100;

function downsampleWithTopRows(rows: ParallelRow[], maxSamples: number): ParallelRow[] {
  if (rows.length <= maxSamples) return rows;

  const topRowCount = Math.min(REQUIRED_TOP_ROW_COUNT, rows.length);
  const sampleLimit = Math.max(maxSamples, topRowCount);
  const topRows = [...rows]
    .sort((a, b) => b.reward - a.reward)
    .slice(0, topRowCount);
  const topSmiles = new Set(topRows.map((row) => row.smiles));
  const randomRows = rows
    .filter((row) => !topSmiles.has(row.smiles))
    .sort((a, b) => hashString(a.smiles) - hashString(b.smiles))
    .slice(0, sampleLimit - topRows.length);

  return [...topRows, ...randomRows];
}

function getRange(values: number[]): [number, number] {
  if (values.length === 0) return [0, 1];
  let min = values[0] as number;
  let max = values[0] as number;
  for (const value of values) {
    if (value < min) min = value;
    if (value > max) max = value;
  }
  if (min === max) return [min - 1, max + 1];
  return [min, max];
}

function formatAxisValue(value: number | string): string {
  const numeric = typeof value === 'number' ? value : Number(value);
  if (!Number.isFinite(numeric)) return String(value);
  if (Math.abs(numeric) >= 1000) return Math.round(numeric).toLocaleString();
  if (Number.isInteger(numeric)) return String(numeric);
  return numeric.toFixed(2).replace(/\.?0+$/, '');
}

function formatVisualMapValue(value: unknown): string {
  if (typeof value === 'number' || typeof value === 'string') {
    return formatAxisValue(value);
  }
  return '';
}

function roundedRange(values: number[], integer = false): [number, number] {
  const [min, max] = getRange(values);
  if (integer) return [Math.floor(min), Math.ceil(max)];

  const span = Math.max(Math.abs(max - min), 0.001);
  const step = span >= 10 ? 1 : span >= 1 ? 0.1 : span >= 0.1 ? 0.01 : 0.001;
  const roundedMin = Math.floor(min / step) * step;
  const roundedMax = Math.ceil(max / step) * step;
  return [
    Number(roundedMin.toFixed(3)),
    Number(roundedMax.toFixed(3)),
  ];
}

interface ParallelSeriesModelLike {
  getRawIndicesByActiveState(state: 'active'): number[];
}

interface ParallelAxisModelLike {
  activeIntervals?: number[][];
}

interface EChartsModelLike {
  getSeries(): unknown[];
  getComponent(mainType: string, index: number): unknown;
}

const PARALLEL_AXIS_COUNT = 8;
const PARALLEL_COLOR_SCALE = ['#1d4ed8', '#0891b2', '#10b981', '#facc15', '#f97316', '#ef4444'];

export default function ParallelCoordinatesPanel({
  molecules,
  maxSamples = 250,
  onFilteredSmilesChange,
  isFiltered = false,
}: ParallelCoordinatesPanelProps) {
  const chartTheme = useChartTheme();
  const chartRef = useRef<EChartsType | null>(null);
  const rows = useMemo<ParallelRow[]>(() => {
    return molecules
      .filter((molecule) => molecule.boltzScores)
      .map((molecule) => {
        const scores = molecule.boltzScores!;
        return {
          molecule,
          smiles: molecule.smiles,
          reward: molecule.reward,
          ensAffinity: scores.affinity_ensemble,
          ensProb: scores.probability_ensemble,
          m1Affinity: scores.affinity_model1,
          m1Prob: scores.probability_model1,
          m2Affinity: scores.affinity_model2,
          m2Prob: scores.probability_model2,
          steps: molecule.trajectory.length,
        };
      });
  }, [molecules]);

  const sampledRows = useMemo(
    () => downsampleWithTopRows(rows, maxSamples),
    [rows, maxSamples]
  );

  const option = useMemo<EChartsOption | null>(() => {
    if (sampledRows.length === 0) return null;
    const reward = rows.map((row) => row.reward);
    const ensAffinity = sampledRows.map((row) => row.ensAffinity);
    const ensProb = sampledRows.map((row) => row.ensProb);
    const m1Affinity = sampledRows.map((row) => row.m1Affinity);
    const m1Prob = sampledRows.map((row) => row.m1Prob);
    const m2Affinity = sampledRows.map((row) => row.m2Affinity);
    const m2Prob = sampledRows.map((row) => row.m2Prob);
    const steps = sampledRows.map((row) => row.steps);
    const rewardRange = roundedRange(reward);
    const ensAffinityRange = roundedRange(ensAffinity);
    const ensProbRange = roundedRange(ensProb);
    const m1AffinityRange = roundedRange(m1Affinity);
    const m1ProbRange = roundedRange(m1Prob);
    const m2AffinityRange = roundedRange(m2Affinity);
    const m2ProbRange = roundedRange(m2Prob);
    const stepsRange = roundedRange(steps, true);
    const data = sampledRows.map((row) => [
      row.reward,
      row.ensAffinity,
      row.ensProb,
      row.m1Affinity,
      row.m1Prob,
      row.m2Affinity,
      row.m2Prob,
      row.steps,
    ]);

    return {
      animation: false,
      textStyle: {
        fontFamily: '"IBM Plex Mono", monospace',
        color: chartTheme.text,
      },
      tooltip: {
        trigger: 'item',
        backgroundColor: chartTheme.tooltipBackground,
        borderColor: chartTheme.tooltipBorder,
        textStyle: { color: chartTheme.tooltipText, fontFamily: '"IBM Plex Mono", monospace', fontSize: 11 },
      },
      parallel: {
        left: 52,
        right: 118,
        top: 24,
        bottom: 28,
        parallelAxisDefault: {
          type: 'value',
          realtime: false,
          nameLocation: 'end',
          nameGap: 10,
          nameTextStyle: { color: chartTheme.axisText, fontSize: 10 },
          axisLabel: { color: chartTheme.axisText, fontSize: 9, formatter: formatAxisValue },
          axisLine: { lineStyle: { color: chartTheme.grid } },
          splitLine: { show: false },
          areaSelectStyle: {
            width: 18,
            borderWidth: 1,
            borderColor: 'rgba(56,189,248,0.9)',
            color: 'rgba(56,189,248,0.35)',
            opacity: 0.35,
          },
        },
      },
      parallelAxis: [
        { dim: 0, name: 'Reward', min: rewardRange[0], max: rewardRange[1] },
        { dim: 1, name: 'Ensemble affinity', min: ensAffinityRange[0], max: ensAffinityRange[1] },
        { dim: 2, name: 'Ensemble probability', min: ensProbRange[0], max: ensProbRange[1] },
        { dim: 3, name: 'Model 1 affinity', min: m1AffinityRange[0], max: m1AffinityRange[1] },
        { dim: 4, name: 'Model 1 probability', min: m1ProbRange[0], max: m1ProbRange[1] },
        { dim: 5, name: 'Model 2 affinity', min: m2AffinityRange[0], max: m2AffinityRange[1] },
        { dim: 6, name: 'Model 2 probability', min: m2ProbRange[0], max: m2ProbRange[1] },
        { dim: 7, name: 'Path', min: stepsRange[0], max: stepsRange[1] },
      ],
      visualMap: {
        show: true,
        seriesIndex: 0,
        min: rewardRange[0],
        max: rewardRange[1],
        dimension: 0,
        orient: 'vertical',
        right: 18,
        top: 'middle',
        text: ['High', 'Low'],
        textStyle: { color: chartTheme.axisText, fontSize: 10 },
        formatter: formatVisualMapValue,
        inRange: {
          color: chartTheme.axisText,
          opacity: 1,
        },
        outOfRange: {
          color: chartTheme.axisText,
          opacity: 0.02,
        },
        controller: {
          inRange: {
            color: PARALLEL_COLOR_SCALE,
            opacity: 1,
          },
          outOfRange: {
            color: ['rgba(148, 163, 184, 0.24)'],
            opacity: 0.24,
          },
        },
        calculable: true,
      },
      series: [
        {
          type: 'parallel',
          lineStyle: {
            color: chartTheme.axisText,
            width: 1,
            opacity: 0.34,
          },
          inactiveOpacity: 0.08,
          activeOpacity: 0.95,
          emphasis: {
            lineStyle: {
              width: 1.8,
              opacity: 0.9,
            },
          },
          data,
        },
      ],
    };
  }, [chartTheme, rows, sampledRows]);

  const isDownsampled = rows.length > sampledRows.length;

  const handleAxisAreaSelected = useCallback((_: unknown, chart: EChartsType) => {
    if (!onFilteredSmilesChange) return;

    const model = (chart as unknown as { getModel: () => EChartsModelLike }).getModel();
    const hasActiveSelection = Array.from({ length: PARALLEL_AXIS_COUNT }, (_, index) => {
      const axisModel = model.getComponent('parallelAxis', index) as ParallelAxisModelLike | undefined;
      return (axisModel?.activeIntervals?.length ?? 0) > 0;
    }).some(Boolean);

    if (!hasActiveSelection) {
      onFilteredSmilesChange(null);
      return;
    }

    const firstSeries = model.getSeries()[0] as ParallelSeriesModelLike | undefined;
    const activeIndices = new Set(firstSeries?.getRawIndicesByActiveState('active') ?? []);
    const filteredSmiles = sampledRows
      .filter((_, index) => activeIndices.has(index))
      .map((row) => row.smiles);

    onFilteredSmilesChange(filteredSmiles);
  }, [onFilteredSmilesChange, sampledRows]);

  const clearSelection = useCallback(() => {
    const chart = chartRef.current;
    if (!chart) return;

    for (let index = 0; index < PARALLEL_AXIS_COUNT; index += 1) {
      chart.dispatchAction({
        type: 'axisAreaSelect',
        parallelAxisIndex: index,
        intervals: [],
      });
    }

    onFilteredSmilesChange?.(null);
  }, [onFilteredSmilesChange]);

  return (
    <Card className="border-border/60 bg-card/80">
      <CardHeader className="pb-2">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="flex items-center gap-2">
            <Activity className="h-4 w-4 text-primary" />
            <CardTitle className="font-display text-base">Parallel Coordinates</CardTitle>
          </div>
          <div className="flex items-center gap-2">
            {isDownsampled ? (
              <Badge className="border-amber-400/40 bg-amber-500/15 px-1.5 py-0 text-[10px] text-amber-700 dark:text-amber-300">
                Downsampled
              </Badge>
            ) : null}
            <p className="font-data text-[10px] text-muted-foreground">
              {isDownsampled
                ? `Showing ${sampledRows.length}/${rows.length} sampled molecules`
                : `${rows.length} samples`}
            </p>
            {isFiltered ? (
              <Button variant="outline" size="sm" className="h-7 px-2.5 text-xs" onClick={clearSelection}>
                Clear selection
              </Button>
            ) : null}
          </div>
        </div>
      </CardHeader>
      <CardContent>
        {option ? (
          <div className="h-[320px] overflow-hidden rounded-md border border-border bg-background">
            <EChart
              option={option}
              className="h-full w-full"
              onChartReady={(chart) => {
                chartRef.current = chart;
              }}
              onEvents={{
                axisareaselected: handleAxisAreaSelected,
              }}
            />
          </div>
        ) : (
          <p className="text-sm text-muted-foreground">No molecule score data available for parallel coordinates.</p>
        )}
      </CardContent>
    </Card>
  );
}
