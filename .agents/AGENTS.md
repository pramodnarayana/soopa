# Architectural Standards (Single Source of Truth)

These laws apply globally to every agent, skill, PR, and package across the monorepo. Role-specific skills extend these standards with domain playbooks without duplicating them.

- **Enterprise-Grade by Default**: Always implement enterprise-grade architecture over MVPs or shortcuts. Take the time to do it cleanly from the first commit.
- **Active Development Policy (Clean V1)**: Backward compatibility is **not** a concern. Never introduce legacy facades, compatibility shims, or dual paths to minimize code churn. When splitting a god file or replacing a model, delete the legacy path cleanly and update all call sites explicitly.
- **No Destructive Commands**: Never execute `git checkout`, `git restore`, `git reset`, `git clean`, or `rm -rf` without explicit user permission. Never commit or push without explicit user permission.
- **Package Managers**: Always use `pnpm` (never `npm`) for Node.js/TypeScript and `uv` / repo `.venv` for Python.

---

# Platform Architecture Paradigms

1. **Domain-Driven Design (DDD) & Hexagonal Architecture**:
   - Break systems into strict Bounded Contexts with Ubiquitous Language.
   - Keep the Domain Layer (`domain/`) 100% pure with zero framework, ORM, HTTP, or cloud SDK imports.
   - Communicate across bounded contexts asynchronously via Transactional Outbox & Events — never via direct cross-module calls or cross-schema SQL joins.
2. **Modular Monolith & Shopify-Style Deployment**:
   - Co-locate bounded contexts in the monorepo; build a single Docker image and run physically isolated containers (Web API, Config Sync Watch, Orchestrator, Delivery, Jobs/Cron) via distinct entrypoints.
   - **Strict API/Worker Decoupling**: The Web API container (`unified-api`) MUST remain 100% pure HTTP serving — never run background loops, queue pollers, or outbox relays in FastAPI lifespan.
3. **Control Plane vs. Sharded Data Plane & Queue-Free Sync**:
   - Global Control Plane (`global_db`) stores tenant topology, identity/authz, and configuration; sharded Data Planes store tenant runtime data.
   - Replicate configuration from Control Plane → Tenant Data Plane declaratively via `REPLICATION_GRAPH` over **Queue-Free HTTPS/SSE Dynamic Watch** (`config_sync`) — zero ad-hoc sync scripts.
   - Event transport uses the centralized **PostgreSQL Pub/Sub (`db://`)** platform package (`pubsub`) — zero AWS SNS/SQS dependencies.
4. **Identity & 4-Layer Local PDP Authorization**:
   - Authentication uses **Casdoor OIDC**; authorization evaluates tenant-scoped capabilities via the **4-Layer Local PDP** (`AuthzRuntimePort`, PostgreSQL `ltree` hierarchy, L1 cache, fail-closed `503` when PDP runtime is unavailable).
5. **Centralized Platform Packages (Zero Duplicate Infrastructure)**:
   - Extract all domain-agnostic infrastructure into `core/platform/packages/` named by capability (`database`, `pubsub`, `outbox`, `config_sync`, `secret_store`, `storage`, `sharding`, `observability`, `seedwork`) — never by vendor/technical detail (e.g., never `orm` or `sqs`).
   - **Centralized DB Engine**: Never call `create_async_engine` or `async_sessionmaker` inside bounded contexts; inject `DatabaseProvider` / `DatabaseRouter` from `database`.
6. **Pure & Independent Seedwork**:
   - `seedwork` and `infra_seedwork` MUST remain 100% generic with zero references to bounded contexts (`platform`, `edi`, `ucp`, `identity`, `notification`, `ip`), domain paths, or domain commands. Drive seedwork strictly via Inversion of Control (IoC).
7. **3-Stage Notification Pipeline**:
   - **Stage 1 (Ingestion)**: Upstream contexts use `notify()` to enqueue a raw `notification.requested` event in their local outbox inside the same DB transaction.
   - **Stage 2 (Compiler)**: Notification context checks preferences, renders templates, writes the immutable `NotificationRecord`, and emits `channel.requested` into its outbox.
   - **Stage 3 (Delivery)**: Stateless delivery workers execute HTTP delivery calls with retries via consumer NACKs without touching templates or domain tables.
   - **Dual Outbox Reliability**: Wire both real-time Outbox Relay and fallback Cron Sweeper.

---

# Strict Coding, Typing & Error Standards

- **SOLID & DRY**: Enforce Single Responsibility, Open/Closed, Liskov Substitution, Interface Segregation, Dependency Inversion, and zero duplicated logic.
- **No Type Suppressions or `Any`**: Never use `# type: ignore` or `typing.Any` to bypass `mypy`. Resolve every mismatch structurally via `@dataclass(frozen=True)` DTOs, Protocols, `JsonValue`/`JsonDict`, or explicit return types.
- **Co-located CQRS DTO Standard**:
  - Command and Query DTOs (`@dataclass(frozen=True)`) MUST be co-located directly inside the Use Case file that handles them (e.g., `CreatePartnerCommand` at the top of `create_partner_use_case.py`). Shared read/response DTOs live in `queries.py` or `responses.py`.
  - Never create a single massive `dto.py` god file or arbitrary `dtos/<entity>.py` folders.
  - Never pass FastAPI/Pydantic `BaseModel`, ORM models, or raw `dict` across the Application Layer boundary; translate at HTTP/Event adapters.
- **First-Class Error Handling (`Result[T, E]`)**:
  - Never raise exceptions for known, expected operational or domain outcomes (validation failures, HTTP 4xx/5xx, missing records). Return structured `Result[T, E]` values or use polymorphic Strategy handlers.
  - Never use bare `except Exception:` to silently swallow failures.
