import { useQuery } from '@tanstack/react-query';
import axios from 'axios';

export interface PlatformConfig {
  available_as2_receive_urls: string[];
}

export const usePlatformConfig = () => {
  return useQuery({
    queryKey: ['platform-config'],
    queryFn: async (): Promise<PlatformConfig> => {
      const response = await axios.get('/api/v1/platform/config');
      return response.data;
    },
    // The configuration is static, so we can keep it cached indefinitely
    staleTime: Infinity,
  });
};
