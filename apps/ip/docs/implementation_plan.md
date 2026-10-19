# Soopa Integration Platform (`apps/ip`)
## Phased Implementation Plan

- **Document:** Engineering Implementation Roadmap & Phased Execution Plan
- **Target Domain:** Energy & Utilities (MDM, AMI, CIS, ERP) + Multi-SaaS (500+ Apps)
- **Status:** Approved Implementation Roadmap
- **Location:** `apps/ip/docs/implementation_plan.md`

---

## 1. Execution Principles

1. **Strict Hexagonal Boundaries:** Every submodule defines pure `@dataclass(frozen=True)` DTOs and Protocols first before any concrete adapter or database model is written.
2. **Red-Green-Refactor Cycle:** Unit tests for domain models and pure business logic must be written first and achieve 100% test pass rates without external mocks.
3. **Staged Transactional Outbox Invariant:** Every layer boundary handoff (`L1 -> L2 -> L3 -> L4 -> L5`) must commit its state and its domain event into the local PostgreSQL outbox in the same transaction.
4. **Database Safety:** All integration tests execute within nested SQLAlchemy transactions (`connection.begin_nested()`) and roll back upon completion, guaranteeing zero shared-state database pollution.
5. **No Broken Migrations:** We maintain a clean, squashed migration baseline during active development.

---

## 2. Implementation Roadmap Overview

| Phase | Focus Area | Deliverables | Status | Target Submodules |
| :--- | :--- | :--- | :--- | :--- |
| **Phase 0** | Workspace & Scaffolding | Monorepo layout, `pyproject.toml`, database migration baseline | **DONE** | All |
| **Phase 1** | Connection CDK & Auth Engine | Auth strategies, AES-256 cipher, reference Itron connector | **DONE** | `ip-connectors` |
| **Phase 2** | Lifecycle Control Plane & Storage | `ip.connections` table, FastAPI control plane, deactivation/re-link | **DONE** | `ip-connectors`, `ip-storage` |
| **Phase 3** | Declarative 500+ Connector Engine | JSON/OpenAPI action engine, dynamic UI property schemas, catalog API | Up Next | `ip-connectors` |
| **Phase 4** | Ingestion Gateway (L1) & Outbox | Webhook/Kafka ingress, S3 tiered offloading, `inbound_record.created` | Up Next | `ip-gateway`, `ip-storage` |
| **Phase 5** | Universal Replica Worker (L2) & Outbox | Parsing, SHA-256 deduplication, upsert `replica_entities`, outbox event | Up Next | `ip-replica`, `ip-storage` |
| **Phase 6** | Canonical Domain & GEM (L3) & Outbox | Canonical Energy DTOs (CIM), GEM cross-reference resolution, outbox event | Up Next | `ip-domain`, `ip-engine` |
| **Phase 7** | Hydrator & "Stitches" (L4) & Outbox | Dynamic mapping templates, payload hydration, `dispatch.enqueued` outbox | Up Next | `ip-engine` |
| **Phase 8** | Delivery Worker (L5) & Token Lock | Redis auth distributed lock, HTTP/SFTP/Kafka dispatch, retries/circuit breaker | Up Next | `ip-engine`, `ip-connectors` |
| **Phase 9** | Support Timeline Ledger | `business_trace_id`, correlation ledger across all 5 stages, support API | Up Next | `ip-timeline` |
| **Phase 10** | AI Source-Introspection (MCP) | Model Context Protocol live query tools for support copilot | Up Next | `ip-ai` |
| **Phase 11** | End-to-End Enterprise Hardening | Full E2E simulation (Itron AMI -> SAP IS-U sync, failure replays) | Up Next | All |

---

## 3. Detailed Phase Breakdown

---

### Phase 0: Workspace & Scaffolding (COMPLETED)
- Configured `pyproject.toml` workspace sources and dependencies (`ip = { workspace = true }`).
- Configured architectural boundary checker in `tach.toml`.
- Established database migration infrastructure.

---

### Phase 1: Connection CDK & Auth Engine (COMPLETED)
- Implemented `ConnectorPort`, `AuthenticatorPort`, and all 7 auth strategies:
  `NoAuthStrategy`, `BasicAuthStrategy`, `BearerAuthStrategy`, `ApiKeyAuthStrategy`, `OAuth2Strategy`, `MtlsAuthStrategy`, `CustomAuthStrategy`.
- Implemented `AesGcmEnvelopeCipher` (AES-256-GCM) for credential encryption at rest.
- Implemented reference `ItronMdmConnector`.
- 100% pure unit test coverage (31 passing tests).

---

### Phase 2: Lifecycle Control Plane & Storage (COMPLETED)
- Control plane database tables: `ip.connections`, `ip.connection_catalogs`.
- Repository adapters: `SqlAlchemyConnectionRepository`, `SqlAlchemyCatalogRepository`.
- Application use cases: `CreateConnectionUseCase`, `CheckConnectionUseCase`, `DiscoverCatalogUseCase`, `DeactivateConnectionUseCase`, `RelinkConnectionUseCase`.
- Wired REST endpoints into `unified-api` (`/connections`).
- Registered domain exception handlers.

---

