import { useState, useRef } from 'react';
import { useForm, Controller } from 'react-hook-form';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from '@/components/ui/dialog';
import { Textarea } from '@/components/ui/textarea';
import type { AS2Partner } from '../types';
import { useCertificatesExportQuery, useUpdatePlatformPartnerMutation, useRotateCertificatesMutation } from '../api/partnerHooks';
import { Copy, Download, Loader2, ChevronDown, ChevronRight, CheckCircle2, Clock, Upload, RefreshCw, ClipboardPaste } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { useToast } from '@/hooks/use-toast';
import { usePlatformConfig } from '@/features/platform/api/configHooks';
import { Combobox } from '@/components/ui/combobox';

export function As2PartnerDetails({ partner, onCancel }: { partner: AS2Partner, onCancel?: () => void }) {
  const { toast } = useToast();
  const { data: platformConfig } = usePlatformConfig();

  const updatePlatform = useUpdatePlatformPartnerMutation();
  const rotateCertificates = useRotateCertificatesMutation();
  const isSubmitting = updatePlatform.isPending;

  const [pasteDialogOpen, setPasteDialogOpen] = useState(false);
  const [pasteValue, setPasteValue] = useState('');

  const { data: certs, isLoading: certsLoading, error: certsError } = useCertificatesExportQuery(partner.id);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const { register, handleSubmit, reset, control, formState: { isDirty } } = useForm({
    defaultValues: {
      name: partner.name,
      as2_id: partner.as2_id || '',
      is_local: partner.is_local || false,
      url: partner.url || '',
    }
  });

  const onSubmit = (formData: any) => {
    const payload: any = {};
    if (formData.name !== partner.name) payload.name = formData.name;
    if (formData.as2_id !== partner.as2_id) payload.as2_id = formData.as2_id;
    if (formData.is_local !== partner.is_local) payload.is_local = formData.is_local;
    if (formData.url !== partner.url) payload.url = formData.url;

    if (formData.is_local && !formData.url?.trim()) {
      toast({ title: 'Error', description: 'Receiving URL is required for local partners.', variant: 'destructive' });
      return;
    }

    updatePlatform.mutate({ id: partner.id, payload }, {
      onSuccess: () => {
        toast({ title: 'Success', description: 'Partner updated successfully.' });
        reset(formData);
      },
    });
  };

  const handleGenerateCertificate = () => {
    rotateCertificates.mutate({ id: partner.id, payload: { action: 'generate' } });
  };

  const handleFileUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files;
    if (!files || files.length === 0) return;

    try {
      let publicCert = '';
      let privateKey = '';

      for (let i = 0; i < files.length; i++) {
        const text = await files[i].text();
        if (text.includes('-----BEGIN CERTIFICATE-----')) {
          const match = text.match(/-----BEGIN CERTIFICATE-----[^-]+-----END CERTIFICATE-----/g);
          if (match && match.length > 0) publicCert += match.join('\n') + '\n';
        }
        if (text.includes('-----BEGIN PRIVATE KEY-----') || text.includes('-----BEGIN RSA PRIVATE KEY-----')) {
          const match = text.match(/-----BEGIN (?:RSA )?PRIVATE KEY-----[^-]+-----END (?:RSA )?PRIVATE KEY-----/g);
          if (match && match.length > 0) privateKey += match.join('\n') + '\n';
        }
      }

      rotateCertificates.mutate({
        id: partner.id,
        payload: {
          action: 'upload',
          public_cert_pem: publicCert.trim() || undefined as any,
          private_key_pem: (partner.is_local && privateKey.trim()) ? privateKey.trim() : undefined
        }
      });
    } catch { // eslint-disable-line no-unused-vars
      toast({ title: 'Error', description: 'Failed to read uploaded files.', variant: 'destructive' });
    } finally {
      if (fileInputRef.current) {
        fileInputRef.current.value = '';
      }
    }
  };

  const handlePasteSubmit = () => {
    if (!pasteValue.trim()) return;

    let publicCert = '';
    let privateKey = '';

    const text = pasteValue;
    if (text.includes('-----BEGIN CERTIFICATE-----')) {
      const match = text.match(/-----BEGIN CERTIFICATE-----[^-]+-----END CERTIFICATE-----/g);
      if (match && match.length > 0) publicCert += match.join('\n') + '\n';
    }
    if (text.includes('-----BEGIN PRIVATE KEY-----') || text.includes('-----BEGIN RSA PRIVATE KEY-----')) {
      const match = text.match(/-----BEGIN (?:RSA )?PRIVATE KEY-----[^-]+-----END (?:RSA )?PRIVATE KEY-----/g);
      if (match && match.length > 0) privateKey += match.join('\n') + '\n';
    }

    rotateCertificates.mutate({
      id: partner.id,
      payload: {
        action: 'upload',
        public_cert_pem: publicCert.trim() || undefined as any,
        private_key_pem: (partner.is_local && privateKey.trim()) ? privateKey.trim() : undefined
      }
    }, {
      onSuccess: () => {
        setPasteDialogOpen(false);
        setPasteValue('');
      }
    });
  };

  return (
    <div className="p-6 bg-slate-50/50 border-t border-slate-100">
      <form onSubmit={handleSubmit(onSubmit)}>
        <div className="flex justify-between items-start mb-6">
          <div>
            <h4 className="text-sm font-semibold text-slate-900 uppercase tracking-wider mb-1">AS2 Partner Details</h4>
          </div>
          <div className="flex items-center gap-3">
            <Button
              type="button"
              variant="outline"
              onClick={() => {
                reset();
                if (onCancel) onCancel();
              }}
              disabled={!isDirty || isSubmitting}
            >
              Cancel
            </Button>
            <Button
              type="submit"
              disabled={!isDirty || isSubmitting}
              className="min-w-[100px]"
            >
              {isSubmitting ? <Loader2 className="w-4 h-4 animate-spin" /> : 'Save'}
            </Button>
          </div>
        </div>

        <div className="grid grid-cols-2 gap-x-8 gap-y-4 mb-8">
          <div>
            <Label className="text-xs text-slate-500 block mb-1">Name</Label>
            <Input {...register("name")} required />
          </div>
          <div>
            <Label className="text-xs text-slate-500 block mb-1">Type</Label>
            <div className="text-sm font-medium text-slate-900 px-3 py-2 border border-transparent">
              AS2
            </div>
          </div>
          <div>
            <Label className="text-xs text-slate-500 block mb-1">AS2 ID</Label>
            <Input {...register("as2_id")} />
          </div>
          <div className="flex items-center gap-2 mt-6">
            <input
              type="checkbox"
              id="is_local"
              {...register("is_local")}
              disabled
              className="rounded border-slate-300 disabled:opacity-50 disabled:cursor-not-allowed"
            />
            <Label htmlFor="is_local" className="text-sm font-medium text-slate-700 opacity-70">Is Local Station?</Label>
          </div>
          <div className="mt-4">
            <Label className="text-xs text-slate-500 block mb-1">Receiving URL</Label>
            {partner.is_local ? (
              <Controller
                name="url"
                control={control}
                render={({ field }) => (
                  <Combobox
                    options={platformConfig?.available_as2_receive_urls || []}
                    value={field.value}
                    onChange={field.onChange}
                    placeholder="https://..."
                    emptyText="Type custom URL..."
                  />
                )}
              />
            ) : (
              <Input {...register("url")} placeholder="https://acme.com/as2/receive" />
            )}
          </div>
        </div>
      </form>

      <div className="space-y-4 border-t border-slate-200 pt-6">
        <div className="flex justify-between items-center pb-2">
          <h4 className="text-sm font-semibold text-slate-900 uppercase tracking-wider">Certificates</h4>
          <div className="flex items-center gap-3">
            {partner.is_local && (
              <Button variant="outline" size="sm" onClick={handleGenerateCertificate} disabled={rotateCertificates.isPending}>
                {rotateCertificates.isPending ? <Loader2 className="w-4 h-4 mr-2 animate-spin" /> : <RefreshCw className="w-4 h-4 mr-2" />}
                Generate Certificate
              </Button>
            )}
            <Button variant="outline" size="sm" onClick={() => setPasteDialogOpen(true)} disabled={rotateCertificates.isPending}>
              <ClipboardPaste className="w-4 h-4 mr-2" />
              Paste
            </Button>
            <Button variant="outline" size="sm" onClick={() => fileInputRef.current?.click()} disabled={rotateCertificates.isPending}>
              <Upload className="w-4 h-4 mr-2" />
              Upload
            </Button>
            <input
              type="file"
              ref={fileInputRef}
              onChange={handleFileUpload}
              multiple
              accept=".pem,.crt,.cer,.key"
              className="hidden"
            />
          </div>
        </div>

        {certsLoading ? (
          <div className="flex items-center gap-2 text-slate-500 text-sm">
            <Loader2 className="w-4 h-4 animate-spin" /> Loading certificates...
          </div>
        ) : certsError ? (
          <div className="text-sm text-red-500">Failed to load certificates.</div>
        ) : certs ? (
          <div className="bg-white border border-slate-200/60 rounded-2xl shadow-sm overflow-hidden flex flex-col">
            <div className="overflow-x-auto">
              <table className="w-full text-left border-collapse">
                <thead>
                  <tr className="border-b border-slate-200/60 bg-slate-50/50">
                    <th className="px-6 py-4 text-xs font-semibold text-slate-500 uppercase tracking-wider">Status</th>
                    <th className="px-6 py-4 text-xs font-semibold text-slate-500 uppercase tracking-wider">Description</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {certs.public_cert_pem && (
                    <CertificateRow
                      role="Active"
                      publicPem={certs.public_cert_pem}
                      privatePem={certs.private_key_pem}
                      partnerName={partner.name}
                    />
                  )}
                  {certs.prev_public_cert_pem && (
                    <CertificateRow
                      role="Previous"
                      publicPem={certs.prev_public_cert_pem}
                      privatePem={certs.prev_private_key_pem}
                      partnerName={partner.name}
                    />
                  )}
                </tbody>
              </table>
            </div>
          </div>
        ) : null}
      </div>

      <Dialog open={pasteDialogOpen} onOpenChange={(open) => {
        setPasteDialogOpen(open);
        if (!open) setPasteValue('');
      }}>
        <DialogContent className="sm:max-w-xl">
          <DialogHeader>
            <DialogTitle>Paste Certificate</DialogTitle>
          </DialogHeader>
          <div className="py-4">
            <Textarea
              className="min-h-[200px] font-mono text-xs p-4 bg-slate-50 border-slate-200"
              placeholder={"-----BEGIN CERTIFICATE-----\nMIID...\n-----END CERTIFICATE-----"}
              value={pasteValue}
              onChange={(e) => setPasteValue(e.target.value)}
            />
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => { setPasteDialogOpen(false); setPasteValue(''); }}>Cancel</Button>
            <Button onClick={handlePasteSubmit} disabled={!pasteValue.trim() || rotateCertificates.isPending}>
              {rotateCertificates.isPending && <Loader2 className="w-4 h-4 mr-2 animate-spin" />}
              Save Certificate
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}


