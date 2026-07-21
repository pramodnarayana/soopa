# Identity Context

`IdentityContext` is the normalized identity object passed to application code
after JWT validation.

| Field | Description |
| --- | --- |
| `subject` | Stable user or service account identifier. |
| `tenant_id` | Current tenant boundary for data access. |
| `organization_id` | Optional organization selected inside the tenant. |
| `roles` | Role names granted in the current context. |
| `permissions` | Fine-grained permission names granted in the current context. |
| `claims` | Original validated token claims for diagnostics and advanced policy. |

Application code should prefer `roles` and `permissions` over raw claims.
