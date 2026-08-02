import { Input } from '@soopa/ui/components/ui/input';
import { Label } from '@soopa/ui/components/ui/label';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@soopa/ui/components/ui/select';
import { useEffect, useState } from 'react';
import { Combobox } from '../../../components/ui/combobox';
import { FormModal } from '../../../components/ui/form-modal';
import { SearchableSelect } from '../../../components/ui/searchable-select';
import { usePlatformSettings } from '../../../features/platform/api/settingsHooks';
import { useCreateAS2PartnershipMutation } from '../api/partnerHooks';

export interface CreateAS2PartnershipModalProps {
  availablePartners: { id: string; name: string; type: string; is_local?: boolean }[];
}

export function CreateAS2PartnershipModal({ availablePartners }: CreateAS2PartnershipModalProps) {
  const [isOpen, setIsOpen] = useState(false);
  const [name, setName] = useState('');
  const [localPartnerId, setLocalPartnerId] = useState('');
  const [remotePartnerId, setRemotePartnerId] = useState('');
  const [mdnType, setMdnType] = useState('SYNC');
  const [mdnUrl, setMdnUrl] = useState('');
  const [encryptionAlgorithm, setEncryptionAlgorithm] = useState('AES256');
  const [signatureAlgorithm, setSignatureAlgorithm] = useState('SHA256');

  const { data: platformSettings } = usePlatformSettings();
  const createPartnership = useCreateAS2PartnershipMutation();

  useEffect(() => {
    if (mdnType === 'ASYNC' && !mdnUrl && platformSettings?.available_as2_receive_urls?.length) {
      setMdnUrl(platformSettings.available_as2_receive_urls[0]);
    }
  }, [platformSettings, mdnUrl, mdnType]);

  const reset = () => {
    setName('');
    setLocalPartnerId('');
    setRemotePartnerId('');
    setMdnType('SYNC');
    setMdnUrl(platformSettings?.available_as2_receive_urls?.[0] || '');
    setEncryptionAlgorithm('AES256');
    setSignatureAlgorithm('SHA256');
  };

  const handleOpenChange = (open: boolean) => {
    setIsOpen(open);
    if (!open) reset();
  };

  const handleSave = async (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();

    const trimmedName = name?.trim();

    createPartnership.mutate(
      {
        name: trimmedName || undefined,
        local_partner_id: localPartnerId,
        remote_partner_id: remotePartnerId,
        mdn_type: mdnType,
        mdn_url: mdnType === 'ASYNC' ? mdnUrl || undefined : undefined,
        encryption_algorithm: encryptionAlgorithm,
        signature_algorithm: signatureAlgorithm,
      },
      {
        onSuccess: () => {
          setIsOpen(false);
          reset();
        },
      },
    );
  };

  const localIdentities = availablePartners.filter((p) => p.type === 'AS2' && p.is_local === true);
  const remoteIdentities = availablePartners.filter((p) => p.type === 'AS2' && !p.is_local);

  return (
    <FormModal
      title="Create Partnership"
      triggerText="Create Partnership"
      isOpen={isOpen}
      onOpenChange={handleOpenChange}
      onSubmit={handleSave}
      isPending={createPartnership.isPending}
      submitText="Create Partnership"
      maxWidth="sm:max-w-[800px]"
    >
      <div className="grid gap-2">
        <Label htmlFor="name" className="text-slate-600 font-medium">
          Partnership Name
        </Label>
        <Input
          id="name"
          name="name"
          value={name}
          onChange={(e) => setName(e.target.value)}
          required
          placeholder="e.g. Acme Corp X12 Exchange"
          className="h-10 rounded-xl"
        />
      </div>

      {/* Identities Section */}
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-6 p-4 bg-slate-50 rounded-xl border border-slate-100">
        <div className="grid gap-2">
          <Label className="text-slate-600 font-medium">Local Station (Your AS2)</Label>
          <SearchableSelect
            value={localPartnerId}
            onChange={setLocalPartnerId}
            placeholder="Select local Trading Partner"
            options={localIdentities.map((p) => ({
              label: p.name,
              value: p.id,
              searchString: p.name,
            }))}
            emptyText="No local stations found"
          />
        </div>

        <div className="grid gap-2">
          <Label className="text-slate-600 font-medium">Remote Station (Partner AS2)</Label>
          <SearchableSelect
            value={remotePartnerId}
            onChange={setRemotePartnerId}
            placeholder="Select remote Trading Partner"
            options={remoteIdentities.map((p) => ({
              label: p.name,
              value: p.id,
              searchString: p.name,
            }))}
            emptyText="No remote stations found"
          />
        </div>
      </div>

      {/* Advanced Settings */}
      <div className="flex flex-col gap-6 pt-2 border-t border-slate-100">
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-6">
          <div className="grid gap-2">
            <Label className="text-slate-600 font-medium">MDN Delivery Type</Label>
            <Select value={mdnType} onValueChange={setMdnType}>
              <SelectTrigger className="h-10 rounded-xl">
                <SelectValue placeholder="Select MDN type" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="SYNC">Synchronous (Recommended)</SelectItem>
                <SelectItem value="ASYNC">Asynchronous</SelectItem>
                <SelectItem value="NONE">None (Fire and Forget)</SelectItem>
              </SelectContent>
            </Select>
          </div>

          {mdnType === 'ASYNC' && (
            <div className="grid gap-2">
              <Label className="text-slate-600 font-medium">Async MDN Receipt URL</Label>
              <Combobox
                options={platformSettings?.available_as2_receive_urls || []}
                value={mdnUrl}
                onChange={setMdnUrl}
                placeholder="https://..."
                emptyText="Type custom URL..."
              />
              <p className="text-xs text-slate-500">
                This is where the remote partner will send asynchronous MDN receipts back to your
                server.
              </p>
            </div>
          )}
        </div>

        <div className="grid grid-cols-1 sm:grid-cols-2 gap-6">
          <div className="grid gap-2">
            <Label className="text-slate-600 font-medium">Encryption</Label>
            <Select value={encryptionAlgorithm} onValueChange={setEncryptionAlgorithm}>
              <SelectTrigger className="h-10 rounded-xl">
                <SelectValue placeholder="Algorithm" />
              </SelectTrigger>
              <SelectContent>
                {(platformSettings?.supported_as2_encryption_algorithms || []).map((o) => (
                  <SelectItem key={o.value} value={o.value}>
                    {o.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          <div className="grid gap-2">
            <Label className="text-slate-600 font-medium">Signature</Label>
            <Select value={signatureAlgorithm} onValueChange={setSignatureAlgorithm}>
              <SelectTrigger className="h-10 rounded-xl">
                <SelectValue placeholder="Algorithm" />
              </SelectTrigger>
              <SelectContent>
                {(platformSettings?.supported_as2_signature_algorithms || []).map((o) => (
                  <SelectItem key={o.value} value={o.value}>
                    {o.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        </div>
      </div>
    </FormModal>
  );
}
