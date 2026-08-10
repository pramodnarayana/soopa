import { Button, buttonVariants } from '@soopa/ui/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from '@soopa/ui/components/ui/dialog';
import { Plus } from 'lucide-react';
import type { ReactNode } from 'react';

interface FormModalProps {
  title: string;
  triggerText: string;
  triggerIcon?: ReactNode;
  icon?: ReactNode;
  isOpen: boolean;
  onOpenChange: (open: boolean) => void;
  onSubmit: React.FormEventHandler<HTMLFormElement>;
  isPending: boolean;
  submitText?: string;
  children: ReactNode;
  submitDisabled?: boolean;
  maxWidth?: string;
  footerContent?: ReactNode;
}

export function FormModal({
  title,
  triggerText,
  triggerIcon = <Plus className="w-5 h-5" />,
  icon,
  isOpen,
  onOpenChange,
  onSubmit,
  isPending,
  submitText = 'Save',
  children,
  submitDisabled = false,
  maxWidth = 'sm:max-w-[600px]',
  footerContent,
}: FormModalProps) {
  return (
    <Dialog open={isOpen} onOpenChange={onOpenChange} modal={false}>
      <DialogTrigger className={buttonVariants({ size: 'cta' })}>
        {triggerIcon}
        {triggerText}
      </DialogTrigger>

      <DialogContent className={`${maxWidth} rounded-2xl`}>
        <DialogHeader>
          <DialogTitle className="text-xl flex items-center gap-2">
            {icon && (
              <div className="w-8 h-8 rounded-lg bg-indigo-50 flex items-center justify-center text-indigo-600">
                {icon}
              </div>
            )}
            {title}
          </DialogTitle>
        </DialogHeader>

        <form onSubmit={onSubmit} className="grid gap-6 py-4">
          {children}

          <div className="flex justify-between items-center mt-2">
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
