import type { ApiProblem, Result } from '@soopa/ui';
import type {
  CreatedSimulatorSandbox,
  CreateSimulatorEntityInput,
  CreateSimulatorSandboxInput,
  SimulatorEntity,
  SimulatorSandbox,
  UpdateSimulatorEntityInput,
} from '../domain/simulator';

export interface SimulatorRepositoryPort {
  createSandbox(
    tenantId: string,
    input: CreateSimulatorSandboxInput,
  ): Promise<Result<CreatedSimulatorSandbox, ApiProblem>>;

  listSandboxes(
    tenantId: string,
    signal?: AbortSignal,
  ): Promise<Result<readonly SimulatorSandbox[], ApiProblem>>;

  getSandbox(
    tenantId: string,
    sandboxId: string,
    signal?: AbortSignal,
  ): Promise<Result<SimulatorSandbox, ApiProblem>>;

  deleteSandbox(tenantId: string, sandboxId: string): Promise<Result<void, ApiProblem>>;

  listEntities(
    tenantId: string,
    sandboxId: string,
    signal?: AbortSignal,
  ): Promise<Result<readonly SimulatorEntity[], ApiProblem>>;

  createEntity(
    tenantId: string,
    sandboxId: string,
    input: CreateSimulatorEntityInput,
  ): Promise<Result<SimulatorEntity, ApiProblem>>;

  updateEntity(
    tenantId: string,
    sandboxId: string,
    entityId: string,
    input: UpdateSimulatorEntityInput,
  ): Promise<Result<SimulatorEntity, ApiProblem>>;

  deleteEntity(
    tenantId: string,
    sandboxId: string,
    entityId: string,
  ): Promise<Result<void, ApiProblem>>;
}