- **No Boolean Control Coupling**: Never pass boolean flags (`fail_fast=True`, `raise_exceptions=True`) to switch core control flow. Inject a polymorphic Strategy / Port instead.
- **Strict Test/Prod Separation**: Production code MUST never import test tools or branch on `if env == "test":`. Fakes and overrides live strictly in `tests/` or `testing/`.
- **No Static Mutable Singletons**: Pass all dependencies via Dependency Injection / Composition Root.
- **Zero Adapter-to-Adapter Coupling**: Adapters depend strictly on abstract Ports (Protocols); only the Composition Root assembles concrete adapters.
- **Explicit Data Mappers & No `getattr()` Masking**:
  - Never use `getattr(obj, "field", None)` or dynamic reflection loops (`dataclasses.fields()`, `__dict__.items()`). Map every field explicitly via dot notation (`_to_domain_model`, `_update_record_from_domain`) so schema drift fails statically in `mypy`.
- **DDD Aggregates & Centralized Outbox Serialization**:
  - Domain events MUST be pure `@dataclass(frozen=True)` (never Pydantic `BaseModel`).
  - Record events via `self.add_domain_event(...)` inside Aggregate Roots and drain them automatically in Repository `save()` — never call procedural `publish_outbox_event()` from Use Cases.
  - Serialize all outbox events via `database.outbox_serializer.serialize_domain_event()`.
- **Prefix-Based IDs**: Generate domain IDs via class-level `ID_PREFIX` + `seedwork.utils.generate_id(...)` (cryptographically secure bytes) — never bare UUIDs or hardcoded IDs.
- **No Magic Strings**: Extract semantically meaningful string/numeric constants into `StrEnum` / `IntEnum` or `@dataclass(frozen=True)` Constant classes.
- **No Inline Imports**: Place all imports at the top of the file; resolve cycles architecturally.
- **Chunked Database Mutations**: Background retention/cleanup jobs MUST mutate in small `LIMIT` chunks inside a loop, committing each batch and yielding (`await asyncio.sleep(0.1)`).
- **Linter Exemptions (`# noqa`)**: Never use file-level `# ruff: noqa`. Inline `# noqa: <RULE>` is permitted only for unavoidable edge cases with an inline architectural justification comment.

---

# Enterprise Observability

- **Zero Stdlib Logging**: Never use `import logging` or `print()`. Always use injected `ILogger` or `structlog.get_logger()`.
- **Structured Context Only**: Never use f-strings in log messages. Bind structured fields (`logger.info("event_processed", tenant_id=tenant_id, resource_id=resource_id)`).
- **Correct Log Levels**: Use `logger.exception(...)` inside `except` blocks. Reserve `logger.warning(...)` strictly for benign transient retries — log all terminal failures, validation rejections, and security violations as `logger.error(...)`.

---

# Architectural Consistency & Audit Methodology

- **Zero Dual-Architectures**: Reject mixing paradigms for the same concept:
  - *Frontend*: Never mix UI primitive kits (`@soopa/ui` + Radix UI + shadcn only — zero Base UI), state managers, or HTTP clients. Use TanStack Router layout routes without polluting `__root.tsx`.
  - *Backend*: Never mix SQLAlchemy ORM and raw `text()` CRUD, never mix procedural event dispatch with DDD `add_domain_event()`, and maintain strict local adapter naming taxonomy (`SqlAlchemy*` vs `Postgres*`) and cross-context file taxonomy.
- **Top-Down Execution Path Tracing**: Audit from entrypoints (`main.py`, routers, workers) down through Use Cases and Adapters to verify uniform control flow across all services.

---

# Infrastructure, Configuration & Migrations

- **Separate Infra PR (Expand-and-Contract)**: Changes to Stateful Infra Pulumi stacks (`foundation`, `platform`, `data`, `routing`, `casdoor`, `openas2` — deployed by `provision-infra.yml`) MUST ship in a dedicated Infra PR and complete `Infra Rollout` **before** Stateless App stacks (`apps/api`, `apps/edi/as2`, `platform/migrator` — deployed by `deploy.yml`) consume any new stack outputs.
- **IaC Environment Injection**: Never use runtime AWS discovery APIs (e.g., `get_queue_url`) inside app containers. Inject ARNs, domains, and endpoints from Pulumi as environment variables.
- **Single Source of Truth Config (`.env.example`)**: Both local and CI load configuration from `.env` (CI copies `.env.example` → `.env`). Never hardcode dummy env vars inline in `package.json` or CI YAML.
- **Single Development Migration File**: Keep a single migration file per database (`global` / `tenant`) during active development — amend in place rather than chaining consecutive migration files. Never work around a missing migration in code; remind the user to run migrations after schema changes.

---

# Enterprise Testing Standards

- **Red-Green-Refactor**: Write failing tests first, implement to pass, then refactor cleanly.
- **Zero Mocks for Pure Logic**: Test Domain models, Value Objects, and pure helpers directly without mocks.
- **Narrow Integration Tests**: Test database repositories and end-to-end use cases against real local PostgreSQL inside nested `SAVEPOINT` rollbacks (`connection.begin_nested()`) with self-contained fixtures (never rely on global `seed.py` state).
- **SRP Test Naming**: Every test function verifies one focused invariant; avoid conjoined `_and_` test function names.
- **Mandatory Quality Gates**: Verify with `ruff`, `mypy`, `tach check`, and `pytest` (Python), plus `oxlint`, `tsc --noEmit`, and `vitest run` (TypeScript).
