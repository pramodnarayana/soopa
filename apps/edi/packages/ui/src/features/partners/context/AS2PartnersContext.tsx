import { createContext, useCallback, useContext } from 'react';
import { useAS2PartnershipsQuery, useAS2PartnersQuery } from '../api/partnerHooks';
import type { Partner, Partnership } from '../types';

// ─────────────────────────────────────────────
// Context contract — read-only data only.
// Mutations are consumed directly via hooks at
// the component level (useCreateAS2PartnerMutation, etc.)
// ─────────────────────────────────────────────

interface AS2PartnersContextType {
  partners: Partner[];
  partnerships: Partnership[];
  isLoading: boolean;
  error: Error | null;
  partnersLoading: boolean;
  partnersError: Error | null;
  partnershipsLoading: boolean;
  partnershipsError: Error | null;
  refresh: () => Promise<void>;
}

const AS2PartnersContext = createContext<AS2PartnersContextType | undefined>(undefined);

export function AS2PartnersProvider({ children }: { children: React.ReactNode }) {
  const {
    data: partners = [],
    isLoading: isLoadingPartners,
    error: errorPartners,
    refetch: refetchPartners,
  } = useAS2PartnersQuery();

  const {
    data: partnerships = [],
    isLoading: isLoadingPartnerships,
    error: errorPartnerships,
    refetch: refetchPartnerships,
  } = useAS2PartnershipsQuery();

  const isLoading = isLoadingPartners || isLoadingPartnerships;
  const error = errorPartners || errorPartnerships;

  const refresh = useCallback(async () => {
    await Promise.all([refetchPartners(), refetchPartnerships()]);
  }, [refetchPartners, refetchPartnerships]);

  return (
    <AS2PartnersContext.Provider
      value={{
        partners,
        partnerships,
        isLoading,
        error,
        partnersLoading: isLoadingPartners,
        partnersError: errorPartners,
        partnershipsLoading: isLoadingPartnerships,
        partnershipsError: errorPartnerships,
        refresh,
      }}
    >
      {children}
    </AS2PartnersContext.Provider>
  );
}

export function useAS2Partners() {
  const ctx = useContext(AS2PartnersContext);
  if (ctx === undefined) {
    throw new Error('useAS2Partners must be used within a AS2PartnersProvider');
  }
  return ctx;
}

// Re-export domain types so consumers don't need a second import path
export type { Partner, Partnership };
