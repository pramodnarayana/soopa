import { Button, buttonVariants } from '@soopa/ui/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from '@soopa/ui/components/ui/dialog';
import { ArrowRightLeft, Plus } from 'lucide-react';
import { useState } from 'react';
import { InboundRouteForm } from './InboundRouteForm';

export function CreateInboundRouteModal() {
  const [isOpen, setIsOpen] = useState(false);

  return (
    <Dialog open={isOpen} onOpenChange={setIsOpen}>
      <DialogTrigger className={buttonVariants({ size: 'cta' })}>
        <Plus className="h-4 w-4" />
        Create Inbound Route
      </DialogTrigger>

      <DialogContent className="sm:max-w-[700px] rounded-2xl" aria-describedby={undefined}>
        <DialogHeader>
          <DialogTitle className="text-xl flex items-center gap-2">
            <div className="w-8 h-8 rounded-lg bg-blue-50 flex items-center justify-center text-blue-600">
              <ArrowRightLeft className="w-4 h-4" />
            </div>
            Create Inbound Route (From EDI)
          </DialogTitle>
        </DialogHeader>

        <div className="flex flex-col h-full py-2">
          <InboundRouteForm onSuccess={() => setIsOpen(false)} />
        </div>
      </DialogContent>
    </Dialog>
  );
}
