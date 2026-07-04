import { useState } from 'react';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { SearchableSelect } from '@/components/ui/searchable-select';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { useCreateInboundRouteMutation, useCreateOutboundRouteMutation } from '../api/routeHooks';
import { useTenantPartnersQuery } from '@/features/partners/api/partnerHooks';
import { useTenantEndpointsQuery } from '@/features/endpoints/api/endpointsHooks';
import { Network } from 'lucide-react';
import { useToast } from '@/hooks/use-toast';
import { FormModal } from '@/components/ui/form-modal';

export function CreateRouteModal() {
  const [isOpen, setIsOpen] = useState(false);
  const [name, setName] = useState('');
  const [direction, setDirection] = useState<'INBOUND' | 'OUTBOUND'>('INBOUND');
  const [processingMode, setProcessingMode] = useState<'TRANSLATE' | 'PASSTHROUGH'>('TRANSLATE');
  const [transactionType, setTransactionType] = useState('*');
  const [isaSender, setIsaSender] = useState('');
  const [isaReceiver, setIsaReceiver] = useState('');
  const [targetId, setTargetId] = useState('');

  const { toast } = useToast();
  const { data: partners, isLoading: partnersLoading } = useTenantPartnersQuery();
  const { data: endpoints, isLoading: endpointsLoading } = useTenantEndpointsQuery();

  const createInbound = useCreateInboundRouteMutation();
  const createOutbound = useCreateOutboundRouteMutation();

  const isPending = createInbound.isPending || createOutbound.isPending;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!name || !isaSender || !isaReceiver || !targetId || !transactionType) {
      toast({ title: 'Please fill all fields', variant: 'destructive' });
      return;
    }

    try {
      if (direction === 'INBOUND') {
        // Inbound: Target is an Endpoint (Webhook)
        const selectedEndpoint = endpoints?.find(e => e.id === targetId);
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
          webhook_partner_id: targetId,
        });
      } else {
        // Outbound: Target is a Trading Partner (AS2/SFTP)
        const selectedPartner = partners?.find(p => p.id === targetId);
        if (!selectedPartner) {
          toast({ title: 'Invalid partner selected', variant: 'destructive' });
          return;
        }
        await createOutbound.mutateAsync({
          name,
          isa_sender_id: isaSender,
          isa_receiver_id: isaReceiver,
          transaction_type: transactionType,
          processing_mode: processingMode,
          as2_partner_id: selectedPartner.type?.toUpperCase() === 'AS2' ? targetId : undefined,
          sftp_partner_id: selectedPartner.type?.toUpperCase() === 'SFTP' ? targetId : undefined,
        });
      }

      toast({ title: 'Route created successfully' });
      setIsOpen(false);

      // Reset form
      setName('');
      setIsaSender('');
      setIsaReceiver('');
      setTargetId('');
      setTransactionType('*');
    } catch (err) {
      toast({ title: 'Failed to create route', description: String(err), variant: 'destructive' });
    }
  };

  const isLoadingDestinations = direction === 'INBOUND' ? endpointsLoading : partnersLoading;

  return (
    <FormModal
      title="Create Routing Rule"
      triggerText="Create Route"
      icon={<Network className="w-4 h-4" />}
      isOpen={isOpen}
      onOpenChange={setIsOpen}
      onSubmit={handleSubmit}
      isPending={isPending}
      submitText="Create Route"
      maxWidth="sm:max-w-[500px]"
    >
      <div className="grid gap-2">
        <Label htmlFor="route_name" className="text-slate-600 font-medium">Route Name</Label>
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
          <Label htmlFor="direction" className="text-slate-600 font-medium">Traffic Flow</Label>
          <Select value={direction} onValueChange={(v: 'INBOUND' | 'OUTBOUND') => { setDirection(v); setTargetId(''); }}>
            <SelectTrigger className="h-10 rounded-xl">
              <SelectValue placeholder="Select traffic flow" />
            </SelectTrigger>
            <SelectContent className="rounded-xl">
              <SelectItem value="INBOUND">From EDI</SelectItem>
              <SelectItem value="OUTBOUND">From JSON</SelectItem>
            </SelectContent>
          </Select>
        </div>
        <div className="grid gap-2">
          <Label htmlFor="transaction_type" className="text-slate-600 font-medium">Transaction</Label>
          <Input
            id="transaction_type"
            value={transactionType}
            onChange={(e) => setTransactionType(e.target.value)}
            placeholder="e.g. 850 or *"
            className="h-10 rounded-xl font-mono text-sm"
          />
        </div>
      </div>

      <div className="grid grid-cols-2 gap-4">
        <div className="grid gap-2">
          <Label htmlFor="sender_id" className="text-slate-600 font-medium">ISA Sender ID</Label>
          <Input
            id="sender_id"
            value={isaSender}
            onChange={(e) => setIsaSender(e.target.value)}
            placeholder="e.g. ACME_CORP"
            className="h-10 rounded-xl font-mono text-sm uppercase"
          />
        </div>
        <div className="grid gap-2">
          <Label htmlFor="receiver_id" className="text-slate-600 font-medium">ISA Receiver ID</Label>
          <Input
            id="receiver_id"
            value={isaReceiver}
            onChange={(e) => setIsaReceiver(e.target.value)}
            placeholder="e.g. WALMART"
            className="h-10 rounded-xl font-mono text-sm uppercase"
          />
        </div>
      </div>

      <div className="grid gap-2">
        <Label htmlFor="processing_mode" className="text-slate-600 font-medium">Processing Mode</Label>
        <Select value={processingMode} onValueChange={(v: 'TRANSLATE' | 'PASSTHROUGH') => setProcessingMode(v)}>
          <SelectTrigger className="h-10 rounded-xl">
            <SelectValue placeholder="Select processing mode" />
          </SelectTrigger>
          <SelectContent className="rounded-xl">
            <SelectItem value="TRANSLATE">
              <div className="flex flex-col">
                <span className="font-medium">Translate (EDI ↔ JSON)</span>
                <span className="text-xs text-slate-500">Parse EDI to JSON and integrate with Webhooks</span>
              </div>
            </SelectItem>
            <SelectItem value="PASSTHROUGH">
              <div className="flex flex-col">
                <span className="font-medium">Passthrough (VAN)</span>
                <span className="text-xs text-slate-500">Forward raw EDI directly to AS2 or SFTP without translating</span>
              </div>
            </SelectItem>
          </SelectContent>
        </Select>
      </div>

      <div className="grid gap-2">
        <Label htmlFor="target" className="text-slate-600 font-medium">Target Destination</Label>
        <SearchableSelect
          disabled={isLoadingDestinations}
          value={targetId}
          onChange={setTargetId}
          placeholder={isLoadingDestinations ? "Loading..." : "Select destination"}
          options={direction === 'INBOUND'
            ? (endpoints || []).map(e => ({
                value: e.id,
                label: (
                  <span className="flex items-center gap-2">
                    <span className="font-mono text-xs bg-slate-100 text-slate-500 px-1.5 py-0.5 rounded">{e.type}</span>
                    {e.name}
                  </span>
                ),
                searchString: e.name
              }))
            : (partners || []).filter(p => !(p.type === 'AS2' && p.is_local)).map(p => ({
                value: p.id,
                label: (
                  <span className="flex items-center gap-2">
                    <span className="font-mono text-xs bg-slate-100 text-slate-500 px-1.5 py-0.5 rounded">{p.type}</span>
                    {p.name}
                  </span>
                ),
                searchString: p.name
              }))
          }
        />
      </div>
    </FormModal>
  );
}
