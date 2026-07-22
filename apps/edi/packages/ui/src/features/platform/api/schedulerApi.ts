export interface JobResponse {
  id: string;
  name: string;
  status: string;
  target_queue: string | null;
  app_namespace: string | null;
  cron_expression: string | null;
  timezone: string | null;
  next_run_at: string | null;
  locked_at: string | null;
  locked_by: string | null;
  retry_count: number;
  interval_seconds: number | null;
  min_interval_seconds: number | null;
  max_interval_seconds: number | null;
  error_message: string | null;
  created_at: string;
  updated_at: string;
}

export interface ConfigResponse {
  key: string;
  value: any;
}

export interface ISchedulerRepository {
  getJobs(): Promise<JobResponse[]>;
  getConfig(): Promise<ConfigResponse[]>;
  updateConfig(key: string, value: any): Promise<ConfigResponse>;
  updateJob(name: string, data: { interval_seconds?: number | null; cron_expression?: string | null; timezone?: string | null; status?: string }): Promise<JobResponse>;
}

class HttpSchedulerRepository implements ISchedulerRepository {
  private readonly headers: Record<string, string>;

  constructor(token: string) {
    this.headers = {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${token}`,
    };
  }

  private async request<T>(url: string, init?: RequestInit): Promise<T> {
    const res = await fetch(url, { ...init, headers: this.headers });
    if (!res.ok) {
      let errorMessage = res.statusText;
      try {
        const data = await res.json();
        errorMessage = data.detail || JSON.stringify(data);
      } catch {}
      throw new Error(errorMessage || 'API request failed');
    }
    const text = await res.text();
    if (!text) return {} as T;
    return JSON.parse(text);
  }

  getJobs(): Promise<JobResponse[]> {
    return this.request('/api/v1/platform/scheduler/jobs');
  }

  getConfig(): Promise<ConfigResponse[]> {
    return this.request('/api/v1/platform/scheduler/config');
  }

  updateConfig(key: string, value: any): Promise<ConfigResponse> {
    return this.request(`/api/v1/platform/scheduler/config/${key}`, {
      method: 'PUT',
      body: JSON.stringify({ value }),
    });
  }

  updateJob(name: string, data: { interval_seconds?: number | null; cron_expression?: string | null; timezone?: string | null; status?: string }): Promise<JobResponse> {
    return this.request(`/api/v1/platform/scheduler/jobs/${name}`, {
      method: 'PUT',
      body: JSON.stringify(data),
    });
  }
}

export function createSchedulerRepository(token: string): ISchedulerRepository {
  return new HttpSchedulerRepository(token);
}
