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

## [Infrastructure] Local Infrastructure Desync (Zitadel vs Postgres)

- **Date Added**: 2026-08-02
- **Description**: The local `infra-reset` script performs a partial teardown of the infrastructure. It wipes and recreates the UCP Postgres database volumes but does not wipe or fully re-sync the Terraform-provisioned Zitadel IdP. Relying on partial reset scripts causes schema drifts to manifest as "missing user domain" or 403 errors, leading to dangerous local state corruption and significant developer time waste.
- **Action Item**: The local development infrastructure scripts (`pnpm infra-reset`, `pnpm db:seed`) must be completely atomic and idempotent. The reset scripts should either tear down Zitadel concurrently with Postgres, OR the seed script must dynamically interact with Zitadel APIs to reconstruct all required developer fixtures (test tenants, test users, project grants) so the local database is perfectly synced with the IdP state.

## [Backend Architecture Alignment] Refactor API Keys and Webhooks to Hexagonal Architecture

- **Date Added**: 2026-08-02
- **Description**: The CRUD controllers for managing Webhooks and API Keys currently contain business logic directly in the endpoints or use an older procedural pattern. They do not fully adhere to the strict Hexagonal Architecture (Ports and Adapters) UseCase patterns established in newer areas of the codebase.
- **Action Item**: Refactor the remaining `webhooks` and `api-keys` controllers to delegate all business logic to dedicated Hexagonal `UseCase` classes, ensuring that the presentation layer strictly handles only HTTP validation and response mapping.

## [Frontend/Backend Alignment] End-to-End OpenAPI Auto-Generation

- **Date Added**: 2026-08-03
- **Description**: The UI currently relies on manually constructed API clients and disconnected TanStack routing configuration. This allows API contracts or payload structure changes in the backend (FastAPI/NestJS) to silently break the frontend at runtime (such as 404s on trace links) without being caught during the build process.
- **Action Item**: Implement a strict end-to-end OpenAPI code generation pipeline (using a tool like Orval or tRPC) across the monorepo. This will auto-generate strictly typed React Query hooks and frontend API clients directly from the backend schemas, ensuring that any breaking changes in the API instantly fail the frontend TypeScript build at compile time.

## [Testing] Missing Python Test Suites & Exit Code 5 Suppression

- **Date Added**: 2026-08-05
- **Description**: Several recently migrated or newly created Python packages (such as `patches`, `edi-grammar`, and `transformer`) currently have zero tests. To prevent Turborepo and the CI pipeline from failing when running `pytest` concurrently (which natively returns Exit Code 5 when no tests are collected), the `package.json` proxy scripts currently suppress this specific exit code (`uv run pytest || (ret=$?; [ $ret -eq 5 ] && exit 0 || exit $ret)`).
- **Action Item**: Write actual unit and integration tests for all untested Python packages. Once all packages have legitimate tests, remove the Exit Code 5 suppression hack from the respective `package.json` files so that accidental test-suite drops correctly fail the CI pipeline.

## [Notifications] In-App Notification Delivery UX

- **Date Added**: 2026-08-11
- **Description**: The Notification Engine now delivers real-time In-App notifications via Server-Sent Events (SSE) and supports tenant-scoped event_type routing. However, user-level subscription preferences are not yet implemented - users cannot opt-in/opt-out of specific notification channels on a per-user basis.
- **Action Item**: Implement user-level notification preferences allowing individual users to configure which event_type notifications they receive via In-App vs. Email channels. This requires extending the preferences system to support user-scoped overrides on top of tenant-wide routing rules, and applying those preferences during recipient/channel resolution in the notification delivery pipeline.

## [Authorization Architecture] Granular PBAC/RBAC for Platform Superusers

- **Date Added**: 2026-08-11
- **Description**: While standard tenant-level users are strictly governed by granular Permission-Based Access Control (PBAC), the global Platform Superuser access is currently granted via an omnipotent "PlatformAdmin" role tied to a sentinel tenant ID (`ten_000000000000000000000000`). This magic string bypasses all granular checks, giving all internal staff omnipotent "Root" privileges across the entire cluster without distinction.
- **Action Item**: Implement granular PBAC/RBAC/ABAC for platform-level users. We need to decompose the omnipotent "PlatformAdmin" role into specific platform capabilities (e.g., `platform:tenant:read`, `platform:tenant:delete`, `platform:billing:manage`) so that internal staff (Support, Engineering, Billing) only receive the minimal platform privileges required for their roles (Principle of Least Privilege).

## [Architecture] Standardize Dependency Injection via `dependency-injector`

- **Date Added**: 2026-08-11
- **Description**: The codebase currently utilizes a mix of Dependency Injection strategies. The `notification_engine` module utilizes `dependency-injector` (the true enterprise standard for IoC), while the `edi` and `ucp` domains rely on FastAPI's native `Depends()` system. While `Depends()` is ergonomic for web APIs, it leaks the web framework into the core application logic and cannot be cleanly utilized in background workers or CLI scripts.
- **Action Item**: Standardize the entire Python monorepo on `dependency-injector`. Refactor the `edi` and `ucp` domains to define declarative containers (`containers.DeclarativeContainer`) for all dependencies, and utilize `@inject` and `Provide` in their FastAPI routers.

## [UI Architecture] Compile-time Enforcement of UI Consistency

- **Date Added**: 2026-08-11
- **Description**: The UI components currently allow arbitrary Tailwind CSS classes (e.g., `text-sm`, `max-w-6xl`) to be passed into them via the `className` prop, leading to UI inconsistency and layout regressions. Developers are currently allowed to bypass the enterprise design system because the compile-time constraints are too loose.
- **Action Item**: Implement strict compile-time UI enforcement by:
  1. Omit the `className` prop from all core design system components, forcing the use of strongly-typed variants (via `cva`).
  2. Extend TanStack Table's `ColumnMeta` to strictly type all table configurations (e.g., `isPrimaryText: true`, `truncate: boolean`) instead of accepting raw CSS string overrides.
  3. Implement ESLint rules (`no-restricted-syntax`) to ban raw HTML tags (`<table>`, `<button>`) outside of the UI library.
  4. Enforce design token constraints by implementing an ESLint plugin or custom Tailwind class validator that rejects unauthorized arbitrary Tailwind values (e.g., `text-[14.5px]`, `w-[347px]`) while still permitting approved design tokens. Note: Tailwind v3.x does not support globally disabling arbitrary values, so enforcement must be done via linting or build-time validation.
