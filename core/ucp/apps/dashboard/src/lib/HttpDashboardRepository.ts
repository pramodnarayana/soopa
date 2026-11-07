import type { DashboardData, IDashboardRepository } from '@soopa/edi-ui';
import type { UcpApiClientPort } from './api-client';

export class HttpDashboardRepository implements IDashboardRepository {
  public constructor(
    private readonly apiClient: UcpApiClientPort,
    private readonly tenantId: string,
  ) {}

  public async getDashboardData(): Promise<DashboardData> {
    const url = `/tenants/${encodeURIComponent(this.tenantId)}/edi/dashboard`;
    return this.apiClient.get<DashboardData>(url);
  }
}
