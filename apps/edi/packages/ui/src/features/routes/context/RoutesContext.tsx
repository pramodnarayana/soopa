import { createContext, useCallback, useContext } from 'react';
import { useRoutesQuery } from '../api/routeHooks';
import type { RouteItem } from '../types';

interface RoutesContextType {
  routes: RouteItem[];
  isLoading: boolean;
  error: Error | null;
  refresh: () => Promise<void>;
}

const RoutesContext = createContext<RoutesContextType | undefined>(undefined);

export function RoutesProvider({ children }: { children: React.ReactNode }) {
  const { data: routes = [], isLoading, error, refetch } = useRoutesQuery();

  const refresh = useCallback(async () => {
    await refetch();
  }, [refetch]);

  return (
    <RoutesContext.Provider value={{ routes, isLoading, error, refresh }}>
      {children}
    </RoutesContext.Provider>
  );
}

export function useRoutes() {
  const ctx = useContext(RoutesContext);
  if (ctx === undefined) {
    throw new Error('useRoutes must be used within a RoutesProvider');
  }
  return ctx;
}
