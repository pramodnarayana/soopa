# Technical Debt Log

This document tracks known architectural drift, quick fixes, and non-critical refactoring tasks that should be addressed in future sprints.



## [Architecture] Rollout Centralized Outbox and Pub/Sub Packages to Remaining Modules

- **Date Added**: 2026-08-26
- **Status**: TO DO
- **Description**: We successfully extracted the `outbox` and `pubsub` generic infrastructure patterns out of the UCP bounded context and into centralized platform packages (`core/platform/packages/outbox` and `core/platform/packages/pubsub`). The UCP Proof-of-Concept is complete and verified. However, the `identity`, `edi`, and `notification` modules still contain duplicated, module-specific implementations of these patterns (Outbox relays, SQS listeners, SNS publishers, etc.).
- **Action Item**: Migrate the `identity`, `edi`, and `notification` modules to use the centralized `outbox` and `pubsub` platform packages. Remove their legacy duplicated infrastructure code, update their Dependency Injection containers to inject the generic `PostgresOutboxRelay`, `AwsSnsPublisher`, and `AwsSqsConsumer`, and verify all tests pass.

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

## [Observability] Standardization of Observability Across Contexts

- **Date Added**: 2026-08-20
- **Description**: While `structlog` has been introduced and legacy `logging` usages have been refactored or tracked in some modules (like UCP, EDI, and Identity), we lack a consistent, standardized approach to context injection and structured logging payloads across newer contexts like Notification and Scheduler. The data structure of our JSON logs must be uniform for effective aggregation and alerting.
- **Action Item**: Audit and standardize the observability implementation across UCP, EDI, Identity, Notification, and Scheduler. Ensure consistent context injection (e.g., `tenant_id`, `event_id`, `job_id`) and payload schemas across all modules using `structlog`.

## [Architecture] Final Enterprise-Grade SSE/Real-time Notifications

- **Date Added**: 2026-08-20
- **Description**: The In-App notification system currently uses basic Server-Sent Events (SSE) bounded to single container memory channels (Python `asyncio.Queue`). This won't scale in a distributed, horizontally scaled environment where users might connect to a different API node than the one processing the notification event.
- **Action Item**: Refactor the SSE streaming implementation to use a true distributed Pub/Sub backplane (e.g., Redis Pub/Sub, AWS IoT Core, or Postgres LISTEN/NOTIFY with a dedicated real-time microservice) to support scale-out real-time notifications.


## [Architecture] Complete Backend Folder Taxonomy Drift

- **Date Added**: 2026-08-20
- **Updated**: 2026-08-21
- **Description**: Taxonomy drift is not limited to HTTP routers — it spans every architectural layer across all bounded contexts. A full audit reveals the following inconsistencies:

### Layer 1 — Inbound Adapters (HTTP Routers)
| Context | Router Location |
|---------|----------------|
| `ucp` | `adapters/inbound/http/routers/*.py` ✅ |
| `identity` | `adapters/inbound/http/` (no `routers/` subdirectory) |
| `notification` | `api/*.py` (flat, no `adapters/` wrapper) |
| `edi` (package) | `routers/**/*.py` (root-level, no `adapters/` at all) |
| `edi-as2-server` | `routers/*.py` (root-level) |

### Layer 2 — Inbound Adapters (Async Workers / SQS Consumers)
| Context | Worker Location |
|---------|----------------|
| `ucp` | `adapters/inbound/workers/*.py` ✅ |
| `scheduler-worker` | `adapters/inbound/workers/*.py` ✅ |
| `notification-worker` | `adapters/inbound/jobs/*.py` (uses `jobs/` not `workers/`) |
| `ucp-worker` | `adapters/inbound/jobs/*.py` (uses `jobs/` not `workers/`) |
| `edi-worker` | Mix: `adapters/inbound/workers/`, `adapters/inbound/jobs/`, and root `adapters/*.py` (flat, no subdirectory) |

### Layer 3 — Outbound Adapters (Repositories)
| Context | Repository Location |
|---------|-------------------|
| `ucp` | `adapters/outbound/database/*.py` ✅ |
| `notification` | `adapters/outbound/*.py` (no `database/` subdirectory) |
| `scheduler` | `adapters/outbound/*.py` (no `database/` subdirectory) |
| `identity` | `adapters/outbound/*.py` (no `database/` subdirectory) |
| `edi-worker` | `adapters/outbound/database/*.py` ✅ but also flat `adapters/*.py` for legacy items |

