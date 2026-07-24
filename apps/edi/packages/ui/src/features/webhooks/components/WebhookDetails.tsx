import { Loader2 } from 'lucide-react';
import { useForm } from 'react-hook-form';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { useUpdateWebhookMutation } from '../api/webhookHooks';
import type { Webhook } from '../types';

export function WebhookDetails({ webhook, onCancel }: { webhook: Webhook; onCancel?: () => void }) {
  const updateWebhook = useUpdateWebhookMutation();
  const isSubmitting = updateWebhook.isPending;

  const {
    register,
    handleSubmit,
    reset,
    formState: { isDirty },
  } = useForm({
    defaultValues: {
      name: webhook.name,
      url: webhook.url || '',
    },
  });

  interface WebhookFormData {
    name: string;
    url: string;
  }

  const onSubmit = (formData: WebhookFormData) => {
    const payload: Partial<WebhookFormData> = {};
    if (formData.name !== webhook.name) payload.name = formData.name;
    const originalUrl = webhook.url || '';
    if (formData.url !== originalUrl) payload.url = formData.url;

    if (Object.keys(payload).length === 0) {
      if (onCancel) onCancel();
      return;
    }

    updateWebhook.mutate(
      { id: webhook.id, payload },
      {
        onSuccess: () => {
          reset(formData);
          if (onCancel) onCancel();
        },
      },
    );
  };

  return (
    <div className="p-6 bg-slate-50/50 border-t border-slate-100">
      <form onSubmit={handleSubmit(onSubmit)}>
        <div className="flex justify-between items-start mb-6">
          <div>
            <h4 className="text-sm font-semibold text-slate-900 uppercase tracking-wider mb-1">
              Webhook Details
            </h4>
          </div>
          <div className="flex items-center gap-3">
            <Button
              type="button"
              variant="outline"
              onClick={() => {
                reset();
                if (onCancel) onCancel();
              }}
              disabled={isSubmitting}
            >
              Cancel
            </Button>
            <Button type="submit" disabled={!isDirty || isSubmitting} className="min-w-[100px]">
              {isSubmitting ? <Loader2 className="w-4 h-4 animate-spin" /> : 'Save'}
            </Button>
          </div>
        </div>

        <div className="grid grid-cols-2 gap-x-8 gap-y-4">
          <div>
            <Label className="text-xs text-slate-500 block mb-1">Name</Label>
            <Input {...register('name')} required />
          </div>
          <div className="mt-4 col-span-2">
            <Label className="text-xs text-slate-500 block mb-1">Webhook URL</Label>
            <Input {...register('url')} required placeholder="https://api.acme.com/inbound" />
          </div>
        </div>
      </form>
    </div>
  );
}
