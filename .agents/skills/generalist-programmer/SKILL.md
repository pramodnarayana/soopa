---
name: generalist-programmer
description: Enterprise Backend Software Engineer profile for implementing Hexagonal Python domain models, co-located CQRS use cases, explicit SQLAlchemy Data Mappers, and FastAPI/event adapters.
---

# Enterprise Backend Engineer Playbook

All universal monorepo laws in `.agents/AGENTS.md` apply automatically. Use this playbook when implementing or refactoring Python services, domain logic, repositories, or API endpoints.

## Implementation Order (Hexagonal + Co-located CQRS)

1. **Co-located Command / Query DTOs & Domain Models First**:
   - Define immutable `@dataclass(frozen=True)` Command/Query DTOs at the top of the Use Case file that handles them (shared read models in `queries.py` or `responses.py`). Never create a monolithic `dto.py` god file.
   - Implement behavioral DDD Aggregates (`AggregateRoot` / `DomainEventMixin`) and Value Objects in `domain/` with zero external imports, prefix-based IDs (`cls.new_id()`), and `Result[T, E]` return types for all expected domain validations.
   - Record state-change events internally via `self.add_domain_event(...)` using pure `@dataclass(frozen=True)` event objects.
2. **Outbound Port Protocols (`ports/outbound/`)**:
   - Type every Port method strictly against Domain Models, `@dataclass(frozen=True)` DTOs, or `tuple[ADTO, BDTO] | None` for joins — never `dict[str, Any]` or ORM models.
3. **Application Use Cases (`application/use_cases/`)**:
   - Orchestrate Ports and Domain Aggregates cleanly using `Result[T, E]` (never `try/except` ladders for expected errors, never procedural `publish_outbox_event()`).
   - Emit structured `structlog` events (`logger.info(...)` on major transitions, `logger.error(...)` on terminal failures, `logger.exception(...)` in `except` blocks — never f-strings, never `logger.warning()` for actual errors).
4. **Infrastructure Adapters (`adapters/`)**:
   - **Database Repositories:** Use explicit, dot-notation Data Mapper helpers (`_to_domain_model`, `_update_record_from_domain`) — zero `getattr()`, zero reflection loops. Flush aggregate domain events to the outbox automatically inside `save()` via `database.outbox_serializer.serialize_domain_event()`. Follow the package's local naming prefix (`SqlAlchemy*` vs `Postgres*`) strictly.
   - **HTTP / Event Inbound Adapters:** Translate FastAPI Pydantic request schemas / event payloads into pure Command DTOs at the boundary, enforce tenant-scoped capability checks via `AuthzRuntimePort` (Local PDP, fail-closed `503`), and map `Result.err` to clean HTTP responses.
   - **Zero Adapter-to-Adapter Coupling:** Depend exclusively on abstract Ports; wire concrete adapters only in the Composition Root (`bootstrap/container.py`).
5. **Control Plane → Data Plane Replication**:
   - When adding or modifying replicated Control Plane tables, update `control_plane.py`, `data_plane.py`, `replication_mappers.py`, `replication_registry.py` (`REPLICATION_GRAPH`), and amend the single dev migration files (`global` + `tenant`) in place.

## Local Verification Gate (Before Reporting Done)

1. `.venv/bin/ruff check <touched_paths>`
2. `.venv/bin/mypy <touched_paths>` (zero errors, zero `# type: ignore`, zero `Any`)
3. `.venv/bin/tach check` (module boundary validation)
4. `.venv/bin/pytest <unit_and_narrow_integration_tests>`
