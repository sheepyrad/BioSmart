import { useMemo, useState } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import type { BoltzMetricSeries } from '@shared/types';
import EChart from '@/components/EChart';
import { TrendingUp } from 'lucide-react';
import type { EChartsOption } from 'echarts';
import { useChartTheme } from '@/lib/chartTheme';
import { cn } from '@/lib/utils';

interface BoltzMetricsPanelProps {
  metrics: BoltzMetricSeries | null;
  isLoading?: boolean;
  className?: string;
  chartHeight?: number;
}

function formatAxisValue(value: number | string): string {
  const numeric = typeof value === 'number' ? value : Number(value);
  if (!Number.isFinite(numeric)) return String(value);
  if (Math.abs(numeric) >= 1000) return Math.round(numeric).toLocaleString();
  if (Number.isInteger(numeric)) return String(numeric);
  return numeric.toFixed(2).replace(/\.?0+$/, '');
}

function getNiceStep(value: number): number {
  if (value <= 0) return 1;
  const magnitude = 10 ** Math.floor(Math.log10(value));
  const normalized = value / magnitude;
  if (normalized <= 1) return magnitude;
  if (normalized <= 2.5) return 2 * magnitude;
  if (normalized <= 5) return 5 * magnitude;
  return 10 * magnitude;
}

function formatWholeNumber(value: number | string): string {
  const numeric = typeof value === 'number' ? value : Number(value);
  if (!Number.isFinite(numeric)) return String(value);
  return Math.round(numeric).toLocaleString();
}

function lineChartOption(
  data: Array<{ label: string; color: string; values: number[] }>,
  yAxisTitle: string,
  theme: ReturnType<typeof useChartTheme>,
  yMax?: number
): EChartsOption {
  const pointCount = data[0]?.values.length ?? 0;
  const xValues = Array.from({ length: pointCount }, (_, idx) => idx + 1);
  const xTickStep = getNiceStep(pointCount / 6);
  const yAxisMax =
    typeof yMax === 'number' && Number.isFinite(yMax)
      ? yMax <= 1
        ? 1
        : Math.ceil(yMax * 1.05)
      : undefined;
  return {
    animation: false,
    tooltip: {
      trigger: 'axis',
      backgroundColor: theme.tooltipBackground,
      borderColor: theme.tooltipBorder,
      textStyle: { color: theme.tooltipText, fontFamily: '"IBM Plex Mono", monospace', fontSize: 12 },
    },
    legend: {
      top: 10,
      right: 16,
      itemWidth: 10,
      itemHeight: 7,
      textStyle: { color: theme.axisText, fontSize: 11, fontFamily: '"IBM Plex Mono", monospace' },
    },
    grid: { left: 62, right: 24, top: 46, bottom: 46, containLabel: true },
    xAxis: {
      type: 'category',
      data: xValues,
      name: 'Molecules processed',
      nameLocation: 'middle',
      nameGap: 24,
      axisLabel: {
        color: theme.axisText,
        fontSize: 11,
        interval: (_index: number, value: string) => {
          const numeric = Number(value);
          if (!Number.isFinite(numeric)) return false;
          if (pointCount <= 12) return true;
          return numeric === 1 || numeric % xTickStep === 0;
        },
        formatter: formatWholeNumber,
      },
      nameTextStyle: { color: theme.axisText, fontSize: 11 },
      axisLine: { lineStyle: { color: theme.grid } },
      splitLine: { show: false },
    },
    yAxis: {
      type: 'value',
      name: yAxisTitle,
      nameLocation: 'middle',
      nameRotate: 90,
      nameGap: 44,
      nameTextStyle: { color: theme.axisText, fontSize: 11, align: 'center' },
      axisLabel: { color: theme.axisText, fontSize: 11, formatter: formatAxisValue },
      axisLine: { lineStyle: { color: theme.grid } },
      splitLine: { lineStyle: { color: theme.grid } },
      min: 0,
      ...(yAxisMax !== undefined ? { max: yAxisMax } : {}),
    },
    series: data.map((series) => ({
      name: series.label,
      type: 'line',
      data: series.values,
      showSymbol: false,
      smooth: true,
      lineStyle: {
        color: series.color,
        width: 2,
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

export default function BoltzMetricsPanel({
  metrics,
  isLoading = false,
  className,
  chartHeight = 224,
}: BoltzMetricsPanelProps) {
  const chartTheme = useChartTheme();
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
    <Card className={cn('flex min-h-0 flex-col border-border/60 bg-card/80', className)}>
      <CardHeader className="shrink-0 pb-1">
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
      <CardContent className="px-4 pb-4 pt-2">
        {isLoading ? (
          <div className="w-full skeleton rounded" style={{ height: chartHeight }} />
        ) : !metrics || metrics.pointCount === 0 || !mainSeries || !thresholdSeries ? (
          <p className="text-sm text-muted-foreground">
            No Boltz metric data available yet.
          </p>
        ) : (
          <div className="grid gap-3 xl:grid-cols-2">
            <div className="w-full overflow-hidden rounded-md border border-border bg-background" style={{ height: chartHeight }}>
                <EChart
                  option={lineChartOption(mainSeries, 'Binding Probability', chartTheme, 1)}
                  className="h-full w-full"
                />
            </div>

            <div className="w-full overflow-hidden rounded-md border border-border bg-background" style={{ height: chartHeight }}>
                <EChart
                  option={lineChartOption(thresholdSeries, 'Number of molecules', chartTheme, thresholdMax)}
                  className="h-full w-full"
                />
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
