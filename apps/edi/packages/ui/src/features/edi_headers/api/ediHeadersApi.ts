import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useTenantId } from '@/contexts/TenantContext';
import { useEdiNetwork } from '../../../contexts/EdiNetworkContext';
import type { CreateEdiHeaderPayload, EdiHeaderItem, UpdateEdiHeaderPayload } from '../types';

export const useEdiHeaders = () => {
  const api = useEdiNetwork();
  const tenantId = useTenantId();
  const QUERY_KEY = ['edi_headers', tenantId];

  return useQuery({
    queryKey: QUERY_KEY,
    queryFn: async (): Promise<EdiHeaderItem[]> => {
      const response = await api.get<EdiHeaderItem[]>('/edi-headers');
      return response.data;
    },
  });
};

export const useCreateEdiHeaderMutation = () => {
  const queryClient = useQueryClient();
  const api = useEdiNetwork();
  const tenantId = useTenantId();
  const QUERY_KEY = ['edi_headers', tenantId];

  return useMutation({
    mutationFn: async (payload: CreateEdiHeaderPayload) => {
      const response = await api.post<EdiHeaderItem>('/edi-headers', payload);
      return response.data;
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: QUERY_KEY });
    },
  });
};

export const useUpdateEdiHeaderMutation = () => {
  const queryClient = useQueryClient();
  const api = useEdiNetwork();
  const tenantId = useTenantId();
  const QUERY_KEY = ['edi_headers', tenantId];

  return useMutation({
    mutationFn: async ({
      headerId,
      payload,
    }: {
      headerId: string;
      payload: UpdateEdiHeaderPayload;
    }) => {
      const response = await api.patch<EdiHeaderItem>(`/edi-headers/${headerId}`, payload);
      return response.data;
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: QUERY_KEY });
    },
  });
};

export const useDeleteEdiHeaderMutation = () => {
  const queryClient = useQueryClient();
  const api = useEdiNetwork();
  const tenantId = useTenantId();
  const QUERY_KEY = ['edi_headers', tenantId];

  return useMutation({
    mutationFn: async (headerId: string) => {
      const response = await api.delete<void>(`/edi-headers/${headerId}`);
      return response.data;
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: QUERY_KEY });
    },
  });
};
