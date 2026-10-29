import { Loader2 } from 'lucide-react';
import React, { useState } from 'react';
import { Button } from '../../../components/ui/button';
import { Input } from '../../../components/ui/input';
import { Label } from '../../../components/ui/label';
import type { WebhookHookConfig } from '../api/webhookHooks';
import { useUpdateWebhookMutation } from '../api/webhookHooks';
import type { Webhook } from '../types';

interface WebhookFieldErrors {
  name?: string;
  url?: string;
}

function validateWebhookInput(name: string, url: string): WebhookFieldErrors {
  const errors: WebhookFieldErrors = {};
  if (!name.trim()) {
    errors.name = 'Name is required';
  }
  if (!url.trim()) {
    errors.url = 'URL is required';
  } else if (!/^https?:\/\/.+/.test(url)) {
    errors.url = 'Must be a valid HTTP/HTTPS URL';
  }
  return errors;
}

export function WebhookDetails({
  config,
  webhook,
  onCancel,
}: {
  readonly config: WebhookHookConfig;
  readonly webhook: Webhook;
  readonly onCancel?: () => void;
}) {
  const updateMutation = useUpdateWebhookMutation(config);

  const [name, setName] = useState(webhook.name);
  const [url, setUrl] = useState(webhook.url);
  const [errors, setErrors] = useState<WebhookFieldErrors>({});
  const [problemMessage, setProblemMessage] = useState<string | null>(null);

  const isDirty = name !== webhook.name || url !== webhook.url;

  const handleSubmit = (e: React.FormEvent): void => {
    e.preventDefault();
    const nextErrors = validateWebhookInput(name, url);
    if (Object.keys(nextErrors).length > 0) {
      setErrors(nextErrors);
      return;
    }
    setErrors({});
    setProblemMessage(null);

    updateMutation.mutate(
      { id: webhook.id, payload: { name, url } },
      {
        onSuccess: (result) => {
          if (!result.ok) {
            setProblemMessage(result.error.message);
            return;
          }
          onCancel?.();
        },
      },
    );
  };

  return (
    <div className="rounded-lg border border-slate-200 bg-slate-50/50 p-6">
      <form onSubmit={handleSubmit} className="space-y-6">
        <div className="mb-6 flex items-center justify-between">
          <h4 className="text-sm font-semibold tracking-wider text-slate-900 uppercase">
            Webhook Details
          </h4>
          <div className="flex justify-end gap-2">
            <Button
              type="button"
              variant="outline"
              className="h-10 rounded-xl px-5 text-sm font-semibold"
              onClick={onCancel}
            >
              Cancel
            </Button>
            <Button
              type="submit"
              disabled={!isDirty || updateMutation.isPending}
              className="h-10 min-w-20 rounded-xl bg-indigo-600 px-5 text-sm font-semibold text-white hover:bg-indigo-700"
            >
              {updateMutation.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : 'Save'}
            </Button>
          </div>
        </div>

        <div className="grid max-w-4xl grid-cols-1 gap-6 md:grid-cols-3">
          <div className="space-y-2 md:col-span-1">
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

          <div className="space-y-2 md:col-span-2">
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

        {problemMessage && (
          <div className="mt-4 rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-600">
            {problemMessage}
          </div>
        )}
      </form>
    </div>
  );
}
