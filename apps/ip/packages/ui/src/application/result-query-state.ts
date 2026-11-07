import type { ApiProblem, Result } from '@soopa/ui';

export interface IpQueryView<T> {
  readonly data: T | undefined;
  readonly problem: ApiProblem | null;
  readonly isLoading: boolean;
  readonly isFetching: boolean;
  readonly refetch: () => Promise<unknown>;
}

export interface ResultQuerySource<T> {
  readonly data: Result<T, ApiProblem> | undefined;
  readonly isLoading: boolean;
  readonly isFetching: boolean;
  readonly refetch: () => Promise<unknown>;
}

export function projectResultQuery<T>(query: ResultQuerySource<T>): IpQueryView<T> {
  const result = query.data;
  const data = result && result.ok ? result.value : undefined;
  const problem = result && !result.ok ? result.error : null;

  return {
    data,
    problem,
    isLoading: query.isLoading,
    isFetching: query.isFetching,
    refetch: query.refetch,
  };
}
