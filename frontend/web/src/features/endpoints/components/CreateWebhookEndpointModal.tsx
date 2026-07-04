import { useState } from 'react';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { FormModal } from '@/components/ui/form-modal';
import { useCreateWebhookEndpointMutation } from '../api/endpointsHooks';
import { useToast } from '@/hooks/use-toast';
import { Webhook } from 'lucide-react';

export function CreateWebhookEndpointModal() {
  const [isOpen, setIsOpen] = useState(false);
  const [name, setName] = useState('');
  const [url, setUrl] = useState('');
  const [authHeader, setAuthHeader] = useState('');

  const { toast } = useToast();
  const createWebhook = useCreateWebhookEndpointMutation();

  const reset = () => {
    setName('');
    setUrl('');
    setAuthHeader('');
  };

  const handleOpenChange = (open: boolean) => {
    setIsOpen(open);
    if (!open) reset();
  };

  const handleSubmit = async (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    if (!url) {
      toast({ title: 'Error', description: 'Webhook URL is required', variant: 'destructive' });
      return;
    }
    try {
      await createWebhook.mutateAsync({
        name,
        url,
        auth_header_vault_ref: authHeader || undefined
      });
      setIsOpen(false);
      reset();
    } catch {
      // Error handled by mutation toast
    }
  };

  return (
    <FormModal
      title="Add Webhook Endpoint"
      triggerText="Add Webhook"
      icon={<Webhook className="w-5 h-5" />}
      isOpen={isOpen}
      onOpenChange={handleOpenChange}
      onSubmit={handleSubmit}
      isPending={createWebhook.isPending}
      submitText="Save Endpoint"
    >
      <div className="grid gap-6">
        <div className="grid gap-2">
          <Label htmlFor="name" className="text-slate-600 font-medium">Endpoint Name</Label>
          <Input
            id="name"
            value={name}
            onChange={(e) => setName(e.target.value)}
            required
            placeholder="e.g. Acme NetSuite ERP"
            className="h-10 rounded-xl"
          />
        </div>

        <div className="grid gap-2">
          <Label className="text-slate-600 font-medium">Webhook URL</Label>
          <Input
            value={url}
            onChange={e => setUrl(e.target.value)}
            placeholder="https://api.your-erp.com/edi-inbox"
            className="h-10 rounded-xl font-mono text-sm"
            required
          />
        </div>
        <div className="grid gap-2">
          <Label className="text-slate-600 font-medium">Authorization Header (Stored securely in Vault)</Label>
          <Input
            value={authHeader}
            onChange={e => setAuthHeader(e.target.value)}
            placeholder="Bearer token123..."
            className="h-10 rounded-xl font-mono text-sm"
          />
        </div>
      </div>
    </FormModal>
  );
}
