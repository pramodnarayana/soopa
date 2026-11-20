import type { ApiProblem, Result } from '@soopa/ui';
import type {
  ListMappingSpecsFilter,
  MappingSpec,
  SaveMappingSpecInput,
} from '../domain/mapping-spec';

export interface MappingSpecRepositoryPort {
  saveMappingSpec(
    tenantId: string,
    input: SaveMappingSpecInput,
    signal?: AbortSignal,
  ): Promise<Result<MappingSpec, ApiProblem>>;

  getMappingSpec(
    tenantId: string,
    mappingSpecId: string,
    signal?: AbortSignal,
  ): Promise<Result<MappingSpec, ApiProblem>>;

  listMappingSpecs(
    tenantId: string,
    filter?: ListMappingSpecsFilter,
    signal?: AbortSignal,
  ): Promise<Result<readonly MappingSpec[], ApiProblem>>;

  deleteMappingSpec(tenantId: string, mappingSpecId: string): Promise<Result<void, ApiProblem>>;
}
