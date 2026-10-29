import {
  FetchHttpClientAdapter,
  type FrontendLoggerPort,
  StructuredJsonLoggerAdapter,
  TenantSessionProvider,
  useProductTheme,
} from '@soopa/ui';
import React, { useCallback, useMemo, useRef, useState } from 'react';
import {
  HttpCatalogRepository,
  HttpConnectionRepository,
  HttpStitchRepository,
  HttpSyncRunRepository,
  HttpTraceRepository,
  HttpTransformationRepository,
} from '../adapters/http';
import { IP_PRODUCT_THEME_TOKEN } from '../domain/enums';
import { CommandPalette } from '../presentation/shared/CommandPalette';
import {
  type IpNavigationPort,
  type IpRepositoriesBundle,
  IpWorkspaceContext,
  type IpWorkspaceContextValue,
} from './IpRepositoriesContext';

export interface IpUIProviderProps {
  readonly baseUrl: string;
  readonly tenantId: string;
  readonly tenantSlug?: string;
  readonly token?: string | null;
  readonly repositories?: IpRepositoriesBundle;
  readonly logger?: FrontendLoggerPort;
  readonly navigation: IpNavigationPort;
  readonly children: React.ReactNode;
}

function createHttpRepositoriesBundle(
  baseUrl: string,
  getToken: () => string | null | undefined,
  logger: FrontendLoggerPort,
): IpRepositoriesBundle {
  const client = new FetchHttpClientAdapter({
    baseUrl,
    getToken,
    logger,
  });
  return {
    catalog: new HttpCatalogRepository(client, logger),
    connections: new HttpConnectionRepository(client, logger),
    syncRuns: new HttpSyncRunRepository(client, logger),
    transformations: new HttpTransformationRepository(client, logger),
    stitches: new HttpStitchRepository(client, logger),
    traces: new HttpTraceRepository(client, logger),
  };
}

export function IpUIProvider({
  baseUrl,
  tenantId,
  tenantSlug = '',
  token,
  repositories: injectedRepositories,
  logger: injectedLogger,
  navigation,
  children,
}: IpUIProviderProps) {
  useProductTheme(IP_PRODUCT_THEME_TOKEN);
  const [commandPaletteOpen, setCommandPaletteOpen] = useState(false);
  const tokenRef = useRef(token);
  tokenRef.current = token;

  const logger = useMemo<FrontendLoggerPort>(
    () =>
      (injectedLogger ?? new StructuredJsonLoggerAdapter()).bind({
        product: 'ip',
        tenant_id: tenantId,
      }),
    [injectedLogger, tenantId],
  );

  const repositories = useMemo<IpRepositoriesBundle>(
    () =>
      injectedRepositories ?? createHttpRepositoriesBundle(baseUrl, () => tokenRef.current, logger),
    [baseUrl, injectedRepositories, logger],
  );

  const openCommandPalette = useCallback(() => setCommandPaletteOpen(true), []);

  const contextValue = useMemo<IpWorkspaceContextValue>(
    () => ({
      tenantId,
      tenantSlug,
      repositories,
      navigation,
      logger,
      openCommandPalette,
    }),
    [tenantId, tenantSlug, repositories, navigation, logger, openCommandPalette],
  );

  return (
    <TenantSessionProvider tenantId={tenantId} token={token ?? ''}>
      <IpWorkspaceContext.Provider value={contextValue}>
        <div
          data-product-theme={IP_PRODUCT_THEME_TOKEN}
          className="min-h-full bg-background text-foreground antialiased"
        >
          {children}
          <CommandPalette
            open={commandPaletteOpen}
            onOpenChange={setCommandPaletteOpen}
            navigation={navigation}
          />
        </div>
      </IpWorkspaceContext.Provider>
    </TenantSessionProvider>
  );
}
