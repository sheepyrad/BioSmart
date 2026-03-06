import { FlaskConical } from 'lucide-react';
import type { TrajectoryStep } from '@shared/types';

interface ReactionPathwayProps {
  trajectory: TrajectoryStep[];
}

export default function ReactionPathway({ trajectory }: ReactionPathwayProps) {
  if (trajectory.length === 0) {
    return (
      <div className="py-8 text-center text-muted-foreground">
        <FlaskConical className="h-8 w-8 mx-auto mb-2 opacity-50" />
        <p className="text-sm">No reaction pathway available</p>
      </div>
    );
  }

  return (
    <div className="space-y-3">
      {trajectory.map((step, idx) => (
        <div
          key={step.step}
          className="grid gap-3 border-l border-border pl-4"
        >
          <div className="flex items-center justify-between gap-3">
            <div className="flex items-center gap-3">
              <span className="inline-flex h-7 w-7 items-center justify-center rounded-md border border-border bg-muted/45 text-sm font-medium">
                {step.step}
              </span>
              <div>
                <p className="text-sm font-medium">{step.action[0]}</p>
                <p className="text-xs text-muted-foreground">Block #{step.action[1]}</p>
              </div>
            </div>
            <span className="text-xs text-muted-foreground">{idx + 1} of {trajectory.length}</span>
          </div>

          {step.smiles && (
            <div className="rounded-md border border-border bg-muted/35 px-3 py-2 font-mono text-xs break-all">
              {step.smiles.length > 80 ? `${step.smiles.substring(0, 80)}...` : step.smiles}
            </div>
          )}

          <div className="pb-4 text-xs text-muted-foreground">
            <span className="font-medium text-foreground">Fragment:</span>{' '}
            <span className="font-mono">{step.action[2]}</span>
          </div>
        </div>
      ))}
    </div>
  );
}
