export interface JobResponse {
  readonly id: string;
  readonly name: string;
  readonly status: string;
  readonly target_queue: string | null;
  readonly app_namespace: string | null;
  readonly cron_expression: string | null;
  readonly timezone: string | null;
  readonly next_run_at: string | null;
  readonly lease_expires_at: string | null;
  readonly owner_token: string | null;
  readonly retry_count: number;
  readonly interval_seconds: number | null;
  readonly min_interval_seconds: number | null;
  readonly max_interval_seconds: number | null;
  readonly error_message: string | null;
  readonly created_at: string;
  readonly updated_at: string;
}

export interface ConfigResponse {
  readonly key: string;
  readonly value: unknown;
}
