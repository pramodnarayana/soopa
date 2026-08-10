import { Button, buttonVariants } from '@soopa/ui/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from '@soopa/ui/components/ui/dialog';
import { Network, Plus } from 'lucide-react';
import { useState } from 'react';
import { CreateEdiHeaderForm } from './CreateEdiHeaderForm';

export function CreateEdiHeaderModal() {
  const [isOpen, setIsOpen] = useState(false);

  return (
    <Dialog open={isOpen} onOpenChange={setIsOpen}>
      <DialogTrigger className={buttonVariants({ size: 'cta' })}>
        <Plus className="h-4 w-4" />
        Create EDI Header
      </DialogTrigger>

      <DialogContent className="sm:max-w-[700px] rounded-2xl">
        <DialogHeader>
          <DialogTitle className="text-xl flex items-center gap-2">
            <div className="w-8 h-8 rounded-lg bg-indigo-50 flex items-center justify-center text-indigo-600">
              <Network className="w-4 h-4" />
            </div>
            Create EDI Header
          </DialogTitle>
        </DialogHeader>

        <div className="flex flex-col h-full py-2">
          <CreateEdiHeaderForm onSuccess={() => setIsOpen(false)} />
        </div>
      </DialogContent>
    </Dialog>
  );
}
