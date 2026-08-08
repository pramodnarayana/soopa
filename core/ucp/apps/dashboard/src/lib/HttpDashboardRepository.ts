import type { DashboardData, IDashboardRepository } from '@soopa/edi-ui';
import { apiClient } from './api-client';

export class HttpDashboardRepository implements IDashboardRepository {
  constructor(private readonly tenantId: string) {}

  async getDashboardData(): Promise<DashboardData> {
    const url = `/tenants/${this.tenantId}/edi/dashboard`;
    return apiClient.get<DashboardData>(url);
  }
}
