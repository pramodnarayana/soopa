import type { DashboardData } from './useDashboardData';

export interface IDashboardRepository {
  getDashboardData(): Promise<DashboardData>;
}
