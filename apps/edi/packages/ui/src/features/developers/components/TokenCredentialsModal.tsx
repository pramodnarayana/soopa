import { useState } from 'react';
import { useToast } from '@/hooks/use-toast';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Check, Copy, AlertTriangle } from 'lucide-react';
import type { ApiTokenCreated } from '../types';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Input } from '@/components/ui/input';

interface Props {
  token: ApiTokenCreated;
  onClose: () => void;
}

export function TokenCredentialsModal({ token, onClose }: Props) {
  const [copiedId, setCopiedId] = useState(false);
  const [copiedSecret, setCopiedSecret] = useState(false);
  const { toast } = useToast();

  const copyToClipboard = async (text: string, isSecret: boolean) => {
    try {
      await navigator.clipboard.writeText(text);
      if (isSecret) {
        setCopiedSecret(true);
        setTimeout(() => setCopiedSecret(false), 2000);
      } else {
        setCopiedId(true);
        setTimeout(() => setCopiedId(false), 2000);
      }
    } catch {
      toast({ title: 'Error', description: 'Failed to copy to clipboard.', variant: 'destructive' });
    }
  };

  return (
    <Dialog open={true} onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="sm:max-w-[550px]">
        <DialogHeader>
          <DialogTitle className="text-xl">Token Generated Successfully</DialogTitle>
          <DialogDescription>
            Please copy your client secret now. For your security, it will never be shown again.
          </DialogDescription>
        </DialogHeader>

        <Alert variant="destructive" className="bg-amber-50 text-amber-900 border-amber-200">
          <AlertTriangle className="h-4 w-4 text-amber-600" />
          <AlertTitle className="text-amber-800">Store this secret securely</AlertTitle>
          <AlertDescription className="text-amber-700">
            If you lose this secret, you will need to generate a new token. We do not store the raw secret in our database.
          </AlertDescription>
        </Alert>

        <div className="grid gap-4 py-4">
          <div className="grid gap-2">
            <span className="text-sm font-medium text-slate-700">Client ID</span>
            <div className="flex gap-2">
              <Input value={token.client_id} readOnly className="font-mono text-sm bg-slate-50" />
              <Button
                variant="outline"
                size="icon"
                onClick={() => copyToClipboard(token.client_id, false)}
                className="shrink-0"
              >
                {copiedId ? <Check className="h-4 w-4 text-green-600" /> : <Copy className="h-4 w-4" />}
              </Button>
            </div>
          </div>

          <div className="grid gap-2">
            <span className="text-sm font-medium text-slate-700">Client Secret</span>
            <div className="flex gap-2">
              <Input value={token.client_secret} readOnly className="font-mono text-sm bg-slate-50" />
              <Button
                variant="outline"
                size="icon"
                onClick={() => copyToClipboard(token.client_secret, true)}
                className="shrink-0"
              >
                {copiedSecret ? <Check className="h-4 w-4 text-green-600" /> : <Copy className="h-4 w-4" />}
              </Button>
            </div>
          </div>
        </div>

        <DialogFooter>
          <Button onClick={onClose} className="w-full bg-indigo-600 hover:bg-indigo-700 text-white">
            I have copied my secret
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
