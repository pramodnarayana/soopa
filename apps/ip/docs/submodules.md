# Soopa Integration Platform (`apps/ip`)
## Submodules Breakdown & Boundary Contracts

- **Document:** Submodules Architecture & Interface Boundaries
- **Target Domain:** Energy & Utilities (MDM, AMI, CIS, ERP) + Multi-SaaS
- **Status:** Approved Architectural Specification
- **Location:** `apps/ip/docs/submodules.md`

---

## 1. Submodule Decomposition Overview

The **Soopa Integration Platform (`apps/ip`)** is divided into 8 strictly decoupled submodules. Each submodule adheres to **Hexagonal Architecture (Ports and Adapters)**, strict typing (no `Any`), and explicit DTO boundaries.

```
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                               Submodule Dependency Graph                               │
│                                                                                        │
│   ┌───────────────────────────┐                         ┌──────────────────────────┐   │
│   │ 1. ip-connectors          │                         │ 4. ip-domain (DDD)       │   │
│   │ (500+ Declarative, Native │                         │ (Canonical CIM, DTOs,    │   │
│   │  Protocols, Dynamic UI)   │                         │  GEM Aggregate)          │   │
│   └─────────────┬─────────────┘                         └────────────┬─────────────┘   │
│                 │                                                    │                 │
│                 ▼                                                    ▼                 │
│   ┌───────────────────────────┐                         ┌──────────────────────────┐   │
│   │ 2. ip-gateway             │                         │ 5. ip-engine             │   │
│   │ (L1 Ingress, Outbox)      │                         │ (L3 Normalizer,          │   │
│   └─────────────┬─────────────┘                         │  L4 Hydrator,            │   │
│                 │ (Transactional Outbox)                │  L5 Delivery Worker)     │   │
│                 ▼                                       └────────────┬─────────────┘   │
│   ┌───────────────────────────┐                                      │                 │
│   │ 3. ip-replica             ├──────────────────────────────────────┘                 │
│   │ (L2 Replica State, Outbox)│ (Transactional Outbox)                                 │
│   └─────────────┬─────────────┘                                                        │
│                 │                                                                      │
│                 └──────────────────────────────┬───────────────────────────────────────┘
│                                                │
│                                                ▼
│                                 ┌──────────────────────────┐
│                                 │ 6. ip-timeline           │
│                                 │ (Support Ledger API)     │
│                                 └──────────────┬───────────┘
│                                                │
│                 ┌──────────────────────────────┴──────────────────────────────┐
│                 ▼                                                             ▼
│   ┌───────────────────────────┐                                 ┌──────────────────────────┐
│   │ 7. ip-ai (MCP)            │                                 │ 8. ip-storage            │
│   │ (Live Source Queries)     │                                 │ (Postgres, S3, Outbox)   │
│   └───────────────────────────┘                                 └──────────────────────────┘
└────────────────────────────────────────────────────────────────────────────────────────┘
```

---

## Submodule 1: Connection CDK & Auth Engine (`ip-connectors`)

### Purpose:
Provides the pluggable connector framework, dynamic schema discovery, health checking, credential encryption, and support for 500+ SaaS apps and streaming protocols.

### Key Responsibilities:
1. **Three-Tier Connector Support:**
   - **Declarative HTTP Action Engine:** Reads JSON/YAML manifests or OpenAPI 3.0 specs to execute REST endpoints for 500+ SaaS apps with zero bespoke Python code.
   - **Native Protocol Adapters:** Message brokers (`aiokafka`, `aio-pika`, AWS SQS), File transfer (`asyncssh` SFTP, AWS S3), and Webhook ingress.
   - **Custom Python Connectors:** Pure Python classes implementing `ConnectorPort` for proprietary protocols (e.g. Itron OpenWay AMI, SAP RFC).
2. **Dynamic UI Property Schemas:**
   - Emits declarative `ConnectorPropertySchema` (`shortText`, `secretText`, `dropdown`, `oauth2`) so frontends render connection modals dynamically.
