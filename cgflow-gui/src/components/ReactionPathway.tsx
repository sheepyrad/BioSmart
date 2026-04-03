import { FlaskConical } from 'lucide-react';
import type { TrajectoryStep } from '@shared/types';

interface ReactionPathwayProps {
  trajectory: TrajectoryStep[];
}

export default function ReactionPathway({ trajectory }: ReactionPathwayProps) {
  if (trajectory.length === 0) {
    return (
      <div className="py-8 text-center text-muted-foreground">
        <FlaskConical className="h-8 w-8 mx-auto mb-2 opacity-30" />
        <p className="text-sm">No reaction pathway available</p>
      </div>
    );
  }

  return (
    <div className="space-y-2">
      {trajectory.map((step, idx) => (
        <div
          key={step.step}
          className="grid gap-3 border-l-2 border-primary/20 pl-4 transition-colors hover:border-primary/40"
        >
          <div className="flex items-center justify-between gap-3">
            <div className="flex items-center gap-3">
              <span className="inline-flex h-6 w-6 items-center justify-center rounded-md bg-primary/10 font-data text-[11px] font-semibold text-primary">
                {step.step}
              </span>
              <div>
                <p className="text-sm font-medium">{step.action[0]}</p>
                <p className="font-data text-[10px] text-muted-foreground">Block #{step.action[1]}</p>
              </div>
            </div>
            <span className="font-data text-[10px] text-muted-foreground tabular-nums">{idx + 1}/{trajectory.length}</span>
          </div>

          {step.smiles && (
            <div className="rounded-md border border-border bg-background px-3 py-2 font-data text-[10px] break-all leading-relaxed text-foreground/70">
              {step.smiles.length > 80 ? `${step.smiles.substring(0, 80)}...` : step.smiles}
            </div>
          )}

          <div className="pb-3 text-xs text-muted-foreground">
            <span className="font-medium text-foreground/80">Fragment:</span>{' '}
            <span className="font-data text-[11px]">{step.action[2]}</span>
          </div>
        </div>
      ))}
    </div>
  );
}
