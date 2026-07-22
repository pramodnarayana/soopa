import { useMutation, useQueryClient } from '@tanstack/react-query';
import { apiClient } from '@/lib/api-client';

export const useCreateTenantUser = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ 
      tenantId, 
      firstName, 
      lastName, 
      email, 
      role 
    }: { 
      tenantId: string; 
      firstName: string; 
      lastName: string; 
      email: string; 
      role: string;
    }) => apiClient.post(`/tenants/${tenantId}/users`, { firstName, lastName, email, role }),
    onSuccess: (_, variables) => {
      queryClient.invalidateQueries({ queryKey: ['tenants', variables.tenantId, 'users'] });
    },
  });
};

export const useUpdateTenantUser = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ 
      tenantId, 
      userId, 
      firstName, 
      lastName, 
      role 
    }: { 
      tenantId: string; 
      userId: string; 
      firstName: string; 
      lastName: string; 
      role: string;
    }) => apiClient.patch(`/tenants/${tenantId}/users/${userId}`, { firstName, lastName, role }),
    onSuccess: (_, variables) => {
      queryClient.invalidateQueries({ queryKey: ['tenants', variables.tenantId, 'users'] });
    },
  });
};

export const useToggleTenantUserStatus = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ 
      tenantId, 
      userId, 
      action 
    }: { 
      tenantId: string; 
      userId: string; 
      action: 'activate' | 'deactivate';
    }) => apiClient.patch(`/tenants/${tenantId}/users/${userId}/status`, { action }),
    onSuccess: (_, variables) => {
      queryClient.invalidateQueries({ queryKey: ['tenants', variables.tenantId, 'users'] });
    },
  });
};

export const useDeleteTenantUser = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ tenantId, userId }: { tenantId: string; userId: string }) => 
      apiClient.delete(`/tenants/${tenantId}/users/${userId}`),
    onSuccess: (_, variables) => {
      queryClient.invalidateQueries({ queryKey: ['tenants', variables.tenantId, 'users'] });
    },
  });
};
