import { Loader2 } from 'lucide-react';
import React, { useState } from 'react';
import { Button } from '../../../components/ui/button';
import { Input } from '../../../components/ui/input';
import { Label } from '../../../components/ui/label';
import type { WebhookHookConfig } from '../api/webhookHooks';
import { useUpdateWebhookMutation } from '../api/webhookHooks';
import type { Webhook } from '../types';

export function WebhookDetails({
  config,
  webhook,
  onCancel,
}: {
  config: WebhookHookConfig;
  webhook: Webhook;
  onCancel?: () => void;
}) {
  const updateMutation = useUpdateWebhookMutation(config);

  const [name, setName] = useState(webhook.name);
  const [url, setUrl] = useState(webhook.url);
  const [errors, setErrors] = useState<{ name?: string; url?: string }>({});

  const isDirty = name !== webhook.name || url !== webhook.url;

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();

    // Simple validation
    const newErrors: { name?: string; url?: string } = {};
    if (!name.trim()) newErrors.name = 'Name is required';
    if (!url.trim()) {
      newErrors.url = 'URL is required';
    } else if (!/^https?:\/\/.+/.test(url)) {
      newErrors.url = 'Must be a valid HTTP/HTTPS URL';
    }

    if (Object.keys(newErrors).length > 0) {
      setErrors(newErrors);
      return;
    }
    setErrors({});

    updateMutation.mutate(
      { id: webhook.id, payload: { name, url } },
      {
        onSuccess: () => {
          if (onCancel) onCancel();
        },
      },
    );
  };

  return (
    <div className="p-6 bg-slate-50/50 rounded-lg border border-slate-200">
      <form onSubmit={handleSubmit} className="space-y-6 max-w-4xl">
        <div className="grid grid-cols-1 md:grid-cols-[1fr_2.5fr] gap-6">
          <div className="space-y-2">
            <Label htmlFor={`name-${webhook.id}`}>Webhook Name</Label>
            <Input
              id={`name-${webhook.id}`}
              value={name}
              onChange={(e) => setName(e.target.value)}
              className={errors.name ? 'border-red-500' : ''}
              placeholder="e.g. Acme Webhook"
            />
            {errors.name && <p className="text-sm text-red-500">{errors.name}</p>}
          </div>

          <div className="space-y-2">
            <Label htmlFor={`url-${webhook.id}`}>Endpoint URL</Label>
            <Input
              id={`url-${webhook.id}`}
              type="url"
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              className={errors.url ? 'border-red-500 font-mono text-sm' : 'font-mono text-sm'}
              placeholder="https://api.example.com/webhook"
            />
            {errors.url && <p className="text-sm text-red-500">{errors.url}</p>}
          </div>
        </div>

        {updateMutation.error && (
          <div className="text-sm text-red-600 bg-red-50 border border-red-200 rounded-md px-3 py-2">
            {updateMutation.error.message}
          </div>
        )}

        <div className="flex justify-end gap-3 pt-4 border-t border-slate-200">
          <Button type="button" variant="outline" onClick={onCancel}>
            Cancel
          </Button>
          <Button type="submit" disabled={!isDirty || updateMutation.isPending}>
            {updateMutation.isPending && <Loader2 className="w-4 h-4 mr-2 animate-spin" />}
            Save Changes
          </Button>
        </div>
      </form>
    </div>
  );
}
