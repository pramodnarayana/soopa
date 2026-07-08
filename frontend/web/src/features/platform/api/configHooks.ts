import { useQuery } from '@tanstack/react-query';
import { useAuth } from 'react-oidc-context';

export interface SupportedAlgorithm {
  value: string;
  label: string;
}

export interface PlatformConfig {
  available_as2_receive_urls: string[];
  supported_as2_encryption_algorithms: SupportedAlgorithm[];
  supported_as2_signature_algorithms: SupportedAlgorithm[];
}

export const usePlatformConfig = () => {
  const auth = useAuth();
  return useQuery({
    queryKey: ['platform-config'],
    queryFn: async (): Promise<PlatformConfig> => {
      const response = await fetch('/api/v1/platform/trading-partners/config', {
        headers: {
          Authorization: `Bearer ${auth.user?.access_token}`,
        },
      });
      if (!response.ok) {
        throw new Error(`Failed to fetch platform config: ${response.statusText}`);
      }
      return response.json();
    },
    // The configuration is static, so we can keep it cached indefinitely
    staleTime: Infinity,
    enabled: !!auth.user?.access_token,
  });
};