### Phase 3: Declarative 500+ Connector Engine & Dynamic UI
- **Goal:** Enable self-service integration for 500+ apps without bespoke React forms or custom Python classes.
- **Tasks:**
  1. Define `ConnectorPropertySchema` model (`shortText`, `secretText`, `dropdown`, `oauth2`).
  2. Implement `DeclarativeHttpConnector`:
     - Reads JSON/YAML OpenAPI manifests.
     - Implements `spec()`, `check()`, `read()`, and `write()` dynamically.
  3. Implement Native Protocol Adapters:
     - Kafka consumer adapter (`aiokafka`).
     - SFTP batch file transfer adapter (`asyncssh`).
     - RabbitMQ consumer adapter (`aio-pika`).
  4. Expose Catalog UI API (`GET /api/v1/catalog/apps`, `GET /api/v1/catalog/apps/{appId}/spec`).

---

### Phase 4: Ingestion Gateway (L1) with Transactional Outbox
- **Goal:** Capture raw payloads with sub-20ms ACK and zero data loss.
- **Tasks:**
  1. Create database migration: `ip_data.inbound_records`.
  2. Implement Tiered Storage Port:
     - Payloads $< 64\text{ KB}$: save inlined in PostgreSQL `raw_payload`.
     - Payloads $\ge 64\text{ KB}$: stream to S3 / MinIO, save `s3_key`.
  3. Implement Inbound Ingress Controller:
     - Assigns `business_trace_id` and extracts `business_correlation_id`.
     - Commits raw record and registers `inbound_record.created` into PostgreSQL Outbox.
     - Replies `202 Accepted` immediately.

---

### Phase 5: Universal Replica Worker (L2) with Transactional Outbox
- **Goal:** Maintain exact external system truth with change detection and replayability.
- **Tasks:**
  1. Create database migration: `ip_data.replica_entities`.
  2. Implement Replica Worker:
     - Consumes `inbound_record.created` outbox events.
     - Computes SHA-256 `data_hash`. If unchanged, drop and skip downstream processing.
     - Idempotently upserts snapshot into `ip_data.replica_entities`.
     - Commits state and registers `replica_entity.updated` into the Outbox.

---

### Phase 6: Canonical Domain & GEM (L3) with Transactional Outbox
- **Goal:** Transform vendor structures into Universal Standards and resolve cross-system IDs.
- **Tasks:**
  1. Create database migrations: `ip_data.canonical_entities` and `ip_data.global_entity_map`.
  2. Define Canonical Energy DTOs (`MeterDevice`, `UsagePoint`, `IntervalReading`).
  3. Implement Global Entity Map (GEM) Aggregate:
     - Look up or bind `Source ID <-> Canonical UUID <-> Destination ID`.
  4. Implement L3 Normalizer Worker:
     - Consumes `replica_entity.updated`.
     - Maps to Canonical DTO, updates GEM.
     - Commits state and registers `canonical_entity.normalized` into the Outbox.

---

### Phase 7: Hydrator & "Stitches" (L4) with Transactional Outbox
- **Goal:** Transform canonical records into target destination payloads.
- **Tasks:**
  1. Create database migration: `ip_data.field_mappings` and `ip_data.outbound_dispatches`.
  2. Implement Hydration Engine:
     - Merges Canonical DTO values into the destination JSON template.
  3. Implement L4 Hydrator Worker:
     - Consumes `canonical_entity.normalized`.
     - Resolves destination credentials and target action.
     - Commits `ip_data.outbound_dispatches` and registers `outbound_dispatch.enqueued` into the Outbox.

---

### Phase 8: Delivery Worker (L5) & Token Lock
- **Goal:** Reliable execution against destination APIs with distributed token safety and retries.
- **Tasks:**
  1. Implement `TokenManagerService`:
     - Redis distributed lock (`redlock`) for OAuth2 token refresh concurrency.
  2. Implement L5 Delivery Worker:
     - Consumes `outbound_dispatch.enqueued`.
     - Injects valid credentials and fires HTTP/SFTP/Kafka call.
     - Retries with exponential backoff on transient errors (429, 502, 503).
     - Marks dispatch `DELIVERED` or `FAILED`.

---

### Phase 9: Support Timeline Ledger & Business Correlation
- **Goal:** Real-time operational transparency for customer support teams.
- **Tasks:**
  1. Create database migration: `ip_data.business_timeline_ledger`.
  2. Implement Timeline Interceptor:
     - Injects breadcrumbs at each outbox transition (L1, L2, L3, L4, L5).
  3. Expose Support Timeline API:
     - `GET /api/v1/timeline?correlation_id=MTR-101`.
     - Sub-15ms response returning chronological journey.

---

### Phase 10: AI Source-Introspection Agent (MCP)
- **Goal:** Live operational querying into external systems via Model Context Protocol.
- **Tasks:**
  1. Implement MCP endpoints and tools in `ip-ai`.
  2. Expose `tool_query_connector(connection_id, query)` calling connector's live `query()` method.
  3. Implement PII scrubbing filter before passing data to LLM context.

---

### Phase 11: End-to-End Enterprise Hardening & Integration Test Suite
- **Goal:** Full enterprise verification across the completed pipeline.
- **Tasks:**
  1. Write end-to-end integration scenario:
     - Webhook/SFTP ingest from Itron AMI $\rightarrow$ L1 S3 offload $\rightarrow$ L2 replica $\rightarrow$ L3 CIM normalizer $\rightarrow$ L4 SAP payload $\rightarrow$ L5 mock delivery.
  2. Test failure isolation and replay:
     - Simulate SAP failure $\rightarrow$ verify L1 & L2 remain committed $\rightarrow$ replay Outbox.
  3. Verify static analysis: `ruff check` and `mypy --strict` with zero warnings.
