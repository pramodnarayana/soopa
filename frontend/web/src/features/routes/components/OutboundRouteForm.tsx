import { useState } from 'react';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { SearchableSelect } from '@/components/ui/searchable-select';
import { useCreateOutboundRouteMutation } from '../api/routeHooks';
import { useTenantDestinations } from '../hooks/useTenantDestinations';
import { useToast } from '@/hooks/use-toast';
import { Button } from '@/components/ui/button';

export function OutboundRouteForm({ onSuccess }: { onSuccess: () => void }) {
  const [name, setName] = useState('');
  const [externalId, setExternalId] = useState('');
  const [targetId, setTargetId] = useState('');

  const { toast } = useToast();
  // For Outbound, we only fetch destinations that are NOT webhooks
  const { data: destinations, isLoading: isLoadingDestinations } = useTenantDestinations('OUTBOUND');
  const createOutbound = useCreateOutboundRouteMutation();

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!name || !externalId || !targetId) {
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
