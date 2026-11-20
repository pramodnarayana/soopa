import { type ApiProblem, ok, type Result } from '@soopa/ui';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import type {
  ListMappingSpecsFilter,
  MappingSpec,
  SaveMappingSpecInput,
} from '../domain/mapping-spec';
import { useIpWorkspace } from '../provider/IpRepositoriesContext';
import { logResultOutcome } from './mutation-telemetry';
import { ipQueryKeys } from './query-keys';
import { type IpQueryView, projectResultQuery } from './result-query-state';

export function useMappingSpecsQuery(
  filter?: ListMappingSpecsFilter,
): IpQueryView<readonly MappingSpec[]> {
  const { tenantId, repositories } = useIpWorkspace();
  const query = useQuery({
    queryKey: ipQueryKeys.mappingSpecs.list(tenantId, filter),
    queryFn: ({ signal }) => repositories.mappingSpecs.listMappingSpecs(tenantId, filter, signal),
    enabled: Boolean(tenantId),
  });
  return projectResultQuery(query);
}

export function useMappingSpecQuery(
  mappingSpecId: string,
  enabled: boolean = true,
): IpQueryView<MappingSpec> {
  const { tenantId, repositories } = useIpWorkspace();
  const query = useQuery({
    queryKey: ipQueryKeys.mappingSpecs.detail(tenantId, mappingSpecId),
    queryFn: ({ signal }) =>
      repositories.mappingSpecs.getMappingSpec(tenantId, mappingSpecId, signal),
    enabled: Boolean(tenantId && mappingSpecId && enabled),
  });
  return projectResultQuery(query);
}

export function useSaveMappingSpecMutation() {
  const { tenantId, repositories, logger } = useIpWorkspace();
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (input: SaveMappingSpecInput) =>
      repositories.mappingSpecs.saveMappingSpec(tenantId, input),
    onSuccess: (res, variables) => {
      logResultOutcome(logger, 'ip_mapping_spec.save', res, {
        name: variables.name,
        target_connection_id: variables.targetConnectionId,
        target_entity_name: variables.targetEntityName,
      });

      if (res.ok) {
        queryClient.setQueryData<Result<MappingSpec, ApiProblem>>(
          ipQueryKeys.mappingSpecs.detail(tenantId, res.value.id),
          ok(res.value),
        );
        void queryClient.invalidateQueries({
          queryKey: ['ip', 'tenant', tenantId, 'mapping-specs'],
        });
      }
    },
  });
}