3. **Authentication Strategies & Token Manager:**
   - `NoAuthStrategy`, `BasicAuthStrategy`, `BearerAuthStrategy`, `ApiKeyAuthStrategy`.
   - `OAuth2Strategy` with Redis distributed locks for safe refresh concurrency across workers.
   - `MtlsAuthStrategy` for Smart Grid AMI head-ends.
4. **Envelope Encryption Service:**
   - Encrypts/decrypts credentials at rest using AES-256-GCM.

---

## Submodule 2: Ingestion & Gateway Layer (`ip-gateway`)

### Purpose:
Handles external inbound traffic, guarantees sub-20ms HTTP acknowledgments, captures immutable audit evidence (L1), and commits the initial Outbox event.

### Key Responsibilities:
1. **L1 Inbound Gateway:**
   - Ingests webhooks, SFTP file batches, and Kafka events.
   - Computes SHA-256 payload checksums.
   - **Tiered Evidence Storage:**
     - Payloads $< 64\text{ KB}$: Inlined into PostgreSQL `inbound_records`.
     - Payloads $\ge 64\text{ KB}$: Uploaded directly to S3 / MinIO; only the pointer is stored in PostgreSQL.
2. **Transactional Outbox Registration:**
   - In the exact same DB transaction as the raw record insert, registers `inbound_record.created` into the transactional outbox.

---

## Submodule 3: Universal Replica Layer (`ip-replica`)

### Purpose:
Maintains the raw, unadulterated state snapshot of external entities (L2), providing change detection and independent replayability.

### Key Responsibilities:
1. **Replica Worker:**
   - Consumes `inbound_record.created` outbox events.
   - Parses the payload against the connector's permissive schema.
   - Computes SHA-256 `data_hash` for change detection. If the hash matches the existing record, redundant downstream processing is skipped.
   - Idempotently upserts into `ip_data.replica_entities` keyed by `(tenant_id, connection_id, stream_name, source_record_id)`.
2. **Transactional Outbox Registration:**
   - Commits the replica snapshot and registers `replica_entity.updated` into the outbox.

---

## Submodule 4: Domain & Canonical Normalization (`ip-domain`)

### Purpose:
The pure business logic core of the platform. Zero external dependencies on web frameworks, databases, or HTTP clients.

### Key Responsibilities:
1. **Canonical Domain Models (Energy CIM & Universal DTOs):**
   - `MeterDevice` (Serial number, multiplier, manufacturer, firmware, status).
   - `UsagePoint` / `ServicePoint` (Physical premise location, tariff, voltage class).
   - `IntervalReading` (Timestamped reads, units of measure, quality flags).
   - `UniversalInvoice` / `UniversalOrder` (Commercial multi-SaaS canonical structures).
2. **Global Entity Map (GEM) Aggregate:**
   - Maintains and resolves cross-system identity relationships:
     $$\text{Source System ID } \longleftrightarrow \text{Canonical UUID } \longleftrightarrow \text{Destination System ID}$$
3. **Pure Normalizer Protocols:**
   - Domain interfaces defining how vendor structures map into canonical aggregates without external mocks.

---

## Submodule 5: Pipeline Engine & Delivery (`ip-engine`)

### Purpose:
Orchestrates the transformation, field hydration, and outbound delivery stages (L3–L5), each physically decoupled by the Transactional Outbox pattern.

### Key Responsibilities:
1. **L3 Canonical Normalizer Worker:**
   - Consumes `replica_entity.updated` outbox events.
   - Transforms replica JSON into Canonical Domain DTOs.
   - Binds and updates IDs in the Global Entity Map (`ip_data.global_entity_map`).
   - Commits state and registers `canonical_entity.normalized` into the outbox.
2. **L4 Outbound Hydrator Worker:**
   - Consumes `canonical_entity.normalized` outbox events.
   - Queries customer transformation templates (`ip_data.field_mappings` / "Stitches").
   - Merges canonical fields into the target payload.
   - Commits state and registers `outbound_dispatch.enqueued` into the outbox.
