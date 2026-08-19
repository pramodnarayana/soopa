# Technical Debt Log

This document tracks known architectural drift, quick fixes, and non-critical refactoring tasks that should be addressed in future sprints.



## [RESOLVED] [Authorization Architecture] Implement Dynamic Enterprise-Grade PBAC/ABAC

- **Date Added**: 2026-07-27
- **Status**: ✅ RESOLVED
- **Description**: The system currently relies on hardcoded Magic Roles (`PlatformAdmin`, `TenantAdmin`, `TenantUser`) provisioned via Terraform and statically checked via strings in the frontend/backend. This is not true enterprise-grade PBAC/ABAC. We lack a dynamic, database-driven authorization engine that allows customers to create custom roles, manage capabilities via the UI, and map them to dynamic attributes.
- **Action Item**: Implement a true Enterprise-Grade Dynamic PBAC/ABAC engine (e.g., using OpenFGA, Keto, or a dedicated robust PostgreSQL schema with caching). Build a complete Role Management UI for tenants to create custom roles and assign granular capabilities. Refactor the backend middleware and frontend React components to fetch and enforce these dynamic capabilities, completely eradicating static magic strings from the codebase.

## [RESOLVED] [UI Architecture] Consolidate UI Primitives (Radix UI vs Base UI)

- **Date Added**: 2026-07-27
- **Status**: ✅ RESOLVED
- **Description**: The monorepo currently mixes two different headless UI libraries: `@soopa/edi-ui` uses Radix UI (`asChild` pattern), while `@soopa/dashboard` uses Base UI (`render` prop pattern). This library mixing led to "swallowed ref" and unclickable button bugs when the dashboard hijacked imports via Vite aliases. We have temporarily mitigated this by isolating the packages with strict ESLint boundaries and relative imports.
- **Action Item**: Standardize the entire monorepo on a single UI library (preferably Base UI, to match the newer Shadcn UI standard). Extract a unified `packages/ui` library, migrate all `@soopa/edi-ui` components to use it, and remove the Radix dependencies to reduce bundle bloat and cognitive load.

## [RESOLVED] [Architecture] Event-Driven Tenant Data Replication via LISTEN/NOTIFY

- **Date Added**: 2026-07-30
- **Status**: ✅ RESOLVED
- **Description**: The Python EDI API currently reads Tenant configuration directly from the Global Control Plane Database (`ucp.tenants` and `ucp.tenant_shards` schemas) using a Read-Only Projection pattern. To achieve absolute physical decoupling without the operational overhead of heavy message brokers like Kafka or SQS, UCP should use lightweight PostgreSQL `LISTEN/NOTIFY` to broadcast `TenantUpdated` events. The EDI service would consume these events to maintain its own isolated `edi_tenants` table.
- **Action Item**: Implement PostgreSQL `LISTEN/NOTIFY` triggers in the UCP database and a corresponding async listener in the EDI worker to seamlessly replicate tenant data into a strictly isolated EDI schema.

## [Security] Infrastructure-Level Database Role Enforcement

- **Date Added**: 2026-07-30
- **Description**: The Python EDI API currently uses database credentials that may have broader access to the `ucp` schema than necessary. Relying solely on code-level Interface Segregation is risky; a database-level enforcement physically guarantees that no rogue developer can accidentally mutate UCP data from the EDI codebase.
- **Action Item**: Implement strict PostgreSQL Roles. The UCP API should authenticate with a role that has full `INSERT/UPDATE/DELETE` privileges on the `ucp` schema. The EDI API should authenticate with a highly restricted role that is strictly granted `GRANT SELECT ON ucp.tenants`.

## [RESOLVED] [Architecture] Global Identification Strategy & Formatting Consistency

