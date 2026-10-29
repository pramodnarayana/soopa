import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import type {
  BindStreamTransformationInput,
  PreviewStreamTransformationInput,
  RegisteredTransformer,
  Transformation,
} from '../domain/transformation';
import { useIpWorkspace } from '../provider/IpRepositoriesContext';
import { logResultOutcome } from './mutation-telemetry';
import { ipQueryKeys } from './query-keys';
import { type IpQueryView, projectResultQuery } from './result-query-state';

export function useRegisteredTransformersQuery(): IpQueryView<readonly RegisteredTransformer[]> {
  const { tenantId, repositories } = useIpWorkspace();
  const query = useQuery({
    queryKey: ipQueryKeys.transformations.transformers(tenantId),
    queryFn: ({ signal }) =>
      repositories.transformations.listRegisteredTransformers(tenantId, signal),
    enabled: Boolean(tenantId),
    staleTime: 60_000,
  });
  return projectResultQuery(query);
}

export function useConnectionTransformationsQuery(
  connectionId: string | null,
): IpQueryView<readonly Transformation[]> {
  const { tenantId, repositories } = useIpWorkspace();
  const query = useQuery({
    queryKey: ipQueryKeys.transformations.byConnection(tenantId, connectionId ?? ''),
    queryFn: ({ signal }) =>
      repositories.transformations.listConnectionTransformations(
        tenantId,
        connectionId ?? '',
        signal,
      ),
    enabled: Boolean(tenantId && connectionId),
  });
  return projectResultQuery(query);
}

export function useBindStreamTransformationMutation() {
  const { tenantId, repositories, logger } = useIpWorkspace();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (params: {
      connectionId: string;
      stream: string;
      input: BindStreamTransformationInput;
    }) =>
      repositories.transformations.bindStreamTransformation(
        tenantId,
        params.connectionId,
        params.stream,
        params.input,
      ),
    onSuccess: (res, variables) => {
      logResultOutcome(logger, 'ip_transformation.bind', res, {
        connection_id: variables.connectionId,
        stream: variables.stream,
        mode: variables.input.mode,
      });
      if (res.ok) {
        void queryClient.invalidateQueries({
          queryKey: ipQueryKeys.transformations.byConnection(tenantId, variables.connectionId),
        });
      }
    },
  });
}

export function usePromoteShadowTransformationMutation() {
  const { tenantId, repositories, logger } = useIpWorkspace();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (params: { connectionId: string; stream: string }) =>
      repositories.transformations.promoteShadowVersion(
        tenantId,
        params.connectionId,
        params.stream,
      ),
    onSuccess: (res, variables) => {
      logResultOutcome(logger, 'ip_transformation.promote_shadow', res, {
        connection_id: variables.connectionId,
        stream: variables.stream,
      });
      if (res.ok) {
        void queryClient.invalidateQueries({
          queryKey: ipQueryKeys.transformations.byConnection(tenantId, variables.connectionId),
        });
      }
    },
  });
}

export function usePreviewTransformationMutation() {
  const { tenantId, repositories, logger } = useIpWorkspace();
  return useMutation({
    mutationFn: (input: PreviewStreamTransformationInput) =>
      repositories.transformations.previewTransformation(tenantId, input),
    onSuccess: (res, variables) => {
      logResultOutcome(logger, 'ip_transformation.preview', res, {
        connection_id: variables.connectionId,
        stream: variables.stream,
      });
    },
  });
}
