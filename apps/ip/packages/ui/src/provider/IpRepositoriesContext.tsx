import type { FrontendLoggerPort } from '@soopa/ui';
import { createContext, useContext } from 'react';
import type { CatalogRepositoryPort } from '../ports/catalog-repository.port';
import type { ConnectionRepositoryPort } from '../ports/connection-repository.port';
import type { StitchRepositoryPort } from '../ports/stitch-repository.port';
import type { SyncRunRepositoryPort } from '../ports/sync-run-repository.port';
import type { TraceRepositoryPort } from '../ports/trace-repository.port';
import type { TransformationRepositoryPort } from '../ports/transformation-repository.port';

export interface IpRepositoriesBundle {
  readonly catalog: CatalogRepositoryPort;
  readonly connections: ConnectionRepositoryPort;
  readonly syncRuns: SyncRunRepositoryPort;
  readonly transformations: TransformationRepositoryPort;
  readonly stitches: StitchRepositoryPort;
  readonly traces: TraceRepositoryPort;
}

export interface IpNavigationPort {
  readonly toCommandCenter: () => void;
  readonly toTraces: (correlationQuery?: string) => void;
  readonly toTraceDetail: (traceId: string) => void;
  readonly toConnections: () => void;
  readonly toConnectionDetail: (connectionId: string) => void;
  readonly toTransformations: (connectionId?: string) => void;
  readonly toStitches: () => void;
  readonly toStitchDefinition: (workflowId: string) => void;
  readonly toStitchRun: (runId: string) => void;
}

export interface IpWorkspaceContextValue {
  readonly tenantId: string;
  readonly tenantSlug: string;
  readonly repositories: IpRepositoriesBundle;
  readonly navigation: IpNavigationPort;
  readonly logger: FrontendLoggerPort;
  readonly openCommandPalette: () => void;
}

export const IpWorkspaceContext = createContext<IpWorkspaceContextValue | null>(null);

export function useIpWorkspace(): IpWorkspaceContextValue {
  const ctx = useContext(IpWorkspaceContext);
  if (!ctx) {
    throw new Error('useIpWorkspace must be used inside <IpUIProvider>.');
  }
  return ctx;
}
