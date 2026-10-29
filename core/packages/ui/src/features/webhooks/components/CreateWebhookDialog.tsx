import { Network } from 'lucide-react';
import React, { useState } from 'react';
import { Button } from '../../../components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '../../../components/ui/dialog';
import { Input } from '../../../components/ui/input';
import { Label } from '../../../components/ui/label';
import type { WebhookHookConfig } from '../api/webhookHooks';
import { useCreateWebhookMutation } from '../api/webhookHooks';

interface CreateWebhookDialogProps {
  readonly config: WebhookHookConfig;
  readonly open: boolean;
  readonly onOpenChange: (open: boolean) => void;
}

export function CreateWebhookDialog({ config, open, onOpenChange }: CreateWebhookDialogProps) {
  const [name, setName] = useState('');
  const [url, setUrl] = useState('');
  const [problemMessage, setProblemMessage] = useState<string | null>(null);
  const createMutation = useCreateWebhookMutation(config);

  const reset = (): void => {
    setName('');
    setUrl('');
    setProblemMessage(null);
  };

  const handleOpenChange = (next: boolean): void => {
    onOpenChange(next);
    if (!next) {
      reset();
    }
  };

  const handleSubmit = async (e: React.FormEvent<HTMLFormElement>): Promise<void> => {
    e.preventDefault();
    if (!url) {
      return;
    }
    setProblemMessage(null);
    const result = await createMutation.mutateAsync({ name, url });
    if (!result.ok) {
      setProblemMessage(result.error.message);
      return;
    }
    handleOpenChange(false);
  };

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Network className="h-5 w-5 text-indigo-600" />
            Add Webhook
          </DialogTitle>
          <DialogDescription>
            Register an HTTPS endpoint to receive platform events.
          </DialogDescription>
        </DialogHeader>

        <form id="create-webhook-form" onSubmit={handleSubmit} className="mt-2 grid gap-4">
          <div className="grid gap-1.5">
            <Label htmlFor="webhook-name">Name</Label>
            <Input
              id="webhook-name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="My production webhook"
              required
            />
          </div>
          <div className="grid gap-1.5">
            <Label htmlFor="webhook-url">URL</Label>
            <Input
              id="webhook-url"
              type="url"
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              placeholder="https://api.acme.com/inbound"
              required
            />
          </div>
          {problemMessage && (
            <div className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-600">
              {problemMessage}
            </div>
          )}
        </form>

        <DialogFooter>
          <Button type="button" variant="outline" onClick={() => handleOpenChange(false)}>
            Cancel
          </Button>
          <Button
            size="cta"
            form="create-webhook-form"
            type="submit"
            disabled={createMutation.isPending}
          >
            {createMutation.isPending ? 'Saving…' : 'Save Webhook'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
