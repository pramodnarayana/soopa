import { Button, buttonVariants } from '@soopa/ui/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from '@soopa/ui/components/ui/dialog';
import { Input } from '@soopa/ui/components/ui/input';
import { Label } from '@soopa/ui/components/ui/label';
import { Key } from 'lucide-react';
import { useState } from 'react';
import { useTenantId } from '../../../contexts/TenantContext';
import { useCreateApiTokenMutation } from '../api/apiTokenHooks';
import type { ApiTokenCreated } from '../types';
import { TokenCredentialsModal } from './TokenCredentialsModal';

export function CreateApiTokenModal() {
  const tenantId = useTenantId();
  const [open, setOpen] = useState(false);
  const [name, setName] = useState('');
  const [createdToken, setCreatedToken] = useState<ApiTokenCreated | null>(null);

  const createMutation = useCreateApiTokenMutation(tenantId);

  const handleCreate = async () => {
    if (!name.trim()) return;
    try {
      const data = await createMutation.mutateAsync({ name: name.trim() });
      setCreatedToken(data);
      setOpen(false);
      setName('');
    } catch {
      // Error handled by hook toast
    }
  };

  return (
    <>
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogTrigger className={buttonVariants({ size: 'cta' })}>
          <Key className="w-4 h-4" />
          Generate Token
        </DialogTrigger>
        <DialogContent className="sm:max-w-[425px]">
          <DialogHeader>
            <DialogTitle>Generate New API Token</DialogTitle>
            <DialogDescription>
              Create a new API token for machine-to-machine integrations.
            </DialogDescription>
          </DialogHeader>
          <div className="grid gap-4 py-4">
            <div className="grid gap-2">
              <Label htmlFor="name">Token Name</Label>
              <Input
                id="name"
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="e.g. ERP Prod Integration"
                autoFocus
              />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setOpen(false)}>
              Cancel
            </Button>
            <Button
              onClick={handleCreate}
              disabled={!name.trim() || createMutation.isPending}
              size="cta"
            >
              {createMutation.isPending ? 'Generating...' : 'Generate Token'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {createdToken && (
        <TokenCredentialsModal token={createdToken} onClose={() => setCreatedToken(null)} />
      )}
    </>
  );
}
