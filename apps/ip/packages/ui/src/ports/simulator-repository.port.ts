import type { ApiProblem, Result } from '@soopa/ui';
import type {
  CreateSimulatorEntityInput,
  SimulatePushInput,
  SimulatePushResult,
  SimulatorEntity,
  UpdateSimulatorEntityInput,
} from '../domain/simulator';

export interface SimulatorRepositoryPort {
  listEntities(
    tenantId: string,
    connectionId: string,
    signal?: AbortSignal,
  ): Promise<Result<readonly SimulatorEntity[], ApiProblem>>;

  createEntity(
    tenantId: string,
    connectionId: string,
    input: CreateSimulatorEntityInput,
  ): Promise<Result<SimulatorEntity, ApiProblem>>;

  updateEntity(
    tenantId: string,
    connectionId: string,
    entityId: string,
    input: UpdateSimulatorEntityInput,
  ): Promise<Result<SimulatorEntity, ApiProblem>>;

  deleteEntity(
    tenantId: string,
    connectionId: string,
    entityId: string,
  ): Promise<Result<void, ApiProblem>>;

  simulatePush(
    tenantId: string,
    connectionId: string,
    input: SimulatePushInput,
  ): Promise<Result<SimulatePushResult, ApiProblem>>;
}
