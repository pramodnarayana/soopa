import { Network } from 'lucide-react';
import { useState } from 'react';
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
  config: WebhookHookConfig;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

export function CreateWebhookDialog({ config, open, onOpenChange }: CreateWebhookDialogProps) {
  const [name, setName] = useState('');
  const [url, setUrl] = useState('');
  const createMutation = useCreateWebhookMutation(config);

  const reset = () => {
    setName('');
    setUrl('');
  };

  const handleOpenChange = (next: boolean) => {
    onOpenChange(next);
    if (!next) reset();
  };

  const handleSubmit = async (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    if (!url) return;
    try {
      await createMutation.mutateAsync({ name, url });
      handleOpenChange(false);
    } catch {
      // error surfaced by react-query onError
    }
  };

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Network className="w-5 h-5 text-indigo-600" />
            Add Webhook
          </DialogTitle>
          <DialogDescription render={<span />}>
            Register an HTTPS endpoint to receive platform events.
          </DialogDescription>
        </DialogHeader>

        <form id="create-webhook-form" onSubmit={handleSubmit} className="grid gap-4 mt-2">
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
        </form>

        <DialogFooter>
          <Button variant="outline" onClick={() => handleOpenChange(false)}>
            Cancel
          </Button>
          <Button form="create-webhook-form" type="submit" disabled={createMutation.isPending}>
            {createMutation.isPending ? 'Saving…' : 'Save Webhook'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
