import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useAuth } from 'react-oidc-context';
import { createPartnersRepository } from './partnersApi';
import type { UpdatePartnerPayload, UpdatePartnershipPayload, CreatePartnerPayload, CreatePartnershipPayload, RotateCertPayload } from '../types';
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
  const queryClient = useQueryClient();
  const { toast } = useToast();

  return useMutation({
    mutationFn: (payload: CreatePartnerPayload) => {
      // Business rule: remote partners require a public certificate
      if (!payload.is_local && !payload.public_cert_pem?.trim()) {
        throw new Error('Remote AS2 partners require a public certificate.');
      }
      return repo.createPlatformPartner(payload);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: partnersKeys.platformPartners() });
      toast({ title: 'Success', description: 'Trading partner created successfully.' });
    },
    onError: (error: Error) => {
      toast({ title: 'Error', description: error.message, variant: 'destructive' });
    },
  });
}

export function useUpdatePlatformPartnerMutation() {
  const repo = useRepository();
  const queryClient = useQueryClient();
  const { toast } = useToast();

  return useMutation({
    mutationFn: ({ id, payload }: { id: string; payload: UpdatePartnerPayload }) =>
      repo.updatePlatformPartner(id, payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: partnersKeys.platformPartners() });
      toast({ title: 'Success', description: 'Partner updated successfully.' });
    },
    onError: (error: Error) => {
      toast({ title: 'Error', description: error.message, variant: 'destructive' });
    },
  });
}

export function useDeletePlatformPartner() {
  const repo = useRepository();
  const queryClient = useQueryClient();
  const { toast } = useToast();

  return useMutation({
    mutationFn: (id: string) => repo.deletePlatformPartner(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: partnersKeys.platformPartners() });
      toast({ title: 'Success', description: 'Partner deleted.' });
    },
    onError: (error: Error) => {
      toast({ title: 'Error', description: error.message, variant: 'destructive' });
    },
  });
}

// ─────────────────────────────────────────────
// Platform Partnership Mutations
// ─────────────────────────────────────────────

export function useCreatePlatformPartnershipMutation() {
  const repo = useRepository();
  const queryClient = useQueryClient();
  const { toast } = useToast();

  return useMutation({
    mutationFn: (payload: CreatePartnershipPayload) => {
      if (!payload.local_partner_id || !payload.remote_partner_id) {
        throw new Error('Both a local and remote trading partner must be selected.');
      }
      return repo.createPlatformPartnership(payload);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: partnersKeys.platformPartnerships() });
      toast({ title: 'Success', description: 'Partnership created successfully.' });
    },
    onError: (error: Error) => {
      toast({ title: 'Error', description: error.message, variant: 'destructive' });
    },
  });
}

export function useUpdatePlatformPartnershipMutation() {
  const repo = useRepository();
  const queryClient = useQueryClient();
  const { toast } = useToast();

  return useMutation({
    mutationFn: ({ id, payload }: { id: string; payload: UpdatePartnershipPayload }) =>
      repo.updatePlatformPartnership(id, payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: partnersKeys.platformPartnerships() });
      toast({ title: 'Success', description: 'Partnership updated successfully.' });
    },
    onError: (error: Error) => {
      toast({ title: 'Error', description: error.message, variant: 'destructive' });
    },
  });
}

export function useDeletePlatformPartnershipMutation() {
  const repo = useRepository();
  const queryClient = useQueryClient();
  const { toast } = useToast();

  return useMutation({
    mutationFn: (id: string) => repo.deletePlatformPartnership(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: partnersKeys.platformPartnerships() });
      toast({ title: 'Success', description: 'Partnership deleted successfully.' });
    },
    onError: (error: Error) => {
      toast({ title: 'Error', description: error.message, variant: 'destructive' });
    },
  });
}

// ─────────────────────────────────────────────
// Tenant Partner Mutations
// ─────────────────────────────────────────────

export function useUpdateSftpPartnerMutation() {
  const repo = useRepository();
  const queryClient = useQueryClient();
  const { toast } = useToast();

  return useMutation({
    mutationFn: ({ id, payload }: { id: string; payload: UpdatePartnerPayload }) =>
      repo.updateSftpPartner(id, payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: partnersKeys.tenant() });
      toast({ title: 'Success', description: 'SFTP Partner updated successfully.' });
    },
    onError: (error: Error) => {
      toast({ title: 'Error', description: error.message, variant: 'destructive' });
    },
  });
}

export function useDeleteSftpPartner() {
  const repo = useRepository();
  const queryClient = useQueryClient();
  const { toast } = useToast();

  return useMutation({
    mutationFn: (id: string) => repo.deleteSftpPartner(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: partnersKeys.tenant() });
      toast({ title: 'Success', description: 'SFTP Partner deleted successfully.' });
    },
    onError: (error: Error) => {
      toast({ title: 'Error', description: error.message, variant: 'destructive' });
    },
  });
}

// ─────────────────────────────────────────────
// Certificate Mutations
// ─────────────────────────────────────────────

export function useRotateCertificatesMutation() {
  const repo = useRepository();
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ id, payload }: { id: string; payload: RotateCertPayload }) =>
      repo.rotateCertificates(id, payload),
    onSuccess: (_, { id }) => {
      queryClient.invalidateQueries({ queryKey: partnersKeys.all });
      queryClient.invalidateQueries({ queryKey: partnersKeys.certificates(id) });
    },
  });
}
