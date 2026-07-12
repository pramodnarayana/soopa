import { useState } from 'react';
import { useForm } from 'react-hook-form';
import type { RouteItem } from '../types';
import { useUpdateRouteMutation } from '../api/routeHooks';
import { useTenantDestinations } from '../hooks/useTenantDestinations';
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
  const isOutbound = route.direction === 'OUTBOUND';

  const { data: destinations } = useTenantDestinations(route.direction);

  const [targetId, setTargetId] = useState(
    route.webhook_id || route.as2_partner_id || route.sftp_partner_id || ''
  );

  const { register, handleSubmit, reset, setValue, watch, formState: { isDirty } } = useForm({
    defaultValues: {
      name: route.name || '',
      trading_partner_id: route.trading_partner_id || '',
      isa_sender_id: route.isa_sender_id || '',
      isa_sender_qualifier: route.isa_sender_qualifier || 'ZZ',
      isa_receiver_id: route.isa_receiver_id || '',
      isa_receiver_qualifier: route.isa_receiver_qualifier || 'ZZ',
      gs_sender_id: route.gs_sender_id || '',
      gs_receiver_id: route.gs_receiver_id || '',
      default_standard: route.default_standard || 'x12',
      default_version: route.default_version || '004010',
      transaction_type: route.transaction_type || '',
      processing_mode: route.processing_mode || 'TRANSLATE',
    }
  });

  const processingMode = watch('processing_mode');

  const onSubmit = (formData: any) => {
    const payload: any = {};
    const initialTargetId = route.webhook_id || route.as2_partner_id || route.sftp_partner_id || '';

    if (formData.name !== route.name) payload.name = formData.name;
    if (formData.transaction_type !== route.transaction_type) payload.transaction_type = formData.transaction_type;
    if (formData.processing_mode !== route.processing_mode) payload.processing_mode = formData.processing_mode;

    if (formData.isa_sender_id !== route.isa_sender_id) payload.isa_sender_id = formData.isa_sender_id;
    if (formData.isa_receiver_id !== route.isa_receiver_id) payload.isa_receiver_id = formData.isa_receiver_id;

    if (formData.trading_partner_id !== route.trading_partner_id) payload.trading_partner_id = formData.trading_partner_id;
    if (formData.gs_sender_id !== route.gs_sender_id) payload.gs_sender_id = formData.gs_sender_id;
    if (formData.gs_receiver_id !== route.gs_receiver_id) payload.gs_receiver_id = formData.gs_receiver_id;

    if (isOutbound) {
      if (formData.isa_sender_qualifier !== route.isa_sender_qualifier) payload.isa_sender_qualifier = formData.isa_sender_qualifier;
      if (formData.isa_receiver_qualifier !== route.isa_receiver_qualifier) payload.isa_receiver_qualifier = formData.isa_receiver_qualifier;
      if (formData.default_standard !== route.default_standard) payload.default_standard = formData.default_standard;
      if (formData.default_version !== route.default_version) payload.default_version = formData.default_version;
    }

    if (targetId !== initialTargetId) {
      if (route.direction === 'INBOUND') {
        payload.webhook_id = targetId;
        payload.as2_partner_id = null;
        payload.sftp_partner_id = null;
      } else {
        const partner = destinations?.find(p => p.id === targetId);
        if (partner?.type === 'AS2') {
          payload.as2_partner_id = targetId;
          payload.sftp_partner_id = null;
        }
        if (partner?.type === 'SFTP') {
          payload.sftp_partner_id = targetId;
          payload.as2_partner_id = null;
        }
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
          {/* Top Info */}
          <div className="space-y-2">
            <Label>Route Name</Label>
            <Input {...register('name')} disabled={isSubmitting} />
          </div>

          <div className="space-y-2">
            <Label>Transaction Type (* for all)</Label>
            <Input {...register('transaction_type')} disabled={isSubmitting} />
          </div>

          <div className="space-y-2">
            <Label>Trading Partner ID</Label>
            <Input {...register('trading_partner_id')} disabled={isSubmitting} className="font-mono text-sm uppercase" />
          </div>

          {!isOutbound && (
            <div className="space-y-2">
              <Label>Processing Mode</Label>
              <Select
                disabled={isSubmitting}
                value={processingMode}
                onValueChange={(val) => setValue('processing_mode', val as any, { shouldDirty: true })}
              >
                <SelectTrigger>
                  <SelectValue placeholder="Select mode" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="TRANSLATE">Translate (EDI ↔ JSON)</SelectItem>
                  <SelectItem value="PASSTHROUGH">Passthrough (Raw Data)</SelectItem>
                </SelectContent>
              </Select>
            </div>
          )}
        </div>

        {/* Envelope Configuration (Grid adjustments based on Outbound) */}
        <div className={`grid grid-cols-1 lg:grid-cols-4 gap-4 pt-4 border-t border-slate-200`}>
          {isOutbound && (
            <div className="space-y-2">
              <Label>ISA Sender Qual</Label>
              <Input {...register('isa_sender_qualifier')} disabled={isSubmitting} className="font-mono text-sm" />
            </div>
          )}
          <div className="space-y-2">
            <Label>ISA Sender ID</Label>
            <Input {...register('isa_sender_id')} disabled={isSubmitting} className="font-mono text-sm uppercase" />
          </div>

          {isOutbound && (
            <div className="space-y-2">
              <Label>ISA Receiver Qual</Label>
              <Input {...register('isa_receiver_qualifier')} disabled={isSubmitting} className="font-mono text-sm" />
            </div>
          )}
          <div className="space-y-2">
            <Label>ISA Receiver ID</Label>
            <Input {...register('isa_receiver_id')} disabled={isSubmitting} className="font-mono text-sm uppercase" />
          </div>

          <div className="space-y-2">
            <Label>GS Sender ID</Label>
            <Input {...register('gs_sender_id')} disabled={isSubmitting} className="font-mono text-sm uppercase" />
          </div>
          <div className="space-y-2">
            <Label>GS Receiver ID</Label>
            <Input {...register('gs_receiver_id')} disabled={isSubmitting} className="font-mono text-sm uppercase" />
          </div>

          {isOutbound && (
            <>
              <div className="space-y-2">
                <Label>Default Standard</Label>
                <Input {...register('default_standard')} disabled={isSubmitting} className="font-mono text-sm" />
              </div>
              <div className="space-y-2">
                <Label>Default Version</Label>
                <Input {...register('default_version')} disabled={isSubmitting} className="font-mono text-sm" />
              </div>
            </>
          )}
        </div>

        {/* Target Destination */}
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 pt-4 border-t border-slate-200">
          <div className="space-y-2">
            <Label>Target Destination</Label>
            <SearchableSelect
              value={targetId}
              onChange={setTargetId}
              placeholder="Select destination"
              options={(destinations || [])
                .filter(d => route.direction === 'INBOUND' || !(d.type === 'AS2' && (d as any).is_local))
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

        <div className="flex items-center justify-end gap-3 pt-4 border-t border-slate-200">
          <Button
            type="button"
            variant="outline"
            onClick={() => {
              reset(); if (onCancel) onCancel();
              setTargetId(route.webhook_id || route.as2_partner_id || route.sftp_partner_id || '');
            }}
            disabled={(!isDirty && targetId === (route.webhook_id || route.as2_partner_id || route.sftp_partner_id || '')) || isSubmitting}
          >
            Cancel
          </Button>
          <Button
            type="submit"
            disabled={(!isDirty && targetId === (route.webhook_id || route.as2_partner_id || route.sftp_partner_id || '')) || isSubmitting}
          >
            {isSubmitting && <Loader2 className="w-4 h-4 mr-2 animate-spin" />}
            Save Changes
          </Button>
        </div>
      </form>
    </div>
  );
}
