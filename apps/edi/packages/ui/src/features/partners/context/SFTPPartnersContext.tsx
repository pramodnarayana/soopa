import { createContext, useCallback, useContext } from 'react';
import { useTenantPartnersQuery } from '../api/partnerHooks';
import type { SFTPPartner } from '../types';

interface SFTPPartnersContextType {
  sftpPartners: SFTPPartner[];
  isLoading: boolean;
  error: Error | null;
  refresh: () => Promise<void>;
}

const SFTPPartnersContext = createContext<SFTPPartnersContextType | undefined>(undefined);

export function SFTPPartnersProvider({ children }: { children: React.ReactNode }) {
  const { data: partners = [], isLoading, error, refetch } = useTenantPartnersQuery();

  const sftpPartners = partners.filter((p): p is SFTPPartner => p.type === 'SFTP');

  const refresh = useCallback(async () => {
    await refetch();
  }, [refetch]);

  return (
    <SFTPPartnersContext.Provider value={{ sftpPartners, isLoading, error, refresh }}>
      {children}
    </SFTPPartnersContext.Provider>
  );
}

export function useSFTPPartners() {
  const ctx = useContext(SFTPPartnersContext);
  if (ctx === undefined) {
    throw new Error('useSFTPPartners must be used within a SFTPPartnersProvider');
  }
  return ctx;
}

// Re-export for backward compatibility
export type { Partner, PartnerType } from '../types';
