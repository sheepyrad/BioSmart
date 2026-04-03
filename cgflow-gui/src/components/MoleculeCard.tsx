import { useEffect, useState, useRef } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import type { MoleculeResult } from '@shared/types';
import { Atom, Copy, Check } from 'lucide-react';
import { Button } from '@/components/ui/button';

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

interface MoleculeCardProps {
  molecule: MoleculeResult;
}

export default function MoleculeCard({ molecule }: MoleculeCardProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [svgContent, setSvgContent] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    if (!molecule.smiles) return;

    const renderMolecule = () => {
      try {
        const RDKit = window.RDKit;
        if (RDKit) {
          const mol = RDKit.get_mol(molecule.smiles);
          if (mol) {
            const svg = mol.get_svg(300, 200);
            setSvgContent(svg);
            setError(null);
            mol.delete();
          } else {
            setError('Invalid SMILES');
            setSvgContent(null);
          }
        } else {
          setTimeout(renderMolecule, 500);
        }
      } catch (err) {
        console.error('Failed to render molecule:', err);
        setError('Render error');
        setSvgContent(null);
      }
    };

    renderMolecule();
  }, [molecule.smiles]);

  const handleCopy = async () => {
    await navigator.clipboard.writeText(molecule.smiles);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <Card className="overflow-hidden border-border/60 bg-card/80">
      <CardHeader className="pb-3">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Atom className="h-4 w-4 text-primary" />
            <CardTitle className="font-display text-base">Structure</CardTitle>
          </div>
          <Badge variant="success" className="font-data text-[10px] tabular-nums">
            Reward: {molecule.reward.toFixed(3)}
          </Badge>
        </div>
      </CardHeader>
      <CardContent>
        <div className="mb-4 flex h-52 items-center justify-center overflow-hidden rounded-md border border-border bg-background">
          {svgContent ? (
            <div
              dangerouslySetInnerHTML={{ __html: svgContent }}
              className="[&_svg]:h-auto [&_svg]:max-w-full p-4 [&_svg_path]:stroke-foreground/80 [&_svg_rect]:fill-transparent"
            />
          ) : error ? (
            <div className="p-4 text-center">
              <p className="text-sm text-destructive">{error}</p>
            </div>
          ) : (
            <div className="p-4 text-center">
              <Atom className="mx-auto mb-2 h-8 w-8 text-muted-foreground/40 animate-pulse" />
              <p className="text-sm text-muted-foreground">Loading structure...</p>
              <canvas ref={canvasRef} width={300} height={150} className="hidden" />
            </div>
          )}
        </div>

        <div className="space-y-2">
          <div className="flex items-center justify-between">
            <p className="text-[10px] font-semibold uppercase tracking-[0.15em] text-muted-foreground">SMILES</p>
            <Button
              variant="ghost"
              size="sm"
              onClick={handleCopy}
              className="h-6 px-2 text-xs"
            >
              {copied ? (
                <span className="flex items-center gap-1 text-primary">
                  <Check className="h-3 w-3" />
                  Copied
                </span>
              ) : (
                <span className="flex items-center gap-1">
                  <Copy className="h-3 w-3" />
                  Copy
                </span>
              )}
            </Button>
          </div>
          <div className="rounded-md border border-border bg-background p-3 font-data text-[11px] break-all leading-relaxed text-foreground/70">
            {molecule.smiles}
          </div>
        </div>
      </CardContent>
    </Card>
  );
}