function CertificateRow({
  role,
  publicPem,
  privatePem,
  partnerName
}: {
  role: 'Active' | 'Previous',
  publicPem?: string,
  privatePem?: string,
  partnerName: string
}) {
  const [expanded, setExpanded] = useState(false);
  const { toast } = useToast();

  const handleCopy = (text: string, label: string) => {
    navigator.clipboard.writeText(text);
    toast({ title: 'Copied', description: `${label} copied to clipboard.` });
  };

  const handleDownload = (text: string, filename: string) => {
    const blob = new Blob([text], { type: 'text/plain' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  };

  const completePem = privatePem ? `${publicPem}\n${privatePem}` : publicPem;

  return (
    <>
      <tr
        className="hover:bg-slate-50 transition-colors cursor-pointer group"
        onClick={() => setExpanded(!expanded)}
        onKeyDown={(e) => {
          if (e.key === 'Enter' || e.key === ' ') {
            e.preventDefault();
            setExpanded(!expanded);
          }
        }}
        tabIndex={0}
        role="button"
        aria-expanded={expanded}
      >
        <td className="px-6 py-4 whitespace-nowrap">
          {role === 'Active' ? (
            <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium bg-emerald-50 text-emerald-700 border border-emerald-200">
              <CheckCircle2 className="w-3.5 h-3.5" />
              Active
            </span>
          ) : (
            <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium bg-amber-50 text-amber-700 border border-amber-200">
              <Clock className="w-3.5 h-3.5" />
              Previous
            </span>
          )}
        </td>
        <td className="px-6 py-4 text-sm text-slate-500 w-full">
          <div className="flex items-center justify-between">
            <span>{role === 'Active' ? 'Actively used for signing and decryption' : 'In grace period for legacy traffic'}</span>
            <div className="flex items-center gap-3">
              <span className="text-xs font-medium text-slate-400 group-hover:text-indigo-600 transition-colors">
                {expanded ? 'Hide Details' : 'View Details'}
              </span>
              {expanded ? <ChevronDown className="w-4 h-4 text-slate-400 group-hover:text-indigo-600 transition-colors" /> : <ChevronRight className="w-4 h-4 text-slate-400 group-hover:text-indigo-600 transition-colors" />}
            </div>
          </div>
        </td>
      </tr>
      {expanded && (
        <tr>
          <td colSpan={2} className="p-0 border-t-0">
            <div className="bg-slate-50 p-4 border-b border-slate-100 flex flex-col gap-4 shadow-inner">

              <div className="flex flex-col gap-2">
                <div className="flex justify-between items-center">
                  <span className="text-xs font-semibold text-slate-600 uppercase">Public Certificate</span>
                  <div className="flex gap-2">
                    <Button type="button" variant="ghost" size="sm" className="h-7 text-xs gap-1" onClick={() => handleCopy(publicPem!, 'Public Certificate')}>
                      <Copy className="w-3 h-3" /> Copy
                    </Button>
                    <Button type="button" variant="ghost" size="sm" className="h-7 text-xs gap-1" onClick={() => handleDownload(publicPem!, `${partnerName}_${role.toLowerCase()}_public.pem`)}>
                      <Download className="w-3 h-3" /> Download
                    </Button>
                  </div>
                </div>
                <pre className="text-[10px] leading-tight text-slate-700 bg-white p-3 rounded border border-slate-200 overflow-x-auto font-mono max-h-48 overflow-y-auto">
                  {publicPem}
                </pre>
              </div>

              {privatePem && (
                <div className="flex flex-col gap-2 pt-2 border-t border-slate-200">
                  <div className="flex justify-between items-center">
                    <span className="text-xs font-semibold text-slate-600 uppercase">Complete Identity (Public + Private)</span>
                    <div className="flex gap-2">
                      <Button type="button" variant="ghost" size="sm" className="h-7 text-xs gap-1 text-amber-600 hover:text-amber-700 hover:bg-amber-50" onClick={() => handleCopy(completePem!, 'Complete Identity')}>
                        <Copy className="w-3 h-3" /> Copy Complete
                      </Button>
                      <Button type="button" variant="ghost" size="sm" className="h-7 text-xs gap-1 text-amber-600 hover:text-amber-700 hover:bg-amber-50" onClick={() => handleDownload(completePem!, `${partnerName}_${role.toLowerCase()}_complete.pem`)}>
                        <Download className="w-3 h-3" /> Download Complete
                      </Button>
                    </div>
                  </div>
                </div>
              )}

            </div>
          </td>
        </tr>
      )}
    </>
  );
}
