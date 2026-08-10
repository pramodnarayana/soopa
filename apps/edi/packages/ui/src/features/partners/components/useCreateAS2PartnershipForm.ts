import { zodResolver } from '@hookform/resolvers/zod';
import { useEffect } from 'react';
import { useForm } from 'react-hook-form';
import * as z from 'zod';
import { usePlatformSettings } from '../../../features/platform/api/settingsHooks';
import { useCreateAS2PartnershipMutation } from '../api/partnerHooks';

export const as2PartnershipSchema = z
  .object({
    name: z.string().trim().min(1, 'Name is required'),
    local_partner_id: z.string().min(1, 'Local Station is required'),
    remote_partner_id: z.string().min(1, 'Remote Station is required'),
    mdn_type: z.string().min(1),
    mdn_url: z.string().optional(),
    encryption_algorithm: z.string().min(1),
    signature_algorithm: z.string().min(1),
  })
  .refine((data) => data.local_partner_id !== data.remote_partner_id, {
    message: 'Local and Remote stations cannot be the same',
    path: ['remote_partner_id'],
  })
  .refine(
    (data) => {
      if (data.mdn_type === 'ASYNC') {
        return !!data.mdn_url && data.mdn_url.trim().length > 0;
      }
      return true;
    },
    {
      message: 'MDN URL is required when MDN type is Asynchronous',
      path: ['mdn_url'],
    },
  );

export type AS2PartnershipFormValues = z.infer<typeof as2PartnershipSchema>;

interface UseCreateAS2PartnershipFormProps {
  onSuccess?: () => void;
}

export function useCreateAS2PartnershipForm({ onSuccess }: UseCreateAS2PartnershipFormProps = {}) {
  const { data: platformSettings } = usePlatformSettings();
  const createPartnership = useCreateAS2PartnershipMutation();

  const form = useForm<AS2PartnershipFormValues>({
    resolver: zodResolver(as2PartnershipSchema),
    defaultValues: {
      name: '',
      local_partner_id: '',
      remote_partner_id: '',
      mdn_type: 'SYNC',
      mdn_url: '',
      encryption_algorithm: 'AES256',
      signature_algorithm: 'SHA256',
    },
  });

  const mdnType = form.watch('mdn_type');
  const mdnUrl = form.watch('mdn_url');

  useEffect(() => {
    if (mdnType === 'ASYNC' && !mdnUrl && platformSettings?.available_as2_receive_urls?.length) {
      form.setValue('mdn_url', platformSettings.available_as2_receive_urls[0], {
        shouldValidate: true,
      });
    }
  }, [platformSettings, mdnUrl, mdnType, form]);

  const onSubmit = (data: AS2PartnershipFormValues) => {
    createPartnership.mutate(
      {
        name: data.name,
        local_partner_id: data.local_partner_id,
        remote_partner_id: data.remote_partner_id,
        mdn_type: data.mdn_type,
        mdn_url: data.mdn_type === 'ASYNC' ? data.mdn_url || undefined : undefined,
        encryption_algorithm: data.encryption_algorithm,
        signature_algorithm: data.signature_algorithm,
      },
      {
        onSuccess: () => {
          form.reset();
          onSuccess?.();
        },
      },
    );
  };

  return {
    form,
    onSubmit: form.handleSubmit(onSubmit),
    isPending: createPartnership.isPending,
    platformSettings,
  };
}
