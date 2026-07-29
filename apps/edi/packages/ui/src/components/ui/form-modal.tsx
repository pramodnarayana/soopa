import { Button } from '@soopa/ui/components/ui/button';
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
  onSubmit: (e: React.FormEvent<HTMLFormElement>) => void;
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
  triggerIcon = <Plus className="h-4 w-4" />,
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
      <DialogTrigger
        render={
          <Button className="flex items-center gap-2 bg-indigo-600 hover:bg-indigo-700 text-white rounded-xl shadow-sm" />
        }
      >
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
            <Button
              type="submit"
              disabled={isPending || submitDisabled}
              className="h-11 px-8 text-base font-semibold shadow-sm rounded-xl bg-indigo-600 hover:bg-indigo-700 text-white disabled:opacity-50"
            >
              {isPending ? 'Saving...' : submitText}
            </Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
}
