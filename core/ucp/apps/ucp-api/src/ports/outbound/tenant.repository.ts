import { Tenant } from '../../domain/models/tenant.model.js';

export const TENANT_REPOSITORY = Symbol('TENANT_REPOSITORY');

export interface ITenantRepository {
  findById(id: string): Promise<Tenant | null>;
  findByIdpTenantId(idpTenantId: string): Promise<Tenant | null>;
  findAll(): Promise<Tenant[]>;
  save(tenant: Tenant, idempotencyKey?: string): Promise<Tenant>;
  delete(id: string, idempotencyKey?: string): Promise<void>;
}
