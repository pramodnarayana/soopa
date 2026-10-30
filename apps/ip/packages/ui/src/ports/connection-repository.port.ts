import type { ApiProblem, Result } from '@soopa/ui';
import type {
  CheckConnectionInput,
  Connection,
  ConnectionCheckResult,
  CreateConnectionInput,
  DiscoveredCatalog,
  RelinkConnectionInput,
} from '../domain/connection';

export interface ConnectionRepositoryPort {
  listConnections(
    tenantId: string,
    status?: string,
    signal?: AbortSignal,
  ): Promise<Result<readonly Connection[], ApiProblem>>;

  getConnection(
    tenantId: string,
    connectionId: string,
    signal?: AbortSignal,
  ): Promise<Result<Connection, ApiProblem>>;

  checkConnection(
    tenantId: string,
    input: CheckConnectionInput,
    signal?: AbortSignal,
  ): Promise<Result<ConnectionCheckResult, ApiProblem>>;

  createConnection(
    tenantId: string,
    input: CreateConnectionInput,
  ): Promise<Result<Connection, ApiProblem>>;

  discoverCatalog(
    tenantId: string,
    connectionId: string,
  ): Promise<Result<DiscoveredCatalog, ApiProblem>>;

  relinkConnection(
    tenantId: string,
    connectionId: string,
    input: RelinkConnectionInput,
  ): Promise<Result<Connection, ApiProblem>>;

  deactivateConnection(
    tenantId: string,
    connectionId: string,
  ): Promise<Result<Connection, ApiProblem>>;
}
