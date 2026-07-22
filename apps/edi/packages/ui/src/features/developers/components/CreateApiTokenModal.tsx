import { useState } from 'react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from '@/components/ui/dialog';
import { Label } from '@/components/ui/label';
import { Key } from 'lucide-react';
import { useCreateApiTokenMutation } from '../api/apiTokenHooks';
import { TokenCredentialsModal } from './TokenCredentialsModal';
import type { ApiTokenCreated } from '../types';

export function CreateApiTokenModal() {
  const [open, setOpen] = useState(false);
  const [name, setName] = useState('');
  const [createdToken, setCreatedToken] = useState<ApiTokenCreated | null>(null);

  const createMutation = useCreateApiTokenMutation();

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
        <DialogTrigger asChild>
          <Button className="gap-2 bg-indigo-600 hover:bg-indigo-700 text-white">
            <Key className="w-4 h-4" />
            Generate Token
          </Button>
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
              className="bg-indigo-600 hover:bg-indigo-700 text-white"
            >
              {createMutation.isPending ? 'Generating...' : 'Generate Token'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {createdToken && (
        <TokenCredentialsModal
          token={createdToken}
          onClose={() => setCreatedToken(null)}
        />
      )}
    </>
  );
}
