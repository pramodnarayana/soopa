import type { ApiProblem, FrontendLoggerPort, HttpClientPort, Result } from '@soopa/ui';
import type {
  BindStreamTransformationInput,
  PreviewStreamTransformationInput,
  PromoteTransformationResult,
  RegisteredTransformer,
  Transformation,
  TransformationPreviewResult,
} from '../../../domain/transformation';
import type { TransformationRepositoryPort } from '../../../ports/transformation-repository.port';
import {
  mapBindStreamTransformationToWire,
  mapPreviewTransformationFromWire,
  mapPreviewTransformationToWire,
  mapPromoteTransformationFromWire,
  mapRegisteredTransformerFromWire,
  mapTransformationFromWire,
} from '../mappers/transformation.mapper';
import { parseAndMapResult } from '../parse-wire';
import {
  PreviewTransformationWireSchema,
  PromoteTransformationWireSchema,
  RegisteredTransformerListWireSchema,
  TransformationListWireSchema,
  TransformationWireSchema,
} from '../schemas/transformation.schema';

export class HttpTransformationRepository implements TransformationRepositoryPort {
  private readonly httpClient: HttpClientPort;
  private readonly logger?: FrontendLoggerPort;

  constructor(httpClient: HttpClientPort, logger?: FrontendLoggerPort) {
    this.httpClient = httpClient;
    this.logger = logger;
  }

  public async listRegisteredTransformers(
    tenantId: string,
    signal?: AbortSignal,
  ): Promise<Result<readonly RegisteredTransformer[], ApiProblem>> {
    const raw = await this.httpClient.get<unknown>(
      `/api/v1/tenants/${encodeURIComponent(tenantId)}/ip/transformations/transformers`,
      { signal },
    );
    return parseAndMapResult(
      raw,
      RegisteredTransformerListWireSchema,
      (items) => items.map(mapRegisteredTransformerFromWire),
      'GET /ip/transformations/transformers',
      this.logger,
    );
  }

  public async listConnectionTransformations(
    tenantId: string,
    connectionId: string,
    signal?: AbortSignal,
  ): Promise<Result<readonly Transformation[], ApiProblem>> {
    const raw = await this.httpClient.get<unknown>(
      `/api/v1/tenants/${encodeURIComponent(tenantId)}/ip/transformations/connections/${encodeURIComponent(connectionId)}`,
      { signal },
    );
    return parseAndMapResult(
      raw,
      TransformationListWireSchema,
      (items) => items.map(mapTransformationFromWire),
      `GET /ip/transformations/connections/${connectionId}`,
      this.logger,
    );
  }

  public async getStreamTransformation(
    tenantId: string,
    connectionId: string,
    stream: string,
    signal?: AbortSignal,
  ): Promise<Result<Transformation, ApiProblem>> {
    const raw = await this.httpClient.get<unknown>(
      `/api/v1/tenants/${encodeURIComponent(tenantId)}/ip/transformations/connections/${encodeURIComponent(connectionId)}/streams/${encodeURIComponent(stream)}`,
      { signal },
    );
    return parseAndMapResult(
      raw,
      TransformationWireSchema,
      mapTransformationFromWire,
      `GET /ip/transformations/connections/${connectionId}/streams/${stream}`,
      this.logger,
    );
  }

  public async bindStreamTransformation(
    tenantId: string,
    connectionId: string,
    stream: string,
    input: BindStreamTransformationInput,
  ): Promise<Result<Transformation, ApiProblem>> {
    const raw = await this.httpClient.put<unknown>(
      `/api/v1/tenants/${encodeURIComponent(tenantId)}/ip/transformations/connections/${encodeURIComponent(connectionId)}/streams/${encodeURIComponent(stream)}`,
      mapBindStreamTransformationToWire(input),
    );
    return parseAndMapResult(
      raw,
      TransformationWireSchema,
      mapTransformationFromWire,
      `PUT /ip/transformations/connections/${connectionId}/streams/${stream}`,
      this.logger,
    );
  }

  public async promoteShadowVersion(
    tenantId: string,
    connectionId: string,
    stream: string,
  ): Promise<Result<PromoteTransformationResult, ApiProblem>> {
    const raw = await this.httpClient.post<unknown>(
      `/api/v1/tenants/${encodeURIComponent(tenantId)}/ip/transformations/connections/${encodeURIComponent(connectionId)}/streams/${encodeURIComponent(stream)}/promote`,
    );
    return parseAndMapResult(
      raw,
      PromoteTransformationWireSchema,
      mapPromoteTransformationFromWire,
      `POST /ip/transformations/connections/${connectionId}/streams/${stream}/promote`,
      this.logger,
    );
  }

  public async previewTransformation(
    tenantId: string,
    input: PreviewStreamTransformationInput,
  ): Promise<Result<TransformationPreviewResult, ApiProblem>> {
    const raw = await this.httpClient.post<unknown>(
      `/api/v1/tenants/${encodeURIComponent(tenantId)}/ip/transformations/preview`,
      mapPreviewTransformationToWire(input),
    );
    return parseAndMapResult(
      raw,
      PreviewTransformationWireSchema,
      mapPreviewTransformationFromWire,
      'POST /ip/transformations/preview',
      this.logger,
    );
  }
}
