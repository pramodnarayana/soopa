export const UCP_API_URL = import.meta.env.VITE_UCP_API_URL || 'http://localhost:3000';

export async function fetchTenants() {
  const res = await fetch(`${UCP_API_URL}/tenants`);
  if (!res.ok) throw new Error('Failed to fetch tenants');
  return res.json();
}

export interface ProvisionTenantDto {
  name: string;
  adminEmail: string;
  appSlugs: string[];
}

export async function provisionTenant(dto: ProvisionTenantDto) {
  const res = await fetch(`${UCP_API_URL}/tenants`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(dto),
  });
  if (!res.ok) throw new Error('Failed to provision tenant');
  return res.json();
}
