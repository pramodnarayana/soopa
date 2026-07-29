import { Button } from '@soopa/ui/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from '@soopa/ui/components/ui/dialog';
import { ArrowLeftRight, Plus } from 'lucide-react';
import { useState } from 'react';
import { OutboundRouteForm } from './OutboundRouteForm';

export function CreateOutboundRouteModal() {
  const [isOpen, setIsOpen] = useState(false);

  return (
    <Dialog open={isOpen} onOpenChange={setIsOpen}>
      <DialogTrigger
        render={
          <Button className="flex items-center gap-2 bg-emerald-600 hover:bg-emerald-700 text-white rounded-xl shadow-sm" />
        }
      >
        <Plus className="h-4 w-4" />
        Create Outbound Route
      </DialogTrigger>

      <DialogContent className="sm:max-w-[700px] rounded-2xl">
        <DialogHeader>
          <DialogTitle className="text-xl flex items-center gap-2">
            <div className="w-8 h-8 rounded-lg bg-emerald-50 flex items-center justify-center text-emerald-600">
              <ArrowLeftRight className="w-4 h-4" />
            </div>
            Create Outbound Route (From JSON)
          </DialogTitle>
        </DialogHeader>

        <div className="flex flex-col h-full py-2">
          <OutboundRouteForm onSuccess={() => setIsOpen(false)} />
        </div>
      </DialogContent>
    </Dialog>
  );
}
