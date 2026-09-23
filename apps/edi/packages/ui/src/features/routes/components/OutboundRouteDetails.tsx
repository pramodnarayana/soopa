import { SearchableSelect } from '@soopa/ui';
import { Button } from '@soopa/ui/components/ui/button';
import { Input } from '@soopa/ui/components/ui/input';
import { Label } from '@soopa/ui/components/ui/label';
import { Loader2 } from 'lucide-react';
import { useState } from 'react';
import { useForm } from 'react-hook-form';
import { useToast } from '../../../hooks/use-toast';
import { useUpdateOutboundRouteMutation } from '../api/outboundRouteHooks';
import { useTenantDestinations } from '../hooks/useTenantDestinations';
import type { OutboundRouteItem } from '../types';

interface OutboundRouteFormData {
  name: string;
  trading_partner_id: string;
}

export function OutboundRouteDetails({
  route,
  onCancel,
}: {
  route: OutboundRouteItem;
  onCancel?: () => void;
}) {
  const { toast } = useToast();
  const updateRoute = useUpdateOutboundRouteMutation();
  const isSubmitting = updateRoute.isPending;

  const { data: destinations } = useTenantDestinations('OUTBOUND');

  const [targetId, setTargetId] = useState(route.as2_partner_id || route.sftp_partner_id || '');

  const {
    register,
    handleSubmit,
    reset,
    formState: { isDirty },
  } = useForm<OutboundRouteFormData>({
    defaultValues: {
      name: route.name || '',
      trading_partner_id: route.trading_partner_id || '',
    },
  });

  const onSubmit = (formData: OutboundRouteFormData) => {
    const initialTargetId = route.as2_partner_id || route.sftp_partner_id || '';
    const payload: Partial<OutboundRouteFormData> & {
      as2_partner_id?: string | null;
      sftp_partner_id?: string | null;
    } = {};

    if (formData.name !== route.name) payload.name = formData.name;
    if (formData.trading_partner_id !== route.trading_partner_id)
      payload.trading_partner_id = formData.trading_partner_id;

    if (targetId !== initialTargetId) {
      const partner = destinations?.find((p) => p.id === targetId);
      if (!partner) {
        toast({
          title: 'Error',
          description: 'Selected destination is invalid or unavailable.',
          variant: 'destructive',
        });
        return;
      }
      if (partner.type === 'AS2') {
        payload.as2_partner_id = targetId;
        payload.sftp_partner_id = null;
      } else if (partner.type === 'SFTP') {
        payload.sftp_partner_id = targetId;
        payload.as2_partner_id = null;
      } else {
        toast({
          title: 'Error',
          description: 'Unsupported destination type.',
          variant: 'destructive',
        });
        return;
      }
    }

    updateRoute.mutate(
      { routeId: route.route_id, payload },
      {
        onSuccess: () => {
          toast({
            title: 'Success',
            description: 'Outbound route updated successfully.',
            variant: 'success',
          });
          reset(formData);
        },
        onError: (err) => {
          toast({
            title: 'Error',
            description: err.message || 'Failed to update outbound route.',
            variant: 'destructive',
          });
        },
      },
    );
  };

  const targetDirty = targetId !== (route.as2_partner_id || route.sftp_partner_id || '');

  return (
    <div className="p-6 bg-slate-50/50 rounded-b-2xl border-t border-slate-100">
      <form onSubmit={handleSubmit(onSubmit)} className="space-y-6">
        <div className="flex justify-between items-center mb-6">
          <h4 className="text-sm font-semibold text-slate-900 uppercase tracking-wider">
            Outbound Route Details
          </h4>
          <div className="flex items-center gap-2">
            <Button
              type="button"
              variant="outline"
              className="rounded-xl h-10 px-5 text-[14px] font-semibold"
              onClick={() => {
                reset();
                setTargetId(route.as2_partner_id || route.sftp_partner_id || '');
                if (onCancel) onCancel();
              }}
              disabled={(!isDirty && !targetDirty) || isSubmitting}
            >
              Cancel
            </Button>
            <Button
              type="submit"
              disabled={(!isDirty && !targetDirty) || isSubmitting}
              className="bg-emerald-600 hover:bg-emerald-700 text-white rounded-xl h-10 px-5 text-[14px] font-semibold min-w-[80px]"
            >
              {isSubmitting ? <Loader2 className="w-4 h-4 animate-spin" /> : 'Save'}
            </Button>
          </div>
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          <div className="space-y-2">
            <Label>Route Name</Label>
            <Input {...register('name')} disabled={isSubmitting} />
          </div>
          <div className="space-y-2">
            <Label>Trading Partner ID</Label>
            <Input
              {...register('trading_partner_id')}
              disabled={isSubmitting}
              className="font-mono text-sm uppercase"
            />
          </div>
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
                .filter((d) => !(d.type === 'AS2' && d.is_local))
                .map((d) => ({
                  value: d.id,
                  label: (
                    <span className="flex items-center gap-2">
                      <span className="font-mono text-xs bg-slate-100 text-slate-500 px-1.5 py-0.5 rounded">
                        {d.type}
                      </span>
                      {d.name}
                    </span>
                  ),
                  searchString: d.name,
                }))}
            />
          </div>
        </div>
      </form>
    </div>
  );
}
