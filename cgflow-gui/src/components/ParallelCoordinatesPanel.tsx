import { useCallback, useMemo, useRef } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Activity } from 'lucide-react';
import type { MoleculeResult } from '@shared/types';
import EChart from '@/components/EChart';
import type { EChartsOption, EChartsType } from 'echarts';

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

function downsampleEvenly<T>(rows: T[], maxSamples: number): T[] {
  if (rows.length <= maxSamples) return rows;
  const stride = rows.length / maxSamples;
  const sampled: T[] = [];
  for (let i = 0; i < maxSamples; i += 1) {
    sampled.push(rows[Math.floor(i * stride)] as T);
  }
  return sampled;
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
  maxSamples = 1200,
  onFilteredSmilesChange,
  isFiltered = false,
}: ParallelCoordinatesPanelProps) {
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
    () => downsampleEvenly(rows, maxSamples),
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

    const rewardRange = getRange(reward);
    return {
      animation: false,
      textStyle: {
        fontFamily: '"IBM Plex Mono", monospace',
        color: 'rgba(255,255,255,0.62)',
      },
      tooltip: {
        trigger: 'item',
        backgroundColor: 'rgba(10, 14, 28, 0.92)',
        borderColor: 'rgba(255,255,255,0.12)',
        textStyle: { color: '#d5d9e4', fontFamily: '"IBM Plex Mono", monospace', fontSize: 11 },
      },
      parallel: {
        left: 54,
        right: 48,
        top: 26,
        bottom: 28,
        parallelAxisDefault: {
          type: 'value',
            realtime: false,
          nameLocation: 'end',
          nameGap: 10,
          nameTextStyle: { color: 'rgba(255,255,255,0.72)', fontSize: 10 },
          axisLabel: { color: 'rgba(255,255,255,0.55)', fontSize: 9 },
          axisLine: { lineStyle: { color: 'rgba(255,255,255,0.22)' } },
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
        { dim: 1, name: 'Ens A', min: getRange(ensAffinity)[0], max: getRange(ensAffinity)[1] },
        { dim: 2, name: 'Ens P', min: getRange(ensProb)[0], max: getRange(ensProb)[1] },
        { dim: 3, name: 'M1 A', min: getRange(m1Affinity)[0], max: getRange(m1Affinity)[1] },
        { dim: 4, name: 'M1 P', min: getRange(m1Prob)[0], max: getRange(m1Prob)[1] },
        { dim: 5, name: 'M2 A', min: getRange(m2Affinity)[0], max: getRange(m2Affinity)[1] },
        { dim: 6, name: 'M2 P', min: getRange(m2Prob)[0], max: getRange(m2Prob)[1] },
        { dim: 7, name: 'Steps', min: getRange(steps)[0], max: getRange(steps)[1] },
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
        textStyle: { color: 'rgba(255,255,255,0.62)', fontSize: 10 },
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
            opacity: 0.25,
          },
          emphasis: {
            lineStyle: {
              width: 1.8,
              opacity: 0.8,
            },
          },
          data: matrix,
        },
      ],
    };
  }, [sampledRows]);

  const isDownsampled = rows.length > sampledRows.length;

  const handleAxisAreaSelected = useCallback((_: unknown, chart: EChartsType) => {
    if (!onFilteredSmilesChange) return;

    const model = chart.getModel() as unknown as EChartsModelLike;
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
                ? `Showing ${sampledRows.length}/${rows.length} (downsampled)`
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
          <div className="h-[360px] overflow-hidden rounded-md border border-border bg-background">
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
