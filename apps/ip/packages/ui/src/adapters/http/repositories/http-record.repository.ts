import type { ApiProblem, FrontendLoggerPort, HttpClientPort, Result } from '@soopa/ui';
import type {
  GlobalEntityMapEntry,
  InboundRecord,
  NormalizedRecord,
  ReplicaRecord,
} from '../../../domain/trace';
import type {
  ListGemRecordsFilter,
  ListInboundRecordsFilter,
  ListNormalizedRecordsFilter,
  ListReplicaRecordsFilter,
  RecordRepositoryPort,
} from '../../../ports/record-repository.port';
import {
  mapGlobalEntityMapFromWire,
  mapInboundFromWire,
  mapNormalizedFromWire,
  mapReplicaFromWire,
} from '../mappers/trace.mapper';
import { parseAndMapResult } from '../parse-wire';
import {
  GlobalEntityMapListWireSchema,
  InboundRecordListWireSchema,
  NormalizedRecordListWireSchema,
  ReplicaRecordListWireSchema,
} from '../schemas/trace.schema';

export class HttpRecordRepository implements RecordRepositoryPort {
  private readonly httpClient: HttpClientPort;
  private readonly logger?: FrontendLoggerPort;

  constructor(httpClient: HttpClientPort, logger?: FrontendLoggerPort) {
    this.httpClient = httpClient;
    this.logger = logger;
  }

  public async listNormalizedRecords(
    tenantId: string,
    filter?: ListNormalizedRecordsFilter,
    signal?: AbortSignal,
  ): Promise<Result<readonly NormalizedRecord[], ApiProblem>> {
    const raw = await this.httpClient.get<unknown>(
      `/api/v1/tenants/${encodeURIComponent(tenantId)}/ip/records/normalized`,
      {
        params: {
          connection_id: filter?.connectionId,
          canonical_type: filter?.canonicalType,
          limit: filter?.limit ?? 50,
          offset: filter?.offset ?? 0,
        },
        signal,
      },
    );
    return parseAndMapResult(
      raw,
      NormalizedRecordListWireSchema,
      (items) => items.map(mapNormalizedFromWire),
      'GET /ip/records/normalized',
      this.logger,
    );
  }

  public async listGemRecords(
    tenantId: string,
    filter?: ListGemRecordsFilter,
    signal?: AbortSignal,
  ): Promise<Result<readonly GlobalEntityMapEntry[], ApiProblem>> {
    const raw = await this.httpClient.get<unknown>(
      `/api/v1/tenants/${encodeURIComponent(tenantId)}/ip/records/gem`,
      {
        params: {
          source_connection_id: filter?.sourceConnectionId,
          entity_domain: filter?.entityDomain,
          limit: filter?.limit ?? 50,
          offset: filter?.offset ?? 0,
        },
        signal,
      },
    );
    return parseAndMapResult(
      raw,
      GlobalEntityMapListWireSchema,
      (items) => items.map(mapGlobalEntityMapFromWire),
      'GET /ip/records/gem',
      this.logger,
    );
  }

  public async listReplicaRecords(
    tenantId: string,
    filter?: ListReplicaRecordsFilter,
    signal?: AbortSignal,
  ): Promise<Result<readonly ReplicaRecord[], ApiProblem>> {
    const raw = await this.httpClient.get<unknown>(
      `/api/v1/tenants/${encodeURIComponent(tenantId)}/ip/records/replica`,
      {
        params: {
          connection_id: filter?.connectionId,
          stream: filter?.stream,
          limit: filter?.limit ?? 50,
          offset: filter?.offset ?? 0,
        },
        signal,
      },
    );
    return parseAndMapResult(
      raw,
      ReplicaRecordListWireSchema,
      (items) => items.map(mapReplicaFromWire),
      'GET /ip/records/replica',
      this.logger,
    );
  }

  public async listInboundRecords(
    tenantId: string,
    filter?: ListInboundRecordsFilter,
    signal?: AbortSignal,
  ): Promise<Result<readonly InboundRecord[], ApiProblem>> {
    const raw = await this.httpClient.get<unknown>(
      `/api/v1/tenants/${encodeURIComponent(tenantId)}/ip/records/inbound`,
      {
        params: {
          connection_id: filter?.connectionId,
          stream_name: filter?.streamName,
          limit: filter?.limit ?? 50,
          offset: filter?.offset ?? 0,
          hydrate_payloads: filter?.hydratePayloads ?? false,
        },
        signal,
      },
    );
    return parseAndMapResult(
      raw,
      InboundRecordListWireSchema,
      (items) => items.map(mapInboundFromWire),
      'GET /ip/records/inbound',
      this.logger,
    );
  }
}
