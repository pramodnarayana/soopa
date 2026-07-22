import { Tenant } from '../../domain/models/tenant.model';

export const TENANT_REPOSITORY = Symbol('TENANT_REPOSITORY');

export interface ITenantRepository {
  findById(id: string): Promise<Tenant | null>;
  findAll(): Promise<Tenant[]>;
  save(tenant: Tenant): Promise<Tenant>;
  delete(id: string): Promise<void>;
}
