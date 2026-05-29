import { useEffect, useState } from 'react';

interface ChartTheme {
  text: string;
  axisText: string;
  grid: string;
  tooltipBackground: string;
  tooltipBorder: string;
  tooltipText: string;
}

const fallbackTheme: ChartTheme = {
  text: 'hsl(222 24% 14% / 0.82)',
  axisText: 'hsl(218 11% 43% / 0.9)',
  grid: 'hsl(214 20% 84% / 0.75)',
  tooltipBackground: 'hsl(0 0% 100% / 0.98)',
  tooltipBorder: 'hsl(214 20% 84%)',
  tooltipText: 'hsl(222 24% 14% / 0.95)',
};

function cssColor(name: string, alpha = 1, fallback: string): string {
  if (typeof window === 'undefined') return fallback;
  const raw = window.getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return raw ? `hsl(${raw} / ${alpha})` : fallback;
}

function readChartTheme(): ChartTheme {
  return {
    text: cssColor('--foreground', 0.82, fallbackTheme.text),
    axisText: cssColor('--muted-foreground', 0.92, fallbackTheme.axisText),
    grid: cssColor('--border', 0.75, fallbackTheme.grid),
    tooltipBackground: cssColor('--popover', 0.98, fallbackTheme.tooltipBackground),
    tooltipBorder: cssColor('--border', 1, fallbackTheme.tooltipBorder),
    tooltipText: cssColor('--popover-foreground', 0.95, fallbackTheme.tooltipText),
  };
}

export function useChartTheme(): ChartTheme {
  const [theme, setTheme] = useState<ChartTheme>(() => readChartTheme());

  useEffect(() => {
    const updateTheme = () => setTheme(readChartTheme());
    updateTheme();

    const observer = new MutationObserver(updateTheme);
    observer.observe(document.documentElement, {
      attributes: true,
      attributeFilter: ['class', 'style'],
    });

    return () => observer.disconnect();
  }, []);

  return theme;
}
