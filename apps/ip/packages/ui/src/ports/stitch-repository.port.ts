import type { ApiProblem, Result } from '@soopa/ui';
import type {
  ListStitchRunsFilter,
  RegisterStitchInput,
  Stitch,
  StitchDefinition,
  StitchRun,
  TriggerStitchEventInput,
  TriggerStitchEventResult,
} from '../domain/stitch';

export interface StitchRepositoryPort {
  listDefinitions(
    tenantId: string,
    signal?: AbortSignal,
  ): Promise<Result<readonly StitchDefinition[], ApiProblem>>;

  getDefinition(
    tenantId: string,
    workflowId: string,
    version?: number,
    signal?: AbortSignal,
  ): Promise<Result<StitchDefinition, ApiProblem>>;

  listStitches(
    tenantId: string,
    signal?: AbortSignal,
  ): Promise<Result<readonly Stitch[], ApiProblem>>;

  registerStitch(tenantId: string, input: RegisterStitchInput): Promise<Result<Stitch, ApiProblem>>;

  dispatchEvent(
    tenantId: string,
    input: TriggerStitchEventInput,
  ): Promise<Result<TriggerStitchEventResult, ApiProblem>>;

  listRuns(
    tenantId: string,
    filter?: ListStitchRunsFilter,
    signal?: AbortSignal,
  ): Promise<Result<readonly StitchRun[], ApiProblem>>;

  getRun(
    tenantId: string,
    runId: string,
    signal?: AbortSignal,
  ): Promise<Result<StitchRun, ApiProblem>>;
}
