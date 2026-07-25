import React, { createContext, useContext } from 'react';
import type { IDashboardRepository } from './IDashboardRepository';

const DashboardContext = createContext<IDashboardRepository | null>(null);

export function DashboardProvider({
  repository,
  children,
}: {
  repository: IDashboardRepository;
  children: React.ReactNode;
}) {
  return <DashboardContext.Provider value={repository}>{children}</DashboardContext.Provider>;
}

export function useDashboardRepository(): IDashboardRepository {
  const context = useContext(DashboardContext);
  if (!context) {
    throw new Error('useDashboardRepository must be used within a DashboardProvider');
  }
  return context;
}
