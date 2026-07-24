import { ArrowRightLeft, Plus } from 'lucide-react';
import { useState } from 'react';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from '@/components/ui/dialog';
import { InboundRouteForm } from './InboundRouteForm';

export function CreateInboundRouteModal() {
  const [isOpen, setIsOpen] = useState(false);

  return (
    <Dialog open={isOpen} onOpenChange={setIsOpen}>
      <DialogTrigger asChild>
        <Button className="flex items-center gap-2 bg-blue-600 hover:bg-blue-700 text-white rounded-xl shadow-sm">
          <Plus className="h-4 w-4" />
          Create Inbound Route
        </Button>
      </DialogTrigger>

      <DialogContent
        className="sm:max-w-[700px] rounded-2xl"
        onPointerDownOutside={(e) => e.preventDefault()}
        aria-describedby={undefined}
      >
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