### Layer 4 — Application Layer (Use Cases)
| Context | Use Case Location |
|---------|-----------------|
| `ucp` | `application/use_cases/**/*.py` (grouped by entity) |
| `notification` | `application/*.py` (flat, no `use_cases/` subdirectory) |
| `scheduler` | `application/*.py` (flat) |
| `identity` | `application/*.py` (flat) |
| `edi-worker` | `application/*.py` (flat) |

### Layer 5 — Ports
| Context | Port Location |
|---------|--------------|
| `ucp` | `ports/outbound/*.py` (namespaced by direction) |
| `notification` | `ports/*.py` (flat) ✅ acceptable |
| `scheduler` | `ports/*.py` (flat) |
| `edi-worker` | `ports/*.py` (flat) |
| `edi-as2-server` | `ports/*.py` (flat) |

### Layer 6 — Domain Models
| Context | Domain Location |
|---------|----------------|
| `ucp` | `domain/models/*.py`, `domain/events/*.py`, `domain/dtos/*.py` (structured) ✅ |
| `notification` | `domain/*.py` (flat) |
| `scheduler` | `domain/*.py` (flat) |
| `identity` | `domain/*.py` (flat) |
| `edi-worker` | `core/*.py` (uses `core/` instead of `domain/`) ❌ |
| `edi-as2-server` | `core/*.py` (uses `core/` instead of `domain/`) ❌ |

### Root Cause
The taxonomy drifted organically as different engineers built different bounded contexts at different times, each making local decisions without a monorepo-wide standard. No canonical reference architecture was ever codified and enforced.

- **Action Item**: Define a single canonical folder taxonomy for every hexagonal layer as the enterprise standard. The `ucp` bounded context (with full `adapters/inbound/http/routers/`, `adapters/outbound/database/`, `application/use_cases/`, `domain/models/`, `ports/`) is the closest to the target state and should be adopted as the **reference pattern**. Refactor all other bounded contexts (`notification`, `scheduler`, `identity`, `edi`, `edi-worker`, `edi-as2-server`) to strictly conform to this pattern. Enforce via a Tach architecture rule or a structural test in each package.

## [Observability Architecture] Full Implementation of Layer 1 to Layer 3 Observability

- **Date Added**: 2026-08-20
- **Description**: The system currently relies on manual `trace_id` injection (Business Correlation IDs) for customer support tracking, and lacks a fully automated, layered technical observability strategy for infrastructure and distributed tracing.
- **Action Item**: Implement the complete 3-layer enterprise observability model:
  - **Layer 1 (Container Orchestration Probes):** Ensure all background workers (SQS/Postgres listeners) run isolated HTTP liveness/readiness ports (e.g., `9090`) to allow orchestrators like ECS/Kubernetes to auto-heal frozen containers.
  - **Layer 2 (Infrastructure Metrics & Scaling):** Ensure all queues and databases emit metrics to CloudWatch/Datadog to drive Horizontal Pod Autoscaling (HPA) or Target Tracking rules.
  - **Layer 3 (APM & Distributed Tracing):** Activate full OpenTelemetry auto-instrumentation (`opentelemetry-instrumentation-fastapi`, `-sqlalchemy`, `-boto3`) to silently intercept database timings and inject OTel context into SQS headers. Ensure the manual business `trace_id` is bridged by tagging the OTel spans (`span.set_attribute("business.trace_id", manual_id)`), allowing seamless pivot from customer support tickets to technical flame graphs.

## [Architecture Enforcement] Strict DTO / Command Object Boundary Standardization

- **Date Added**: 2026-08-23
- **Description**: The `edi` bounded context has established a strict, true enterprise-grade boundary using pure `@dataclass(frozen=True)` Command Objects (DTOs) in `application/dto.py`. However, other bounded contexts (like `identity`, `billing`, `ucp`) are currently suffering from dual-architectures, where web-specific frameworks (like FastAPI / Pydantic models) leak directly into core application logic. This violates Hexagonal Architecture and CQRS best practices.
- **Action Item**: Standardize the DTO / Command Object pattern across all bounded contexts in the monorepo. Every module must define a pure `application/dto.py` boundary for mutations (Commands) and reads (Queries), completely decoupling the business logic from HTTP adapters and 3rd-party validation frameworks like Pydantic.

