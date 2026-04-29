import { useCallback, useMemo, useRef } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
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

function downsampleByBoltzScore(rows: ParallelRow[], maxSamples: number): ParallelRow[] {
  if (rows.length <= maxSamples) return rows;
  return [...rows]
    .sort((a, b) => b.reward - a.reward)
    .slice(0, maxSamples);
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
    () => downsampleByBoltzScore(rows, maxSamples),
    [rows, maxSamples]
  );

  const option = useMemo<EChartsOption | null>(() => {
    if (sampledRows.length === 0) return null;
    const reward = sampledRows.map((row) => row.reward);
    const ensAffinity = sampledRows.map((row) => row.ensAffinity);
    const ensProb = sampledRows.map((row) => row.ensProb);
    const m1Affinity = sampledRows.map((row) => row.m1Affinity);
    const m1Prob = sampledRows.map((row) => row.m1Prob);
    const m2Affinity = sampledRows.map((row) => row.m2Affinity);
    const m2Prob = sampledRows.map((row) => row.m2Prob);
    const steps = sampledRows.map((row) => row.steps);
    const matrix = sampledRows.map((row) => [
      row.reward,
      row.ensAffinity,
      row.ensProb,
      row.m1Affinity,
      row.m1Prob,
      row.m2Affinity,
      row.m2Prob,
      row.steps,
    ]);

    const rewardRange = roundedRange(reward);
    const ensAffinityRange = roundedRange(ensAffinity);
    const ensProbRange = roundedRange(ensProb);
    const m1AffinityRange = roundedRange(m1Affinity);
    const m1ProbRange = roundedRange(m1Prob);
    const m2AffinityRange = roundedRange(m2Affinity);
    const m2ProbRange = roundedRange(m2Prob);
    const stepsRange = roundedRange(steps, true);
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
        right: 42,
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
        { dim: 1, name: 'Ens A', min: ensAffinityRange[0], max: ensAffinityRange[1] },
        { dim: 2, name: 'Ens P', min: ensProbRange[0], max: ensProbRange[1] },
        { dim: 3, name: 'M1 A', min: m1AffinityRange[0], max: m1AffinityRange[1] },
        { dim: 4, name: 'M1 P', min: m1ProbRange[0], max: m1ProbRange[1] },
        { dim: 5, name: 'M2 A', min: m2AffinityRange[0], max: m2AffinityRange[1] },
        { dim: 6, name: 'M2 P', min: m2ProbRange[0], max: m2ProbRange[1] },
        { dim: 7, name: 'Path', min: stepsRange[0], max: stepsRange[1] },
      ],
      visualMap: {
        show: true,
        min: rewardRange[0],
        max: rewardRange[1],
        dimension: 0,
        orient: 'vertical',
        right: 8,
        top: 'middle',
        text: ['High', 'Low'],
        textStyle: { color: chartTheme.axisText, fontSize: 10 },
        formatter: formatVisualMapValue,
        inRange: {
          color: ['#14385b', '#1d6f8f', '#2db7c4', '#7ed957', '#f4d35e', '#f59e0b'],
        },
        calculable: true,
      },
      series: [
        {
          type: 'parallel',
          lineStyle: {
            width: 1,
            opacity: 0.32,
          },
          emphasis: {
            lineStyle: {
              width: 1.8,
              opacity: 0.9,
            },
          },
          data: matrix,
        },
      ],
    };
  }, [chartTheme, sampledRows]);

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
