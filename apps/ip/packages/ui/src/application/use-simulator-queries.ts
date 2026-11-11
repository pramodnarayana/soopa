import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import type {
  CreateSimulatorEntityInput,
  CreateSimulatorSandboxInput,
  SimulatorEntity,
  SimulatorSandbox,
  UpdateSimulatorEntityInput,
} from '../domain/simulator';
import { useIpWorkspace } from '../provider/IpRepositoriesContext';
import { logResultOutcome } from './mutation-telemetry';
import { ipQueryKeys } from './query-keys';
import { type IpQueryView, projectResultQuery } from './result-query-state';

export function useSimulatorSandboxesQuery(
  enabled: boolean = true,
): IpQueryView<readonly SimulatorSandbox[]> {
  const { tenantId, repositories } = useIpWorkspace();
  const query = useQuery({
    queryKey: ipQueryKeys.simulator.sandboxes(tenantId),
    queryFn: ({ signal }) => repositories.simulator.listSandboxes(tenantId, signal),
    enabled: Boolean(tenantId && enabled),
  });
  return projectResultQuery(query);
}

export function useSimulatorSandboxQuery(
  sandboxId: string | null | undefined,
): IpQueryView<SimulatorSandbox> {
  const { tenantId, repositories } = useIpWorkspace();
  const resolvedSandboxId = sandboxId?.trim() ?? '';
  const query = useQuery({
    queryKey: ipQueryKeys.simulator.sandboxDetail(tenantId, resolvedSandboxId),
    queryFn: ({ signal }) => repositories.simulator.getSandbox(tenantId, resolvedSandboxId, signal),
    enabled: Boolean(tenantId && resolvedSandboxId),
  });
  return projectResultQuery(query);
}

export function useSimulatorEntitiesQuery(
  sandboxId: string | null | undefined,
): IpQueryView<readonly SimulatorEntity[]> {
  const { tenantId, repositories } = useIpWorkspace();
  const resolvedSandboxId = sandboxId?.trim() ?? '';
  const query = useQuery({
    queryKey: ipQueryKeys.simulator.entities(tenantId, resolvedSandboxId),
    queryFn: ({ signal }) =>
      repositories.simulator.listEntities(tenantId, resolvedSandboxId, signal),
    enabled: Boolean(tenantId && resolvedSandboxId),
  });
  return projectResultQuery(query);
}

export function useCreateSimulatorSandboxMutation() {
  const { tenantId, repositories, logger } = useIpWorkspace();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input: CreateSimulatorSandboxInput) =>
      repositories.simulator.createSandbox(tenantId, input),
    onSuccess: (res, variables) => {
      logResultOutcome(logger, 'ip_simulator.create_sandbox', res, {
        sandbox_name: variables.name,
      });
      if (res.ok) {
        void queryClient.invalidateQueries({
          queryKey: ipQueryKeys.simulator.sandboxes(tenantId),
        });
      }
    },
  });
}

export function useDeleteSimulatorSandboxMutation() {
  const { tenantId, repositories, logger } = useIpWorkspace();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (sandboxId: string) => repositories.simulator.deleteSandbox(tenantId, sandboxId),
    onSuccess: (res, sandboxId) => {
      logResultOutcome(logger, 'ip_simulator.delete_sandbox', res, {
        sandbox_id: sandboxId,
      });
      if (res.ok) {
        void queryClient.invalidateQueries({
          queryKey: ipQueryKeys.simulator.all(tenantId),
        });
      }
    },
  });
}

export function useCreateSimulatorEntityMutation(sandboxId: string) {
  const { tenantId, repositories, logger } = useIpWorkspace();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input: CreateSimulatorEntityInput) =>
      repositories.simulator.createEntity(tenantId, sandboxId, input),
    onSuccess: (res, variables) => {
      logResultOutcome(logger, 'ip_simulator.create_entity', res, {
        sandbox_id: sandboxId,
        entity_name: variables.entityName,
      });
      if (res.ok) {
        void queryClient.invalidateQueries({
          queryKey: ipQueryKeys.simulator.entities(tenantId, sandboxId),
        });
      }
    },
  });
}

export function useUpdateSimulatorEntityMutation(sandboxId: string) {
  const { tenantId, repositories, logger } = useIpWorkspace();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({
      entityId,
      input,
    }: {
      readonly entityId: string;
      readonly input: UpdateSimulatorEntityInput;
    }) => repositories.simulator.updateEntity(tenantId, sandboxId, entityId, input),
    onSuccess: (res, variables) => {
      logResultOutcome(logger, 'ip_simulator.update_entity', res, {
        sandbox_id: sandboxId,
        entity_id: variables.entityId,
      });
      if (res.ok) {
        void queryClient.invalidateQueries({
          queryKey: ipQueryKeys.simulator.entities(tenantId, sandboxId),
        });
      }
    },
  });
}

export function useDeleteSimulatorEntityMutation(sandboxId: string) {
  const { tenantId, repositories, logger } = useIpWorkspace();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (entityId: string) =>
      repositories.simulator.deleteEntity(tenantId, sandboxId, entityId),
    onSuccess: (res, entityId) => {
      logResultOutcome(logger, 'ip_simulator.delete_entity', res, {
        sandbox_id: sandboxId,
        entity_id: entityId,
      });
      if (res.ok) {
        void queryClient.invalidateQueries({
          queryKey: ipQueryKeys.simulator.entities(tenantId, sandboxId),
        });
      }
    },
  });
}