## [Architecture Cleanup] Aggressive Cleanup of Legacy `bots` Engine Django Settings

- **Date Added**: 2026-08-23
- **Description**: The original `bots` EDI engine relied on a Django backend for configuration management (`botsinit`, `bots.ini`, and `settings.py`). In the modern architecture, the configuration is injected externally, and Django has been entirely removed from the data plane. Currently, `apps/edi/packages/edi/src/edi/core/bots/config/defaults/settings.py` is being kept alive by a `NullConfigProvider` / `LegacySettingsAdapter` stub to prevent `ImportError` cascades deep within the legacy X12/EDIFACT parsing logic.
- **Action Item**: Identify all legacy modules importing `edi.core.bots.config.defaults.settings`. Refactor the parsing logic to accept injected configuration objects (or remove the dependency entirely if the settings are unused). Delete `settings.py` and the `LegacySettingsAdapter` entirely.

## [Strict Typing/Linting] Complete Overhaul of Vendored BOTS Engine

- **Date Added**: 2026-08-23
- **Status**: TO DO
- **Description**: The core EDI processing engine (`apps/edi/packages/edi/src/edi/core/bots`) is a vendored legacy codebase that heavily utilizes `noqa` directives and is explicitly excluded from strict typechecking (`mypy`) to prevent CI failures. While this allowed us to stabilize the modern architecture around it, the engine itself remains a black box of untyped Python, making future maintenance and bug-fixing hazardous.
- **Action Item**: Incrementally remove `noqa` directives and fix underlying linting violations. Introduce strict type hints across the entire BOTS engine domain models, parsers, and grammar files. Once fully typed, remove the `src/edi/core/bots` and `src/edi/core/grammar` exclusions from the `[tool.mypy]` config to enforce enterprise-grade strict typing across the entire pipeline.

## [Architecture Cleanup] Replace Legacy `endesive` S/MIME Implementation with `cryptography`

- **Date Added**: 2026-08-24
- **Status**: TO DO
- **Description**: The AS2 module currently uses `endesive` for S/MIME signature verification and encryption/decryption of EDI data (`src/edi/adapters/outbound/security/smime.py`). While `endesive` provides high-level wrappers for S/MIME, it pulls in heavy, unwanted C-extension dependencies like `PyKCS11` (for HSMs) which caused Docker/CI build failures and required us to inject a dummy package to bypass. The team previously attempted to use the native `cryptography` library directly but faced challenges with standardizing the complex ASN.1 PKCS#7/CMS structures and MIME multipart construction for EDI payloads.
- **Action Item**: Research and implement a pure `cryptography`-based solution for S/MIME AS2 signing/encryption that doesn't rely on `endesive`. Once the native `cryptography` implementation is proven to cleanly handle AS2 EDI payloads, deprecate `endesive`, remove the `dummy-pykcs11` build override, and clean up the dependencies.

## [Architecture] Extract Scheduled Cleanup Jobs from EDI Orchestrator and Hookup Control Plane Jobs

- **Date Added**: 2026-08-25
- **Status**: TO DO
- **Description**: Currently, data-plane cleanup jobs are executing inside `edi-orchestrator-worker` (which polls `edi-orchestrator-jobs`), tightly coupling low-priority DB sweeps with high-throughput real-time AS2/X12 event processing. This queue name is also misleading since it implies "orchestration" rather than "background jobs". Furthermore, control-plane cleanup jobs (`EDI_CONTROL_PLANE_OUTBOX_CLEANUP`) are defined in the domain but the SQS polling logic is missing entirely from `edi-config-sync-worker`, leaving these tables unswept.
- **Action Item**:
  1. Rename `edi-orchestrator-jobs` to `edi-data-plane-jobs.fifo` (to match standard FIFO semantics) in Localstack setup and code.
  2. Following Shopify-style monolith patterns, create a dedicated `edi-background-worker` entrypoint to execute all EDI background jobs, isolating them from the high-throughput workers.
  3. Ensure the missing control-plane sweeper polling is wired up correctly in the new background worker infrastructure.

