import type { ApiProblem, Result } from '@soopa/ui';
import type {
  BindStreamTransformationInput,
  PreviewStreamTransformationInput,
  PromoteTransformationResult,
  RegisteredTransformer,
  Transformation,
  TransformationPreviewResult,
} from '../domain/transformation';

export interface TransformationRepositoryPort {
  listRegisteredTransformers(
    tenantId: string,
    signal?: AbortSignal,
  ): Promise<Result<readonly RegisteredTransformer[], ApiProblem>>;

  listConnectionTransformations(
    tenantId: string,
    connectionId: string,
    signal?: AbortSignal,
  ): Promise<Result<readonly Transformation[], ApiProblem>>;

  getStreamTransformation(
    tenantId: string,
    connectionId: string,
    stream: string,
    signal?: AbortSignal,
  ): Promise<Result<Transformation, ApiProblem>>;

  bindStreamTransformation(
    tenantId: string,
    connectionId: string,
    stream: string,
    input: BindStreamTransformationInput,
  ): Promise<Result<Transformation, ApiProblem>>;

  promoteShadowVersion(
    tenantId: string,
    connectionId: string,
    stream: string,
  ): Promise<Result<PromoteTransformationResult, ApiProblem>>;

  previewTransformation(
    tenantId: string,
    input: PreviewStreamTransformationInput,
  ): Promise<Result<TransformationPreviewResult, ApiProblem>>;
}
