import { motion } from 'framer-motion';
import { Badge } from '@/components/ui/badge';
import { ArrowRight, ChevronRight, FlaskConical, Beaker } from 'lucide-react';
import type { TrajectoryStep } from '@shared/types';

interface ReactionPathwayProps {
  trajectory: TrajectoryStep[];
}

const stepVariants = {
  hidden: { opacity: 0, x: -20 },
  visible: (i: number) => ({
    opacity: 1,
    x: 0,
    transition: {
      delay: i * 0.1,
      duration: 0.3,
      ease: 'easeOut',
    },
  }),
};

export default function ReactionPathway({ trajectory }: ReactionPathwayProps) {
  if (trajectory.length === 0) {
    return (
      <div className="text-center py-8 text-muted-foreground">
        <FlaskConical className="h-8 w-8 mx-auto mb-2 opacity-50" />
        <p className="text-sm">No reaction pathway available</p>
      </div>
    );
  }

  return (
    <div className="space-y-3">
      {trajectory.map((step, idx) => (
        <motion.div
          key={step.step}
          variants={stepVariants}
          initial="hidden"
          animate="visible"
          custom={idx}
          className="flex items-start gap-3 group"
        >
          {/* Step number with connecting line */}
          <div className="flex flex-col items-center">
            <motion.div
              className="w-8 h-8 rounded-full bg-gradient-to-br from-primary/20 to-primary/5 border border-primary/30 flex items-center justify-center shadow-sm"
              whileHover={{ scale: 1.1 }}
              transition={{ duration: 0.2 }}
            >
              <span className="text-sm font-semibold text-primary">{step.step}</span>
            </motion.div>
            {idx < trajectory.length - 1 && (
              <motion.div
                className="w-0.5 h-full min-h-[40px] bg-gradient-to-b from-primary/30 to-transparent mt-1"
                initial={{ scaleY: 0 }}
                animate={{ scaleY: 1 }}
                transition={{ delay: idx * 0.1 + 0.2, duration: 0.3 }}
              />
            )}
          </div>

          {/* Step content */}
          <div className="flex-1 min-w-0 pb-4">
            <div className="flex items-center gap-2 mb-2">
              <Badge variant="default" className="text-xs font-medium">
                {step.action[0]}
              </Badge>
              <span className="text-xs text-muted-foreground">
                Block #{step.action[1]}
              </span>
            </div>

            {/* SMILES at this step */}
            {step.smiles && (
              <motion.div
                className="bg-slate-50 rounded-lg px-3 py-2 font-mono text-xs break-all border border-slate-200"
                initial={{ opacity: 0, y: 5 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: idx * 0.1 + 0.1 }}
              >
                {step.smiles.length > 80
                  ? `${step.smiles.substring(0, 80)}...`
                  : step.smiles}
              </motion.div>
            )}

            {/* Fragment added */}
            <motion.div
              className="mt-2 flex items-center gap-1.5 text-xs"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              transition={{ delay: idx * 0.1 + 0.15 }}
            >
              <ChevronRight className="h-3 w-3 text-green-500" />
              <span className="text-muted-foreground">Fragment:</span>
              <span className="font-mono text-green-500/90 bg-green-500/10 px-1.5 py-0.5 rounded">
                {step.action[2]}
              </span>
            </motion.div>
          </div>
        </motion.div>
      ))}

      {/* Visual pathway diagram */}
      <motion.div
        className="mt-4 pt-4 border-t border-border/50"
        initial={{ opacity: 0, y: 10 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: trajectory.length * 0.1 }}
      >
        <div className="flex items-center gap-2 mb-3">
          <Beaker className="h-4 w-4 text-muted-foreground" />
          <p className="text-xs font-medium text-muted-foreground uppercase tracking-wide">Synthesis Flow</p>
        </div>
        <div className="flex items-center flex-wrap gap-1.5 p-3 bg-slate-50 rounded-lg border border-slate-200">
          <motion.div
            className="px-2.5 py-1 bg-muted rounded-md text-xs font-medium border border-border/50"
            initial={{ scale: 0 }}
            animate={{ scale: 1 }}
            transition={{ delay: trajectory.length * 0.1 + 0.1 }}
          >
            Start
          </motion.div>
          {trajectory.map((step, idx) => (
            <motion.div
              key={step.step}
              className="flex items-center gap-1.5"
              initial={{ opacity: 0, x: -10 }}
              animate={{ opacity: 1, x: 0 }}
              transition={{ delay: trajectory.length * 0.1 + 0.15 + idx * 0.05 }}
            >
              <ArrowRight className="h-3 w-3 text-muted-foreground" />
              <div className="px-2.5 py-1 bg-primary/10 rounded-md text-xs border border-primary/20">
                <span className="font-medium text-primary">{step.action[0]}</span>
              </div>
            </motion.div>
          ))}
          <motion.div
            className="flex items-center gap-1.5"
            initial={{ opacity: 0, x: -10 }}
            animate={{ opacity: 1, x: 0 }}
            transition={{ delay: trajectory.length * 0.1 + 0.15 + trajectory.length * 0.05 }}
          >
            <ArrowRight className="h-3 w-3 text-muted-foreground" />
            <div className="px-2.5 py-1 bg-green-500/10 rounded-md text-xs font-medium text-green-500 border border-green-500/20">
              Product
            </div>
          </motion.div>
        </div>
      </motion.div>
    </div>
  );
}
