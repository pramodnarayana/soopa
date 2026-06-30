import React, { createContext, useContext, useState, useEffect } from 'react';

export type PartnerType = 'AS2' | 'SFTP';

export interface Partner {
  id: string;
  name: string;
  type: PartnerType;
  host?: string;
  as2_id?: string;
  username?: string;
  is_local?: boolean;
}

interface PartnersContextType {
  partners: Partner[];
  addPartner: (partner: Omit<Partner, 'id'>) => void;
  removePartner: (id: string) => void;
}

const PartnersContext = createContext<PartnersContextType | undefined>(undefined);

export function PartnersProvider({ children }: { children: React.ReactNode }) {
  const [partners, setPartners] = useState<Partner[]>([]);

  // Load from local storage on mount
  useEffect(() => {
    const saved = localStorage.getItem('soopa_partners');
    if (saved) {
      try {
        setPartners(JSON.parse(saved));
      } catch {}
    }
  }, []);

  // Save to local storage on change
  useEffect(() => {
    localStorage.setItem('soopa_partners', JSON.stringify(partners));
  }, [partners]);

  const addPartner = (partner: Omit<Partner, 'id'>) => {
    const newPartner = { ...partner, id: Math.random().toString(36).substring(2, 9) };
    setPartners((prev) => [...prev, newPartner]);
  };

  const removePartner = (id: string) => {
    setPartners((prev) => prev.filter((p) => p.id !== id));
  };

  return (
    <PartnersContext.Provider value={{ partners, addPartner, removePartner }}>
      {children}
    </PartnersContext.Provider>
  );
}

export function usePartners() {
  const context = useContext(PartnersContext);
  if (context === undefined) {
    throw new Error('usePartners must be used within a PartnersProvider');
  }
  return context;
}
