import { useQuery } from '@tanstack/react-query';
import { useEdiNetwork } from '../../../contexts/EdiNetworkContext';

export interface SupportedAlgorithm {
  value: string;
  label: string;
}

export interface PlatformSettings {
  available_as2_receive_urls: string[];
  supported_as2_encryption_algorithms: SupportedAlgorithm[];
  supported_as2_signature_algorithms: SupportedAlgorithm[];
}

export const usePlatformSettings = () => {
  const api = useEdiNetwork();
  return useQuery({
    queryKey: ['platform-settings'],
    queryFn: async (): Promise<PlatformSettings> => {
      const response = await api.get('/platform/trading-partners/config');
      return response.data;
    },
    // The configuration is static, so we can keep it cached indefinitely
    staleTime: Infinity,
  });
};
