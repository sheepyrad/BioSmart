import { useMemo, useState } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import type { BoltzMetricSeries } from '@shared/types';
import Plot from 'react-plotly.js';

interface BoltzMetricsPanelProps {
  metrics: BoltzMetricSeries | null;
  isLoading?: boolean;
}

function lineChart(
  data: Array<{ label: string; color: string; values: number[] }>,
  yAxisTitle: string,
  yMax?: number
) {
  const pointCount = data[0]?.values.length ?? 0;
  const xValues = Array.from({ length: pointCount }, (_, idx) => idx + 1);
  const traces = data.map((series) => ({
    x: xValues,
    y: series.values,
    type: 'scatter',
    mode: 'lines',
    name: series.label,
    line: { color: series.color, width: 2 },
    hovertemplate: 'Molecules processed: %{x}<br>%{y:.4f}<extra>%{fullData.name}</extra>',
  }));

  return (
    <div className="h-44 w-full overflow-hidden rounded-md border border-border bg-card">
      <Plot
        data={traces as any}
        layout={{
          autosize: true,
          height: 176,
          margin: { l: 62, r: 12, t: 10, b: 46 },
          paper_bgcolor: 'rgba(0,0,0,0)',
          plot_bgcolor: '#fffdfb',
          showlegend: false,
          xaxis: {
            title: { text: 'Molecules processed' },
            automargin: true,
            zeroline: false,
            gridcolor: '#e9dfd2',
          },
          yaxis: {
            title: { text: yAxisTitle },
            automargin: true,
            rangemode: 'tozero',
            gridcolor: '#e9dfd2',
            ...(typeof yMax === 'number' && Number.isFinite(yMax) ? { range: [0, yMax * 1.05] } : {}),
          },
        } as any}
        config={{
          responsive: true,
          displaylogo: false,
          scrollZoom: true,
          modeBarButtonsToRemove: ['lasso2d', 'select2d'],
        }}
        style={{ width: '100%', height: '100%' }}
        useResizeHandler
      />
    </div>
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
    <Card>
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
              {lineChart(mainSeries, 'Binding Probability', 1)}
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
              {lineChart(thresholdSeries, 'Number of molecules', thresholdMax)}
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
