import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useMemo, useRef } from 'react';
import {
  FetchHttpClientAdapter,
  type HttpClientPort,
  type PlatformResultQueryView,
  projectPlatformResultQuery,
  recordPlatformMutationOutcome,
} from '../../../network';
import { type FrontendLoggerPort, StructuredJsonLoggerAdapter } from '../../../observability';
import type { ApiToken, CreateApiTokenPayload } from '../types';
import { type ApiTokenRepositoryPort, HttpApiTokenRepository } from './apiTokenRepository';

export type { ApiTokenRepositoryPort };
export { HttpApiTokenRepository };

export interface ApiTokenHookConfig {
  readonly baseUrl: string;
  readonly tenantId: string;
  readonly token: string;
  readonly httpClient?: HttpClientPort;
  readonly logger?: FrontendLoggerPort;
}

export const apiTokenKeys = {
  all: (tenantId: string) => ['platform', 'api-tokens', tenantId] as const,
};

function useApiTokenWiring({ baseUrl, tenantId, token, httpClient, logger }: ApiTokenHookConfig): {
  readonly repo: ApiTokenRepositoryPort;
  readonly logger: FrontendLoggerPort;
} {
  const tokenRef = useRef(token);
  tokenRef.current = token;

  return useMemo(() => {
    const resolvedLogger = (logger ?? new StructuredJsonLoggerAdapter()).bind({
      feature: 'api_tokens',
      tenant_id: tenantId,
    });
    const resolvedClient =
      httpClient ??
      new FetchHttpClientAdapter({
        baseUrl,
        getToken: () => tokenRef.current,
        logger: resolvedLogger,
      });
    return {
      repo: new HttpApiTokenRepository(resolvedClient, tenantId),
      logger: resolvedLogger,
    };
  }, [baseUrl, httpClient, logger, tenantId]);
}

export function useApiTokensQuery(config: ApiTokenHookConfig): PlatformResultQueryView<ApiToken[]> {
  const { repo } = useApiTokenWiring(config);
  const query = useQuery({
    queryKey: apiTokenKeys.all(config.tenantId),
    queryFn: ({ signal }) => repo.getAll(signal),
    enabled: Boolean(config.token && config.tenantId),
  });
  return projectPlatformResultQuery(query);
}

export function useCreateApiTokenMutation(config: ApiTokenHookConfig) {
  const { repo, logger } = useApiTokenWiring(config);
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: CreateApiTokenPayload) => repo.create(payload),
    onSuccess: (result) => {
      if (recordPlatformMutationOutcome(logger, 'api_token.create', result)) {
        void queryClient.invalidateQueries({ queryKey: apiTokenKeys.all(config.tenantId) });
      }
    },
  });
}

export function useUpdateApiTokenMutation(config: ApiTokenHookConfig) {
  const { repo, logger } = useApiTokenWiring(config);
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({
      id,
      data,
    }: {
      readonly id: string;
      readonly data: { readonly name?: string; readonly active?: boolean };
    }) => repo.update(id, data),
    onSuccess: (result, variables) => {
      if (
        recordPlatformMutationOutcome(logger, 'api_token.update', result, {
          token_id: variables.id,
        })
      ) {
        void queryClient.invalidateQueries({ queryKey: apiTokenKeys.all(config.tenantId) });
      }
    },
  });
}

export function useDeleteApiTokenMutation(config: ApiTokenHookConfig) {
  const { repo, logger } = useApiTokenWiring(config);
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => repo.delete(id),
    onSuccess: (result, id) => {
      if (recordPlatformMutationOutcome(logger, 'api_token.delete', result, { token_id: id })) {
        void queryClient.invalidateQueries({ queryKey: apiTokenKeys.all(config.tenantId) });
      }
    },
  });
}
