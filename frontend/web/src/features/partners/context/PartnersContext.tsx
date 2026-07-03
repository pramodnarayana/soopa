import { createContext, useContext, useCallback } from 'react';
import type { Partner } from '../types';
import { useTenantPartnersQuery } from '../api/partnerHooks';

interface PartnersContextType {
  partners: Partner[];
  isLoading: boolean;
  error: Error | null;
  refresh: () => Promise<void>;
}

const PartnersContext = createContext<PartnersContextType | undefined>(undefined);

export function PartnersProvider({ children }: { children: React.ReactNode }) {
  const { data: partners = [], isLoading, error, refetch } = useTenantPartnersQuery();

  const refresh = useCallback(async () => {
    await refetch();
  }, [refetch]);

  return (
    <PartnersContext.Provider value={{ partners, isLoading, error, refresh }}>
      {children}
    </PartnersContext.Provider>
  );
}

export function usePartners() {
  const ctx = useContext(PartnersContext);
  if (ctx === undefined) {
    throw new Error('usePartners must be used within a PartnersProvider');
  }
  return ctx;
}

// Re-export for backward compatibility
export type { Partner };
export type { PartnerType } from '../types';
