import { cva, type VariantProps } from 'class-variance-authority';
import type { LucideIcon, LucideProps } from 'lucide-react';
import * as React from 'react';
import { cn } from '../../lib/utils';

const iconVariants = cva('', {
  variants: {
    size: {
      default: 'h-5 w-5',
      xs: 'h-3 w-3',
      sm: 'h-4 w-4',
      md: 'h-5 w-5',
      lg: 'h-6 w-6',
      xl: 'h-8 w-8',
    },
    color: {
      default: 'text-slate-900 dark:text-slate-100',
      muted: 'text-slate-500 dark:text-slate-400',
      primary: 'text-indigo-600 dark:text-indigo-400',
      success: 'text-emerald-600 dark:text-emerald-400',
      warning: 'text-amber-600 dark:text-amber-400',
      destructive: 'text-red-600 dark:text-red-400',
    },
  },
  defaultVariants: {
    size: 'default',
    color: 'default',
  },
});

export interface IconProps
  extends Omit<LucideProps, 'className' | 'color' | 'size'>,
    VariantProps<typeof iconVariants> {
  icon: LucideIcon;
}

export function Icon({ icon: LucideIconComponent, size, color, ...props }: IconProps) {
  return <LucideIconComponent className={cn(iconVariants({ size, color }))} {...props} />;
}
