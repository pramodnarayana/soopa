# Soopa Identity Architecture

Soopa Identity is a shared identity boundary for products written in different
languages. It is not a user interface and it does not own product-specific user
workflows. It owns contracts, identity interpretation, and authorization rules
that must remain consistent across services.

## Principles

- Contract-first: shared models live in `specification/`.
- Hexagonal architecture: application code depends on ports, not vendors.
- Clean domain logic: tenant, subject, role, and permission decisions are pure.
- Narrow integration tests: adapters verify framework and Zitadel behavior at
  the boundary.
- No framework leakage: Express, Fastify, and FastAPI live in adapters.

## Runtime Flow

1. Inbound middleware extracts the bearer token.
2. The token verifier validates issuer, audience, expiry, and signature.
3. Claims are mapped into an `IdentityContext`.
4. Authorization policies evaluate roles and permissions.
5. Application handlers receive a validated identity context.

## Package Responsibilities

- `specification`: source of truth for ports, models, roles, and permissions.
- `node`: TypeScript SDK for `soopa-integration` and future Node services.
- `python`: Python SDK for `soopa-edi`, `soopa-idp`, and future Python services.
- `examples`: app-specific integration sketches.