3. **L5 Delivery Worker:**
   - Consumes `outbound_dispatch.enqueued` outbox events.
   - Acquires token credentials and distributed lock via `TokenManagerService`.
   - Dispatches outbound HTTP / SFTP / Kafka requests.
   - Implements exponential backoff retries and circuit breaking for transient errors (HTTP 429, 502, 503).
   - Updates `ip_data.outbound_dispatches` with final response codes and delivery status.

---

## Submodule 6: Support Timeline Ledger (`ip-timeline`)

### Purpose:
Provides real-time, domain-centric visibility for customer service and operational support teams.

### Key Responsibilities:
1. **Business Context Propagation:**
   - Propagates `business_trace_id` and `business_correlation_id` (e.g., Meter Serial, Account Number) through every single outbox transition (L1 $\rightarrow$ L2 $\rightarrow$ L3 $\rightarrow$ L4 $\rightarrow$ L5).
2. **Immutable Timeline Ledger (`ip_data.business_timeline_ledger`):**
   - Records state transitions (`STARTED`, `COMPLETED`, `FAILED`, `RETRIED`).
   - Stores clear, human-readable operational summaries.
3. **Customer Support Query API:**
   - REST endpoints allowing support agents to query `/timeline?correlation_id=MTR-101` and receive an instant journey breakdown in $< 15\text{ms}$.

---

## Submodule 7: AI Source-Introspection Agent (`ip-ai`)

### Purpose:
Enables autonomous AI assistants to inspect real-time state directly in connected source systems.

### Key Responsibilities:
1. **Model Context Protocol (MCP) Tool Suite:**
   - Exposes connector primitives (`read_record`, `query`, `list_objects`) as structured MCP tools.
2. **Live Query Execution:**
   - Queries source systems dynamically via `ip-connectors` to answer customer support prompts (e.g. *"What is the live work order status for Meter MTR-994?"*).
3. **Data Redaction:**
   - Sanitizes PII and credentials prior to feeding external system payloads into LLM context windows.

---

## Submodule 8: Storage & Infrastructure Layer (`ip-storage`)

### Purpose:
Encapsulates all database persistence, SQLAlchemy models, migration scripts, and polyglot time-series routing following the platform's **Hybrid Multi-Tenancy Architecture**.

### Key Responsibilities:
1. **Control Plane Repositories (`GlobalSession`):**
   - CRUD and state management for `ip.connections`, `ip.connection_catalogs`, and `ip.outbox` residing on `global_db` under `schema="ip"`.
2. **Dedicated Data Plane Repositories (`TenantSession`):**
   - High-throughput access to `inbound_records`, `replica_entities`, `canonical_entities`, `global_entity_map`, and `outbound_dispatches` residing in the **`public` schema** of dedicated IP Shards (`ip_shard_1`, `ip_shard_2`, `ip_shard_enterprise_*`).
   - Strictly isolated from other applications (never shared with EDI or UCP shards).
   - Multi-tenancy on shared standard shards enforced via PostgreSQL Row-Level Security (`platform.current_tenant_id()`).
3. **Dynamic Shard Resolution (`TenantShardResolver`):**
   - Resolves tenant-to-shard DSN mappings dynamically using `ucp.shard_registry` on composite key `(tenant_id, app_id="ip")`.
4. **Outbox Engine Adapter:**
   - Connects to platform outbox infrastructure (Postgres LISTEN/NOTIFY Relay + fallback Sweeper).
5. **Polyglot Time-Series Storage Port (`TimeSeriesStoragePort`):**
   - PostgreSQL Range Partitioning adapter for standard volume (declarative monthly partitioning for `public.inbound_records`).
   - Columnar Engine adapter (TimescaleDB / ClickHouse) for enterprise clients ($> 1\text{M meters}$).
