import { useMemo, useState } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import type { BoltzMetricSeries } from '@shared/types';

interface BoltzMetricsPanelProps {
  metrics: BoltzMetricSeries | null;
  isLoading?: boolean;
}

function buildPath(values: number[], width: number, height: number, yMax: number) {
  if (values.length === 0 || yMax <= 0) return '';
  const points = values.map((value, idx) => {
    const x = values.length === 1 ? 0 : (idx / (values.length - 1)) * width;
    const y = height - (Math.max(0, value) / yMax) * height;
    return `${x.toFixed(2)},${y.toFixed(2)}`;
  });
  return `M ${points.join(' L ')}`;
}

function lineChart(data: Array<{ label: string; color: string; values: number[] }>, yMax: number) {
  const width = 900;
  const height = 180;
  return (
    <svg viewBox={`0 0 ${width} ${height}`} className="w-full h-44 rounded bg-slate-50">
      {data.map((series) => (
        <path
          key={series.label}
          d={buildPath(series.values, width, height, yMax)}
          fill="none"
          stroke={series.color}
          strokeWidth={2}
        />
      ))}
    </svg>
  );
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
      { label: 'Best', color: '#2563eb', values: metrics.bestProb.slice(0, visibleCount) },
      { label: 'Top 10 Avg', color: '#16a34a', values: metrics.top10AvgProb.slice(0, visibleCount) },
      { label: 'Top 100 Avg', color: '#9333ea', values: metrics.top100AvgProb.slice(0, visibleCount) },
    ];
  }, [metrics, visibleCount]);

  const thresholdSeries = useMemo(() => {
    if (!metrics || visibleCount === 0) return null;
    const colors = ['#ea580c', '#f59e0b', '#14b8a6', '#ef4444'];
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
    <Card className="glass-card">
      <CardHeader className="pb-2">
        <div className="flex items-center justify-between gap-2">
          <CardTitle className="text-base">Boltz Score Trends</CardTitle>
          <div className="flex gap-1">
            <Button
              variant={mode === 'all' ? 'default' : 'outline'}
              size="sm"
              onClick={() => setMode('all')}
            >
              Full
            </Button>
            <Button
              variant={mode === '10k' ? 'default' : 'outline'}
              size="sm"
              onClick={() => setMode('10k')}
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
            No Boltz metric data available for this run yet.
          </p>
        ) : (
          <>
            <div className="space-y-1">
              {lineChart(mainSeries, 1)}
              <div className="flex gap-3 text-xs text-muted-foreground">
                {mainSeries.map((entry) => (
                  <span key={entry.label} className="inline-flex items-center gap-1">
                    <span className="inline-block h-2 w-2 rounded-full" style={{ backgroundColor: entry.color }} />
                    {entry.label}
                  </span>
                ))}
              </div>
            </div>

            <div className="space-y-1">
              {lineChart(thresholdSeries, thresholdMax)}
              <div className="flex gap-3 text-xs text-muted-foreground">
                {thresholdSeries.map((entry) => (
                  <span key={entry.label} className="inline-flex items-center gap-1">
                    <span className="inline-block h-2 w-2 rounded-full" style={{ backgroundColor: entry.color }} />
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
