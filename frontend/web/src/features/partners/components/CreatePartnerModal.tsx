import { useState } from 'react';
import { Button } from '@/components/ui/button';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger } from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Plus } from 'lucide-react';
import { CertificateInput } from './CertificateInput';
import { useCreatePlatformPartnerMutation } from '../api/partnerHooks';
import { usePlatformConfig } from '@/features/platform/api/configHooks';
import { useToast } from '@/hooks/use-toast';
import { Combobox } from '@/components/ui/combobox';
import { useEffect } from 'react';

export function CreatePartnerModal({ existingAs2Ids = [] }: { existingAs2Ids?: string[] }) {
  const [isOpen, setIsOpen] = useState(false);
  const [isLocal, setIsLocal] = useState(false);
  const [certPem, setCertPem] = useState('');
  const [as2Id, setAs2Id] = useState('');
  const [url, setUrl] = useState('');

  const isDuplicate = existingAs2Ids.includes(as2Id);

  const { data: platformConfig } = usePlatformConfig();
  const { toast } = useToast();
  const createPartner = useCreatePlatformPartnerMutation();

  useEffect(() => {
    if (isLocal && !url && platformConfig?.available_as2_receive_urls?.length) {
      setUrl(platformConfig.available_as2_receive_urls[0]);
    }
  }, [isLocal, platformConfig, url]);

  const reset = () => {
    setIsLocal(false);
    setCertPem('');
    setAs2Id('');
    setUrl('');
  };

  const handleOpenChange = (open: boolean) => {
    setIsOpen(open);
    if (!open) reset();
  };

  const handleSubmit = async (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    const data = new FormData(e.currentTarget);

    if (!url || url.trim() === '') {
      toast({ title: 'Error', description: 'Receiving URL is required.', variant: 'destructive' });
      return;
    }

    try {
      new URL(url);
    } catch {
      toast({ title: 'Error', description: 'Receiving URL must be a valid URL.', variant: 'destructive' });
      return;
    }

    createPartner.mutate(
      {
        name: data.get('name') as string,
        type: 'AS2',
        as2_id: data.get('as2_id') as string,
        is_local: isLocal,
        url: url,
        public_cert_pem: isLocal ? undefined : certPem,
      },
      {
        onSuccess: () => {
          setIsOpen(false);
          reset();
        },
      },
    );
  };

  return (
    <Dialog open={isOpen} onOpenChange={handleOpenChange}>
      <DialogTrigger asChild>
        <Button className="flex items-center gap-2 bg-indigo-600 hover:bg-indigo-700 text-white rounded-xl shadow-sm">
          <Plus className="h-4 w-4" />
          Create Trading Partner
        </Button>
      </DialogTrigger>

      <DialogContent className="sm:max-w-[600px] rounded-2xl" onPointerDownOutside={(e) => e.preventDefault()}>
        <DialogHeader>
          <DialogTitle className="text-xl">Add AS2 Partner</DialogTitle>
        </DialogHeader>

        <form onSubmit={handleSubmit} className="grid gap-6 py-4">
          {/* Local / Remote toggle */}
          <div className="flex items-center gap-2 pb-2 border-b border-slate-100">
            <Input
              type="checkbox"
              id="is_local"
              checked={isLocal}
              onChange={(e) => setIsLocal(e.target.checked)}
              className="h-4 w-4 rounded border-slate-300 text-indigo-600 focus:ring-indigo-600"
            />
            <Label htmlFor="is_local" className="text-slate-600 font-medium">
              This is a Local Trading Partner (Generates Certificate automatically)
            </Label>
          </div>

          {/* Name + AS2 ID */}
          <div className="grid grid-cols-2 gap-6">
            <div className="grid gap-2">
              <Label htmlFor="name" className="text-slate-600 font-medium">Partner Name</Label>
              <Input id="name" name="name" required placeholder="e.g. Acme Corp" className="h-10 rounded-xl" />
            </div>
            <div className="grid gap-2">
              <Label htmlFor="as2_id" className="text-slate-600 font-medium">AS2 ID</Label>
              <Input
                id="as2_id"
                name="as2_id"
                required
                value={as2Id}
                onChange={(e) => setAs2Id(e.target.value)}
                placeholder="ACME_AS2"
                className={`h-10 rounded-xl ${isDuplicate ? 'border-red-500 focus-visible:ring-red-500' : ''}`}
              />
              {isDuplicate && (
                <span className="text-xs font-medium text-red-500">AS2 ID is already in use</span>
              )}
            </div>
          </div>

          <div className="grid gap-2">
            <Label className="text-slate-600 font-medium">Receiving URL</Label>
            {isLocal ? (
              <Combobox
                options={platformConfig?.available_as2_receive_urls || []}
                value={url}
                onChange={setUrl}
                placeholder="https://..."
                emptyText="Type custom URL..."
              />
            ) : (
              <Input
                value={url}
                onChange={e => setUrl(e.target.value)}
                placeholder="https://acme.com/as2/receive"
                className="h-10 rounded-xl"
                required
              />
            )}
          </div>

          {/* Certificate — remote partners only */}
          {!isLocal && (
            <div className="grid gap-2">
              <Label className="text-slate-600 font-medium">Public Certificate</Label>
              <CertificateInput value={certPem} onChange={setCertPem} />
            </div>
          )}

          <div className="flex justify-end mt-2">
            <Button
              type="submit"
              disabled={createPartner.isPending || isDuplicate}
              className="h-11 px-8 text-base font-semibold shadow-sm rounded-xl bg-indigo-600 hover:bg-indigo-700 text-white disabled:opacity-50"
            >
              {createPartner.isPending ? 'Saving...' : 'Save'}
            </Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
}
