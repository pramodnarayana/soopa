# Architectural Standards
- ALWAYS default to Enterprise-Grade architectural patterns over minimum viable products (MVPs) or shortcuts.
- Use proper separation of concerns (e.g. TanStack layout routes instead of polluting `__root.tsx`).
- Implement robust error handling, proper typing, and scalable folder structures from the very first commit.
- Never use anti-patterns to save time. If a proper implementation takes more steps, take the time to do it right.

# Enterprise Coding Standards (Strictly Enforced)
- **Hexagonal Architecture**: Keep the domain isolated. Ports and Adapters must strictly separate business logic from external frameworks, APIs, and databases.
- **SOLID Principles**: Adhere to Single Responsibility, Open/Closed, Liskov Substitution, Interface Segregation, and Dependency Inversion.
- **Red-Green-Refactor Cycle**: Write failing tests first, make them pass, then refactor to clean up.
- **Zero Mocks for Pure Logic**: Do not mock pure business logic. Domain models and core logic must be self-contained and testable without external mocks.
- **Narrow Integration Tests**: Stop writing "forced" unit tests with excessive mocking just to hit coverage limits. Focus on writing Narrow Integration Tests that actually connect to databases/external systems via test harnesses to test real behavior.
- **No Static Mutable Singletons**: Avoid global state. Use dependency injection to pass dependencies dynamically.
- **Infra & Business Decoupling**: Infrastructure code (AWS, SQS, DB connections) must never leak into business/domain logic.
- **No Leakage**: Data transfer objects (DTOs), API models, and ORM models must not leak across their respective boundaries. Map them appropriately.
- **DRY (Don't Repeat Yourself)**: Avoid code duplication. Extract shared logic into reusable, well-named functions/modules.
- **Chunked Database Mutations**: NEVER use unbounded `DELETE` or `UPDATE` queries that could lock massive datasets. Background jobs (like sweeping or data retention) MUST use a chunked iteration (e.g. a `while True` loop with a small `LIMIT`), commit on each iteration, and yield execution (`await asyncio.sleep(0.1)`) to allow PostgreSQL to run autovacuum and serve live API traffic.
- **Strict API/Worker Decoupling**: NEVER run asynchronous background loops, Queue Pollers (SQS), or Outbox Relays inside the web API container (e.g., FastAPI `lifespan.py`). The web API container must be 100% pure and only serve HTTP requests. All background polling and async processing must be physically isolated into a dedicated worker container.

# Package Manager
- ALWAYS use `pnpm` for frontend/Node.js package management instead of `npm`. Do not use `npm install`.

# Destructive Commands
- NEVER use destructive terminal commands like `git checkout`, `git restore`, `git reset`, `git clean`, or `rm -rf` without explicitly asking for and receiving the user's permission first. Always prefer precise code-editing tools for reverting changes.

## Development Phase Policy

- **Phase:** Active Development
- **Backward Compatibility:** NOT a concern. Do NOT prioritize backwards compatibility, legacy facade patterns, or minimizing code churn when refactoring.
- **Enterprise Grade:** Always prioritize true enterprise-grade software architecture, explicit imports, separation of concerns, and clean architectural principles over 'quick fixes'. If a 'god file' needs to be split, update all dependent files explicitly rather than relying on re-exports/facades.

# Local Infrastructure
- NEVER attempt to work around a missing migration with code changes. Missing tables are an infrastructure problem, not a code problem.
- After any change to a Drizzle schema file, remind the user to run `pnpm db:migrate` to apply the migration locally.

# Platform Architecture Paradigms (Core Tenets)

The following paradigms define the entire system structure. Any new design or module MUST strictly adhere to them:
1. **Domain-Driven Design (DDD)**: Systems must be broken down into Generic Subdomains/Core Domains with strict Bounded Contexts. Use Ubiquitous Language. Enforce strict isolation where business logic (Domain Layer) has ZERO external dependencies.
2. **Modular Monolith**: Code must be physically co-located in the monorepo and run against the same database cluster, but logically strictly isolated. Communication between modules must happen asynchronously via Outbox Patterns or Events, NOT via direct cross-module function calls or SQL joins.
3. **Shopify-Style Deployment Strategy (Single Image, Multiple Containers)**: Avoid versioning hell. We build one single massive Docker image containing the entire Modular Monolith codebase. At runtime, we spin up multiple containers from this identical image, each acting as a different worker (e.g., API Web Server, SQS Poller, Outbox Sweeper, Cron Scheduler) simply by executing a different entrypoint.

# Enterprise Observability (Strictly Enforced)

- **Cornerstone Observability**: Observability is a first-class architectural concern, not an afterthought. You must NEVER use Python's standard `import logging` or `logging.getLogger(__name__)`.
- **Structured JSON Logging**: ALWAYS use the injected `ILogger` port or `structlog.get_logger()` from the platform observability package.
- **Context Injection (No String Interpolation)**: NEVER use f-strings to inject variables into log messages. ALWAYS use structured context binding (e.g., `logger.info("event_processed", tenant_id=tenant_id, event_id=event.id)` or `bound_logger = logger.bind(tenant_id=tenant_id)`).
- **Exceptions**: Use `logger.exception("operation_failed", reason=...)` inside except blocks to automatically capture the stack trace into the structured log payload.
- **Comprehensive Coverage**: We should always put enough logs for observability. Log major state transitions (e.g., started, completed), skipped actions, and dropped events so that every operational flow is fully traceable.

# Architectural Consistency (No Dual-Architectures)

- **Strict Consistency Enforcement**: REJECT code that introduces or perpetuates dual-architectures (implementing the same pattern in two different ways across the codebase). Explicitly flag and reject:
    - **Frontend**: Mixing UI component libraries (e.g., Radix UI vs Base UI), state management paradigms, or API clients (Axios vs native fetch).
    - **Backend**: Mixing database access patterns (ORM models vs raw SQL `text()` queries for standard CRUD), mixing event dispatching methods (e.g., manually calling `register_event(...)` vs DDD `add_domain_event()`), or mixing API clients.
    - **General**: If there is an established enterprise standard for a pattern, any deviation from that standard in a new or refactored flow must be rejected.
    - **Strict File Taxonomy Consistency**: Different Bounded Contexts must not drift in their internal folder/file naming taxonomies for identical architectural concepts. If one context uses `database/models/events.py`, another context must use `database/models/events.py` for its events, rather than arbitrary structures. Call out any file path taxonomy drift across domains as a CRITICAL violation.
