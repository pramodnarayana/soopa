import { useState } from 'react';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { SearchableSelect } from '@/components/ui/searchable-select';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { useCreateInboundRouteMutation } from '../api/routeHooks';
import { useTenantDestinations } from '../hooks/useTenantDestinations';
import { ProcessingMode, DestinationType, Direction } from '../types';
import { useToast } from '@/hooks/use-toast';
import { Button } from '@/components/ui/button';

export function InboundRouteForm({ onSuccess }: { onSuccess: () => void }) {
  const [name, setName] = useState('');
  const [tradingPartnerId, setTradingPartnerId] = useState('');
  const [processingMode, setProcessingMode] = useState<ProcessingMode>(ProcessingMode.TRANSFORM);
  const [transactionType, setTransactionType] = useState('*');
  const [isaSender, setIsaSender] = useState('');
  const [isaReceiver, setIsaReceiver] = useState('');
  const [gsSender, setGsSender] = useState('');
  const [gsReceiver, setGsReceiver] = useState('');
  const [targetId, setTargetId] = useState('');

  const { toast } = useToast();
  const { data: allDestinations, isLoading: isLoadingDestinations } = useTenantDestinations(Direction.INBOUND);

  // Filter destinations based on processing mode
  const destinations = (allDestinations || []).filter(d => {
    if (processingMode === ProcessingMode.TRANSFORM) return d.type === DestinationType.WEBHOOK;
    if (processingMode === ProcessingMode.PASSTHROUGH) return d.type === DestinationType.AS2 || d.type === DestinationType.SFTP;
    return true;
  });

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
        trading_partner_id: tradingPartnerId || undefined,
        isa_sender_id: isaSender,
        isa_receiver_id: isaReceiver,
        gs_sender_id: gsSender || undefined,
        gs_receiver_id: gsReceiver || undefined,
        transaction_type: transactionType,
        processing_mode: processingMode,
        webhook_id: selectedEndpoint.type === DestinationType.WEBHOOK ? targetId : undefined,
        as2_partner_id: selectedEndpoint.type === DestinationType.AS2 ? targetId : undefined,
        sftp_partner_id: selectedEndpoint.type === DestinationType.SFTP ? targetId : undefined,
      });

      toast({ title: 'Inbound route created successfully' });
      onSuccess();
    } catch (err) {
      toast({ title: 'Failed to create inbound route', description: String(err), variant: 'destructive' });
    }
  };

  return (
    <form onSubmit={handleSubmit} className="flex flex-col gap-6">

      {/* General Settings */}
      <div className="bg-slate-50/50 border border-slate-100 p-4 rounded-xl space-y-4">
        <h3 className="text-sm font-semibold text-slate-800">General Settings</h3>
        <div className="grid grid-cols-2 gap-4">
          <div className="grid gap-2">
            <Label htmlFor="route_name" className="text-slate-600 font-medium">Route Name *</Label>
            <Input
              id="route_name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="e.g. Inbound Walmart 850"
              className="h-10 bg-white"
            />
          </div>
          <div className="grid gap-2">
            <Label htmlFor="trading_partner_id" className="text-slate-600 font-medium">Trading Partner ID</Label>
            <Input
              id="trading_partner_id"
              value={tradingPartnerId}
              onChange={(e) => setTradingPartnerId(e.target.value)}
              placeholder="e.g. WALMART_US"
              className="h-10 bg-white font-mono uppercase text-sm"
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
              className="h-10 bg-white font-mono text-sm"
            />
          </div>
          <div className="grid gap-2">
            <Label htmlFor="processing_mode" className="text-slate-600 font-medium">Processing Mode *</Label>
            <Select
              value={processingMode}
              onValueChange={(v: ProcessingMode) => {
                setProcessingMode(v);
                setTargetId(''); // Reset target when mode changes
              }}
            >
              <SelectTrigger className="h-10 bg-white">
                <SelectValue placeholder="Select processing mode" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value={ProcessingMode.TRANSFORM}>Transform (EDI ↔ JSON)</SelectItem>
                <SelectItem value={ProcessingMode.PASSTHROUGH}>Passthrough (VAN)</SelectItem>
              </SelectContent>
            </Select>
          </div>
        </div>
      </div>

      {/* EDI Envelope Matchers */}
      <div className="bg-indigo-50/30 border border-indigo-100 p-4 rounded-xl space-y-4">
        <h3 className="text-sm font-semibold text-indigo-800">EDI Envelope Matchers</h3>

        <div className="grid grid-cols-4 gap-4">
          <div className="grid gap-2">
            <Label htmlFor="isa_sender" className="text-slate-600 font-medium text-sm font-bold">ISA Sender ID *</Label>
            <Input id="isa_sender" value={isaSender} onChange={e => setIsaSender(e.target.value)} placeholder="PARTNER" className="h-10 bg-white font-mono text-sm uppercase" />
          </div>
          <div className="grid gap-2">
            <Label htmlFor="isa_receiver" className="text-slate-600 font-medium text-sm font-bold">ISA Receiver ID *</Label>
            <Input id="isa_receiver" value={isaReceiver} onChange={e => setIsaReceiver(e.target.value)} placeholder="ACME_CORP" className="h-10 bg-white font-mono text-sm uppercase" />
          </div>
          <div className="grid gap-2">
            <Label htmlFor="gs_sender" className="text-slate-600 font-medium text-sm">GS Sender ID</Label>
            <Input id="gs_sender" value={gsSender} onChange={e => setGsSender(e.target.value)} placeholder="PARTNER_GS" className="h-10 bg-white font-mono text-sm uppercase" />
          </div>
          <div className="grid gap-2">
            <Label htmlFor="gs_receiver" className="text-slate-600 font-medium text-sm">GS Receiver ID</Label>
            <Input id="gs_receiver" value={gsReceiver} onChange={e => setGsReceiver(e.target.value)} placeholder="ACME_GS" className="h-10 bg-white font-mono text-sm uppercase" />
          </div>
        </div>
      </div>

      {/* Target Destination */}
      <div className="bg-emerald-50/30 border border-emerald-100 p-4 rounded-xl space-y-4">
        <h3 className="text-sm font-semibold text-emerald-800">Target Destination</h3>
        <div className="grid gap-2">
          <Label htmlFor="target" className="text-slate-600 font-medium">Webhook / System *</Label>
          <SearchableSelect
            disabled={isLoadingDestinations}
            value={targetId}
            onChange={setTargetId}
            placeholder={isLoadingDestinations ? "Loading..." : `Select ${processingMode === ProcessingMode.TRANSFORM ? 'webhook' : 'partner'} destination`}
            options={destinations.map(d => ({
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
      </div>

      <div className="flex justify-end mt-2">
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
