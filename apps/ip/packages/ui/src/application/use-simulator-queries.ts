import { type ApiProblem, ok, type Result } from '@soopa/ui';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import type { DiscoveredCatalog } from '../domain/connection';
import type {
  CreateSimulatorEntityInput,
  SimulatePushInput,
  SimulatorEntity,
  UpdateSimulatorEntityInput,
} from '../domain/simulator';
import { useIpWorkspace } from '../provider/IpRepositoriesContext';
import { logResultOutcome } from './mutation-telemetry';
import { ipQueryKeys } from './query-keys';
import { type IpQueryView, projectResultQuery } from './result-query-state';

export function useSimulatorEntitiesQuery(
  connectionId: string | null | undefined,
  enabled: boolean = true,
): IpQueryView<readonly SimulatorEntity[]> {
  const { tenantId, repositories } = useIpWorkspace();
  const resolvedConnectionId = connectionId?.trim() ?? '';
  const query = useQuery({
    queryKey: ipQueryKeys.simulator.entities(tenantId, resolvedConnectionId),
    queryFn: ({ signal }) =>
      repositories.simulator.listEntities(tenantId, resolvedConnectionId, signal),
    enabled: Boolean(tenantId && resolvedConnectionId && enabled),
  });
  return projectResultQuery(query);
}

export function useCreateSimulatorEntityMutation(connectionId: string | null | undefined) {
  const { tenantId, repositories, logger } = useIpWorkspace();
  const queryClient = useQueryClient();
  const resolvedConnectionId = connectionId?.trim() ?? '';
  return useMutation({
    mutationFn: (input: CreateSimulatorEntityInput) =>
      repositories.simulator.createEntity(tenantId, resolvedConnectionId, input),
    onSuccess: (res, variables) => {
      logResultOutcome(logger, 'ip_simulator.create_entity', res, {
        connection_id: resolvedConnectionId,
        entity_name: variables.entityName,
      });
      if (res.ok && resolvedConnectionId) {
        queryClient.setQueryData<Result<readonly SimulatorEntity[], ApiProblem>>(
          ipQueryKeys.simulator.entities(tenantId, resolvedConnectionId),
          (previous) => {
            const existing = previous?.ok ? previous.value : [];
            const filtered = existing.filter((item) => item.id !== res.value.id);
            return ok([...filtered, res.value]);
          },
        );
        void queryClient.invalidateQueries({
          queryKey: ipQueryKeys.simulator.entities(tenantId, resolvedConnectionId),
        });
        void queryClient.invalidateQueries({
          queryKey: ipQueryKeys.connections.discoveredStreams(tenantId, resolvedConnectionId),
        });
      }
    },
  });
}

export function useUpdateSimulatorEntityMutation(connectionId: string | null | undefined) {
  const { tenantId, repositories, logger } = useIpWorkspace();
  const queryClient = useQueryClient();
  const resolvedConnectionId = connectionId?.trim() ?? '';
  return useMutation({
    mutationFn: ({
      entityId,
      input,
    }: {
      readonly entityId: string;
      readonly input: UpdateSimulatorEntityInput;
    }) => repositories.simulator.updateEntity(tenantId, resolvedConnectionId, entityId, input),
    onSuccess: (res, variables) => {
      logResultOutcome(logger, 'ip_simulator.update_entity', res, {
        connection_id: resolvedConnectionId,
        entity_id: variables.entityId,
      });
      if (res.ok && resolvedConnectionId) {
        queryClient.setQueryData<Result<readonly SimulatorEntity[], ApiProblem>>(
          ipQueryKeys.simulator.entities(tenantId, resolvedConnectionId),
          (previous) => {
            if (!previous?.ok) return ok([res.value]);
            return ok(previous.value.map((item) => (item.id === res.value.id ? res.value : item)));
          },
        );
        void queryClient.invalidateQueries({
          queryKey: ipQueryKeys.simulator.entities(tenantId, resolvedConnectionId),
        });
        void queryClient.invalidateQueries({
          queryKey: ipQueryKeys.connections.discoveredStreams(tenantId, resolvedConnectionId),
        });
      }
    },
  });
}

export function useDeleteSimulatorEntityMutation(connectionId: string | null | undefined) {
  const { tenantId, repositories, logger } = useIpWorkspace();
  const queryClient = useQueryClient();
  const resolvedConnectionId = connectionId?.trim() ?? '';
  return useMutation({
    mutationFn: (entityId: string) =>
      repositories.simulator.deleteEntity(tenantId, resolvedConnectionId, entityId),
    onSuccess: (res, entityId) => {
      logResultOutcome(logger, 'ip_simulator.delete_entity', res, {
        connection_id: resolvedConnectionId,
        entity_id: entityId,
      });
      if (res.ok && resolvedConnectionId) {
        let deletedEntityName: string | undefined;
        queryClient.setQueryData<Result<readonly SimulatorEntity[], ApiProblem>>(
          ipQueryKeys.simulator.entities(tenantId, resolvedConnectionId),
          (previous) => {
            if (!previous?.ok) return previous;
            deletedEntityName = previous.value.find((item) => item.id === entityId)?.entityName;
            return ok(previous.value.filter((item) => item.id !== entityId));
          },
        );
        if (deletedEntityName) {
          queryClient.setQueryData<Result<DiscoveredCatalog, ApiProblem>>(
            ipQueryKeys.connections.discoveredStreams(tenantId, resolvedConnectionId),
            (previous) => {
              if (!previous?.ok) return previous;
              return ok({
                ...previous.value,
                streams: previous.value.streams.filter((s) => s.name !== deletedEntityName),
              });
            },
          );
        }
        void queryClient.invalidateQueries({
          queryKey: ipQueryKeys.simulator.entities(tenantId, resolvedConnectionId),
        });
        void queryClient.invalidateQueries({
          queryKey: ipQueryKeys.connections.discoveredStreams(tenantId, resolvedConnectionId),
        });
      }
    },
  });
}

export function useSimulatePushMutation(connectionId: string) {
  const { tenantId, repositories, logger } = useIpWorkspace();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input: SimulatePushInput) =>
      repositories.simulator.simulatePush(tenantId, connectionId, input),
    onSuccess: (res, variables) => {
      logResultOutcome(logger, 'ip_simulator.simulate_push', res, {
        connection_id: connectionId,
        stream_name: variables.streamName,
        count: variables.count ?? 1,
      });
      if (res.ok) {
        const invalidate = () => {
          void queryClient.invalidateQueries({
            queryKey: ipQueryKeys.traces.all(tenantId),
          });
          void queryClient.invalidateQueries({
            queryKey: ipQueryKeys.records.all(tenantId),
          });
        };
        invalidate();
        setTimeout(invalidate, 500);
        setTimeout(invalidate, 1500);
      }
    },
  });
}
