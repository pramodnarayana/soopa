# Technical Debt Log

This document tracks known architectural drift, quick fixes, and non-critical refactoring tasks that should be addressed in future sprints.

## [TypeScript Version Drift] Monorepo TypeScript Alignment
- **Date Added**: 2026-07-23
- **Description**: The `@soopa/dashboard` uses `typescript: ~6.0.2` while `@soopa/edi-ui` uses `typescript: ^5.4.0`. This dependency drift caused `ignoreDeprecations` mismatch issues in `tsconfig.json` during the CI build process.
- **Action Item**: Standardize the entire monorepo to use a single, unified workspace version of TypeScript (e.g. `6.0.x`). Remove the divergent `ignoreDeprecations` flags across packages once unified.

## [Python Static Typing] Enforce Strict `mypy` in CI/CD
- **Date Added**: 2026-07-23
- **Description**: Although `py.typed` markers were added to internal Python packages (`identity`, `database`, `scheduler`), the `mypy` static type checker currently only logs warnings and does not block commits or CI pipelines on failure. Furthermore, type-checking rules are not centralized.
- **Action Item**: Centrally configure `mypy` (e.g. in a workspace `pyproject.toml` or `mypy.ini`) with strict rules like `disallow_untyped_defs = true`. Update the pre-commit hooks and GitHub Actions to enforce `exit 1` on type-checking failures, preventing untyped code from reaching the main branch.

## [Authorization Architecture] Replace Magic Roles with Permission-Based Access Control (PBAC)

- **Date Added**: 2026-07-27
- **Description**: The API authorization middleware (`auth.py`) and Zero Trust ACL currently hardcode external Identity Provider (Zitadel) role names (e.g. `PlatformAdmin`) and virtual tenant IDs (`"0"`). This violates Hexagonal Architecture and creates tight coupling to external IdP nomenclature.
- **Action Item**: Implement an Anti-Corruption Layer (ACL) that dynamically maps IdP roles to canonical internal capabilities/permissions (e.g. `Permissions.SYSTEM_TENANT_BYPASS`) via configuration. Update all backend dependencies to evaluate generic capabilities rather than checking for magic strings or virtual tenant IDs.

## [UI Architecture] Consolidate UI Primitives (Radix UI vs Base UI)

- **Date Added**: 2026-07-27
- **Description**: The monorepo currently mixes two different headless UI libraries: `@soopa/edi-ui` uses Radix UI (`asChild` pattern), while `@soopa/dashboard` uses Base UI (`render` prop pattern). This library mixing led to "swallowed ref" and unclickable button bugs when the dashboard hijacked imports via Vite aliases. We have temporarily mitigated this by isolating the packages with strict ESLint boundaries and relative imports.
- **Action Item**: Standardize the entire monorepo on a single UI library (preferably Base UI, to match the newer Shadcn UI standard). Extract a unified `packages/ui` library, migrate all `@soopa/edi-ui` components to use it, and remove the Radix dependencies to reduce bundle bloat and cognitive load.

## [Architecture] Event-Driven Tenant Data Replication via LISTEN/NOTIFY

- **Date Added**: 2026-07-30
- **Description**: The Python EDI API currently reads Tenant configuration directly from the Global Control Plane Database (`ucp.tenants` and `ucp.tenant_shards` schemas) using a Read-Only Projection pattern. To achieve absolute physical decoupling without the operational overhead of heavy message brokers like Kafka or SQS, UCP should use lightweight PostgreSQL `LISTEN/NOTIFY` to broadcast `TenantUpdated` events. The EDI service would consume these events to maintain its own isolated `edi_tenants` table.
- **Action Item**: Implement PostgreSQL `LISTEN/NOTIFY` triggers in the UCP database and a corresponding async listener in the EDI worker to seamlessly replicate tenant data into a strictly isolated EDI schema.

## [Security] Infrastructure-Level Database Role Enforcement

- **Date Added**: 2026-07-30
- **Description**: The Python EDI API currently uses database credentials that may have broader access to the `ucp` schema than necessary. Relying solely on code-level Interface Segregation is risky; a database-level enforcement physically guarantees that no rogue developer can accidentally mutate UCP data from the EDI codebase.
- **Action Item**: Implement strict PostgreSQL Roles. The UCP API should authenticate with a role that has full `INSERT/UPDATE/DELETE` privileges on the `ucp` schema. The EDI API should authenticate with a highly restricted role that is strictly granted `GRANT SELECT ON ucp.tenants`.

## [Architecture] Global Identification Strategy & Formatting Consistency

- **Date Added**: 2026-08-01
- **Description**: The system suffers from Identity formatting fragmentation across bounded contexts. The EDI Context defaults to standard UUIDs (e.g., `d7b4e9a0...`), the UCP Context utilizes prefixed, human-readable IDs (e.g., `ten_...`, `wh_...`), and the UI previously contained legacy references to auto-incrementing integers. This causes type mismatch errors (e.g., Pydantic UUID validation rejecting string IDs) and requires complex mapping layers.
- **Action Item**: Establish and enforce a single, global Enterprise Identification Standard. Prefixed IDs (like Stripe's `cus_xyz123`) mapping to UUIDv7/KSUIDs internally are the gold standard. Every bounded context, database schema, and DTO must strictly adhere to the unified ID format, eliminating all implicit type coercion or cross-boundary cast failures.

## [Architecture] Outbox Management & Architectural Inconsistency (Python vs TypeScript)

- **Date Added**: 2026-08-02
- **Description**: The Python EDI API and TypeScript UCP API use different architectural patterns for managing Domain Events / Outbox records. The Python EDI API uses a Service/Transaction Script pattern where the Service layer explicitly manages the outbox via `publish_outbox_event(...)`. The TypeScript UCP API uses a strict Domain-Driven Design (DDD) Hexagonal architecture where Aggregate Roots internally queue events, which are implicitly pulled and saved to the outbox by the Drizzle Repository during a `.save()` operation.
- **Action Item**: Both APIs should ideally align on a single, monorepo-wide architectural standard for event-driven mutation (e.g., standardizing on strict DDD Aggregate Roots across both languages) to ensure concepts like Client-Side Idempotency flow uniformly through the layers.
