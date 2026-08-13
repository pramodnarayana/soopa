# Technical Debt Log

This document tracks known architectural drift, quick fixes, and non-critical refactoring tasks that should be addressed in future sprints.



## [Authorization Architecture] Implement Dynamic Enterprise-Grade PBAC/ABAC

- **Date Added**: 2026-07-27
- **Description**: The system currently relies on hardcoded Magic Roles (`PlatformAdmin`, `TenantAdmin`, `TenantUser`) provisioned via Terraform and statically checked via strings in the frontend/backend. This is not true enterprise-grade PBAC/ABAC. We lack a dynamic, database-driven authorization engine that allows customers to create custom roles, manage capabilities via the UI, and map them to dynamic attributes.
- **Action Item**: Implement a true Enterprise-Grade Dynamic PBAC/ABAC engine (e.g., using OpenFGA, Keto, or a dedicated robust PostgreSQL schema with caching). Build a complete Role Management UI for tenants to create custom roles and assign granular capabilities. Refactor the backend middleware and frontend React components to fetch and enforce these dynamic capabilities, completely eradicating static magic strings from the codebase.

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


## [Notifications] In-App Notification Delivery UX

- **Date Added**: 2026-08-11
- **Description**: The Notification Engine now delivers real-time In-App notifications via Server-Sent Events (SSE) and supports tenant-scoped event_type routing. However, user-level subscription preferences are not yet implemented - users cannot opt-in/opt-out of specific notification channels on a per-user basis.
- **Action Item**: Implement user-level notification preferences allowing individual users to configure which event_type notifications they receive via In-App vs. Email channels. This requires extending the preferences system to support user-scoped overrides on top of tenant-wide routing rules, and applying those preferences during recipient/channel resolution in the notification delivery pipeline.




## [UI Architecture] Compile-time Enforcement of UI Consistency

- **Date Added**: 2026-08-11
- **Description**: The UI components currently allow arbitrary Tailwind CSS classes (e.g., `text-sm`, `max-w-6xl`) to be passed into them via the `className` prop, leading to UI inconsistency and layout regressions. Developers are currently allowed to bypass the enterprise design system because the compile-time constraints are too loose.
- **Action Item**: Implement strict compile-time UI enforcement by:
  1. Omit the `className` prop from all core design system components, forcing the use of strongly-typed variants (via `cva`).
  2. Extend TanStack Table's `ColumnMeta` to strictly type all table configurations (e.g., `isPrimaryText: true`, `truncate: boolean`) instead of accepting raw CSS string overrides.
  3. Implement ESLint rules (`no-restricted-syntax`) to ban raw HTML tags (`<table>`, `<button>`) outside of the UI library.
  4. Enforce design token constraints by implementing an ESLint plugin or custom Tailwind class validator that rejects unauthorized arbitrary Tailwind values (e.g., `text-[14.5px]`, `w-[347px]`) while still permitting approved design tokens. Note: Tailwind v3.x does not support globally disabling arbitrary values, so enforcement must be done via linting or build-time validation.

## [UI Architecture] Magic String className Eradication Codemod

- **Date Added**: 2026-08-12
- **Description**: Magic string `className` usages persist across the feature codebase (approx. 2000+ instances in 93 files). This bypasses the strict primitive design system (`<Box>`, `<Stack>`, `<Icon>`).
- **Action Item**: Build a `ts-morph` codemod to parse Tailwind strings and map them systematically to the new layout primitives. Once complete, enforce the `no-restricted-syntax` ban on `className` globally via ESLint, completely removing the temporary need for `/* eslint-disable no-restricted-syntax */` suppressions.

## [Architecture Enforcement] Automated Architecture Unit Testing

- **Date Added**: 2026-08-12
- **Description**: We currently rely on human code review to catch architectural drift (like developers creating monolithic God `Service` classes instead of strict single-responsibility `UseCase` classes). This is error-prone and scales poorly.
- **Action Item**: Implement `pytest-archon` (Python) or a custom AST linter to write automated architecture unit tests. These tests must run in CI/CD and explicitly fail the build if a developer violates Hexagonal Architecture boundaries (e.g., naming a class `Service` instead of `UseCase`, or having multiple public methods on a UseCase).

## [Architecture Enforcement] Strict Scaffolding CLI

- **Date Added**: 2026-08-12
- **Description**: Developers currently create files manually, which leads to boilerplate errors and architectural drift.
- **Action Item**: Build an internal CLI (e.g., `pnpm run generate:use-case`) that scaffolds new features with strict Hexagonal boundaries, ensuring developers fall into the "pit of success" by default.

## [Observability Architecture] Massive Refactoring of Legacy Logging

- **Date Added**: 2026-08-13
- **Status**: ✅ RESOLVED
- **Description**: We attempted to enforce strict Enterprise Observability standards globally by configuring Ruff to ban `import logging` (TID251) and block f-strings in logging (G004). However, the linter detected over 600 violations across legacy systems, causing the CI pipeline to fail completely. To unblock the team, these strict checks have been temporarily deactivated in `pyproject.toml`.
- **Action Item**: Reactivate `TID251` and `G004` in Ruff, and systematically refactor all 600+ violations across the codebase to use `structlog` and context injection, eradicating all legacy standard logging usages and f-string anti-patterns.

## [Strict Typing] Legacy Mypy Violations

- **Date Added**: 2026-08-13
- **Description**: The Mypy strict type checker currently detects 40 legacy violations across 14 files (primarily missing return types, untyped function calls, and incorrect generic types). To unblock the current enterprise refactor commit, the `mypy` pre-commit hook has been temporarily commented out.
- **Action Item**: Resolve the 40 legacy Mypy errors and reactivate the `mypy` hook in `.pre-commit-config.yaml` to ensure strict CI type enforcement.
