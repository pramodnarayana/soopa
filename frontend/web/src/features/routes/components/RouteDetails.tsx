import { useState } from 'react';
import { useForm } from 'react-hook-form';
import type { RouteItem } from '../types';
import { useUpdateRouteMutation } from '../api/routeHooks';
import { useTenantPartnersQuery } from '@/features/partners/api/partnerHooks';
import { useTenantEndpointsQuery } from '@/features/endpoints/api/endpointsHooks';
import { Loader2 } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { useToast } from '@/hooks/use-toast';
import { SearchableSelect } from '@/components/ui/searchable-select';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';

export function RouteDetails({ route, onCancel }: { route: RouteItem, onCancel?: () => void }) {
  const { toast } = useToast();
  const updateRoute = useUpdateRouteMutation();
  const isSubmitting = updateRoute.isPending;

  const { data: partners } = useTenantPartnersQuery();
  const { data: endpoints } = useTenantEndpointsQuery();

  const [targetId, setTargetId] = useState(
    route.webhook_partner_id || route.as2_partner_id || route.sftp_partner_id || ''
  );

  const { register, handleSubmit, reset, setValue, watch, formState: { isDirty } } = useForm({
    defaultValues: {
      name: route.name || '',
      isa_sender_id: route.isa_sender_id || '',
      isa_receiver_id: route.isa_receiver_id || '',
      transaction_type: route.transaction_type || '',
      processing_mode: route.processing_mode || 'TRANSLATE',
    }
  });

  const processingMode = watch('processing_mode');

  const onSubmit = (formData: any) => {
    const payload: any = {};
    const initialTargetId = route.webhook_partner_id || route.as2_partner_id || route.sftp_partner_id || '';

    if (formData.name !== route.name) payload.name = formData.name;
    if (formData.isa_sender_id !== route.isa_sender_id) payload.isa_sender_id = formData.isa_sender_id;
    if (formData.isa_receiver_id !== route.isa_receiver_id) payload.isa_receiver_id = formData.isa_receiver_id;
    if (formData.transaction_type !== route.transaction_type) payload.transaction_type = formData.transaction_type;
    if (formData.processing_mode !== route.processing_mode) payload.processing_mode = formData.processing_mode;

    if (targetId !== initialTargetId) {
      if (route.direction === 'INBOUND') {
        payload.webhook_partner_id = targetId;
      } else {
        const partner = partners?.find(p => p.id === targetId);
        if (partner?.type === 'AS2') payload.as2_partner_id = targetId;
        if (partner?.type === 'SFTP') payload.sftp_partner_id = targetId;
      }
    }

    updateRoute.mutate({ routeId: route.route_id, direction: route.direction, payload }, {
      onSuccess: () => {
        toast({ title: 'Success', description: 'Route updated successfully.' });
        reset(formData);
      },
      onError: (err) => {
        toast({ title: 'Error', description: err.message || 'Failed to update route.', variant: 'destructive' });
      }
    });
  };

  return (
    <div className="p-6 bg-slate-50/50 rounded-b-2xl border-t border-slate-100">
      <form onSubmit={handleSubmit(onSubmit)} className="space-y-6">
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          <div className="space-y-2">
            <Label htmlFor={`name-${route.route_id}`}>Route Name</Label>
            <Input id={`name-${route.route_id}`} {...register('name')} disabled={isSubmitting} />
          </div>

          <div className="space-y-2">
            <Label htmlFor={`txn-${route.route_id}`}>Transaction Type (* for all)</Label>
            <Input id={`txn-${route.route_id}`} {...register('transaction_type')} disabled={isSubmitting} />
          </div>

          <div className="space-y-2">
            <Label htmlFor={`snd-${route.route_id}`}>ISA Sender ID</Label>
            <Input id={`snd-${route.route_id}`} {...register('isa_sender_id')} disabled={isSubmitting} />
          </div>

          <div className="space-y-2">
            <Label htmlFor={`rcv-${route.route_id}`}>ISA Receiver ID</Label>
            <Input id={`rcv-${route.route_id}`} {...register('isa_receiver_id')} disabled={isSubmitting} />
          </div>

          <div className="space-y-2">
            <Label htmlFor={`mode-${route.route_id}`}>Processing Mode</Label>
            <Select
              disabled={isSubmitting}
              value={processingMode}
              onValueChange={(val) => setValue('processing_mode', val as any, { shouldDirty: true })}
            >
              <SelectTrigger id={`mode-${route.route_id}`}>
                <SelectValue placeholder="Select mode" />
              </SelectTrigger>
              <SelectContent >
                <SelectItem value="TRANSLATE">Translate (EDI ↔ JSON)</SelectItem>
                <SelectItem value="PASSTHROUGH">Passthrough (Raw Data)</SelectItem>
              </SelectContent>
            </Select>
          </div>

          <div className="space-y-2">
            <Label>Target Destination</Label>
            <SearchableSelect
              value={targetId}
              onChange={setTargetId}
              placeholder="Select destination"
              options={route.direction === 'INBOUND'
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
        </div>

        <div className="flex items-center justify-end gap-3 pt-4 border-t border-slate-200">
          <Button
            type="button"
            variant="outline"
            onClick={() => {
              reset(); if (onCancel) onCancel();
              setTargetId(route.webhook_partner_id || route.as2_partner_id || route.sftp_partner_id || '');
            }}
            disabled={(!isDirty && targetId === (route.webhook_partner_id || route.as2_partner_id || route.sftp_partner_id || '')) || isSubmitting}
          >
            Cancel
          </Button>
          <Button
            type="submit"
            disabled={(!isDirty && targetId === (route.webhook_partner_id || route.as2_partner_id || route.sftp_partner_id || '')) || isSubmitting}
          >
            {isSubmitting && <Loader2 className="w-4 h-4 mr-2 animate-spin" />}
            Save Changes
          </Button>
        </div>
      </form>
    </div>
  );
}
