'use client';

import { cva, type VariantProps } from 'class-variance-authority';
import * as React from 'react';
import { cn } from '../../lib/utils';

const labelVariants = cva(
  'flex items-center gap-2 text-sm leading-none font-medium select-none group-data-[disabled=true]:pointer-events-none group-data-[disabled=true]:opacity-50 peer-disabled:cursor-not-allowed peer-disabled:opacity-50',
  {
    variants: {
      variant: {
        default: 'text-foreground',
        muted: 'text-slate-600',
      },
    },
    defaultVariants: {
      variant: 'default',
    },
  },
);

export interface LabelProps
  extends Omit<React.ComponentProps<'label'>, 'className'>,
    VariantProps<typeof labelVariants> {}

function Label({ variant, ...props }: LabelProps) {
  return <label data-slot="label" className={cn(labelVariants({ variant }))} {...props} />;
}

export { Label };
