# Token Claims

The SDKs expect standards-compliant JWT claims plus Soopa-specific tenant and
authorization claims.

## Standard Claims

- `iss`: issuer URL
- `sub`: user or service subject
- `aud`: accepted audience or audiences
- `exp`: expiration timestamp
- `iat`: issued-at timestamp

## Soopa Claims

- `tenant_id`: active tenant
- `organization_id`: active organization, when applicable
- `roles`: role names
- `permissions`: permission names
