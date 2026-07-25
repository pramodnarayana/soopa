import type { QueryKey } from '@tanstack/react-query';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useToast } from '@/hooks/use-toast';
import { useEdiNetwork } from '../../../contexts/EdiNetworkContext';
import type {
  CertificatesExport,
  CreatePartnerPayload,
  CreatePartnershipPayload,
  CreateSftpPartnerPayload,
  Partner,
  Partnership,
  RotateCertPayload,
  UpdatePartnerPayload,
  UpdatePartnershipPayload,
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

function useApi() {
  const api = useEdiNetwork();
  return api;
}

// ─────────────────────────────────────────────
// Helper — reusable mutation wrapper with toast
// ─────────────────────────────────────────────

function useToastMutation<TData, TVariables = unknown>(
  mutationFn: (variables: TVariables) => Promise<TData>,
  successMessage: string,
  queryKeysToInvalidate: QueryKey[] = [],
) {
  const queryClient = useQueryClient();
  const { toast } = useToast();

  return useMutation({
    mutationFn,
    onSuccess: () => {
      queryKeysToInvalidate.forEach((key) => {
        void queryClient.invalidateQueries({ queryKey: key });
      });
      toast({ title: 'Success', description: successMessage });
    },
    onError: (error: Error) => {
      toast({ title: 'Error', description: error.message, variant: 'destructive' });
    },
  });
}

// ─────────────────────────────────────────────
// Queries
// ─────────────────────────────────────────────

export function usePlatformPartnersQuery() {
  const api = useApi();
  return useQuery({
    queryKey: partnersKeys.platformPartners(),
    queryFn: async (): Promise<Partner[]> => {
      const res = await api.get<Partner[]>('/platform/trading-partners/as2/trading-partners');
      return res.data;
    },
  });
}

export function usePlatformPartnershipsQuery() {
  const api = useApi();
  return useQuery({
    queryKey: partnersKeys.platformPartnerships(),
    queryFn: async (): Promise<Partnership[]> => {
      const res = await api.get<Partnership[]>('/platform/trading-partners/as2/partnerships');
      return res.data;
    },
  });
}

export function useCertificatesExportQuery(partnerId: string) {
  const api = useApi();
  return useQuery({
    queryKey: partnersKeys.certificates(partnerId),
    queryFn: async (): Promise<CertificatesExport> => {
      const res = await api.get<CertificatesExport>(
        `/platform/trading-partners/as2/certificates/${partnerId}/export`,
      );
      return res.data;
    },
    enabled: !!partnerId,
  });
}

export function useTenantPartnersQuery() {
  const api = useApi();
  return useQuery({
    queryKey: partnersKeys.tenant(),
    queryFn: async (): Promise<Partner[]> => {
      const res = await api.get<Partner[]>('/trading-partners/sftp');
      return res.data;
    },
  });
}

// ─────────────────────────────────────────────
// Platform Partner Mutations
// ─────────────────────────────────────────────

export function useCreatePlatformPartnerMutation() {
  const api = useApi();

  return useToastMutation(
    async (payload: CreatePartnerPayload) => {
      if (!payload.is_local && !payload.public_cert_pem?.trim()) {
        throw new Error('Remote AS2 partners require a public certificate.');
      }
      const res = await api.post<Partner>(
        '/platform/trading-partners/as2/trading-partners',
        payload,
      );
      return res.data;
    },
    'Trading partner created successfully.',
    [partnersKeys.platformPartners()],
  );
}

export function useUpdatePlatformPartnerMutation() {
  const api = useApi();

  return useToastMutation(
    async ({ id, payload }: { id: string; payload: UpdatePartnerPayload }) => {
      const res = await api.put<Partner>(
        `/platform/trading-partners/as2/trading-partners/${id}`,
        payload,
      );
      return res.data;
    },
    'Partner updated successfully.',
    [partnersKeys.platformPartners()],
  );
}

export function useDeletePlatformPartnerMutation() {
  const api = useApi();
  return useToastMutation(
    async (id: string) => {
      await api.delete(`/platform/trading-partners/as2/trading-partners/${id}`);
    },
    'Partner deleted.',
    [partnersKeys.platformPartners()],
  );
}

export function useDeleteCertificateSecretMutation() {
  const api = useApi();
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

export function useCreatePlatformPartnershipMutation() {
  const api = useApi();

  return useToastMutation(
    async (payload: CreatePartnershipPayload) => {
      if (!payload.local_partner_id || !payload.remote_partner_id) {
        throw new Error('Both a local and remote trading partner must be selected.');
      }
      const res = await api.post<Partnership>(
        '/platform/trading-partners/as2/partnerships',
        payload,
      );
      return res.data;
    },
    'Partnership created successfully.',
    [partnersKeys.platformPartnerships()],
  );
}

export function useUpdatePlatformPartnershipMutation() {
  const api = useApi();

  return useToastMutation(
    async ({ id, payload }: { id: string; payload: UpdatePartnershipPayload }) => {
      const res = await api.put<Partnership>(
        `/platform/trading-partners/as2/partnerships/${id}`,
        payload,
      );
      return res.data;
    },

    'Partnership updated successfully.',
    [partnersKeys.platformPartnerships()],
  );
}

export function useDeletePlatformPartnershipMutation() {
  const api = useApi();

  return useToastMutation(
    async (id: string) => {
      await api.delete(`/platform/trading-partners/as2/partnerships/${id}`);
    },
    'Partnership deleted successfully.',
    [partnersKeys.platformPartnerships()],
  );
}

// ─────────────────────────────────────────────
// Tenant Partner Mutations
// ─────────────────────────────────────────────

export function useCreateSftpPartnerMutation() {
  const api = useApi();

  return useToastMutation(
    async (payload: CreateSftpPartnerPayload) => {
      const res = await api.post<Partner>('/trading-partners/sftp', payload);
      return res.data;
    },
    'SFTP Partner created successfully.',
    [partnersKeys.tenant()],
  );
}

export function useUpdateSftpPartnerMutation() {
  const api = useApi();

  return useToastMutation(
    async ({ id, payload }: { id: string; payload: UpdatePartnerPayload }) => {
      const res = await api.put<Partner>(`/trading-partners/sftp/${id}`, payload);
      return res.data;
    },
    'SFTP Partner updated successfully.',
    [partnersKeys.tenant()],
  );
}

export function useDeleteSftpPartner() {
  const api = useApi();

  return useToastMutation(
    async (id: string) => {
      await api.delete(`/trading-partners/sftp/${id}`);
    },
    'SFTP Partner deleted successfully.',
    [partnersKeys.tenant()],
  );
}

// ─────────────────────────────────────────────
// Certificate Mutations
// ─────────────────────────────────────────────

export function useRotateCertificatesMutation() {
  const api = useApi();
  return useToastMutation(
    async ({ id, payload }: { id: string; payload: RotateCertPayload }) => {
      const res = await api.post<Partner>(
        `/platform/trading-partners/as2/certificates/${id}/rotate`,
        payload,
      );
      return res.data;
    },
    'Certificate operation successful.',
    [partnersKeys.all],
  );
}

export function useGenerateCertificateMutation() {
  const api = useApi();
  return useMutation({
    mutationFn: async (as2Id: string) => {
      const res = await api.post<{ public_cert_pem: string; private_key_vault_ref: string }>(
        `/platform/trading-partners/as2/certificates/generate?as2_id=${encodeURIComponent(as2Id)}`,
      );
      return res.data;
    },
  });
}

export function useTestSftpConnectionMutation() {
  const api = useApi();
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
  const api = useApi();
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
  const api = useApi();
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
