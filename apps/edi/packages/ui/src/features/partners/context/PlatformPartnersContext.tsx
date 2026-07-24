import { createContext, useCallback, useContext } from 'react';
import { usePlatformPartnershipsQuery, usePlatformPartnersQuery } from '../api/partnerHooks';
import type { Partner, Partnership } from '../types';

// ─────────────────────────────────────────────
// Context contract — read-only data only.
// Mutations are consumed directly via hooks at
// the component level (useCreatePlatformPartnerMutation, etc.)
// ─────────────────────────────────────────────

interface PlatformPartnersContextType {
  partners: Partner[];
  partnerships: Partnership[];
  isLoading: boolean;
  error: Error | null;
  refresh: () => Promise<void>;
}

const PlatformPartnersContext = createContext<PlatformPartnersContextType | undefined>(undefined);

export function PlatformPartnersProvider({ children }: { children: React.ReactNode }) {
  const {
    data: partners = [],
    isLoading: isLoadingPartners,
    error: errorPartners,
    refetch: refetchPartners,
  } = usePlatformPartnersQuery();

  const {
    data: partnerships = [],
    isLoading: isLoadingPartnerships,
    error: errorPartnerships,
    refetch: refetchPartnerships,
  } = usePlatformPartnershipsQuery();

  const isLoading = isLoadingPartners || isLoadingPartnerships;
  const error = errorPartners || errorPartnerships;

  const refresh = useCallback(async () => {
    await Promise.all([refetchPartners(), refetchPartnerships()]);
  }, [refetchPartners, refetchPartnerships]);

  return (
    <PlatformPartnersContext.Provider value={{ partners, partnerships, isLoading, error, refresh }}>
      {children}
    </PlatformPartnersContext.Provider>
  );
}

export function usePlatformPartners() {
  const ctx = useContext(PlatformPartnersContext);
  if (ctx === undefined) {
    throw new Error('usePlatformPartners must be used within a PlatformPartnersProvider');
  }
  return ctx;
}

// Re-export domain types so consumers don't need a second import path
export type { Partner, Partnership };
