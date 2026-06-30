import React, { createContext, useContext, useState, useEffect, useCallback } from 'react';
import type { Partner } from './PartnersContext';
import { useAuth } from 'react-oidc-context';

export type Partnership = {
  id: string;
  local_partner_id: string;
  remote_partner_id: string;
  host?: string;
  port?: number;
  mdn_type: string;
  encryption_algorithm: string;
  signature_algorithm: string;
}

interface PlatformPartnersContextType {
  partners: Partner[];
  partnerships: Partnership[];
  addPartner: (partner: any) => Promise<void>;
  addPartnership: (payload: any) => Promise<void>;
  removePartner: (id: string) => void;
  isLoading: boolean;
  refresh: () => Promise<void>;
}

const PlatformPartnersContext = createContext<PlatformPartnersContextType | undefined>(undefined);

export function PlatformPartnersProvider({ children }: { children: React.ReactNode }) {
  const [partners, setPartners] = useState<Partner[]>([]);
  const [partnerships, setPartnerships] = useState<Partnership[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const auth = useAuth();

  const fetchPartners = useCallback(async () => {
    if (!auth.isAuthenticated) return;
    try {
      setIsLoading(true);
      const [partnersRes, partnershipsRes] = await Promise.all([
        fetch('/api/v1/platform/partners/as2/trading-partners', {
          headers: { Authorization: `Bearer ${auth.user?.access_token}` },
        }),
        fetch('/api/v1/platform/partners/as2/partnerships', {
          headers: { Authorization: `Bearer ${auth.user?.access_token}` },
        })
      ]);

      if (partnersRes.ok) {
        const data = await partnersRes.json();
        setPartners(data);
      } else {
        setPartners([]);
      }
      if (partnershipsRes.ok) {
        const data = await partnershipsRes.json();
        setPartnerships(data);
      } else {
        setPartnerships([]);
      }
    } catch (e) {
      console.error("Failed to fetch platform partners", e);
    } finally {
      setIsLoading(false);
    }
  }, [auth.isAuthenticated, auth.user?.access_token]);

  useEffect(() => {
    fetchPartners();
  }, [fetchPartners]);

  const addPartner = async (payload: any) => {
    if (!auth.isAuthenticated) return;
    try {
      const res = await fetch('/api/v1/platform/partners/as2/trading-partners', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${auth.user?.access_token}`,
        },
        body: JSON.stringify(payload),
      });
      if (res.ok) {
        await fetchPartners();
      } else {
        const err = await res.json();
        console.error("Failed to create partner", err);
        throw new Error(err.detail || "Failed to create partner");
      }
    } catch (e) {
      console.error(e);
      throw e;
    }
  };

  const addPartnership = async (payload: any) => {
    if (!auth.isAuthenticated) return;
    try {
      const res = await fetch('/api/v1/platform/partners/as2/partnerships', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${auth.user?.access_token}`,
        },
        body: JSON.stringify(payload),
      });
      if (res.ok) {
        await fetchPartners();
      } else {
        const err = await res.json();
        console.error("Failed to create partnership", err);
        throw new Error(err.detail || "Failed to create partnership");
      }
    } catch (e) {
      console.error(e);
      throw e;
    }
  };

  const removePartner = (id: string) => {
    // API not implemented yet, just optimistic update for now
    setPartners((prev) => prev.filter((p) => p.id !== id));
  };

  return (
    <PlatformPartnersContext.Provider value={{ partners, partnerships, addPartner, addPartnership, removePartner, isLoading, refresh: fetchPartners }}>
      {children}
    </PlatformPartnersContext.Provider>
  );
}

export function usePlatformPartners() {
  const context = useContext(PlatformPartnersContext);
  if (context === undefined) {
    throw new Error('usePlatformPartners must be used within a PlatformPartnersProvider');
  }
  return context;
}
