import { useState } from 'react';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { SearchableSelect } from '@/components/ui/searchable-select';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { useCreateInboundRouteMutation } from '../api/routeHooks';
import { useTenantDestinations } from '../hooks/useTenantDestinations';
import { useToast } from '@/hooks/use-toast';
import { Button } from '@/components/ui/button';

export function InboundRouteForm({ onSuccess }: { onSuccess: () => void }) {
  const [name, setName] = useState('');
  const [processingMode, setProcessingMode] = useState<'TRANSLATE' | 'PASSTHROUGH'>('TRANSLATE');
  const [transactionType, setTransactionType] = useState('*');
  const [isaSender, setIsaSender] = useState('');
  const [isaReceiver, setIsaReceiver] = useState('');
  const [targetId, setTargetId] = useState('');

  const { toast } = useToast();
  const { data: destinations, isLoading: isLoadingDestinations } = useTenantDestinations('INBOUND');
  const createInbound = useCreateInboundRouteMutation();

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!name || !isaSender || !isaReceiver || !targetId || !transactionType) {
      toast({ title: 'Please fill all required fields', variant: 'destructive' });
      return;
    }

    try {
      const selectedEndpoint = destinations?.find(e => e.id === targetId);
      if (!selectedEndpoint) {
        toast({ title: 'Invalid endpoint selected', variant: 'destructive' });
        return;
      }

      await createInbound.mutateAsync({
        name,
        isa_sender_id: isaSender,
        isa_receiver_id: isaReceiver,
        transaction_type: transactionType,
        processing_mode: processingMode,
        webhook_id: targetId,
      });

      toast({ title: 'Inbound route created successfully' });
      onSuccess();
    } catch (err) {
      toast({ title: 'Failed to create inbound route', description: String(err), variant: 'destructive' });
    }
  };

  return (
    <form onSubmit={handleSubmit} className="flex flex-col gap-6">
      <div className="grid gap-2">
        <Label htmlFor="route_name" className="text-slate-600 font-medium">Route Name *</Label>
        <Input
          id="route_name"
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="e.g. Inbound Walmart 850"
          className="h-10 rounded-xl text-sm"
        />
      </div>

      <div className="grid grid-cols-2 gap-4">
        <div className="grid gap-2">
          <Label htmlFor="sender_id" className="text-slate-600 font-medium">ISA Sender ID *</Label>
          <Input
            id="sender_id"
            value={isaSender}
            onChange={(e) => setIsaSender(e.target.value)}
            placeholder="e.g. ACME_CORP"
            className="h-10 rounded-xl font-mono text-sm uppercase"
          />
        </div>
        <div className="grid gap-2">
          <Label htmlFor="receiver_id" className="text-slate-600 font-medium">ISA Receiver ID *</Label>
          <Input
            id="receiver_id"
            value={isaReceiver}
            onChange={(e) => setIsaReceiver(e.target.value)}
            placeholder="e.g. WALMART"
            className="h-10 rounded-xl font-mono text-sm uppercase"
          />
        </div>
      </div>

      <div className="grid grid-cols-2 gap-4">
        <div className="grid gap-2">
          <Label htmlFor="transaction_type" className="text-slate-600 font-medium">Transaction *</Label>
          <Input
            id="transaction_type"
            value={transactionType}
            onChange={(e) => setTransactionType(e.target.value)}
            placeholder="e.g. 850 or *"
            className="h-10 rounded-xl font-mono text-sm"
          />
        </div>
        <div className="grid gap-2">
          <Label htmlFor="processing_mode" className="text-slate-600 font-medium">Processing Mode *</Label>
          <Select value={processingMode} onValueChange={(v: 'TRANSLATE' | 'PASSTHROUGH') => setProcessingMode(v)}>
            <SelectTrigger className="h-10 rounded-xl">
              <SelectValue placeholder="Select processing mode" />
            </SelectTrigger>
            <SelectContent className="rounded-xl">
              <SelectItem value="TRANSLATE">Translate (EDI ↔ JSON)</SelectItem>
              <SelectItem value="PASSTHROUGH">Passthrough (VAN)</SelectItem>
            </SelectContent>
          </Select>
        </div>
      </div>

      <div className="grid gap-2">
        <Label htmlFor="target" className="text-slate-600 font-medium">Target Destination *</Label>
        <SearchableSelect
          disabled={isLoadingDestinations}
          value={targetId}
          onChange={setTargetId}
          placeholder={isLoadingDestinations ? "Loading..." : "Select webhook destination"}
          options={(destinations || [])
            .map(d => ({
            value: d.id,
            label: (
              <span className="flex items-center gap-2">
                <span className="font-mono text-xs bg-slate-100 text-slate-500 px-1.5 py-0.5 rounded">{d.type}</span>
                {d.name}
              </span>
            ),
            searchString: d.name
          }))}
        />
      </div>

      <div className="flex justify-end mt-4">
        <Button
          type="submit"
          disabled={createInbound.isPending}
          className="bg-indigo-600 hover:bg-indigo-700 text-white rounded-xl px-6 h-10 shadow-sm"
        >
          {createInbound.isPending ? 'Creating...' : 'Create Inbound Route'}
        </Button>
      </div>
    </form>
  );
}
