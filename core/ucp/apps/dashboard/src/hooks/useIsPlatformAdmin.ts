import { useAuthUser } from './useAuthUser';

export function useIsPlatformAdmin() {
  const { data: authUser, isLoading } = useAuthUser();

  return {
    isPlatformAdmin: authUser?.isPlatformAdmin ?? false,
    isLoading,
  };
}
