import { useEffect, useRef } from 'react';
import ReactECharts, { type EChartsReactProps } from 'echarts-for-react';
import type { EChartsOption, EChartsType } from 'echarts';

interface EChartProps {
  option: EChartsOption;
  className?: string;
  onChartReady?: (chart: EChartsType) => void;
  onEvents?: EChartsReactProps['onEvents'];
}

export default function EChart({ option, className, onChartReady, onEvents }: EChartProps) {
  const chartRef = useRef<EChartsType | null>(null);
  const containerRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;

    const resizeObserver = new ResizeObserver(() => {
      chartRef.current?.resize();
    });
    resizeObserver.observe(el);

    return () => {
      resizeObserver.disconnect();
      chartRef.current = null;
    };
  }, []);

  return (
    <div ref={containerRef} className={className}>
      <ReactECharts
        option={option}
        notMerge
        lazyUpdate
        autoResize
        onEvents={onEvents}
        opts={{ renderer: 'svg' }}
        style={{ height: '100%', width: '100%' }}
        onChartReady={(chart) => {
          chartRef.current = chart;
          onChartReady?.(chart);
        }}
      />
    </div>
  );
}
