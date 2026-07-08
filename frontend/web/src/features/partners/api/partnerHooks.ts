import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import type { QueryKey } from '@tanstack/react-query';
import { useAuth } from 'react-oidc-context';
import { createPartnersRepository } from './partnersApi';
import type { UpdatePartnerPayload, UpdatePartnershipPayload, CreatePartnerPayload, CreatePartnershipPayload, RotateCertPayload, CreateSftpPartnerPayload } from '../types';
import { useToast } from '@/hooks/use-toast';

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

function useRepository() {
  const auth = useAuth();
  return createPartnersRepository(auth.user?.access_token ?? '');
}

// ─────────────────────────────────────────────
// Helper — reusable mutation wrapper with toast
// ─────────────────────────────────────────────

function useToastMutation<TData, TVariables = any>(
  mutationFn: (variables: TVariables) => Promise<TData>,
  successMessage: string,
  queryKeysToInvalidate: QueryKey[] = []
) {
  const queryClient = useQueryClient();
  const { toast } = useToast();

  return useMutation({
    mutationFn,
    onSuccess: () => {
      queryKeysToInvalidate.forEach(key => {
        queryClient.invalidateQueries({ queryKey: key });
      });
      toast({ title: 'Success', description: successMessage });
    },
    onError: (error: Error) => {
      toast({ title: 'Error', description: error.message, variant: 'destructive' });
    }
  });
}

// ─────────────────────────────────────────────
// Queries
// ─────────────────────────────────────────────

export function usePlatformPartnersQuery() {
  const auth = useAuth();
  const repo = useRepository();
  return useQuery({
    queryKey: partnersKeys.platformPartners(),
    queryFn: () => repo.getPlatformPartners(),
    enabled: !!auth.user?.access_token,
  });
}

export function usePlatformPartnershipsQuery() {
  const auth = useAuth();
  const repo = useRepository();
  return useQuery({
    queryKey: partnersKeys.platformPartnerships(),
    queryFn: () => repo.getPlatformPartnerships(),
    enabled: !!auth.user?.access_token,
  });
}

export function useCertificatesExportQuery(partnerId: string) {
  const auth = useAuth();
  const repo = useRepository();
  return useQuery({
    queryKey: partnersKeys.certificates(partnerId),
    queryFn: () => repo.exportCertificates(partnerId),
    enabled: !!auth.user?.access_token && !!partnerId,
  });
}

export function useTenantPartnersQuery() {
  const auth = useAuth();
  const repo = useRepository();
  return useQuery({
    queryKey: partnersKeys.tenant(),
    queryFn: () => repo.getTenantPartners(),
    enabled: !!auth.user?.access_token,
  });
}

// ─────────────────────────────────────────────
// Platform Partner Mutations
// ─────────────────────────────────────────────

export function useCreatePlatformPartnerMutation() {
  const repo = useRepository();

  return useToastMutation(
    (payload: CreatePartnerPayload) => {
      if (!payload.is_local && !payload.public_cert_pem?.trim()) {
        throw new Error('Remote AS2 partners require a public certificate.');
      }
      return repo.createPlatformPartner(payload);
    },
    'Trading partner created successfully.',
    [partnersKeys.platformPartners()]
  );
}

export function useUpdatePlatformPartnerMutation() {
  const repo = useRepository();

  return useToastMutation(
    ({ id, payload }: { id: string; payload: UpdatePartnerPayload }) =>
      repo.updatePlatformPartner(id, payload),
    'Partner updated successfully.',
    [partnersKeys.platformPartners()]
  );
}

export function useDeletePlatformPartner() {
  const repo = useRepository();

  return useToastMutation(
    (id: string) => repo.deletePlatformPartner(id),
    'Partner deleted.',
    [partnersKeys.platformPartners()]
  );
}

// ─────────────────────────────────────────────
// Platform Partnership Mutations
// ─────────────────────────────────────────────

export function useCreatePlatformPartnershipMutation() {
  const repo = useRepository();

  return useToastMutation(
    (payload: CreatePartnershipPayload) => {
      if (!payload.local_partner_id || !payload.remote_partner_id) {
        throw new Error('Both a local and remote trading partner must be selected.');
      }
      return repo.createPlatformPartnership(payload);
    },
    'Partnership created successfully.',
    [partnersKeys.platformPartnerships()]
  );
}

export function useUpdatePlatformPartnershipMutation() {
  const repo = useRepository();

  return useToastMutation(
    ({ id, payload }: { id: string; payload: UpdatePartnershipPayload }) =>
      repo.updatePlatformPartnership(id, payload),
    'Partnership updated successfully.',
    [partnersKeys.platformPartnerships()]
  );
}

export function useDeletePlatformPartnershipMutation() {
  const repo = useRepository();

  return useToastMutation(
    (id: string) => repo.deletePlatformPartnership(id),
    'Partnership deleted successfully.',
    [partnersKeys.platformPartnerships()]
  );
}

// ─────────────────────────────────────────────
// Tenant Partner Mutations
// ─────────────────────────────────────────────

export function useCreateSftpPartnerMutation() {
  const repo = useRepository();

  return useToastMutation(
    (payload: CreateSftpPartnerPayload) => repo.createSftpPartner(payload),
    'SFTP Partner created successfully.',
    [partnersKeys.tenant()]
  );
}

export function useUpdateSftpPartnerMutation() {
  const repo = useRepository();

  return useToastMutation(
    ({ id, payload }: { id: string; payload: UpdatePartnerPayload }) =>
      repo.updateSftpPartner(id, payload),
    'SFTP Partner updated successfully.',
    [partnersKeys.tenant()]
  );
}

export function useDeleteSftpPartner() {
  const repo = useRepository();

  return useToastMutation(
    (id: string) => repo.deleteSftpPartner(id),
    'SFTP Partner deleted successfully.',
    [partnersKeys.tenant()]
  );
}

// ─────────────────────────────────────────────
// Certificate Mutations
// ─────────────────────────────────────────────

export function useRotateCertificatesMutation() {
  const repo = useRepository();
  return useToastMutation(
    ({ id, payload }: { id: string; payload: RotateCertPayload }) =>
      repo.rotateCertificates(id, payload),
    'Certificate operation successful.',
    [
      partnersKeys.all,
    ]
  );
}

export function useTestSftpConnectionMutation() {
  const repo = useRepository();
  return useMutation({
    mutationFn: (payload: Omit<CreateSftpPartnerPayload, 'name' | 'inbound_remote_path' | 'outbound_remote_path'>) =>
      repo.testSftpConnection(payload)
  });
}

export function useTestExistingSftpConnectionMutation() {
  const repo = useRepository();
  return useMutation({
    mutationFn: ({ id, payload }: { id: string; payload: Omit<CreateSftpPartnerPayload, 'name' | 'inbound_remote_path' | 'outbound_remote_path'> }) =>
      repo.testExistingSftpConnection(id, payload)
  });
}

export function useTestAs2PartnershipConnectionMutation() {
  const repo = useRepository();
  return useMutation({
    mutationFn: ({ id, custom_payload }: { id: string; custom_payload?: string }) =>
      repo.testAs2PartnershipConnection(id, custom_payload),
  });
}
