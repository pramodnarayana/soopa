import { useMutation, useQuery } from '@tanstack/react-query';
import { useEdiNetwork } from '../../../contexts/EdiNetworkContext';
import { useEdiPlatformNetwork } from '../../../contexts/EdiPlatformNetworkContext';
import { useToastMutation } from '../../../hooks/use-toast-mutation';
import type {
  AS2Partnership,
  CertificatesExport,
  CreateAS2PartnershipPayload,
  CreatePartnerPayload,
  CreateSftpPartnerPayload,
  GenerateCertRequest,
  GenerateCertResponse,
  Partner,
  RotateCertPayload,
  UpdateAS2PartnershipPayload,
  UpdatePartnerPayload,
} from '../types';
// ─────────────────────────────────────────────
// Query Key Factory
// ─────────────────────────────────────────────

export const partnersKeys = {
  all: ['partners'] as const,
  tenant: () => [...partnersKeys.all, 'tenant'] as const,
  platform: () => [...partnersKeys.all, 'platform'] as const,
  platformPartners: () => [...partnersKeys.platform(), 'trading-partners'] as const,
  platformPartnerships: () => [...partnersKeys.platform(), 'partnerships'] as const,
  certificates: (id: string) => [...partnersKeys.all, 'certificates', id] as const,
};

// ─────────────────────────────────────────────
// Helper — resolves the repository for the current auth user
// ─────────────────────────────────────────────

// ─────────────────────────────────────────────
// Queries
// ─────────────────────────────────────────────

import {
  AS2PartnershipSchema,
  AS2PartnershipsArraySchema,
  normalizePartnerResponse,
  PartnerSchema,
  PartnersArraySchema,
} from './partnerSchemas';

export function useAS2PartnersQuery() {
  const api = useEdiPlatformNetwork();
  return useQuery({
    queryKey: partnersKeys.platformPartners(),
    queryFn: async (): Promise<Partner[]> => {
      const res = await api.get('platform/trading-partners/as2/trading-partners');
      return PartnersArraySchema.parse(res.data);
    },
  });
}

export function useAS2PartnershipsQuery() {
  const api = useEdiPlatformNetwork();
  return useQuery({
    queryKey: partnersKeys.platformPartnerships(),
    queryFn: async (): Promise<AS2Partnership[]> => {
      const res = await api.get('platform/trading-partners/as2/partnerships');
      return AS2PartnershipsArraySchema.parse(res.data);
    },
  });
}

export function useCertificatesExportQuery(partnerId: string) {
  const api = useEdiPlatformNetwork();
  return useQuery({
    queryKey: partnersKeys.certificates(partnerId),
    queryFn: async (): Promise<CertificatesExport> => {
      const res = await api.get<CertificatesExport>(
        `/platform/trading-partners/as2/certificates/${partnerId}/export`,
      );
      return res.data;
    },
    enabled: !!partnerId,
    gcTime: 0,
  });
}

export function useTenantPartnersQuery() {
  const api = useEdiNetwork();
  return useQuery({
    queryKey: partnersKeys.tenant(),
    queryFn: async (): Promise<Partner[]> => {
      const res = await api.get('trading-partners');
      const rawData = Array.isArray(res.data) ? res.data : [];
      const normalizedData = rawData.map(normalizePartnerResponse);
      return PartnersArraySchema.parse(normalizedData);
    },
  });
}

// ─────────────────────────────────────────────
// Platform Partner Mutations
// ─────────────────────────────────────────────

export function useCreateAS2PartnerMutation() {
  const api = useEdiPlatformNetwork();

  return useToastMutation(
    async (payload: CreatePartnerPayload) => {
      if (!payload.is_local && !payload.public_cert_pem?.trim()) {
        throw new Error('Remote AS2 partners require a public certificate.');
      }
      const res = await api.post('platform/trading-partners/as2/trading-partners', payload);
      return PartnerSchema.parse(res.data);
    },
    'Trading partner created successfully.',
    [partnersKeys.platformPartners()],
  );
}

export function useUpdateAS2PartnerMutation() {
  const api = useEdiPlatformNetwork();

  return useToastMutation(
    async ({ id, payload }: { id: string; payload: UpdatePartnerPayload }) => {
      const res = await api.put(`platform/trading-partners/as2/trading-partners/${id}`, payload);
      return PartnerSchema.parse(res.data);
    },
    'Partner updated successfully.',
    [partnersKeys.platformPartners()],
  );
}

export function useDeleteAS2PartnerMutation() {
  const api = useEdiPlatformNetwork();
  return useToastMutation(
    async (id: string) => {
      await api.delete(`platform/trading-partners/as2/trading-partners/${id}`);
    },
    'Partner deleted.',
    [partnersKeys.platformPartners()],
  );
}

export function useDeleteCertificateSecretMutation() {
  const api = useEdiPlatformNetwork();
  return useMutation({
    mutationFn: async (vaultRef: string) => {
      await api.delete(
        `/platform/trading-partners/as2/certificates/secret?vault_ref=${encodeURIComponent(vaultRef)}`,
      );
    },
  });
}

