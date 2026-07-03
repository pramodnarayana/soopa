
import { useEffect } from 'react';
import { useForm, Controller } from 'react-hook-form';
import type { Partnership } from '../context/PlatformPartnersContext';
import { useUpdatePlatformPartnershipMutation } from '../api/partnerHooks';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Loader2 } from 'lucide-react';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { useToast } from '@/hooks/use-toast';
import { usePlatformConfig } from '@/features/platform/api/configHooks';
import { Combobox } from '@/components/ui/combobox';

export interface PartnershipDetailsProps {
  partnership: Partnership;
  availablePartners: { id: string; name: string; type: string; is_local?: boolean }[];
}

export function PartnershipDetails({ partnership, availablePartners }: PartnershipDetailsProps) {
  const { toast } = useToast();
  const updatePartnership = useUpdatePlatformPartnershipMutation();
  const { data: platformConfig } = usePlatformConfig();
  const isSubmitting = updatePartnership.isPending;

  const { register, handleSubmit, control, watch, setValue, formState: { isDirty }, reset } = useForm({
    defaultValues: {
      name: partnership.name || '',
      local_partner_id: partnership.local_partner_id,
      remote_partner_id: partnership.remote_partner_id,
      mdn_type: partnership.mdn_type || 'SYNC',
      mdn_url: partnership.mdn_url || '',
      encryption_algorithm: partnership.encryption_algorithm || 'AES256_CBC',
      signature_algorithm: partnership.signature_algorithm || 'MIC_SHA256',
      edi_version: partnership.edi_version || 'X12_004010',
    }
  });

  const mdnType = watch("mdn_type");
  const mdnUrl = watch("mdn_url");

  useEffect(() => {
    if (mdnType === 'ASYNC' && !mdnUrl && platformConfig?.available_as2_receive_urls?.length) {
      setValue('mdn_url', platformConfig.available_as2_receive_urls[0], { shouldDirty: true });
    }
  }, [mdnType, mdnUrl, setValue, platformConfig]);

  const onSubmit = (formData: any) => {
    const payload: any = {};
    if (formData.name !== partnership.name) payload.name = formData.name;
    if (formData.local_partner_id !== partnership.local_partner_id) payload.local_partner_id = formData.local_partner_id;
    if (formData.remote_partner_id !== partnership.remote_partner_id) payload.remote_partner_id = formData.remote_partner_id;
    if (formData.mdn_type !== partnership.mdn_type) payload.mdn_type = formData.mdn_type;
    if (formData.mdn_url !== partnership.mdn_url) payload.mdn_url = formData.mdn_url || null;
    if (formData.encryption_algorithm !== partnership.encryption_algorithm) payload.encryption_algorithm = formData.encryption_algorithm;
    if (formData.signature_algorithm !== partnership.signature_algorithm) payload.signature_algorithm = formData.signature_algorithm;
    if (formData.edi_version !== partnership.edi_version) payload.edi_version = formData.edi_version;

    updatePartnership.mutate({ id: partnership.id, payload }, {
      onSuccess: () => {
        toast({ title: 'Success', description: 'Partnership updated successfully.' });
        reset(formData);
      },
    });
  };

  return (
    <div className="p-6 bg-slate-50/50 border-t border-slate-100">
      <form onSubmit={handleSubmit(onSubmit)}>
        <div className="flex justify-between items-start mb-6">
          <div>
            <h4 className="text-sm font-semibold text-slate-900 uppercase tracking-wider mb-1">Partnership Details</h4>
          </div>
          <Button
            type="submit"
            disabled={!isDirty || isSubmitting}
            className="min-w-[100px]"
          >
            {isSubmitting ? <Loader2 className="w-4 h-4 animate-spin" /> : 'Save'}
          </Button>
        </div>

        <div className="grid grid-cols-2 gap-x-8 gap-y-4">

          <div>
            <Label className="text-xs text-slate-500 block mb-1">Local Partner</Label>
            <Controller
              name="local_partner_id"
              control={control}
              render={({ field }) => (
                <Select value={field.value} onValueChange={field.onChange}>
                  <SelectTrigger className="bg-slate-50 text-slate-500 font-mono text-sm opacity-100 border-slate-200">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {availablePartners.filter(p => p.type === 'AS2' && p.is_local === true).map(p => (
                      <SelectItem key={p.id} value={p.id}>{p.name}</SelectItem>
                    ))}
                    {!availablePartners.find(p => p.id === field.value) && field.value && (
                      <SelectItem value={field.value}>{field.value}</SelectItem>
                    )}
                  </SelectContent>
                </Select>
              )}
            />
          </div>

          <div>
            <Label className="text-xs text-slate-500 block mb-1">Remote Partner</Label>
            <Controller
              name="remote_partner_id"
              control={control}
              render={({ field }) => (
                <Select value={field.value} onValueChange={field.onChange}>
                  <SelectTrigger className="bg-slate-50 text-slate-500 font-mono text-sm opacity-100 border-slate-200">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {availablePartners.filter(p => p.type === 'AS2' && !p.is_local).map(p => (
                      <SelectItem key={p.id} value={p.id}>{p.name}</SelectItem>
                    ))}
                    {!availablePartners.find(p => p.id === field.value) && field.value && (
                      <SelectItem value={field.value}>{field.value}</SelectItem>
                    )}
                  </SelectContent>
                </Select>
              )}
            />
          </div>

          <div>
            <Label className="text-xs text-slate-500 block mb-1">Partnership Name</Label>
            <Input {...register("name")} required placeholder="e.g. Acme Corp X12 Exchange" />
          </div>

          <div>
            <Label className="text-xs text-slate-500 block mb-1">MDN Type</Label>
            <Controller
              name="mdn_type"
              control={control}
              render={({ field }) => (
                <Select value={field.value} onValueChange={field.onChange}>
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="SYNC">SYNC</SelectItem>
                    <SelectItem value="ASYNC">ASYNC</SelectItem>
                    <SelectItem value="NONE">NONE</SelectItem>
                  </SelectContent>
                </Select>
              )}
            />
          </div>

          {mdnType === 'ASYNC' && (
            <div>
              <Label className="text-xs text-slate-500 block mb-1">MDN URL</Label>
              <Controller
                name="mdn_url"
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
            </div>
          )}

          <div>
            <Label className="text-xs text-slate-500 block mb-1">Encryption</Label>
            <Controller
              name="encryption_algorithm"
              control={control}
              render={({ field }) => (
                <Select value={field.value} onValueChange={field.onChange}>
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="AES256_CBC">AES-256-CBC</SelectItem>
                    <SelectItem value="AES128_CBC">AES-128-CBC</SelectItem>
                    <SelectItem value="3DES">3DES (Legacy)</SelectItem>
                  </SelectContent>
                </Select>
              )}
            />
          </div>

          <div>
            <Label className="text-xs text-slate-500 block mb-1">Signature</Label>
            <Controller
              name="signature_algorithm"
              control={control}
              render={({ field }) => (
                <Select value={field.value} onValueChange={field.onChange}>
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="MIC_SHA256">SHA-256</SelectItem>
                    <SelectItem value="MIC_SHA384">SHA-384</SelectItem>
                    <SelectItem value="MIC_SHA512">SHA-512</SelectItem>
                    <SelectItem value="MIC_SHA1">SHA-1 (Legacy)</SelectItem>
                  </SelectContent>
                </Select>
              )}
            />
          </div>

          <div>
            <Label className="text-xs text-slate-500 block mb-1">EDI Version</Label>
            <Controller
              name="edi_version"
              control={control}
              render={({ field }) => (
                <Select value={field.value} onValueChange={field.onChange}>
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="X12_004010">X12 4010</SelectItem>
                    <SelectItem value="X12_005010">X12 5010</SelectItem>
                    <SelectItem value="EDIFACT_D96A">EDIFACT D96A</SelectItem>
                    <SelectItem value="EDIFACT_D01B">EDIFACT D01B</SelectItem>
                  </SelectContent>
                </Select>
              )}
            />
          </div>
        </div>
      </form>
    </div>
  );
}