## [Architecture] Eliminate `NULL` Tenant IDs in Favor of `PLATFORM_TENANT_ID`

- **Date Added**: 2026-08-25
- **Status**: TO DO
- **Description**: Currently, the Identity ORM models (`Role`, `UserRole`) define `tenant_id` as `nullable=True`, using `NULL` to signify "Global" or "Platform" scoped resources. This is a non-enterprise pattern that breaks PostgreSQL referential integrity and makes writing Row-Level Security (RLS) policies and unified SQL constraints difficult. The system already defines a canonical `PLATFORM_TENANT_ID` in `identity_context.py`, but the database and repositories were never refactored to enforce it.
- **Action Item**:
  1. Refactor the Identity ORM models to enforce `nullable=False` on `tenant_id` columns.
  2. Update all Identity repositories (`role_repository.py`, `user_repository.py`, etc.) to use `PLATFORM_TENANT_ID` instead of `None` when querying or saving global platform resources.
  3. Create an Alembic database migration to backfill any existing `NULL` tenant records with the `PLATFORM_TENANT_ID` and apply the `NOT NULL` constraint.

## [RESOLVED] [Architecture] Centralize and Dynamic SQS Queue URL Resolution

- **Date Added**: 2026-08-25
- **Status**: ✅ RESOLVED
- **Description**: This work was completed: `SqsEventListener` implementations now accept logical queue names, adapters resolve absolute queue URLs at runtime through boto3 `get_queue_url()`, and explicit URL settings were removed from environment configuration and `Settings` classes.
- **Action Item**: Completed by migrating consumers to logical queue names and removing the obsolete URL configuration.

## [RESOLVED] [Architecture] Class Naming Taxonomy Drift (Listener vs Consumer)

- **Date Added**: 2026-08-26
- **Status**: ✅ RESOLVED
- **Description**: There is a class naming taxonomy drift in the Inbound Adapters layer regarding SQS message processors. We currently mix suffixes like `*EventListener`, `*SqsConsumer`, and `*Poller` (e.g., `SqsUcpEventListener`, `UcpEventsSqsConsumer`, `SqsPoller`) to describe similar asynchronous worker patterns. This causes confusion in the mental model.
- **Action Item**: Establish a canonical naming convention for asynchronous message handlers (e.g., standardizing on `*Consumer` or `*Listener`) and rename the divergent classes across all bounded contexts to adhere to this standard.

## [Architecture Testing] True Enterprise-Grade Data Plane Integration Tests

- **Date Added**: 2026-08-25
- **Status**: TO DO
- **Description**: The `test_sweeper_integration.py` in the EDI orchestrator currently uses a hack to simulate shards by dumping Data Plane tables (`audit_log`, `outbox`) directly into the `public` schema of the UCP global database. Furthermore, test data is inserted using hardcoded dictionaries rather than robust ORM factories, leading to brittle tests when domain models evolve (e.g., NotNull violations on new fields).
- **Action Item**: Refactor integration tests to use true enterprise-grade boundaries. Implement semantic schemas (`test_ctrl_ucp`, `test_data_shard_1`) inside the test database to strictly isolate global and shard data during local runs. Implement a Test Builder Pattern / ORM Factory (e.g., `DataPlaneOutboxBuilder`) to auto-generate valid underlying test data states, completely eradicating brittle hardcoded dictionaries.

## [RESOLVED] [Architecture] Refactor EDI Data & Control Plane Outboxes

- **Date Added**: 2026-08-26
- **Status**: ✅ RESOLVED
- **Description**: The EDI bounded context (both Data and Control planes) currently uses custom outbox jobs/sweepers. They need to be migrated to use the generic `outbox` infrastructure package (like the Notification bounded context did).
- **Action Item**: Migrate all custom EDI outbox jobs and sweepers to the generic `OutboxProcessorUseCase` and `SweepOutboxUseCase` from the platform outbox package. Remove duplicated legacy logic.

## [Architecture] Centralize DDD AggregateRoot and Eliminate Taxonomy Drift

