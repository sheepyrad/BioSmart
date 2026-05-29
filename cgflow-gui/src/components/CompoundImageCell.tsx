import { useEffect, useRef, useState } from 'react';
import { Check, Copy, Atom } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { useChartTheme } from '@/lib/chartTheme';

declare global {
  interface Window {
    RDKit?: {
      get_mol: (smiles: string) => {
        get_svg: (width: number, height: number) => string;
        delete: () => void;
      } | null;
      version: () => string;
    };
  }
}

interface CompoundImageCellProps {
  smiles: string;
  width?: number;
  height?: number;
  renderImage?: boolean;
}

function applyThemeToSvg(svg: string, color: string): string {
  const withoutBackground = svg.replace(/<rect[^>]*>/gi, '');
  const themed = withoutBackground
    .replace(/stroke:\s*(#000000|black)/gi, `stroke:${color}`)
    .replace(/stroke=(["'])(#000000|black)\1/gi, `stroke="${color}"`)
    .replace(/fill:\s*(#000000|black)/gi, `fill:${color}`)
    .replace(/fill=(["'])(#000000|black)\1/gi, `fill="${color}"`);

  return themed.replace(
    /<svg([^>]*)>/i,
    `<svg$1><style>rect{fill:transparent;} text{fill:${color};} path,line,polyline,polygon,circle,ellipse{stroke:${color};}</style>`
  );
}

export default function CompoundImageCell({ smiles, width = 180, height = 96, renderImage = true }: CompoundImageCellProps) {
  const theme = useChartTheme();
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [svgContent, setSvgContent] = useState<string | null>(null);
  const [pngUrl, setPngUrl] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    if (!renderImage) {
      return;
    }

    let cancelled = false;
    let retry: number | undefined;

    const render = () => {
      try {
        const rdkit = window.RDKit;
        if (!rdkit) {
          retry = window.setTimeout(render, 500);
          return;
        }

        const mol = rdkit.get_mol(smiles);
        if (!mol) {
          if (!cancelled) {
            setError('Invalid molecule');
            setSvgContent(null);
            setPngUrl(null);
          }
          return;
        }

        const svg = applyThemeToSvg(mol.get_svg(width, height), theme.text);
        mol.delete();

        if (!cancelled) {
          setSvgContent(svg);
          setError(null);
        }

        const image = new Image();
        const svgDataUrl = `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}`;

        image.onload = () => {
          if (cancelled) return;
          const canvas = canvasRef.current;
          if (!canvas) return;

          const scale = window.devicePixelRatio || 1;
          canvas.width = width * scale;
          canvas.height = height * scale;
          canvas.style.width = `${width}px`;
          canvas.style.height = `${height}px`;

          const ctx = canvas.getContext('2d');
          if (!ctx) return;
          ctx.setTransform(scale, 0, 0, scale, 0, 0);
          ctx.clearRect(0, 0, width, height);
          ctx.drawImage(image, 0, 0, width, height);

          try {
            setPngUrl(canvas.toDataURL('image/png'));
          } catch {
            // Some browsers refuse SVG-to-canvas export; the themed SVG fallback remains visible.
            setPngUrl(null);
          }
          setError(null);
        };

        image.onerror = () => {
          if (!cancelled) {
            // Keep the SVG fallback when PNG conversion fails.
            setError(null);
            setPngUrl(null);
          }
        };

        image.src = svgDataUrl;
      } catch {
        if (!cancelled) {
          setError('Render error');
          setSvgContent(null);
          setPngUrl(null);
        }
      }
    };

    render();

    return () => {
      cancelled = true;
      if (retry) window.clearTimeout(retry);
    };
  }, [height, renderImage, smiles, theme.text, width]);

  const handleCopy = async (event: React.MouseEvent<HTMLButtonElement>) => {
    event.stopPropagation();
    await navigator.clipboard.writeText(smiles);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1600);
  };

  return (
    <div className="group/cell relative flex min-h-24 w-fit max-w-full items-center justify-center rounded-md border border-border/50 bg-background px-1.5 py-1">
      <Button
        variant="outline"
        size="icon"
        className="pointer-events-none absolute right-2 top-2 z-10 h-6 w-6 bg-background/85 opacity-0 shadow-sm transition-opacity group-hover:pointer-events-auto group-hover:opacity-100 group-hover/cell:pointer-events-auto group-hover/cell:opacity-100 focus-visible:pointer-events-auto focus-visible:opacity-100"
        title="Copy SMILES"
        onClick={handleCopy}
      >
        {copied ? <Check className="h-3.5 w-3.5 text-primary" /> : <Copy className="h-3.5 w-3.5" />}
      </Button>

      {!renderImage && !pngUrl && !svgContent ? (
        <div
          className="flex items-center justify-center text-center text-[10px] text-muted-foreground/70"
          style={{ width, height }}
        >
          Release scroll to render
        </div>
      ) : pngUrl ? (
        <img
          src={pngUrl}
          alt="Compound structure"
          className="object-contain"
          style={{ width, height }}
        />
      ) : svgContent ? (
        <div
          className="[&_svg]:h-auto"
          style={{ width, height }}
          dangerouslySetInnerHTML={{ __html: svgContent }}
        />
      ) : error ? (
        <p className="px-8 text-center text-xs text-muted-foreground">{error}</p>
      ) : (
        <div className="px-8 text-center text-xs text-muted-foreground">
          <Atom className="mx-auto mb-1 h-5 w-5 animate-pulse opacity-40" />
          Rendering...
        </div>
      )}

      <canvas ref={canvasRef} className="hidden" />
    </div>
  );
}
