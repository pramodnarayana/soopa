import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import axios from 'axios';
import { useAuth } from 'react-oidc-context';
import type { EdiHeaderItem, CreateEdiHeaderPayload, UpdateEdiHeaderPayload } from '../types';

const QUERY_KEY = ['edi_headers'];

export const useEdiHeaders = () => {
  const auth = useAuth();
  return useQuery({
    queryKey: QUERY_KEY,
    queryFn: async (): Promise<EdiHeaderItem[]> => {
      const response = await axios.get('/api/v1/edi-headers', {
        headers: { Authorization: `Bearer ${auth.user?.access_token}` }
      });
      return response.data;
    },
    enabled: !!auth.user?.access_token,
  });
};

export const useCreateEdiHeaderMutation = () => {
  const queryClient = useQueryClient();
  const auth = useAuth();
  return useMutation({
    mutationFn: async (payload: CreateEdiHeaderPayload) => {
      const response = await axios.post('/api/v1/edi-headers', payload, {
        headers: { Authorization: `Bearer ${auth.user?.access_token}` }
      });
      return response.data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: QUERY_KEY });
    },
  });
};

export const useUpdateEdiHeaderMutation = () => {
  const queryClient = useQueryClient();
  const auth = useAuth();
  return useMutation({
    mutationFn: async ({ headerId, payload }: { headerId: string; payload: UpdateEdiHeaderPayload }) => {
      const response = await axios.patch(`/api/v1/edi-headers/${headerId}`, payload, {
        headers: { Authorization: `Bearer ${auth.user?.access_token}` }
      });
      return response.data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: QUERY_KEY });
    },
  });
};

export const useDeleteEdiHeaderMutation = () => {
  const queryClient = useQueryClient();
  const auth = useAuth();
  return useMutation({
    mutationFn: async (headerId: string) => {
      const response = await axios.delete(`/api/v1/edi-headers/${headerId}`, {
        headers: { Authorization: `Bearer ${auth.user?.access_token}` }
      });
      return response.data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: QUERY_KEY });
    },
  });
};