- **Date Added**: 2026-08-26
- **Status**: TO DO
- **Description**: The codebase currently suffers from Taxonomy Drift in how it implements Domain-Driven Design (DDD) Aggregates. The `identity` and `ucp` bounded contexts define a custom `AggregateRoot` base class in `domain/aggregate_root.py`, while the `edi` context implements the exact same logic as a `DomainEventMixin` inside `domain/models.py`. This violates the Enterprise Architecture rule against duplicate infrastructure and file path taxonomy drift.
- **Action Item**: Create a centralized platform package (e.g., `core/platform/packages/ddd`) containing a single, unified `AggregateRoot` base class and `DomainEvent` definition. Refactor all bounded contexts (`identity`, `ucp`, `edi`) to import and inherit from this central package, completely removing the duplicated local implementations and Mixins.

## [Architecture] Centralize UnitOfWork (UoW) Transaction Management

- **Date Added**: 2026-08-26
- **Status**: TO DO
- **Description**: Currently, every bounded context (`ucp`, `edi`, etc.) implements an identical `SqlAlchemyUnitOfWork` (e.g., `SqlAlchemyUcpUnitOfWork`, `SqlAlchemyDataPlaneUnitOfWork`). The transaction lifecycle methods (`__aenter__`, `__aexit__`, `commit`, `rollback`) are highly duplicated. This includes the complex logic inside `commit()` that intercepts `psycopg` `IntegrityError`, parses the `pgcode`, and translates it into domain-friendly errors.
- **Action Item**: Centralize the base `UnitOfWork` into `core/platform/packages/orm/src/platform_orm/uow.py`. Bounded contexts should only define a thin subclass to type-hint their specific repositories, inheriting the heavy transaction and error-handling logic from the shared platform base class.

## [RESOLVED] [Architecture] Standardize Database Engine & Connection Pooling

- **Date Added**: 2026-08-26
- **Status**: ✅ RESOLVED
- **Description**: In the Dependency Injection setup (`bootstrap/container.py`), every single worker and API module manually initializes its database connection via `self._engine = create_async_engine(self.database_url, pool_pre_ping=True)`. This means connection pool sizes, timeouts, and recycling strategies are managed on a per-module basis, creating a fragmented infrastructure configuration.
- **Action Item**: Extract the `AsyncEngine` creation into a centralized `DatabaseProvider` within `core/platform/packages/orm`. Update all DI containers across the monorepo to rely on this provider to guarantee identical infrastructure tuning and a single place to modify pool settings.

## [Architecture] Eliminate Dual-Architecture in Database Exception Translation

- **Date Added**: 2026-08-26
- **Status**: TO DO
- **Description**: Different bounded contexts handle unique database constraints differently: `ucp` catches and translates constraint violations centrally at the Unit of Work layer (inside `commit()`), whereas `edi` catches them locally inside individual Repositories (e.g., `_constraint_name(e: IntegrityError)` inside `as2_partner_repository.py`), wrapping them into custom exceptions. This creates a confusing dual-architecture for developers writing Application Use Cases.
- **Action Item**: Standardize exception translation. Build a `BaseSqlAlchemyRepository` in `platform_orm` that exposes standard methods (`save`, `get`) wrapped in a centralized error-interceptor decorator to translate all raw PostgreSQL exceptions into a unified hierarchy of Platform Infrastructure Errors.

## [Architecture] Centralize SQS Message Pump / Polling Infrastructure

- **Date Added**: 2026-08-26
- **Status**: TO DO
- **Description**: While `AwsSqsPublisher` successfully centralizes the publishing of events, the consumer side exhibits architectural drift. Classes like `UcpEventsSqsConsumer` (UCP) and `NotificationOutboxSweeperJob` (Notification) duplicate the boilerplate for polling SQS, acknowledging messages, and handling leases (`mark_completed`, `mark_failed`). Naming conventions also drift between `jobs/` and `workers/`.
- **Action Item**: Build a centralized `BaseMessagePump` or `SqsConsumerManager` in `core/platform/packages/pubsub` that natively handles the `receive_message -> process -> delete_message` lifecycle loop, so that bounded contexts only need to inject a pure `MessageHandler` callback.
