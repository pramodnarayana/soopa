import { useState } from 'react';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { SearchableSelect } from '@/components/ui/searchable-select';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { useCreateOutboundRouteMutation } from '../api/routeHooks';
import { useTenantDestinations } from '../hooks/useTenantDestinations';
import { useToast } from '@/hooks/use-toast';
import { Button } from '@/components/ui/button';

export function OutboundRouteForm({ onSuccess }: { onSuccess: () => void }) {
  const [name, setName] = useState('');
  const [externalId, setExternalId] = useState('');
  const [processingMode] = useState<'TRANSLATE' | 'PASSTHROUGH'>('TRANSLATE');
  const [transactionType, setTransactionType] = useState('*');

  // Envelope fields
  const [isaSender, setIsaSender] = useState('');
  const [isaSenderQual, setIsaSenderQual] = useState('ZZ');
  const [isaReceiver, setIsaReceiver] = useState('');
  const [isaReceiverQual, setIsaReceiverQual] = useState('ZZ');
  const [gsSender, setGsSender] = useState('');
  const [gsReceiver, setGsReceiver] = useState('');
  const [defaultStandard, setDefaultStandard] = useState('x12');
  const [defaultVersion, setDefaultVersion] = useState('004010');

  const [targetId, setTargetId] = useState('');

  const { toast } = useToast();
  // For Outbound, we only fetch destinations that are NOT webhooks
  const { data: destinations, isLoading: isLoadingDestinations } = useTenantDestinations('OUTBOUND');
  const createOutbound = useCreateOutboundRouteMutation();

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!name || !externalId || !isaSender || !isaReceiver || !gsSender || !gsReceiver || !targetId || !transactionType) {
      toast({ title: 'Please fill all required fields', variant: 'destructive' });
      return;
    }

    try {
      const selectedPartner = destinations?.find(p => p.id === targetId);
      if (!selectedPartner) {
        toast({ title: 'Invalid partner selected', variant: 'destructive' });
        return;
      }

      await createOutbound.mutateAsync({
        trading_partner_id: externalId,
        name,
        isa_sender_id: isaSender,
        isa_sender_qualifier: isaSenderQual,
        isa_receiver_id: isaReceiver,
        isa_receiver_qualifier: isaReceiverQual,
        gs_sender_id: gsSender,
        gs_receiver_id: gsReceiver,
        default_standard: defaultStandard,
        default_version: defaultVersion,
        transaction_type: transactionType,
        processing_mode: processingMode,
        as2_partner_id: selectedPartner.type?.toUpperCase() === 'AS2' ? targetId : undefined,
        sftp_partner_id: selectedPartner.type?.toUpperCase() === 'SFTP' ? targetId : undefined,
      });

      toast({ title: 'Outbound route created successfully' });
      onSuccess();
    } catch (err) {
      toast({ title: 'Failed to create outbound route', description: String(err), variant: 'destructive' });
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
              placeholder="e.g. Outbound Conway AS2"
              className="h-10 bg-white"
            />
          </div>
          <div className="grid gap-2">
            <Label htmlFor="trading_partner_id" className="text-slate-600 font-medium">Trading Partner ID *</Label>
            <Input
              id="trading_partner_id"
              value={externalId}
              onChange={(e) => setExternalId(e.target.value)}
              placeholder="e.g. CONWAY_OUT"
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
        </div>
      </div>

      {/* EDI Envelope Settings */}
      <div className="bg-emerald-50/30 border border-emerald-100 p-4 rounded-xl space-y-4">
        <h3 className="text-sm font-semibold text-emerald-800">EDI Envelope Configuration</h3>

        <div className="grid grid-cols-4 gap-4">
          <div className="grid gap-2">
            <Label htmlFor="isa_sender_qual" className="text-slate-600 font-medium text-sm">ISA Sender Qual</Label>
            <Input id="isa_sender_qual" value={isaSenderQual} onChange={e => setIsaSenderQual(e.target.value)} className="h-10 bg-white font-mono text-sm" />
          </div>
          <div className="grid gap-2">
            <Label htmlFor="isa_sender" className="text-slate-600 font-medium text-sm font-bold">ISA Sender ID *</Label>
            <Input id="isa_sender" value={isaSender} onChange={e => setIsaSender(e.target.value)} placeholder="ACME_CORP" className="h-10 bg-white font-mono text-sm uppercase" />
          </div>
          <div className="grid gap-2">
            <Label htmlFor="isa_receiver_qual" className="text-slate-600 font-medium text-sm">ISA Receiver Qual</Label>
            <Input id="isa_receiver_qual" value={isaReceiverQual} onChange={e => setIsaReceiverQual(e.target.value)} className="h-10 bg-white font-mono text-sm" />
          </div>
          <div className="grid gap-2">
            <Label htmlFor="isa_receiver" className="text-slate-600 font-medium text-sm font-bold">ISA Receiver ID *</Label>
            <Input id="isa_receiver" value={isaReceiver} onChange={e => setIsaReceiver(e.target.value)} placeholder="PARTNER" className="h-10 bg-white font-mono text-sm uppercase" />
          </div>
        </div>

        <div className="grid grid-cols-4 gap-4 pt-2">
          <div className="grid gap-2">
            <Label htmlFor="gs_sender" className="text-slate-600 font-medium text-sm font-bold">GS Sender ID *</Label>
            <Input id="gs_sender" value={gsSender} onChange={e => setGsSender(e.target.value)} placeholder="ACME" className="h-10 bg-white font-mono text-sm uppercase" />
          </div>
          <div className="grid gap-2">
            <Label htmlFor="gs_receiver" className="text-slate-600 font-medium text-sm font-bold">GS Receiver ID *</Label>
            <Input id="gs_receiver" value={gsReceiver} onChange={e => setGsReceiver(e.target.value)} placeholder="PARTNER" className="h-10 bg-white font-mono text-sm uppercase" />
          </div>
          <div className="grid gap-2">
            <Label htmlFor="default_standard" className="text-slate-600 font-medium text-sm">Standard</Label>
            <Select value={defaultStandard} onValueChange={setDefaultStandard}>
              <SelectTrigger className="h-10 bg-white text-sm"><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="x12">X12</SelectItem>
                <SelectItem value="edifact">EDIFACT</SelectItem>
              </SelectContent>
            </Select>
          </div>
          <div className="grid gap-2">
            <Label htmlFor="default_version" className="text-slate-600 font-medium text-sm">Version</Label>
            <Input id="default_version" value={defaultVersion} onChange={e => setDefaultVersion(e.target.value)} placeholder="004010" className="h-10 bg-white font-mono text-sm" />
          </div>
        </div>
      </div>

      {/* Target Destination */}
      <div className="bg-indigo-50/30 border border-indigo-100 p-4 rounded-xl space-y-4">
        <h3 className="text-sm font-semibold text-indigo-800">Target Destination</h3>
        <div className="grid gap-2">
          <Label htmlFor="target" className="text-slate-600 font-medium">AS2 / SFTP Partner *</Label>
          <SearchableSelect
            disabled={isLoadingDestinations}
            value={targetId}
            onChange={setTargetId}
            placeholder={isLoadingDestinations ? "Loading..." : "Select remote partner"}
            options={(destinations || [])
              .filter(d => !(d.type === 'AS2' && (d as any).is_local))
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
      </div>

      <div className="flex justify-end mt-2">
        <Button
          type="submit"
          disabled={createOutbound.isPending}
          className="bg-emerald-600 hover:bg-emerald-700 text-white rounded-xl px-6 h-10 shadow-sm"
        >
          {createOutbound.isPending ? 'Creating...' : 'Create Outbound Route'}
        </Button>
      </div>
    </form>
  );
}
