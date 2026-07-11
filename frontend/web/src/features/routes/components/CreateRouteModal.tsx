import { useState } from 'react';
import { Network, Plus } from 'lucide-react';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger } from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { InboundRouteForm } from './InboundRouteForm';
import { OutboundRouteForm } from './OutboundRouteForm';

export function CreateRouteModal() {
  const [isOpen, setIsOpen] = useState(false);
  const [activeTab, setActiveTab] = useState('inbound');

  return (
    <Dialog open={isOpen} onOpenChange={setIsOpen} modal={false}>
      <DialogTrigger asChild>
        <Button className="flex items-center gap-2 bg-indigo-600 hover:bg-indigo-700 text-white rounded-xl shadow-sm">
          <Plus className="h-4 w-4" />
          Create Route
        </Button>
      </DialogTrigger>

      <DialogContent
        className="sm:max-w-[700px] rounded-2xl"
        onPointerDownOutside={(e) => e.preventDefault()}
        onFocusOutside={(e) => e.preventDefault()}
      >
        <DialogHeader>
          <DialogTitle className="text-xl flex items-center gap-2">
            <div className="w-8 h-8 rounded-lg bg-indigo-50 flex items-center justify-center text-indigo-600">
              <Network className="w-4 h-4" />
            </div>
            Create Routing Rule
          </DialogTitle>
        </DialogHeader>

        <div className="flex flex-col h-full py-2">
          <Tabs value={activeTab} onValueChange={setActiveTab} className="w-full">
            <TabsList className="grid w-full grid-cols-2 mb-6 h-12 p-1 bg-slate-100 rounded-xl">
              <TabsTrigger value="inbound" className="rounded-lg data-[state=active]:bg-white data-[state=active]:text-indigo-600 data-[state=active]:shadow-sm">
                Inbound (From EDI)
              </TabsTrigger>
              <TabsTrigger value="outbound" className="rounded-lg data-[state=active]:bg-white data-[state=active]:text-emerald-600 data-[state=active]:shadow-sm">
                Outbound (From JSON)
              </TabsTrigger>
            </TabsList>

            <TabsContent value="inbound" className="mt-0 outline-none">
              <InboundRouteForm onSuccess={() => setIsOpen(false)} />
            </TabsContent>

            <TabsContent value="outbound" className="mt-0 outline-none">
              <OutboundRouteForm onSuccess={() => setIsOpen(false)} />
            </TabsContent>
          </Tabs>
        </div>
      </DialogContent>
    </Dialog>
  );
}
