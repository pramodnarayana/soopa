import { ApiErrorCode, err } from '@soopa/ui';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import type {
  CheckConnectionInput,
  Connection,
  CreateConnectionInput,
  DiscoveredCatalog,
  RelinkConnectionInput,
  UpdateConnectionInput,
} from '../domain/connection';
import { useIpWorkspace } from '../provider/IpRepositoriesContext';
import { logResultOutcome } from './mutation-telemetry';
import { ipQueryKeys } from './query-keys';
import { type IpQueryView, projectResultQuery } from './result-query-state';

export function useConnectionsQuery(status?: string): IpQueryView<readonly Connection[]> {
  const { tenantId, repositories } = useIpWorkspace();
  const query = useQuery({
    queryKey: ipQueryKeys.connections.list(tenantId, status),
    queryFn: ({ signal }) => repositories.connections.listConnections(tenantId, status, signal),
    enabled: Boolean(tenantId),
  });
  return projectResultQuery(query);
}

export function useConnectionDetailQuery(connectionId: string): IpQueryView<Connection> {
  const { tenantId, repositories } = useIpWorkspace();
  const query = useQuery({
    queryKey: ipQueryKeys.connections.detail(tenantId, connectionId),
    queryFn: ({ signal }) => repositories.connections.getConnection(tenantId, connectionId, signal),
    enabled: Boolean(tenantId && connectionId),
  });
  return projectResultQuery(query);
}

export function useDiscoveredStreamsQuery(connectionId: string): IpQueryView<DiscoveredCatalog> {
  const { tenantId, repositories } = useIpWorkspace();
  const query = useQuery({
    queryKey: ipQueryKeys.connections.discoveredStreams(tenantId, connectionId),
    queryFn: () => repositories.connections.discoverCatalog(tenantId, connectionId),
    enabled: false,
    staleTime: Number.POSITIVE_INFINITY,
  });
  return projectResultQuery(query);
}

export function useCheckConnectionMutation() {
  const { tenantId, repositories, logger } = useIpWorkspace();
  return useMutation({
    mutationFn: (input: CheckConnectionInput) =>
      repositories.connections.checkConnection(tenantId, input),
    onSuccess: (res, variables) => {
      logResultOutcome(logger, 'ip_connection.preflight_check', res, {
        app_id: variables.appId,
        auth_type: variables.authType,
      });
    },
  });
}

export function useCreateConnectionMutation() {
  const { tenantId, repositories, logger } = useIpWorkspace();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input: CreateConnectionInput) =>
      repositories.connections.createConnection(tenantId, input),
    onSuccess: (res, variables) => {
      logResultOutcome(logger, 'ip_connection.create', res, {
        app_id: variables.appId,
        auth_type: variables.authType,
      });
      if (res.ok) {
        void queryClient.invalidateQueries({ queryKey: ipQueryKeys.connections.all(tenantId) });
      }
    },
  });
}

export function useDiscoverCatalogMutation(connectionId: string) {
  const { tenantId, repositories, logger } = useIpWorkspace();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => repositories.connections.discoverCatalog(tenantId, connectionId),
    onSuccess: (res) => {
      logResultOutcome(logger, 'ip_connection.discover_catalog', res, {
        connection_id: connectionId,
      });
      if (res.ok) {
        queryClient.setQueryData(
          ipQueryKeys.connections.discoveredStreams(tenantId, connectionId),
          res,
        );
      }
    },
  });
}

export function useUpdateConnectionMutation(connectionId: string) {
  const { tenantId, repositories, logger } = useIpWorkspace();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input: UpdateConnectionInput) =>
      repositories.connections.updateConnection(tenantId, connectionId, input),
    onSuccess: (res) => {
      logResultOutcome(logger, 'ip_connection.update', res, {
        connection_id: connectionId,
      });
      if (res.ok) {
        queryClient.setQueryData(ipQueryKeys.connections.detail(tenantId, connectionId), res);
        void queryClient.invalidateQueries({ queryKey: ipQueryKeys.connections.all(tenantId) });
        void queryClient.invalidateQueries({
          queryKey: ipQueryKeys.connections.detail(tenantId, connectionId),
        });
      }
    },
  });
}

export function useRelinkConnectionMutation(connectionId: string) {
  const { tenantId, repositories, logger } = useIpWorkspace();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input: RelinkConnectionInput) =>
      repositories.connections.relinkConnection(tenantId, connectionId, input),
    onSuccess: (res) => {
      logResultOutcome(logger, 'ip_connection.relink', res, {
        connection_id: connectionId,
      });
      if (res.ok) {
        queryClient.setQueryData(ipQueryKeys.connections.detail(tenantId, connectionId), res);
        void queryClient.invalidateQueries({ queryKey: ipQueryKeys.connections.all(tenantId) });
      }
    },
  });
}

export function useDeactivateConnectionMutation(connectionId: string) {
  const { tenantId, repositories, logger } = useIpWorkspace();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => repositories.connections.deactivateConnection(tenantId, connectionId),
    onSuccess: (res) => {
      logResultOutcome(logger, 'ip_connection.deactivate', res, {
        connection_id: connectionId,
      });
      if (res.ok) {
        void queryClient.invalidateQueries({ queryKey: ipQueryKeys.connections.all(tenantId) });
      }
    },
  });
}

export function useDeleteConnectionMutation(defaultConnectionId?: string) {
  const { tenantId, repositories, logger } = useIpWorkspace();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (targetId?: string) => {
      const id = targetId?.trim() || defaultConnectionId?.trim();
      if (!id) {
        return Promise.resolve(
          err({
            code: ApiErrorCode.VALIDATION_ERROR,
            status: 400,
            message: 'Connection ID is required to delete connection.',
          }),
        );
      }
      return repositories.connections.deleteConnection(tenantId, id);
    },
    onSuccess: (res, targetId) => {
      const id = targetId ?? defaultConnectionId;
      logResultOutcome(logger, 'ip_connection.delete', res, {
        connection_id: id,
      });
      if (res.ok) {
        void queryClient.invalidateQueries({ queryKey: ipQueryKeys.connections.all(tenantId) });
      }
    },
  });
}
