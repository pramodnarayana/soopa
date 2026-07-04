import { useState } from 'react';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { FormModal } from '@/components/ui/form-modal';
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
    <FormModal
      title="Add AS2 Partner"
      triggerText="Create Trading Partner"
      isOpen={isOpen}
      onOpenChange={handleOpenChange}
      onSubmit={handleSubmit}
      isPending={createPartner.isPending}
      submitDisabled={isDuplicate}
      submitText="Create Trading Partner"
    >
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
    </FormModal>
  );
}
