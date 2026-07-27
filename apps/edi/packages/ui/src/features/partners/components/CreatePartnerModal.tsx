import { Loader2 } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';
import { Button } from '@/components/ui/button';
import { Combobox } from '@/components/ui/combobox';
import { FormModal } from '@/components/ui/form-modal';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { usePlatformSettings } from '@/features/platform/api/settingsHooks';
import { useToast } from '@/hooks/use-toast';
import {
  useCreateAS2PartnerMutation,
  useDeleteCertificateSecretMutation,
  useGenerateCertificateMutation,
} from '../api/partnerHooks';
import { extractCertificateMaterial } from '../utils/certificate';
import { CertificateInput } from './CertificateInput';

export function CreatePartnerModal({ existingAs2Ids = [] }: { existingAs2Ids?: string[] }) {
  const [isOpen, setIsOpen] = useState(false);
  const [isLocal, setIsLocal] = useState(false);
  const [certPem, setCertPem] = useState('');
  const [privateKeyVaultRef, setPrivateKeyVaultRef] = useState<string | null>(null);
  const [generatedForAs2Id, setGeneratedForAs2Id] = useState<string | null>(null);
  const [as2Id, setAs2Id] = useState('');
  const [url, setUrl] = useState('');

  const isOpenRef = useRef(isOpen);
  useEffect(() => {
    isOpenRef.current = isOpen;
  }, [isOpen]);

  const isLocalRef = useRef(isLocal);
  useEffect(() => {
    isLocalRef.current = isLocal;
  }, [isLocal]);

  const isDuplicate = existingAs2Ids.includes(as2Id);

  const { data: platformSettings } = usePlatformSettings();
  const { toast } = useToast();
  const createPartner = useCreateAS2PartnerMutation();
  const generateCert = useGenerateCertificateMutation();
  const deleteCertSecret = useDeleteCertificateSecretMutation();

  const handleCleanup = async () => {
    if (privateKeyVaultRef) {
      await deleteCertSecret.mutateAsync(privateKeyVaultRef);
    }
  };

  const reset = async () => {
    // Only cleanup if we are abandoning an unsaved draft
    try {
      await handleCleanup();
      setPrivateKeyVaultRef(null);
      setCertPem('');
      setGeneratedForAs2Id(null);
      setIsLocal(false);
      setAs2Id('');
      setUrl('');
    } catch (e) {
      console.error('Failed to cleanup orphaned secret during reset', e);
    }
  };

  const handleOpenChange = (open: boolean) => {
    setIsOpen(open);
    if (!open) {
      void reset();
    }
  };

  const handleSubmit = async (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    const data = new FormData(e.currentTarget);
    const submittedAs2Id = data.get('as2_id') as string;

    if (!url || url.trim() === '') {
      toast({ title: 'Error', description: 'Receiving URL is required.', variant: 'destructive' });
      return;
    }

    try {
      new URL(url);
    } catch {
      toast({
        title: 'Error',
        description: 'Receiving URL must be a valid URL.',
        variant: 'destructive',
      });
      return;
    }

    // Check if AS2 ID changed after generating cert
    let finalCertPem = certPem;
    const finalVaultRef = privateKeyVaultRef;
    let extractedPrivateKey = '';

    if (isLocal && !privateKeyVaultRef && certPem) {
      const { publicCert, privateKey } = extractCertificateMaterial(certPem);
      finalCertPem = publicCert;
      extractedPrivateKey = privateKey;
    }

    if (
      isLocal &&
      privateKeyVaultRef &&
      generatedForAs2Id &&
      submittedAs2Id !== generatedForAs2Id
    ) {
      // Invalidate existing if AS2 ID changed
      try {
        await handleCleanup();
        setPrivateKeyVaultRef(null);
        setCertPem('');
        setGeneratedForAs2Id(null);
      } catch {
        toast({
          title: 'Error',
          description: 'Failed to cleanup old certificate.',
          variant: 'destructive',
        });
        return;
      }
      toast({
        title: 'Warning',
        description: 'AS2 ID changed. Please regenerate the certificate.',
        variant: 'destructive',
      });
      return;
    }

    createPartner.mutate(
      {
        name: data.get('name') as string,
        type: 'AS2',
        as2_id: submittedAs2Id,
        is_local: isLocal,
        url: url,
        // Always pass the cert PEM if the user provided one
        public_cert_pem: finalCertPem || undefined,
        // If user went through the generate flow, send vault ref
        // If user uploaded their own key, send the raw PEM so backend stores it
        private_key_vault_ref: finalVaultRef || undefined,
        private_key_pem:
          isLocal && !finalVaultRef && extractedPrivateKey ? extractedPrivateKey : undefined,
      },
      {
        onSuccess: () => {
          setIsOpen(false);
          // Don't call reset() here because we don't want to delete the saved secret
          setIsLocal(false);
          setCertPem('');
          setPrivateKeyVaultRef(null);
          setGeneratedForAs2Id(null);
          setAs2Id('');
          setUrl('');
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
      maxWidth="sm:max-w-[780px]"
    >
      {/* Local / Remote toggle */}
      <div className="flex items-center gap-3">
        <Label className="text-slate-600 font-medium">Partner Type</Label>
        <button
          type="button"
          role="switch"
          aria-checked={isLocal}
          onClick={async () => {
            const nextIsLocal = !isLocal;
            if (nextIsLocal) {
              try {
                await handleCleanup();
                setPrivateKeyVaultRef(null);
                setCertPem('');
                setGeneratedForAs2Id(null);
              } catch {
                toast({
                  title: 'Error',
                  description: 'Failed to cleanup old certificate.',
                  variant: 'destructive',
                });
                return;
              }
              setIsLocal(nextIsLocal);
              if (!url && platformSettings?.available_as2_receive_urls?.length) {
                setUrl(platformSettings.available_as2_receive_urls[0]);
              }
            } else {
              try {
                await handleCleanup();
                setPrivateKeyVaultRef(null);
                setCertPem('');
                setGeneratedForAs2Id(null);
              } catch {
                toast({
                  title: 'Error',
                  description: 'Failed to cleanup old certificate.',
                  variant: 'destructive',
                });
                return;
              }
              setIsLocal(nextIsLocal);
              if (platformSettings?.available_as2_receive_urls?.includes(url)) {
                setUrl('');
              }
            }
          }}
          className={`relative inline-flex h-7 w-[90px] shrink-0 cursor-pointer items-center rounded-full border transition-colors duration-200 ease-in-out focus:outline-none focus:ring-2 focus:ring-offset-2 ${isLocal ? 'bg-indigo-50 border-indigo-200 focus:ring-indigo-200' : 'bg-violet-50 border-violet-200 focus:ring-violet-200'}`}
        >
          <span
            className={`absolute left-2.5 text-[10px] font-bold uppercase tracking-wider transition-opacity duration-200 ${isLocal ? 'opacity-100 text-indigo-700' : 'opacity-0'}`}
          >
            Local
          </span>
          <span
            className={`absolute right-1.5 text-[10px] font-bold uppercase tracking-wider transition-opacity duration-200 ${isLocal ? 'opacity-0' : 'opacity-100 text-violet-700'}`}
          >
            Remote
          </span>
          <span
            aria-hidden="true"
            className={`pointer-events-none absolute left-1 flex h-5 w-5 transform items-center justify-center rounded-full shadow ring-0 transition-transform duration-200 ease-in-out ${isLocal ? 'translate-x-[62px] bg-indigo-600' : 'translate-x-0 bg-violet-600'}`}
          />
        </button>
      </div>

      {/* Name + AS2 ID */}
      <div className="grid grid-cols-2 gap-6">
        <div className="grid gap-2">
          <Label htmlFor="name" className="text-slate-600 font-medium">
            Partner Name
          </Label>
          <Input
            id="name"
            name="name"
            required
            placeholder="e.g. Acme Corp"
            className="h-10 rounded-xl"
          />
        </div>
        <div className="grid gap-2">
          <Label htmlFor="as2_id" className="text-slate-600 font-medium">
            AS2 ID
          </Label>
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
            options={platformSettings?.available_as2_receive_urls || []}
            value={url}
            onChange={setUrl}
            placeholder="https://..."
            emptyText="Type custom URL..."
          />
        ) : (
          <Input
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            placeholder="https://acme.com/as2/receive"
            className="h-10 rounded-xl"
            required
          />
        )}
      </div>

      {/* Certificate */}
      <div className="grid gap-2">
        <Label className="text-slate-600 font-medium">Public Certificate</Label>
        <CertificateInput
          value={certPem}
          onChange={setCertPem}
          extraActions={
            isLocal ? (
              <Button
                type="button"
                variant="outline"
                size="sm"
                className="gap-2"
                disabled={generateCert.isPending}
                onClick={async () => {
                  if (!as2Id.trim()) {
                    toast({
                      title: 'Error',
                      description: 'Please enter an AS2 ID first to use as the Common Name.',
                      variant: 'destructive',
                    });
                    return;
                  }
                  if (privateKeyVaultRef) {
                    try {
                      await handleCleanup();
                      setPrivateKeyVaultRef(null);
                      setCertPem('');
                      setGeneratedForAs2Id(null);
                    } catch {
                      toast({
                        title: 'Error',
                        description: 'Failed to cleanup old certificate.',
                        variant: 'destructive',
                      });
                      return;
                    }
                  }
                  generateCert.mutate(as2Id, {
                    onSuccess: (res) => {
                      if (!isOpenRef.current || !isLocalRef.current) {
                        // The modal was closed or switched to remote while the mutation was inflight.
                        // Cleanup the newly created orphaned secret immediately.
                        deleteCertSecret.mutate(res.private_key_vault_ref);
                        return;
                      }
                      setCertPem(res.public_cert_pem);
                      setPrivateKeyVaultRef(res.private_key_vault_ref);
                      setGeneratedForAs2Id(as2Id);
                      toast({
                        title: 'Certificate Generated',
                        description: 'The certificate has been generated and populated.',
                      });
                    },
                    onError: () => {
                      toast({
                        title: 'Error',
                        description: 'Failed to generate certificate.',
                        variant: 'destructive',
                      });
                    },
                  });
                }}
              >
                {generateCert.isPending ? <Loader2 className="w-4 h-4 mr-2 animate-spin" /> : null}
                Generate Certificate
              </Button>
            ) : undefined
          }
        />
      </div>
    </FormModal>
  );
}
