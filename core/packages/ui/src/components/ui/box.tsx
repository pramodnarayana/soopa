import { Slot } from '@radix-ui/react-slot';
import { cva, type VariantProps } from 'class-variance-authority';
import * as React from 'react';
import { cn } from '../../lib/utils';

const boxVariants = cva('', {
  variants: {
    p: {
      0: 'p-0',
      1: 'p-1',
      2: 'p-2',
      3: 'p-3',
      4: 'p-4',
      6: 'p-6',
      8: 'p-8',
    },
    m: {
      0: 'm-0',
      1: 'm-1',
      2: 'm-2',
      3: 'm-3',
      4: 'm-4',
      6: 'm-6',
      8: 'm-8',
    },
    bg: {
      default: 'bg-white dark:bg-slate-950',
      muted: 'bg-slate-50 dark:bg-slate-900',
      primary: 'bg-indigo-50 dark:bg-indigo-900/20',
      transparent: 'bg-transparent',
    },
    border: {
      none: 'border-none',
      default: 'border border-slate-200 dark:border-slate-800',
      primary: 'border border-indigo-200 dark:border-indigo-800',
    },
    rounded: {
      none: 'rounded-none',
      sm: 'rounded-sm',
      md: 'rounded-md',
      lg: 'rounded-lg',
      xl: 'rounded-xl',
      full: 'rounded-full',
    },
  },
  defaultVariants: {},
});

export interface BoxProps
  extends Omit<React.HTMLAttributes<HTMLDivElement>, 'className'>,
    VariantProps<typeof boxVariants> {
  asChild?: boolean;
}

const Box = React.forwardRef<HTMLDivElement, BoxProps>(
  ({ p, m, bg, border, rounded, asChild = false, ...props }, ref) => {
    const Comp = asChild ? Slot : 'div';
    return <Comp ref={ref} className={cn(boxVariants({ p, m, bg, border, rounded }))} {...props} />;
  },
);
Box.displayName = 'Box';

export { Box, boxVariants };
