export {
  FetchHttpClientAdapter,
  type FetchHttpClientConfig,
} from './fetch-http-client';
export {
  ApiErrorCode,
  type ApiErrorCodeValue,
  type ApiProblem,
  ApiProblemError,
  err,
  type HttpClientPort,
  HttpMethod,
  type HttpMethodValue,
  type HttpRequestOptions,
  ok,
  type QueryParamScalar,
  type QueryParamsRecord,
  type Result,
  unwrapOrThrow,
} from './ports';
export {
  type PlatformResultQuerySource,
  type PlatformResultQueryView,
  projectPlatformResultQuery,
  recordPlatformMutationOutcome,
} from './result-query';
