import { useMemo, useState } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import type { BoltzMetricSeries } from '@shared/types';
import EChart from '@/components/EChart';
import { TrendingUp } from 'lucide-react';
import type { EChartsOption } from 'echarts';

interface BoltzMetricsPanelProps {
  metrics: BoltzMetricSeries | null;
  isLoading?: boolean;
}

const GRID_COLOR = 'rgba(255,255,255,0.06)';
const AXIS_COLOR = 'rgba(255,255,255,0.3)';

function lineChartOption(
  data: Array<{ label: string; color: string; values: number[] }>,
  yAxisTitle: string,
  yMax?: number
): EChartsOption {
  const pointCount = data[0]?.values.length ?? 0;
  const xValues = Array.from({ length: pointCount }, (_, idx) => idx + 1);
  return {
    animation: false,
    tooltip: {
      trigger: 'axis',
      backgroundColor: 'rgba(10, 14, 28, 0.92)',
      borderColor: 'rgba(255,255,255,0.12)',
      textStyle: { color: '#d5d9e4', fontFamily: '"IBM Plex Mono", monospace', fontSize: 11 },
    },
    grid: { left: 62, right: 12, top: 10, bottom: 46 },
    xAxis: {
      type: 'category',
      data: xValues,
      name: 'Molecules processed',
      nameLocation: 'middle',
      nameGap: 30,
      axisLabel: { color: AXIS_COLOR, fontSize: 10 },
      nameTextStyle: { color: AXIS_COLOR, fontSize: 10 },
      axisLine: { lineStyle: { color: GRID_COLOR } },
      splitLine: { show: false },
    },
    yAxis: {
      type: 'value',
      name: yAxisTitle,
      nameTextStyle: { color: AXIS_COLOR, fontSize: 10 },
      axisLabel: { color: AXIS_COLOR, fontSize: 10 },
      axisLine: { lineStyle: { color: GRID_COLOR } },
      splitLine: { lineStyle: { color: GRID_COLOR } },
      min: 0,
      ...(typeof yMax === 'number' && Number.isFinite(yMax) ? { max: yMax * 1.05 } : {}),
    },
    series: data.map((series) => ({
      name: series.label,
      type: 'line',
      data: series.values,
      showSymbol: false,
      smooth: true,
      lineStyle: {
        color: series.color,
        width: 1.5,
      },
    })),
  };
}

function getMaxValue(values: number[]): number {
  let max = 1;
  for (const value of values) {
    if (value > max) max = value;
  }
  return max;
}

export default function BoltzMetricsPanel({ metrics, isLoading = false }: BoltzMetricsPanelProps) {
  const [mode, setMode] = useState<'all' | '10k'>('all');
  const visibleCount = useMemo(() => {
    if (!metrics) return 0;
    return mode === '10k' ? Math.min(10_000, metrics.pointCount) : metrics.pointCount;
  }, [metrics, mode]);

  const mainSeries = useMemo(() => {
    if (!metrics || visibleCount === 0) return null;
    return [
      { label: 'Best', color: '#00d4aa', values: metrics.bestProb.slice(0, visibleCount) },
      { label: 'Top 10 Avg', color: '#38bdf8', values: metrics.top10AvgProb.slice(0, visibleCount) },
      { label: 'Top 100 Avg', color: '#c084fc', values: metrics.top100AvgProb.slice(0, visibleCount) },
    ];
  }, [metrics, visibleCount]);

  const thresholdSeries = useMemo(() => {
    if (!metrics || visibleCount === 0) return null;
    const colors = ['#f0c040', '#fb923c', '#34d399', '#f87171'];
    return metrics.thresholds.map((threshold, idx) => ({
      label: `>${threshold.toFixed(1)}`,
      color: colors[idx % colors.length]!,
      values: (metrics.thresholdCounts[threshold.toFixed(1)] ?? []).slice(0, visibleCount),
    }));
  }, [metrics, visibleCount]);

  const thresholdMax = useMemo(() => {
    if (!thresholdSeries) return 1;
    const flattened = thresholdSeries.flatMap((entry) => entry.values);
    if (flattened.length === 0) return 1;
    return getMaxValue(flattened);
  }, [thresholdSeries]);

  return (
    <Card className="border-border/60 bg-card/80">
      <CardHeader className="pb-2">
        <div className="flex items-center justify-between gap-2">
          <div className="flex items-center gap-2">
            <TrendingUp className="h-4 w-4 text-primary" />
            <CardTitle className="font-display text-base">Boltz Score Trends</CardTitle>
          </div>
          <div className="flex gap-1">
            <Button
              variant={mode === 'all' ? 'default' : 'outline'}
              size="sm"
              onClick={() => setMode('all')}
              className="h-7 px-2.5 text-xs"
            >
              Full
            </Button>
            <Button
              variant={mode === '10k' ? 'default' : 'outline'}
              size="sm"
              onClick={() => setMode('10k')}
              className="h-7 px-2.5 text-xs"
            >
              First 10k
            </Button>
          </div>
        </div>
      </CardHeader>
      <CardContent className="space-y-3">
        {isLoading ? (
          <div className="h-44 w-full skeleton rounded" />
        ) : !metrics || metrics.pointCount === 0 || !mainSeries || !thresholdSeries ? (
          <p className="text-sm text-muted-foreground">
            No Boltz metric data available yet.
          </p>
        ) : (
          <>
            <div className="space-y-1.5">
              <div className="h-44 w-full overflow-hidden rounded-md border border-border bg-background">
                <EChart
                  option={lineChartOption(mainSeries, 'Binding Probability', 1)}
                  className="h-full w-full"
                />
              </div>
              <div className="flex gap-3 px-1 font-data text-[10px] text-muted-foreground">
                {mainSeries.map((entry) => (
                  <span key={entry.label} className="inline-flex items-center gap-1.5">
                    <span className="inline-block h-1.5 w-1.5 rounded-full" style={{ backgroundColor: entry.color }} />
                    {entry.label}
                  </span>
                ))}
              </div>
            </div>

            <div className="space-y-1.5">
              <div className="h-44 w-full overflow-hidden rounded-md border border-border bg-background">
                <EChart
                  option={lineChartOption(thresholdSeries, 'Number of molecules', thresholdMax)}
                  className="h-full w-full"
                />
              </div>
              <div className="flex gap-3 px-1 font-data text-[10px] text-muted-foreground">
                {thresholdSeries.map((entry) => (
                  <span key={entry.label} className="inline-flex items-center gap-1.5">
                    <span className="inline-block h-1.5 w-1.5 rounded-full" style={{ backgroundColor: entry.color }} />
                    {entry.label}
                  </span>
                ))}
              </div>
            </div>
          </>
        )}
      </CardContent>
    </Card>
  );
}
