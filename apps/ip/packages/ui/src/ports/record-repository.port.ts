import type { ApiProblem, Result } from '@soopa/ui';
import type {
  GlobalEntityMapEntry,
  InboundRecord,
  NormalizedRecord,
  ReplicaRecord,
} from '../domain/trace';

export interface ListNormalizedRecordsFilter {
  readonly connectionId?: string;
  readonly canonicalType?: string;
  readonly limit?: number;
  readonly offset?: number;
}

export interface ListGemRecordsFilter {
  readonly sourceConnectionId?: string;
  readonly entityDomain?: string;
  readonly limit?: number;
  readonly offset?: number;
}

export interface ListReplicaRecordsFilter {
  readonly connectionId?: string;
  readonly stream?: string;
  readonly limit?: number;
  readonly offset?: number;
}

export interface ListInboundRecordsFilter {
  readonly connectionId?: string;
  readonly streamName?: string;
  readonly limit?: number;
  readonly offset?: number;
  readonly hydratePayloads?: boolean;
}

export interface RecordRepositoryPort {
  listNormalizedRecords(
    tenantId: string,
    filter?: ListNormalizedRecordsFilter,
    signal?: AbortSignal,
  ): Promise<Result<readonly NormalizedRecord[], ApiProblem>>;

  listGemRecords(
    tenantId: string,
    filter?: ListGemRecordsFilter,
    signal?: AbortSignal,
  ): Promise<Result<readonly GlobalEntityMapEntry[], ApiProblem>>;

  listReplicaRecords(
    tenantId: string,
    filter?: ListReplicaRecordsFilter,
    signal?: AbortSignal,
  ): Promise<Result<readonly ReplicaRecord[], ApiProblem>>;

  listInboundRecords(
    tenantId: string,
    filter?: ListInboundRecordsFilter,
    signal?: AbortSignal,
  ): Promise<Result<readonly InboundRecord[], ApiProblem>>;
}