- **Date Added**: 2026-08-01
- **Status**: ✅ RESOLVED
- **Description**: The system suffers from Identity formatting fragmentation across bounded contexts. The EDI Context defaults to standard UUIDs (e.g., `d7b4e9a0...`), the UCP Context utilizes prefixed, human-readable IDs (e.g., `ten_...`, `wh_...`), and the UI previously contained legacy references to auto-incrementing integers. This causes type mismatch errors (e.g., Pydantic UUID validation rejecting string IDs) and requires complex mapping layers.
- **Action Item**: Establish and enforce a single, global Enterprise Identification Standard. Prefixed IDs (like Stripe's `cus_xyz123`) mapping to UUIDv7/KSUIDs internally are the gold standard. Every bounded context, database schema, and DTO must strictly adhere to the unified ID format, eliminating all implicit type coercion or cross-boundary cast failures.

## [RESOLVED] [Infrastructure] Local Infrastructure Desync (Zitadel vs Postgres)

- **Date Added**: 2026-08-02
- **Status**: ✅ RESOLVED
- **Description**: The local `infra-reset` script performs a partial teardown of the infrastructure. It wipes and recreates the UCP Postgres database volumes but does not wipe or fully re-sync the Terraform-provisioned Zitadel IdP. Relying on partial reset scripts causes schema drifts to manifest as "missing user domain" or 403 errors, leading to dangerous local state corruption and significant developer time waste.
- **Action Item**: The local development infrastructure scripts (`pnpm infra-reset`, `pnpm db:seed`) must be completely atomic and idempotent. The reset scripts should either tear down Zitadel concurrently with Postgres, OR the seed script must dynamically interact with Zitadel APIs to reconstruct all required developer fixtures (test tenants, test users, project grants) so the local database is perfectly synced with the IdP state.

## [RESOLVED] [Backend Architecture Alignment] Refactor API Keys and Webhooks to Hexagonal Architecture

- **Date Added**: 2026-08-02
- **Status**: ✅ RESOLVED
- **Description**: The CRUD controllers for managing Webhooks and API Keys currently contain business logic directly in the endpoints or use an older procedural pattern. They do not fully adhere to the strict Hexagonal Architecture (Ports and Adapters) UseCase patterns established in newer areas of the codebase.
- **Action Item**: Refactor the remaining `webhooks` and `api-keys` controllers to delegate all business logic to dedicated Hexagonal `UseCase` classes, ensuring that the presentation layer strictly handles only HTTP validation and response mapping.

## [Frontend/Backend Alignment] End-to-End OpenAPI Auto-Generation

- **Date Added**: 2026-08-03
- **Description**: The UI currently relies on manually constructed API clients and disconnected TanStack routing configuration. This allows API contracts or payload structure changes in the backend (FastAPI) to silently break the frontend at runtime (such as 404s on trace links) without being caught during the build process.
- **Action Item**: Implement a strict end-to-end OpenAPI code generation pipeline using Orval (`orval.dev`) or `openapi-ts`. Configure the tool to download FastAPI's native `openapi.json` during the build step and auto-generate strictly-typed React Query hooks and frontend API clients. This ensures that any breaking changes in the backend API instantly fail the frontend TypeScript build at compile time.


## [RESOLVED] [Notifications] In-App Notification Delivery UX

- **Date Added**: 2026-08-11
- **Status**: ✅ RESOLVED
- **Description**: The Notification Engine now delivers real-time In-App notifications via Server-Sent Events (SSE) and supports tenant-scoped event_type routing. However, user-level subscription preferences are not yet implemented - users cannot opt-in/opt-out of specific notification channels on a per-user basis.
- **Action Item**: Implement user-level notification preferences allowing individual users to configure which event_type notifications they receive via In-App vs. Email channels. This requires extending the preferences system to support user-scoped overrides on top of tenant-wide routing rules, and applying those preferences during recipient/channel resolution in the notification delivery pipeline.




## [RESOLVED] [UI Architecture] Compile-time Enforcement of UI Consistency

- **Date Added**: 2026-08-11
- **Status**: ✅ RESOLVED
- **Solution**: Instead of banning `className` which broke Tailwind's layout engine, we implemented strict compile-time enforcement using `eslint-plugin-tailwindcss`. Arbitrary "magic" values (e.g., `w-[150px]`) are now strictly rejected by the compiler, forcing developers to use standard design tokens while preserving development velocity.
- **Action Item**:

## [RESOLVED] [UI Architecture] Magic String `className` Eradication Codemod

- **Date Added**: 2026-08-12
- **Status**: ✅ RESOLVED
- **Description**: Magic string `className` usages persist across the feature codebase (approx. 2000+ instances in 93 files). This bypasses the strict primitive design system (`<Box>`, `<Stack>`, `<Icon>`).
- **Action Item**: Build a `ts-morph` codemod to parse Tailwind strings and map them systematically to the new layout primitives. Once complete, enforce the `no-restricted-syntax` ban on `className` globally via ESLint, completely removing the temporary need for `/* eslint-disable no-restricted-syntax */` suppressions.

## [Architecture Enforcement] Automated Architecture Unit Testing

- **Date Added**: 2026-08-12
- **Status**: ✅ RESOLVED
- **Description**: We currently rely on human code review to catch architectural drift (like developers creating monolithic God `Service` classes instead of strict single-responsibility `UseCase` classes). This is error-prone and scales poorly.
- **Action Item**: Implement `pytest-archon` (Python) or a custom AST linter to write automated architecture unit tests. These tests must run in CI/CD and explicitly fail the build if a developer violates Hexagonal Architecture boundaries (e.g., naming a class `Service` instead of `UseCase`, or having multiple public methods on a UseCase).

## [Architecture Enforcement] Strict Scaffolding CLI

- **Date Added**: 2026-08-12
- **Description**: Developers currently create files manually, which leads to boilerplate errors and architectural drift.
- **Action Item**: Build an internal CLI (e.g., `pnpm run generate:use-case`) that scaffolds new features with strict Hexagonal boundaries, ensuring developers fall into the "pit of success" by default.

## [Observability Architecture] Legacy Logging Refactoring

- **Date Added**: 2026-08-13
- **Status**: IN PROGRESS
- **Description**: Strict Enterprise Observability standards have been enforced by configuring Ruff to ban `import logging` (TID251). The check is now active in `pyproject.toml` and enforced in CI. Legacy violations are being addressed incrementally through per-file ignores and systematic refactoring to `structlog`.
- **Action Item**: Complete the systematic refactoring of remaining legacy `logging` usages to use `structlog` and context injection, gradually removing per-file ignores as violations are resolved.

## [Strict Typing] Mypy Type Enforcement

- **Date Added**: 2026-08-13
- **Status**: IN PROGRESS
- **Description**: The Mypy strict type checker is active in the pre-commit configuration and enforced in CI. Legacy type violations are being addressed incrementally through per-file configuration and systematic type annotation improvements.
- **Action Item**: Continue resolving legacy Mypy violations across the codebase to achieve full strict type coverage without per-file exceptions.

## [Security/UX] Hide Internal Tenant IDs from Client-Facing URLs

- **Date Added**: 2026-08-13
- **Status**: ✅ RESOLVED
- **Solution**: Added an immutable `slug` field (e.g., `acme-corp`) to the `identity.tenants` table, auto-generated at provision time from the tenant name. The frontend TanStack Router routes were updated to use `$tenantSlug` instead of `$tenantId`. The internal `ten_...` ID is no longer exposed in any client-facing URL.

## [Security/UX] Slug Redirect Trail for Self-Service Tenant Portals

- **Date Added**: 2026-08-14
- **Description**: The current slug implementation is intentionally immutable — if a tenant renames itself, the slug does not change. This is acceptable for the internal platform admin dashboard (operators update their bookmarks manually), but will become a problem when customer-facing self-service tenant portals are introduced (e.g., `yourplatform.com/t/acme-corp/portal`). At that point, slug changes would break bookmarked and shared URLs in the wild.
- **Action Item**: When self-service tenant sign-in / customer-facing portals are built, implement a `tenant_slug_history` table that permanently reserves old slugs and issues `HTTP 301` redirects to the current slug. The redirect middleware should sit in the `unified-api` shell. Historical slugs must participate in the global unique constraint to prevent slug hijacking (a new tenant claiming a released slug to impersonate a renamed one).


## [DONE] Backend Database Dual-Architecture (ORM vs Raw SQL)

**Category**: Architecture
**Impact**: Medium
**Description**: The codebase was audited for mixing SQLAlchemy 2.0 ORM features with raw SQL executions via `session.execute(text("..."))` for standard CRUD operations. The audit confirmed that raw SQL is currently only used for valid infrastructure boundaries (e.g. database migrations, testing truncates, PostgreSQL NOTIFY commands, and schema constraints), while all CRUD Repositories correctly use SQLAlchemy 2.0 typed constructs (`select()`, `insert()`, etc).
- **Status**: ✅ RESOLVED

**Audit Results**: Audit complete, no CRUD violation found.

## [DONE] Frontend API Client Dual-Architecture (Axios vs Fetch)

**Category**: Architecture
**Impact**: Low
**Description**: Found a tiny pocket of `axios` usage inside `apps/edi/packages/ui/src` while the rest of the monorepo standardizes on native `fetch`.
- **Status**: ✅ RESOLVED

**Fix details**: Replaced the `axios` implementation inside `createNetworkContext.tsx` and related hooks with a custom native `fetch` wrapper that preserves the identical `.get()`, `.post()` API signatures for backwards compatibility. Uninstalled `axios` from all `package.json` files.

## [DONE] Webhooks Bounded Context Migration

**Category**: Architecture
**Impact**: High
**Description**: The recent Hexagonal Architecture refactoring of Webhooks correctly extracted the logic into Use Cases, Ports, and Adapters. However, the entire Webhook feature was incorrectly implemented inside the EDI application module (`apps/edi/packages/edi/src/edi/...`). Webhooks are a core platform capability that belong in the UCP (User Control Plane) boundary.
**Status**: Resolved. Webhook Use Cases, Router, and Domain Models have been extracted to UCP, and EDI now correctly subscribes to `webhook.created` via the global outbox.

## [RESOLVED] [Architecture] Dual-Architecture Naming Conventions (Domain Services vs Clean Architecture Use Cases)

- **Date Added**: 2026-08-17
- **Status**: ✅ RESOLVED
- **Description**: The codebase currently mixes Domain-Driven Design (DDD) "Application Services" (grouping multiple commands into a single `Service` class, e.g., `AS2PartnerService`) with Clean Architecture "Use Cases" (standalone single-responsibility classes, e.g., `ProcessInboundEdiUseCase`).
- **Action Item**: The enterprise standard is now strictly Single-Responsibility **Clean Architecture Use Cases** (`_use_case.py`). The legacy `_service.py` God Class pattern is officially deprecated. Migrated `as2_partner_service.py` into isolated use cases as a proof-of-concept template.

## [Architecture] Missing Scheduler Engine for Background Jobs

- **Date Added**: 2026-08-19
- **Description**: The `ucp-worker` is currently polling an SQS queue (`ucp-jobs.fifo`) for scheduled background tasks (like `ucp_outbox_sweeper` and `ucp_data_retention_cleanup`). However, the infrastructure for this queue is missing in Pulumi, and there is no centralized Scheduler Engine pushing cron-trigger messages to it. As a result, critical cleanup jobs are currently never executing, which will eventually lead to unbounded database growth.
- **Action Item**: Implement a centralized Scheduler Module (or AWS EventBridge rules via Pulumi) to push cron-based triggers to the `ucp-jobs.fifo` queue, and ensure the queue infrastructure is correctly provisioned.

## [Architecture] Architectural Drift in Bounded Context File Taxonomy

- **Date Added**: 2026-08-19
- **Description**: Different bounded contexts (UCP vs EDI) have drifted in their internal folder/file naming taxonomies for identical architectural concepts. For example, database event models are located at `core/ucp/.../ucp_models/events.py` in UCP, but at `apps/edi/.../database/models/control_plane.py` in EDI. This violates Modular Monolith structural consistency rules.
- **Action Item**: Standardize the internal file/folder taxonomy across all bounded contexts (e.g., standardizing on `[BoundedContext]/database/models/events.py`) and implement `pytest-archon` rules to automatically enforce these structural conventions in CI.
