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

### Phase 3: Declarative 500+ Connector Engine & Dynamic UI (COMPLETED)
- **Goal:** Enable self-service integration for 500+ apps without bespoke React forms or custom Python classes.
- **Deliverables:**
  1. Dynamic UI & Manifest Domain Models (`ConnectorPropertySchema`, `ConnectorProperty`, `PropertyType`, `OAuthConfig`, `DeclarativeManifest`, `HttpActionSpec`, `PaginationConfig`).
  2. Declarative HTTP Engine (`DeclarativeHttpConnector`) implementing dynamic `spec()`, `check()`, `discover()`, cursor/offset `read_stream()`, and `write_record()`.
  3. Pre-seeded connector catalog (`ConnectorCatalogRegistry`) covering Salesforce CRM, HubSpot, Stripe Payments, ServiceNow ITSM, Itron OpenWay Riva MDM, and SFTP File Gateway.
  4. Native Protocol Connector (`SftpConnector`) for secure batch file transfers using pure `paramiko`.
  5. Application Use Cases (`ListCatalogAppsUseCase`, `GetAppSpecUseCase`) and Port (`CatalogRegistryPort`).
  6. Inbound HTTP Router & DTOs in `unified-api` (`GET /api/v1/ip/catalog/apps`, `GET /api/v1/ip/catalog/apps/{app_id}/spec`).
  7. Automated testing: 13 unit tests + 6 integration tests passing cleanly; 100% boundary check validated via `tach check`.

---

### Phase 4: Ingestion Gateway (L1) with Transactional Outbox (COMPLETED)
- **Goal:** Capture raw payloads with sub-20ms ACK and zero data loss on dedicated IP shards.
- **Deliverables:**
  1. Shard Database Schema: Amended `inbound_records` with composite primary key `(id, received_at)`, `tenant_id`, `business_trace_id`, `business_correlation_id`, `raw_payload` JSONB, `s3_key`, and indexed queries.
  2. Tiered Storage Port & Adapter (`TieredStoragePort`, `TieredStorageAdapter`):
     - Payloads $< 64\text{ KB}$: saved inlined in `raw_payload`.
     - Payloads $\ge 64\text{ KB}$: streamed to S3 / object storage, saving `s3_key`.
  3. Domain Models & Events:
     - `InboundRecord` aggregate root with high-entropy ID generation (`ip_inb_...`, `ip_trc_...`) and SHA-256 payload hashing.
     - `InboundRecordCreatedEvent` pure domain event for downstream L2 consumers.
  4. Repository Adapter: `SqlAlchemyInboundRecordRepository` with strict explicit data mappers and transactional outbox event draining (`IpOutboxRecord`).
  5. Application Use Case: `IngestRecordUseCase` with co-located `IngestRecordCommand` and `IngestRecordResultDTO`.
  6. Inbound Ingress Controller: `ingress_router.py` wired into `unified-api` (`POST /api/v1/tenants/{tenant_id}/ip/ingress/{connection_id}?stream=...`) replying `202 Accepted` with `business_trace_id` and storage telemetry.
  7. Automated Testing: 47 unit tests + 13 integration tests passing cleanly; 100% boundary check validated via `tach check`.

---

### Phase 5: Universal Replica Worker (L2) with Transactional Outbox
- **Goal:** Maintain exact external system truth with change detection and replayability on dedicated IP shards.
- **Tasks:**
  1. Create shard database migration (`public.replica_entities` with GIN indexing and RLS).
  2. Implement Replica Worker:
     - Consumes `inbound_record.created` outbox events.
     - Computes SHA-256 `data_hash`. If unchanged, drop and skip downstream processing.
     - Idempotently upserts snapshot into `public.replica_entities` on the tenant's IP shard.
     - Commits state and registers `replica_entity.updated` into the Outbox.

---

### Phase 6: Canonical Domain & GEM (L3) with Transactional Outbox
- **Goal:** Transform vendor structures into Universal Standards and resolve cross-system IDs.
- **Tasks:**
  1. Create shard database migrations (`public.canonical_entities` and `public.global_entity_map` with RLS).
  2. Define Canonical Energy DTOs (`MeterDevice`, `UsagePoint`, `IntervalReading`).
  3. Implement Global Entity Map (GEM) Aggregate:
     - Look up or bind `Source ID <-> Canonical UUID <-> Destination ID`.
  4. Implement L3 Normalizer Worker:
     - Consumes `replica_entity.updated`.
     - Maps to Canonical DTO, updates GEM in shard database.
     - Commits state and registers `canonical_entity.normalized` into the Outbox.

---

### Phase 7: Hydrator & "Stitches" (L4) with Transactional Outbox
- **Goal:** Transform canonical records into target destination payloads.
- **Tasks:**
  1. Create shard database migrations (`public.field_mappings` and `public.outbound_dispatches` with RLS).
  2. Implement Hydration Engine:
     - Merges Canonical DTO values into the destination JSON template.
  3. Implement L4 Hydrator Worker:
     - Consumes `canonical_entity.normalized`.
     - Resolves destination credentials and target action.
     - Commits `public.outbound_dispatches` on the tenant's IP shard and registers `outbound_dispatch.enqueued` into the Outbox.

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
     - Updates dispatch state (`DELIVERED` or `FAILED`) on the tenant's IP shard.

---

### Phase 9: Support Timeline Ledger & Business Correlation
- **Goal:** Real-time operational transparency for customer support teams.
- **Tasks:**
  1. Create shard database migration (`public.business_timeline_ledger` with RLS).
  2. Implement Timeline Interceptor:
     - Injects breadcrumbs at each outbox transition (L1, L2, L3, L4, L5) on the tenant's IP shard.
  3. Expose Support Timeline API:
     - `GET /api/v1/timeline?correlation_id=MTR-101`.
     - Resolves tenant IP shard and queries timeline ledger in $< 15\text{ms}$.

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
