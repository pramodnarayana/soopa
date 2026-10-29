import { Plus } from 'lucide-react';
import React, { type ReactNode } from 'react';
import { cn } from '../../lib/utils';
import { Button, buttonVariants } from './button';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger } from './dialog';

export interface FormModalProps {
  readonly title: string;
  readonly triggerText: string;
  readonly triggerIcon?: ReactNode;
  readonly icon?: ReactNode;
  readonly isOpen: boolean;
  readonly onOpenChange: (open: boolean) => void;
  readonly onSubmit: React.FormEventHandler<HTMLFormElement>;
  readonly isPending: boolean;
  readonly submitText?: string;
  readonly children: ReactNode;
  readonly submitDisabled?: boolean;
  readonly maxWidth?: string;
  readonly footerContent?: ReactNode;
}

export function FormModal({
  title,
  triggerText,
  triggerIcon = <Plus className="h-5 w-5" />,
  icon,
  isOpen,
  onOpenChange,
  onSubmit,
  isPending,
  submitText = 'Save',
  children,
  submitDisabled = false,
  maxWidth = 'sm:max-w-xl',
  footerContent,
}: FormModalProps) {
  return (
    <Dialog open={isOpen} onOpenChange={onOpenChange} modal={false}>
      <DialogTrigger className={buttonVariants({ size: 'cta' })}>
        {triggerIcon}
        {triggerText}
      </DialogTrigger>

      <DialogContent className={cn('rounded-2xl', maxWidth)}>
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2 text-xl">
            {icon ? (
              <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-accent text-accent-foreground">
                {icon}
              </div>
            ) : null}
            {title}
          </DialogTitle>
        </DialogHeader>

        <form onSubmit={onSubmit} className="grid gap-6 py-4">
          {children}

          <div className="mt-2 flex items-center justify-between">
            <div>{footerContent}</div>
            <Button type="submit" size="cta" disabled={isPending || submitDisabled}>
              {isPending ? 'Saving...' : submitText}
            </Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
}
