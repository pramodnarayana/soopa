import { type ApiProblem, ok, type Result } from '@soopa/ui';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import type {
  AddConnectionEntityInput,
  ConnectionEntity,
  UpdateConnectionEntityInput,
} from '../domain/connection-entity';
import { useIpWorkspace } from '../provider/IpRepositoriesContext';
import { logResultOutcome } from './mutation-telemetry';
import { ipQueryKeys } from './query-keys';
import { type IpQueryView, projectResultQuery } from './result-query-state';

export function useConnectionEntitiesQuery(
  connectionId: string,
  enabled: boolean = true,
): IpQueryView<readonly ConnectionEntity[]> {
  const { tenantId, repositories } = useIpWorkspace();
  const query = useQuery({
    queryKey: ipQueryKeys.connections.entities(tenantId, connectionId),
    queryFn: ({ signal }) => repositories.entities.listEntities(tenantId, connectionId, signal),
    enabled: Boolean(tenantId && connectionId && enabled),
  });
  return projectResultQuery(query);
}

export function useAddConnectionEntityMutation(connectionId: string) {
  const { tenantId, repositories, logger } = useIpWorkspace();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input: AddConnectionEntityInput) =>
      repositories.entities.addEntity(tenantId, connectionId, input),
    onSuccess: (res, variables) => {
      logResultOutcome(logger, 'ip_connection_entity.add', res, {
        connection_id: connectionId,
        stream_name: variables.streamName,
      });
      if (res.ok) {
        queryClient.setQueryData<Result<readonly ConnectionEntity[], ApiProblem>>(
          ipQueryKeys.connections.entities(tenantId, connectionId),
          (previous) => {
            const existing = previous?.ok ? previous.value : [];
            const filtered = existing.filter((item) => item.streamName !== res.value.streamName);
            return ok([...filtered, res.value]);
          },
        );
        void queryClient.invalidateQueries({
          queryKey: ipQueryKeys.connections.entities(tenantId, connectionId),
        });
        if (variables.defaultTransformationId) {
          void queryClient.invalidateQueries({
            queryKey: ipQueryKeys.transformations.byConnection(tenantId, connectionId),
          });
        }
      }
    },
  });
}

export function useUpdateConnectionEntityMutation(connectionId: string) {
  const { tenantId, repositories, logger } = useIpWorkspace();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({
      streamName,
      input,
    }: {
      readonly streamName: string;
      readonly input: UpdateConnectionEntityInput;
    }) => repositories.entities.updateEntity(tenantId, connectionId, streamName, input),
    onSuccess: (res, variables) => {
      logResultOutcome(logger, 'ip_connection_entity.update', res, {
        connection_id: connectionId,
        stream_name: variables.streamName,
      });
      if (res.ok) {
        queryClient.setQueryData<Result<readonly ConnectionEntity[], ApiProblem>>(
          ipQueryKeys.connections.entities(tenantId, connectionId),
          (previous) => {
            if (!previous?.ok) return ok([res.value]);
            return ok(
              previous.value.map((item) =>
                item.streamName === res.value.streamName ? res.value : item,
              ),
            );
          },
        );
        void queryClient.invalidateQueries({
          queryKey: ipQueryKeys.connections.entities(tenantId, connectionId),
        });
      }
    },
  });
}

export function useRemoveConnectionEntityMutation(connectionId: string) {
  const { tenantId, repositories, logger } = useIpWorkspace();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (streamName: string) =>
      repositories.entities.removeEntity(tenantId, connectionId, streamName),
    onSuccess: (res, streamName) => {
      logResultOutcome(logger, 'ip_connection_entity.remove', res, {
        connection_id: connectionId,
        stream_name: streamName,
      });
      if (res.ok) {
        queryClient.setQueryData<Result<readonly ConnectionEntity[], ApiProblem>>(
          ipQueryKeys.connections.entities(tenantId, connectionId),
          (previous) => {
            if (!previous?.ok) return previous;
            return ok(previous.value.filter((item) => item.streamName !== streamName));
          },
        );
        void queryClient.invalidateQueries({
          queryKey: ipQueryKeys.connections.entities(tenantId, connectionId),
        });
      }
    },
  });
}

export function useResetConnectionEntityCheckpointMutation(connectionId: string) {
  const { tenantId, repositories, logger } = useIpWorkspace();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (streamName: string) =>
      repositories.entities.resetCheckpoint(tenantId, connectionId, streamName),
    onSuccess: (res, streamName) => {
      logResultOutcome(logger, 'ip_connection_entity.reset_checkpoint', res, {
        connection_id: connectionId,
        stream_name: streamName,
      });
      if (res.ok) {
        queryClient.setQueryData<Result<readonly ConnectionEntity[], ApiProblem>>(
          ipQueryKeys.connections.entities(tenantId, connectionId),
          (previous) => {
            if (!previous?.ok) return ok([res.value]);
            return ok(
              previous.value.map((item) =>
                item.streamName === res.value.streamName ? res.value : item,
              ),
            );
          },
        );
        void queryClient.invalidateQueries({
          queryKey: ipQueryKeys.connections.entities(tenantId, connectionId),
        });
      }
    },
  });
}
