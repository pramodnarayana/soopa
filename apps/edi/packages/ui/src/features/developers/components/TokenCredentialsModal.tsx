import { Alert, AlertDescription, AlertTitle } from '@soopa/ui';
import { Button } from '@soopa/ui/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@soopa/ui/components/ui/dialog';
import { Input } from '@soopa/ui/components/ui/input';
import { AlertTriangle, Check, Copy } from 'lucide-react';
import { useState } from 'react';
import { useToast } from '../../../hooks/use-toast';
import type { ApiTokenCreated } from '../types';

interface Props {
  token: ApiTokenCreated;
  onClose: () => void;
}

export function TokenCredentialsModal({ token, onClose }: Props) {
  const [copiedId, setCopiedId] = useState(false);
  const [copiedSecret, setCopiedSecret] = useState(false);
  const [copiedCombined, setCopiedCombined] = useState(false);
  const { toast } = useToast();

  const copyToClipboard = async (text: string, type: 'id' | 'secret' | 'combined') => {
    try {
      await navigator.clipboard.writeText(text);
      if (type === 'secret') {
        setCopiedSecret(true);
        setTimeout(() => setCopiedSecret(false), 2000);
      } else if (type === 'id') {
        setCopiedId(true);
        setTimeout(() => setCopiedId(false), 2000);
      } else {
        setCopiedCombined(true);
        setTimeout(() => setCopiedCombined(false), 2000);
      }
    } catch {
      toast({
        title: 'Error',
        description: 'Failed to copy to clipboard.',
        variant: 'destructive',
      });
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
            If you lose this secret, you will need to generate a new token. We do not store the raw
            secret in our database.
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
                onClick={() => copyToClipboard(token.client_id, 'id')}
                className="shrink-0"
              >
                {copiedId ? (
                  <Check className="h-4 w-4 text-green-600" />
                ) : (
                  <Copy className="h-4 w-4" />
                )}
              </Button>
            </div>
          </div>

          <div className="grid gap-2">
            <span className="text-sm font-medium text-slate-700">Client Secret</span>
            <div className="flex gap-2">
              <Input
                value={token.token.split('.')[1] || ''}
                readOnly
                type="password"
                className="font-mono text-sm bg-slate-50"
              />
              <Button
                variant="outline"
                size="icon"
                onClick={() => copyToClipboard(token.token.split('.')[1] || '', 'secret')}
                className="shrink-0"
              >
                {copiedSecret ? (
                  <Check className="h-4 w-4 text-green-600" />
                ) : (
                  <Copy className="h-4 w-4" />
                )}
              </Button>
            </div>
          </div>

          <div className="grid gap-2">
            <span className="text-sm font-medium text-slate-700">
              Combined Token (Bearer Token)
            </span>
            <div className="flex gap-2">
              <Input
                value={token.token}
                readOnly
                type="password"
                className="font-mono text-sm bg-slate-50"
              />
              <Button
                variant="outline"
                size="icon"
                onClick={() => copyToClipboard(token.token, 'combined')}
                className="shrink-0"
              >
                {copiedCombined ? (
                  <Check className="h-4 w-4 text-green-600" />
                ) : (
                  <Copy className="h-4 w-4" />
                )}
              </Button>
            </div>
          </div>
        </div>

        <div className="p-4 rounded-lg bg-indigo-50 border border-indigo-100 text-sm text-indigo-900">
          <p className="font-semibold text-indigo-950 mb-1">Developer Note: How to authenticate</p>
          <p className="text-indigo-800">
            Include the Combined Token in your HTTP requests using the standard Authorization
            header. If using Postman, select <strong>"Bearer Token"</strong> and paste the Combined
            Token exactly as is.
          </p>
          <code className="block mt-2 p-2.5 bg-white rounded border border-indigo-100 font-mono text-xs text-indigo-950">
            Authorization: Bearer {'<COMBINED_TOKEN>'}
          </code>
          <p className="text-xs text-indigo-700 mt-2 font-medium">
            Note: Do not manually type the word "Bearer" when using Postman's Auth tab, as Postman
            adds it automatically.
          </p>
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
