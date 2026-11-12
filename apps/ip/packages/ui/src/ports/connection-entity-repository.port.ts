import type { ApiProblem, Result } from '@soopa/ui';
import type {
  AddConnectionEntityInput,
  ConnectionEntity,
  UpdateConnectionEntityInput,
} from '../domain/connection-entity';

export interface ConnectionEntityRepositoryPort {
  listEntities(
    tenantId: string,
    connectionId: string,
    signal?: AbortSignal,
  ): Promise<Result<readonly ConnectionEntity[], ApiProblem>>;

  addEntity(
    tenantId: string,
    connectionId: string,
    input: AddConnectionEntityInput,
  ): Promise<Result<ConnectionEntity, ApiProblem>>;

  updateEntity(
    tenantId: string,
    connectionId: string,
    streamName: string,
    input: UpdateConnectionEntityInput,
  ): Promise<Result<ConnectionEntity, ApiProblem>>;

  removeEntity(
    tenantId: string,
    connectionId: string,
    streamName: string,
  ): Promise<Result<void, ApiProblem>>;

  resetCheckpoint(
    tenantId: string,
    connectionId: string,
    streamName: string,
  ): Promise<Result<ConnectionEntity, ApiProblem>>;
}
