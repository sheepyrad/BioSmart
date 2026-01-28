import { useEffect, useState, useRef } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import type { MoleculeResult } from '@shared/types';
import { Atom, Copy, Check } from 'lucide-react';
import { Button } from '@/components/ui/button';

// RDKit.js type declaration
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
    <Card className="glass-card overflow-hidden">
      <CardHeader className="pb-2">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <div className="p-2 rounded-lg bg-cyan-500/10">
              <Atom className="h-4 w-4 text-cyan-500" />
            </div>
            <CardTitle className="text-base">Structure</CardTitle>
          </div>
          <Badge variant="success">
            Reward: {molecule.reward.toFixed(3)}
          </Badge>
        </div>
      </CardHeader>
      <CardContent>
        {/* Molecule visualization */}
        <motion.div 
          className="bg-gradient-to-br from-slate-50 to-white rounded-xl h-52 flex items-center justify-center mb-4 overflow-hidden border border-slate-200"
          initial={{ opacity: 0, scale: 0.95 }}
          animate={{ opacity: 1, scale: 1 }}
          transition={{ duration: 0.3 }}
        >
          <AnimatePresence mode="wait">
            {svgContent ? (
              <motion.div
                key="svg"
                initial={{ opacity: 0, scale: 0.9 }}
                animate={{ opacity: 1, scale: 1 }}
                exit={{ opacity: 0, scale: 0.9 }}
                transition={{ duration: 0.3 }}
                dangerouslySetInnerHTML={{ __html: svgContent }}
                className="[&_svg]:max-w-full [&_svg]:h-auto p-4"
              />
            ) : error ? (
              <motion.div
                key="error"
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                exit={{ opacity: 0 }}
                className="text-center p-4"
              >
                <p className="text-sm text-destructive">{error}</p>
              </motion.div>
            ) : (
              <motion.div
                key="loading"
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                exit={{ opacity: 0 }}
                className="text-center p-4"
              >
                <motion.div
                  animate={{
                    rotate: 360,
                  }}
                  transition={{
                    duration: 2,
                    repeat: Infinity,
                    ease: 'linear',
                  }}
                >
                  <Atom className="h-8 w-8 text-muted-foreground/50 mx-auto mb-2" />
                </motion.div>
                <p className="text-sm text-muted-foreground">Loading structure...</p>
                <canvas ref={canvasRef} width={300} height={150} className="hidden" />
              </motion.div>
            )}
          </AnimatePresence>
        </motion.div>

        {/* SMILES string */}
        <div className="space-y-2">
          <div className="flex items-center justify-between">
            <p className="text-xs font-medium text-muted-foreground uppercase tracking-wide">SMILES</p>
            <Button
              variant="ghost"
              size="sm"
              onClick={handleCopy}
              className="h-6 px-2 text-xs"
            >
              <AnimatePresence mode="wait">
                {copied ? (
                  <motion.div
                    key="check"
                    initial={{ scale: 0 }}
                    animate={{ scale: 1 }}
                    exit={{ scale: 0 }}
                    className="flex items-center gap-1 text-green-500"
                  >
                    <Check className="h-3 w-3" />
                    Copied
                  </motion.div>
                ) : (
                  <motion.div
                    key="copy"
                    initial={{ scale: 0 }}
                    animate={{ scale: 1 }}
                    exit={{ scale: 0 }}
                    className="flex items-center gap-1"
                  >
                    <Copy className="h-3 w-3" />
                    Copy
                  </motion.div>
                )}
              </AnimatePresence>
            </Button>
          </div>
          <motion.div 
            className="bg-slate-50 p-3 rounded-lg font-mono text-xs break-all border border-slate-200"
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.1 }}
          >
            {molecule.smiles}
          </motion.div>
        </div>
      </CardContent>
    </Card>
  );
}
