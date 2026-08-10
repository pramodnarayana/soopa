import { Input } from '@soopa/ui/components/ui/input';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@soopa/ui/components/ui/select';
import { useState } from 'react';
import type { ControllerRenderProps } from 'react-hook-form';
import { Combobox } from '../../../components/ui/combobox';
import {
  Form,
  FormControl,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from '../../../components/ui/form';
import { FormModal } from '../../../components/ui/form-modal';
import { SearchableSelect } from '../../../components/ui/searchable-select';
import {
  type AS2PartnershipFormValues,
  useCreateAS2PartnershipForm,
} from './useCreateAS2PartnershipForm';

export interface CreateAS2PartnershipModalProps {
  availablePartners: { id: string; name: string; type: string; is_local?: boolean }[];
}

export function CreateAS2PartnershipModal({ availablePartners }: CreateAS2PartnershipModalProps) {
  const [isOpen, setIsOpen] = useState(false);

  const { form, onSubmit, isPending, platformSettings } = useCreateAS2PartnershipForm({
    onSuccess: () => {
      form.reset();
      setIsOpen(false);
    },
  });

  const handleOpenChange = (open: boolean) => {
    setIsOpen(open);
    if (!open) form.reset();
  };

  const mdnType = form.watch('mdn_type');

  const localIdentities = availablePartners.filter((p) => p.type === 'AS2' && p.is_local === true);
  const remoteIdentities = availablePartners.filter((p) => p.type === 'AS2' && !p.is_local);

  return (
    <Form {...form}>
      <FormModal
        title="Create Partnership"
        triggerText="Create Partnership"
        isOpen={isOpen}
        onOpenChange={handleOpenChange}
        onSubmit={onSubmit}
        isPending={isPending}
        submitText="Create Partnership"
        maxWidth="sm:max-w-[800px]"
      >
        <div className="grid gap-2">
          <FormField<AS2PartnershipFormValues, 'name'>
            control={form.control}
            name="name"
            render={({
              field,
            }: {
              field: ControllerRenderProps<AS2PartnershipFormValues, 'name'>;
            }) => (
              <FormItem>
                <FormLabel>Partnership Name</FormLabel>
                <FormControl>
                  <Input
                    {...field}
                    placeholder="e.g. Acme Corp X12 Exchange"
                    className="h-10 rounded-xl"
                  />
                </FormControl>
                <FormMessage />
              </FormItem>
            )}
          />
        </div>

        {/* Identities Section */}
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-6 p-4 bg-muted/30 rounded-xl border border-border">
          <FormField<AS2PartnershipFormValues, 'local_partner_id'>
            control={form.control}
            name="local_partner_id"
            render={({
              field,
            }: {
              field: ControllerRenderProps<AS2PartnershipFormValues, 'local_partner_id'>;
            }) => (
              <FormItem className="grid gap-2">
                <FormLabel>Local Station (Your AS2)</FormLabel>
                <FormControl>
                  <SearchableSelect
                    value={field.value}
                    onChange={field.onChange}
                    placeholder="Select local Trading Partner"
                    options={localIdentities.map((p) => ({
                      label: p.name,
                      value: p.id,
                      searchString: p.name,
                    }))}
                    emptyText="No local stations found"
                    allowCustomValue={false}
                  />
                </FormControl>
                <FormMessage />
              </FormItem>
            )}
          />

          <FormField<AS2PartnershipFormValues, 'remote_partner_id'>
            control={form.control}
            name="remote_partner_id"
            render={({
              field,
            }: {
              field: ControllerRenderProps<AS2PartnershipFormValues, 'remote_partner_id'>;
            }) => (
              <FormItem className="grid gap-2">
                <FormLabel>Remote Station (Partner AS2)</FormLabel>
                <FormControl>
                  <SearchableSelect
                    value={field.value}
                    onChange={field.onChange}
                    placeholder="Select remote Trading Partner"
                    options={remoteIdentities.map((p) => ({
                      label: p.name,
                      value: p.id,
                      searchString: p.name,
                    }))}
                    emptyText="No remote stations found"
                    allowCustomValue={false}
                  />
                </FormControl>
                <FormMessage />
              </FormItem>
            )}
          />
        </div>

        {/* Advanced Settings */}
        <div className="flex flex-col gap-6 pt-4 border-t border-border">
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-6">
            <FormField<AS2PartnershipFormValues, 'encryption_algorithm'>
              control={form.control}
              name="encryption_algorithm"
              render={({
                field,
              }: {
                field: ControllerRenderProps<AS2PartnershipFormValues, 'encryption_algorithm'>;
              }) => (
                <FormItem className="grid gap-2">
                  <FormLabel>Encryption</FormLabel>
                  <FormControl>
                    <Select value={field.value} onValueChange={field.onChange}>
                      <SelectTrigger>
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
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />

            <FormField<AS2PartnershipFormValues, 'signature_algorithm'>
              control={form.control}
              name="signature_algorithm"
              render={({
                field,
              }: {
                field: ControllerRenderProps<AS2PartnershipFormValues, 'signature_algorithm'>;
              }) => (
                <FormItem className="grid gap-2">
                  <FormLabel>Signature</FormLabel>
                  <FormControl>
                    <Select value={field.value} onValueChange={field.onChange}>
                      <SelectTrigger>
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
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />

            <FormField<AS2PartnershipFormValues, 'mdn_type'>
              control={form.control}
              name="mdn_type"
              render={({
                field,
              }: {
                field: ControllerRenderProps<AS2PartnershipFormValues, 'mdn_type'>;
              }) => (
                <FormItem className="grid gap-2">
                  <FormLabel>MDN Delivery Type</FormLabel>
                  <FormControl>
                    <Select value={field.value} onValueChange={field.onChange}>
                      <SelectTrigger>
                        <SelectValue placeholder="Select MDN type" />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="SYNC">Synchronous (Recommended)</SelectItem>
                        <SelectItem value="ASYNC">Asynchronous</SelectItem>
                        <SelectItem value="NONE">None (Fire and Forget)</SelectItem>
                      </SelectContent>
                    </Select>
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />
          </div>

          {mdnType === 'ASYNC' && (
            <FormField<AS2PartnershipFormValues, 'mdn_url'>
              control={form.control}
              name="mdn_url"
              render={({
                field,
              }: {
                field: ControllerRenderProps<AS2PartnershipFormValues, 'mdn_url'>;
              }) => (
                <FormItem className="grid gap-2">
                  <FormLabel>Async MDN Receipt URL</FormLabel>
                  <FormControl>
                    <Combobox
                      options={platformSettings?.available_as2_receive_urls || []}
                      value={field.value || ''}
                      onChange={field.onChange}
                      placeholder="https://..."
                      emptyText="Type custom URL..."
                    />
                  </FormControl>
                  <p className="text-xs text-muted-foreground">
                    This is where the remote partner will send asynchronous MDN receipts back to
                    your server.
                  </p>
                  <FormMessage />
                </FormItem>
              )}
            />
          )}
        </div>
      </FormModal>
    </Form>
  );
}
