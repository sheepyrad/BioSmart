import * as React from 'react';
import { cva, type VariantProps } from 'class-variance-authority';
import { cn } from '@/lib/utils';

const badgeVariants = cva(
  'inline-flex items-center rounded-full border px-2.5 py-0.5 text-xs font-medium transition-all duration-200 focus:outline-none focus:ring-2 focus:ring-ring focus:ring-offset-2',
  {
    variants: {
      variant: {
        default: 'border-primary/30 bg-primary/10 text-primary hover:bg-primary/20',
        secondary: 'border-border bg-secondary text-secondary-foreground hover:bg-secondary/80',
        destructive: 'border-red-200 bg-red-50 text-red-600 hover:bg-red-100',
        outline: 'text-foreground border-border bg-white',
        success: 'border-green-200 bg-green-50 text-green-600 hover:bg-green-100',
        warning: 'border-yellow-200 bg-yellow-50 text-yellow-600 hover:bg-yellow-100',
      },
    },
    defaultVariants: {
      variant: 'default',
    },
  }
);

export interface BadgeProps
  extends React.HTMLAttributes<HTMLDivElement>,
    VariantProps<typeof badgeVariants> {}

function Badge({ className, variant, ...props }: BadgeProps) {
  return <div className={cn(badgeVariants({ variant }), className)} {...props} />;
}

export { Badge, badgeVariants };
