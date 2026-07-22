import { useForm } from 'react-hook-form';
import { Loader2 } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { useToast } from '@/hooks/use-toast';
import type { EdiHeaderItem } from '../types';
import { useUpdateEdiHeaderMutation } from '../api/ediHeadersApi';

export function EdiHeaderDetails({ header, onCancel }: { header: EdiHeaderItem, onCancel?: () => void }) {
  const { toast } = useToast();
  const updateEdiHeader = useUpdateEdiHeaderMutation();
  const isSubmitting = updateEdiHeader.isPending;

  const { register, handleSubmit, reset, formState: { isDirty } } = useForm({
    defaultValues: {
      name: header.name || '',
      trading_partner_id: header.trading_partner_id || '',
      isa_sender_id: header.isa_sender_id || '',
      isa_sender_qualifier: header.isa_sender_qualifier || 'ZZ',
      isa_receiver_id: header.isa_receiver_id || '',
      isa_receiver_qualifier: header.isa_receiver_qualifier || 'ZZ',
      gs_sender_id: header.gs_sender_id || '',
      gs_receiver_id: header.gs_receiver_id || '',
      default_standard: header.default_standard || 'x12',
      default_version: header.default_version || '004010',
      transaction_type: header.transaction_type || '',
    }
  });

  const onSubmit = (formData: any) => {
    const payload: any = {};

    if (formData.name !== header.name) payload.name = formData.name;
    if (formData.trading_partner_id !== header.trading_partner_id) payload.trading_partner_id = formData.trading_partner_id;
    if (formData.transaction_type !== header.transaction_type) payload.transaction_type = formData.transaction_type;
    if (formData.isa_sender_id !== header.isa_sender_id) payload.isa_sender_id = formData.isa_sender_id;
    if (formData.isa_receiver_id !== header.isa_receiver_id) payload.isa_receiver_id = formData.isa_receiver_id;
    if (formData.gs_sender_id !== header.gs_sender_id) payload.gs_sender_id = formData.gs_sender_id;
    if (formData.gs_receiver_id !== header.gs_receiver_id) payload.gs_receiver_id = formData.gs_receiver_id;
    if (formData.isa_sender_qualifier !== header.isa_sender_qualifier) payload.isa_sender_qualifier = formData.isa_sender_qualifier;
    if (formData.isa_receiver_qualifier !== header.isa_receiver_qualifier) payload.isa_receiver_qualifier = formData.isa_receiver_qualifier;
    if (formData.default_standard !== header.default_standard) payload.default_standard = formData.default_standard;
    if (formData.default_version !== header.default_version) payload.default_version = formData.default_version;

    updateEdiHeader.mutate({ headerId: header.id, payload }, {
      onSuccess: () => {
        toast({ title: 'Success', description: 'EDI Header updated successfully.' });
        reset(formData);
      },
      onError: (err) => {
        toast({ title: 'Error', description: err.message || 'Failed to update EDI Header.', variant: 'destructive' });
      }
    });
  };



  return (
    <div className="p-6 bg-slate-50/50 rounded-b-2xl border-t border-slate-100">
      <form onSubmit={handleSubmit(onSubmit)} className="space-y-6">

        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          <div className="space-y-2">
            <Label>Name</Label>
            <Input {...register('name')} disabled={isSubmitting} />
          </div>

          <div className="space-y-2">
            <Label>Trading Partner ID</Label>
            <Input {...register('trading_partner_id')} disabled={isSubmitting} className="font-mono text-sm uppercase" />
          </div>

          <div className="space-y-2">
            <Label>Transaction Type (* for all)</Label>
            <Input {...register('transaction_type')} disabled={isSubmitting} />
          </div>
        </div>

        {/* Envelope Configuration */}
        <div className={`grid grid-cols-1 lg:grid-cols-4 gap-4 pt-4 border-t border-slate-200`}>
          <div className="space-y-2">
            <Label>ISA Sender Qual</Label>
            <Input {...register('isa_sender_qualifier')} disabled={isSubmitting} className="font-mono text-sm" />
          </div>
          <div className="space-y-2">
            <Label>ISA Sender ID</Label>
            <Input {...register('isa_sender_id')} disabled={isSubmitting} className="font-mono text-sm uppercase" />
          </div>

          <div className="space-y-2">
            <Label>ISA Receiver Qual</Label>
            <Input {...register('isa_receiver_qualifier')} disabled={isSubmitting} className="font-mono text-sm" />
          </div>
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

          <div className="space-y-2">
            <Label>Default Standard</Label>
            <Input {...register('default_standard')} disabled={isSubmitting} className="font-mono text-sm" />
          </div>
          <div className="space-y-2">
            <Label>Default Version</Label>
            <Input {...register('default_version')} disabled={isSubmitting} className="font-mono text-sm" />
          </div>
        </div>

        <div className="flex items-center justify-end pt-4 border-t border-slate-200">
          <div className="flex items-center gap-3">
            <Button
              type="button"
              variant="outline"
              onClick={() => { reset(); if (onCancel) onCancel(); }}
              disabled={!isDirty || isSubmitting}
            >
              Cancel
            </Button>
            <Button
              type="submit"
              disabled={!isDirty || isSubmitting}
            >
              {isSubmitting && <Loader2 className="w-4 h-4 mr-2 animate-spin" />}
              Save Changes
            </Button>
          </div>
        </div>
      </form>
    </div>
  );
}
