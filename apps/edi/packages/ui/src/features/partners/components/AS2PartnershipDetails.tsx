import { Button } from '@soopa/ui/components/ui/button';
import { Input } from '@soopa/ui/components/ui/input';
import { Label } from '@soopa/ui/components/ui/label';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@soopa/ui/components/ui/select';
import { CheckCircle2, Loader2, Trash2, XCircle, Zap } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';
import { Controller, useForm } from 'react-hook-form';
import { Combobox } from '../../../components/ui/combobox';
import { EdiEditorPane } from '../../../components/ui/edi-editor-pane';
import { SearchableSelect } from '../../../components/ui/searchable-select';
import { usePlatformSettings } from '../../../features/platform/api/settingsHooks';
import { useToast } from '../../../hooks/use-toast';
import {
  useTestAs2PartnershipConnectionMutation,
  useUpdateAS2PartnershipMutation,
} from '../api/partnerHooks';
import type { AS2Partnership } from '../context/AS2PartnersContext';
import type { Partner, UpdateAS2PartnershipPayload } from '../types';

export interface AS2PartnershipDetailsProps {
  as2Partnership: AS2Partnership;
  availablePartners: Partner[];
  onCancel?: () => void;
}

export function AS2PartnershipDetails({
  as2Partnership,
  availablePartners,
  onCancel,
}: AS2PartnershipDetailsProps) {
  const { toast } = useToast();
  const updateAS2Partnership = useUpdateAS2PartnershipMutation();
  const testConnection = useTestAs2PartnershipConnectionMutation();
  const { data: platformSettings } = usePlatformSettings();
  const isSubmitting = updateAS2Partnership.isPending;

  // Custom Payload State
  const [customPayload, setCustomPayload] = useState('');
  const [showRawMdn, setShowRawMdn] = useState(false);

  const {
    register,
    handleSubmit,
    control,
    watch,
    setValue,
    formState: { isDirty },
    reset,
  } = useForm({
    defaultValues: {
      name: as2Partnership.name || '',
      local_partner_id: as2Partnership.local_partner_id,
      remote_partner_id: as2Partnership.remote_partner_id,
      mdn_type: as2Partnership.mdn_type || 'SYNC',
      mdn_url: as2Partnership.mdn_url || '',
      encryption_algorithm: as2Partnership.encryption_algorithm || 'AES256',
      signature_algorithm: as2Partnership.signature_algorithm || 'SHA256',
    },
  });

  const mdnType = watch('mdn_type');
  const mdnUrl = watch('mdn_url');

  useEffect(() => {
    if (mdnType === 'ASYNC' && !mdnUrl && platformSettings?.available_as2_receive_urls?.length) {
      setValue('mdn_url', platformSettings.available_as2_receive_urls[0], { shouldDirty: true });
    }
  }, [mdnType, mdnUrl, setValue, platformSettings]);

  // Track previous partnership ID to detect when the selected partnership changes
  const previousPartnershipIdRef = useRef(as2Partnership.id);

  // Sync form when as2Partnership changes (e.g. refetched)
  // Reset when partnership ID changes (even if dirty) or when form is pristine (not dirty)
  useEffect(() => {
    const partnershipIdChanged = previousPartnershipIdRef.current !== as2Partnership.id;

    if (partnershipIdChanged || !isDirty) {
      reset(
        {
          name: as2Partnership.name || '',
          local_partner_id: as2Partnership.local_partner_id,
          remote_partner_id: as2Partnership.remote_partner_id,
          mdn_type: as2Partnership.mdn_type || 'SYNC',
          mdn_url: as2Partnership.mdn_url || '',
          encryption_algorithm: as2Partnership.encryption_algorithm || 'AES256',
          signature_algorithm: as2Partnership.signature_algorithm || 'SHA256',
        },
        { keepDirty: false },
      );
    }

    previousPartnershipIdRef.current = as2Partnership.id;
  }, [as2Partnership.id, as2Partnership, reset, isDirty]);
  interface AS2PartnershipFormData {
    name: string;
    local_partner_id: string;
    remote_partner_id: string;
    mdn_type: string;
    mdn_url: string;
    encryption_algorithm: string;
    signature_algorithm: string;
  }
  const onSubmit = (formData: AS2PartnershipFormData) => {
    const payload: UpdateAS2PartnershipPayload = {};
    if (formData.name !== as2Partnership.name) payload.name = formData.name;
    if (formData.local_partner_id !== as2Partnership.local_partner_id)
      payload.local_partner_id = formData.local_partner_id;
    if (formData.remote_partner_id !== as2Partnership.remote_partner_id)
      payload.remote_partner_id = formData.remote_partner_id;
    if (formData.mdn_type !== as2Partnership.mdn_type) payload.mdn_type = formData.mdn_type;
    if (formData.mdn_url !== as2Partnership.mdn_url) payload.mdn_url = formData.mdn_url || null;
    if (formData.encryption_algorithm !== as2Partnership.encryption_algorithm)
      payload.encryption_algorithm = formData.encryption_algorithm;
    if (formData.signature_algorithm !== as2Partnership.signature_algorithm)
      payload.signature_algorithm = formData.signature_algorithm;

    updateAS2Partnership.mutate(
      { id: as2Partnership.id, payload },
      {
        onSuccess: () => {
          toast({ title: 'Success', description: 'AS2Partnership updated successfully.' });
          reset(formData);
        },
      },
    );
  };

  return (
    <div className="p-6 bg-slate-50/50 border-t border-slate-100">
      <form onSubmit={handleSubmit(onSubmit)}>
        {/* ── Header ─────────────────────────────────────────────────────── */}
        <div className="flex justify-between items-center mb-5">
          <h4 className="text-sm font-semibold text-slate-900 uppercase tracking-wider">
            AS2Partnership Details
          </h4>
          <div className="flex items-center gap-2">
            <Button
              type="button"
              variant="outline"
              size="sm"
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
              size="sm"
              disabled={!isDirty || isSubmitting}
              className="min-w-[80px]"
            >
              {isSubmitting ? <Loader2 className="w-4 h-4 animate-spin" /> : 'Save'}
            </Button>
          </div>
        </div>

        {/* ── Editable fields ─────────────────────────────────────────────── */}
        <div className="grid grid-cols-2 gap-x-8 gap-y-4">
          <div>
            <Label className="text-xs text-slate-500 block mb-1">Local Partner</Label>
            <Controller
              name="local_partner_id"
              control={control}
              render={({ field }) => (
                <SearchableSelect
                  value={field.value}
                  onChange={field.onChange}
                  options={availablePartners
                    .filter((p) => p.type === 'AS2' && p.is_local === true)
                    .map((p) => ({ label: p.name, value: p.id, searchString: p.name }))}
                />
              )}
            />
          </div>
          <div>
            <Label className="text-xs text-slate-500 block mb-1">Remote Partner</Label>
            <Controller
              name="remote_partner_id"
              control={control}
              render={({ field }) => (
                <SearchableSelect
                  value={field.value}
                  onChange={field.onChange}
                  options={availablePartners
                    .filter((p) => p.type === 'AS2' && !p.is_local)
                    .map((p) => ({ label: p.name, value: p.id, searchString: p.name }))}
                />
              )}
            />
          </div>

          <div>
            <Label className="text-xs text-slate-500 block mb-1">AS2Partnership Name</Label>
            <Input {...register('name')} required placeholder="e.g. Acme Corp X12 Exchange" />
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
                    options={platformSettings?.available_as2_receive_urls || []}
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
                    {(platformSettings?.supported_as2_encryption_algorithms || []).map((o) => (
                      <SelectItem key={o.value} value={o.value}>
                        {o.label}
                      </SelectItem>
                    ))}
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
                    {(platformSettings?.supported_as2_signature_algorithms || []).map((o) => (
                      <SelectItem key={o.value} value={o.value}>
                        {o.label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              )}
            />
          </div>
        </div>
      </form>

      {/* ── Test Connection Section ──────────────────────────────────────── */}
      <div className="mt-8 pt-6 border-t border-slate-200">
        {/* Drag, Drop, Paste Area (Monaco) */}
        <div className="flex flex-col border rounded-xl bg-white shadow-sm overflow-hidden relative h-[350px]">
          <div className="bg-slate-50 px-4 py-2 border-b flex items-center justify-end">
            <div className="flex items-center gap-2">
              {isDirty && (
                <span className="text-xs text-amber-600 font-medium mr-2">
                  ⚠️ Save changes before testing
                </span>
              )}
              <Button
                type="button"
                id={`test-as2-connection-${as2Partnership.id}`}
                variant="default"
                size="sm"
                className="gap-1.5 bg-indigo-600 hover:bg-indigo-700 text-white shadow-sm h-7 text-xs px-3"
                onClick={() => {
                  setShowRawMdn(false);
                  testConnection.mutate({
                    id: as2Partnership.id,
                    custom_payload: customPayload || undefined,
                  });
                }}
                disabled={testConnection.isPending || (isDirty && !isSubmitting)}
                title={isDirty ? 'Save changes before testing' : ''}
              >
                {testConnection.isPending ? (
                  <Loader2 className="w-3.5 h-3.5 animate-spin" />
                ) : (
                  <Zap className="w-3.5 h-3.5 fill-current opacity-70" />
                )}
                Test Connection
              </Button>
              <div className="h-4 w-px bg-slate-300 mx-1 shrink-0" />
              <button
                type="button"
                onClick={() => setCustomPayload('')}
                className="p-1 hover:bg-slate-200 rounded text-slate-500 hover:text-red-600 transition-colors flex items-center justify-center border-slate-200"
                title="Clear Payload"
              >
                <Trash2 className="w-4 h-4" />
              </button>
            </div>
          </div>
          <EdiEditorPane value={customPayload} onChange={(val) => setCustomPayload(val)} />
        </div>

        {/* Results Panel */}
        {testConnection.data && (
          <div className="space-y-3">
            <div
              className={`flex items-start gap-3 rounded-lg px-4 py-3 text-sm border ${
                testConnection.data.success
                  ? 'bg-emerald-50 border-emerald-200 text-emerald-800'
                  : 'bg-red-50 border-red-200 text-red-800'
              }`}
            >
              {testConnection.data.success ? (
                <CheckCircle2 className="w-5 h-5 mt-0.5 shrink-0 text-emerald-600" />
              ) : (
                <XCircle className="w-5 h-5 mt-0.5 shrink-0 text-red-500" />
              )}
              <div>
                <p className="font-semibold text-base">
                  {testConnection.data.success ? 'Connection successful' : 'Connection failed'}
                </p>
                <p className="mt-1 opacity-90 leading-relaxed">
                  {testConnection.data.success
                    ? `MDN: ${testConnection.data.mdn_disposition ?? 'processed'}`
                    : (testConnection.data.reason ?? 'Unknown error')}
                </p>
              </div>
            </div>

            {/* Display raw MDN if available, fallback to sent_payload if not */}
            {(testConnection.data.raw_mdn || testConnection.data.sent_payload) && (
              <div className="rounded-lg border border-slate-200 bg-white overflow-hidden">
                <div className="bg-slate-50 px-4 py-2 border-b border-slate-200 flex justify-between items-center">
                  <p className="text-xs font-semibold text-slate-600 uppercase tracking-wider">
                    {testConnection.data.raw_mdn ? 'Received MDN' : 'Payload Sent'}
                  </p>
                  {testConnection.data.raw_mdn && (
                    <Button
                      type="button"
                      variant="ghost"
                      size="sm"
                      onClick={() => setShowRawMdn(!showRawMdn)}
                      aria-expanded={showRawMdn}
                      aria-controls="raw-mdn-panel"
                      className="text-xs text-slate-500 hover:text-slate-800"
                    >
                      {showRawMdn ? 'Hide Raw MDN' : 'View Raw MDN'}
                    </Button>
                  )}
                </div>
                {(showRawMdn || !testConnection.data.raw_mdn) && (
                  <div id="raw-mdn-panel" role="region" className="p-4 bg-slate-50 overflow-x-auto">
                    <pre className="text-xs font-mono text-slate-800 whitespace-pre-wrap break-all">
                      {testConnection.data.raw_mdn || testConnection.data.sent_payload}
                    </pre>
                  </div>
                )}
              </div>
            )}
          </div>
        )}

        {testConnection.isError && (
          <div className="flex items-start gap-3 rounded-lg px-4 py-3 text-sm border bg-red-50 border-red-200 text-red-800">
            <XCircle className="w-5 h-5 mt-0.5 shrink-0 text-red-500" />
            <div>
              <p className="font-semibold text-base">Request failed</p>
              <p className="mt-1 opacity-90">
                {testConnection.error?.message ?? 'Could not reach the server.'}
              </p>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
