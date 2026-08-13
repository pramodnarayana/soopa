import { Slot } from '@radix-ui/react-slot';
import { cva, type VariantProps } from 'class-variance-authority';
import * as React from 'react';
import { cn } from '../../lib/utils';

const stackVariants = cva('flex', {
  variants: {
    direction: {
      row: 'flex-row',
      col: 'flex-col',
    },
    align: {
      start: 'items-start',
      center: 'items-center',
      end: 'items-end',
      stretch: 'items-stretch',
      baseline: 'items-baseline',
    },
    justify: {
      start: 'justify-start',
      center: 'justify-center',
      end: 'justify-end',
      between: 'justify-between',
      around: 'justify-around',
    },
    wrap: {
      wrap: 'flex-wrap',
      nowrap: 'flex-nowrap',
    },
    gap: {
      0: 'gap-0',
      1: 'gap-1',
      2: 'gap-2',
      3: 'gap-3',
      4: 'gap-4',
      6: 'gap-6',
      8: 'gap-8',
    },
  },
  defaultVariants: {
    direction: 'col',
    align: 'stretch',
    justify: 'start',
    wrap: 'nowrap',
    gap: 0,
  },
});

export interface StackProps
  extends Omit<React.HTMLAttributes<HTMLDivElement>, 'className'>,
    VariantProps<typeof stackVariants> {
  asChild?: boolean;
}

const Stack = React.forwardRef<HTMLDivElement, StackProps>(
  ({ direction, align, justify, wrap, gap, asChild = false, ...props }, ref) => {
    const Comp = asChild ? Slot : 'div';
    return (
      <Comp
        ref={ref}
        className={cn(stackVariants({ direction, align, justify, wrap, gap }))}
        {...props}
      />
    );
  },
);
Stack.displayName = 'Stack';

const HStack = React.forwardRef<HTMLDivElement, Omit<StackProps, 'direction'>>(
  ({ align = 'center', ...props }, ref) => (
    <Stack ref={ref} direction="row" align={align} {...props} />
  ),
);
HStack.displayName = 'HStack';

const VStack = React.forwardRef<HTMLDivElement, Omit<StackProps, 'direction'>>((props, ref) => (
  <Stack ref={ref} direction="col" {...props} />
));
VStack.displayName = 'VStack';

export { HStack, Stack, stackVariants, VStack };
