import { useQuery } from '@tanstack/react-query';
import type {
  GlobalEntityMapEntry,
  InboundRecord,
  NormalizedRecord,
  ReplicaRecord,
} from '../domain/trace';
import type {
  ListGemRecordsFilter,
  ListInboundRecordsFilter,
  ListNormalizedRecordsFilter,
  ListReplicaRecordsFilter,
} from '../ports/record-repository.port';
import { useIpWorkspace } from '../provider/IpRepositoriesContext';
import { ipQueryKeys } from './query-keys';
import { type IpQueryView, projectResultQuery } from './result-query-state';

export function useNormalizedRecordsQuery(
  filter?: ListNormalizedRecordsFilter,
  enabled = true,
): IpQueryView<readonly NormalizedRecord[]> {
  const { tenantId, repositories } = useIpWorkspace();
  const query = useQuery({
    queryKey: ipQueryKeys.records.normalized(tenantId, filter),
    queryFn: ({ signal }) => repositories.records.listNormalizedRecords(tenantId, filter, signal),
    enabled: Boolean(tenantId) && enabled,
  });
  return projectResultQuery(query);
}

export function useGemRecordsQuery(
  filter?: ListGemRecordsFilter,
  enabled = true,
): IpQueryView<readonly GlobalEntityMapEntry[]> {
  const { tenantId, repositories } = useIpWorkspace();
  const query = useQuery({
    queryKey: ipQueryKeys.records.gem(tenantId, filter),
    queryFn: ({ signal }) => repositories.records.listGemRecords(tenantId, filter, signal),
    enabled: Boolean(tenantId) && enabled,
  });
  return projectResultQuery(query);
}

export function useReplicaRecordsQuery(
  filter?: ListReplicaRecordsFilter,
  enabled = true,
): IpQueryView<readonly ReplicaRecord[]> {
  const { tenantId, repositories } = useIpWorkspace();
  const query = useQuery({
    queryKey: ipQueryKeys.records.replica(tenantId, filter),
    queryFn: ({ signal }) => repositories.records.listReplicaRecords(tenantId, filter, signal),
    enabled: Boolean(tenantId) && enabled,
  });
  return projectResultQuery(query);
}

export function useInboundRecordsQuery(
  filter?: ListInboundRecordsFilter,
  enabled = true,
): IpQueryView<readonly InboundRecord[]> {
  const { tenantId, repositories } = useIpWorkspace();
  const query = useQuery({
    queryKey: ipQueryKeys.records.inbound(tenantId, filter),
    queryFn: ({ signal }) => repositories.records.listInboundRecords(tenantId, filter, signal),
    enabled: Boolean(tenantId) && enabled,
  });
  return projectResultQuery(query);
}