// ─────────────────────────────────────────────
// Platform Partnership Mutations
// ─────────────────────────────────────────────

export function useCreateAS2PartnershipMutation() {
  const api = useEdiPlatformNetwork();

  return useToastMutation(
    async (payload: CreateAS2PartnershipPayload) => {
      if (!payload.local_partner_id || !payload.remote_partner_id) {
        throw new Error('Both a local and remote trading partner must be selected.');
      }
      const res = await api.post('platform/trading-partners/as2/partnerships', payload);
      return AS2PartnershipSchema.parse(res.data);
    },
    'Partnership created successfully.',
    [partnersKeys.platformPartnerships()],
  );
}

export function useUpdateAS2PartnershipMutation() {
  const api = useEdiPlatformNetwork();

  return useToastMutation(
    async ({ id, payload }: { id: string; payload: UpdateAS2PartnershipPayload }) => {
      const res = await api.put(`platform/trading-partners/as2/partnerships/${id}`, payload);
      return AS2PartnershipSchema.parse(res.data);
    },

    'Partnership updated successfully.',
    [partnersKeys.platformPartnerships()],
  );
}

export function useDeleteAS2PartnershipMutation() {
  const api = useEdiPlatformNetwork();

  return useToastMutation(
    async (id: string) => {
      await api.delete(`platform/trading-partners/as2/partnerships/${id}`);
    },
    'Partnership deleted successfully.',
    [partnersKeys.platformPartnerships()],
  );
}

// ─────────────────────────────────────────────
// Tenant Partner Mutations
// ─────────────────────────────────────────────

export function useCreateSftpPartnerMutation() {
  const api = useEdiNetwork();

  return useToastMutation(
    async (payload: CreateSftpPartnerPayload) => {
      const res = await api.post('trading-partners/sftp', payload);
      return PartnerSchema.parse(res.data);
    },
    'SFTP Partner created successfully.',
    [partnersKeys.tenant()],
  );
}

export function useUpdateSftpPartnerMutation() {
  const api = useEdiNetwork();

  return useToastMutation(
    async ({ id, payload }: { id: string; payload: UpdatePartnerPayload }) => {
      const res = await api.put(`trading-partners/sftp/${id}`, payload);
      return PartnerSchema.parse(res.data);
    },
    'SFTP Partner updated successfully.',
    [partnersKeys.tenant()],
  );
}

export function useDeleteSftpPartner() {
  const api = useEdiNetwork();

  return useToastMutation(
    async (id: string) => {
      await api.delete(`trading-partners/sftp/${id}`);
    },
    'SFTP Partner deleted successfully.',
    [partnersKeys.tenant()],
  );
}

// ─────────────────────────────────────────────
// Certificate Mutations
// ─────────────────────────────────────────────

export function useRotateCertificatesMutation() {
  const api = useEdiPlatformNetwork();
  return useToastMutation(
    async ({ id, payload }: { id: string; payload: RotateCertPayload }) => {
      const res = await api.put(
        `/platform/trading-partners/as2/certificates/${id}/rotate`,
        payload,
      );
      return PartnerSchema.parse(res.data);
    },
    'Certificate operation successful.',
    [partnersKeys.all],
  );
}

export function useGenerateCertificateMutation() {
  const api = useEdiPlatformNetwork();
  return useToastMutation(async (payload: GenerateCertRequest) => {
    const res = await api.post<GenerateCertResponse>(
      '/platform/trading-partners/as2/certificates/generate',
      payload,
    );
    return res.data;
  }, 'Certificate generated successfully.');
}

export function useTestSftpConnectionMutation() {
  const api = useEdiNetwork();
  return useMutation({
    mutationFn: async (
      payload: Omit<
        CreateSftpPartnerPayload,
        'name' | 'inbound_remote_path' | 'outbound_remote_path'
      >,
    ) => {
      const res = await api.post<{ success: boolean; reason?: string }>(
        '/trading-partners/sftp/test',
        payload,
      );
      return res.data;
    },
  });
}

export function useTestExistingSftpConnectionMutation() {
  const api = useEdiNetwork();
  return useMutation({
    mutationFn: async ({
      id,
      payload,
    }: {
      id: string;
      payload: Omit<
        CreateSftpPartnerPayload,
        'name' | 'inbound_remote_path' | 'outbound_remote_path'
      >;
    }) => {
      const res = await api.post<{ success: boolean; reason?: string }>(
        `/trading-partners/sftp/${id}/test`,
        payload,
      );
      return res.data;
    },
  });
}

export function useTestAs2PartnershipConnectionMutation() {
  const api = useEdiPlatformNetwork();
  return useMutation({
    mutationFn: async ({ id, custom_payload }: { id: string; custom_payload?: string }) => {
      const res = await api.post<{
        success: boolean;
        mdn_disposition?: string | null;
        reason?: string | null;
        sent_payload?: string | null;
        raw_mdn?: string | null;
      }>(`/platform/trading-partners/as2/partnerships/${id}/test`, { custom_payload });
      return res.data;
    },
  });
}
