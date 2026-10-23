# Soopa Integration Platform (`apps/ip`)
## Submodules Breakdown & Boundary Contracts

- **Document:** Submodules Architecture & Interface Boundaries
- **Target Domain:** Energy & Utilities (MDM, AMI, CIS, ERP) + Multi-SaaS
- **Status:** Approved Architectural Specification
- **Location:** `apps/ip/docs/submodules.md`

---

## 1. Submodule Decomposition Overview

The **Soopa Integration Platform (`apps/ip`)** is housed in a single package (`apps/ip/packages/ip/src/ip/`) separated into two top-level architectural planes:
1. **`ip.engine` (The Execution Kernel):** Platform orchestration, 5-layer SEDA pipeline, auth strategies, generic declarative HTTP/SFTP engines, tiered storage, timeline ledger, and MCP AI introspection.
2. **`ip.application` (The Business Layer):** Canonical domains and dedicated SQL tables (`domains`), vendor-specific connectors & manifests (`connectors`), pure data transformers (`transformers`), and destination workflows (`stitches`).

Across these two planes, the platform comprises 8 strictly decoupled logical submodules (with **no `ip-` prefixes**). Each submodule adheres to **Hexagonal Architecture (Ports and Adapters)**, strict typing (no `Any`), and explicit DTO boundaries.

```
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                               Submodule Dependency Graph                               │
│                                                                                        │
│   ┌───────────────────────────┐                         ┌──────────────────────────┐   │
│   │ 1. connectors             │                         │ 4. domain (DDD)          │   │
│   │ (500+ Declarative, Native │                         │ (Canonical CIM, Tables,  │   │
│   │  Protocols, Dynamic UI)   │                         │  DTOs, GEM Aggregate)    │   │
│   └─────────────┬─────────────┘                         └────────────┬─────────────┘   │
│                 │                                                    │                 │
│                 ▼                                                    ▼                 │
│   ┌───────────────────────────┐                         ┌──────────────────────────┐   │
│   │ 2. gateway                │                         │ 5. engine                │   │
│   │ (L1 Ingress, Outbox)      │                         │ (L3 Normalizer,          │   │
│   └─────────────┬─────────────┘                         │  L4 Hydrator,            │   │
│                 │ (Transactional Outbox)                │  L5 Delivery Worker)     │   │
│                 ▼                                       └────────────┬─────────────┘   │
│   ┌───────────────────────────┐                                      │                 │
│   │ 3. replica                ├──────────────────────────────────────┘                 │
│   │ (L2 Replica State, Outbox)│ (Transactional Outbox)                                 │
│   └─────────────┬─────────────┘                                                        │
│                 │                                                                      │
│                 └──────────────────────────────┬───────────────────────────────────────┘
│                                                │
│                                                ▼
│                                 ┌──────────────────────────┐
│                                 │ 6. timeline              │
│                                 │ (Support Ledger API)     │
│                                 └──────────────┬───────────┘
│                                                │
│                 ┌──────────────────────────────┴──────────────────────────────┐
│                 ▼                                                             ▼
│   ┌───────────────────────────┐                                 ┌──────────────────────────┐
│   │ 7. ai (MCP)               │                                 │ 8. storage               │
│   │ (Live Source Queries)     │                                 │ (Postgres, S3, Outbox)   │
│   └───────────────────────────┘                                 └──────────────────────────┘
└────────────────────────────────────────────────────────────────────────────────────────┘
```

---

## Submodule 1: Connection CDK & Auth Engine (`connectors`)

### Plane Mapping:
- Generic CDK & Auth Strategies: `ip.engine.adapters.outbound.auth` & `ip.engine.adapters.outbound.connectors`
- App Catalog Manifests & Bespoke Vendor Connectors: `ip.application.connectors`

### Purpose:
Provides the pluggable connector framework, dynamic schema discovery, health checking, credential encryption, and support for 500+ SaaS apps and streaming protocols.

### Key Responsibilities:
1. **Three-Tier Connector Support:**
   - **Declarative HTTP Action Engine:** Reads JSON/YAML manifests or OpenAPI 3.0 specs to execute REST endpoints for 500+ SaaS apps with zero bespoke Python code.
   - **Native Protocol Adapters:** Message brokers (`aiokafka`, `aio-pika`, AWS SQS), File transfer (`paramiko` SFTP, AWS S3), and Webhook ingress.
   - **Custom Python Connectors:** Pure Python classes implementing `ConnectorPort` for proprietary protocols (e.g. Itron OpenWay AMI, SAP RFC).
2. **Dynamic UI Property Schemas:**
   - Emits declarative `ConnectorPropertySchema` (`shortText`, `secretText`, `dropdown`, `oauth2`) so frontends render connection modals dynamically.
3. **Authentication Strategies & Token Manager:**
   - `NoAuthStrategy`, `BasicAuthStrategy`, `BearerAuthStrategy`, `ApiKeyAuthStrategy`.
   - `OAuth2Strategy` with Redis distributed locks for safe refresh concurrency across workers.
   - `MtlsAuthStrategy` for Smart Grid AMI head-ends.
4. **Envelope Encryption Service:**
   - Encrypts/decrypts credentials at rest using AES-256-GCM via `security` platform package.

---

## Submodule 2: Ingestion & Gateway Layer (`gateway`)

### Plane Mapping:
- `ip.engine.application.ingress` & `ip.engine.domain.models.inbound_record`

### Purpose:
Handles external inbound traffic, guarantees sub-20ms HTTP acknowledgments, captures immutable audit evidence (L1), and commits the initial Outbox event.

### Key Responsibilities:
1. **L1 Inbound Gateway:**
   - Ingests webhooks, SFTP file batches, and Kafka events.
   - Computes SHA-256 payload checksums.
   - **Tiered Evidence Storage:**
     - Payloads $< 64\text{ KB}$: Inlined into PostgreSQL `public.inbound_records` on the tenant's IP shard.
     - Payloads $\ge 64\text{ KB}$: Uploaded directly to S3 / MinIO; only the pointer (`request_s3_key`) is stored in PostgreSQL.
2. **Transactional Outbox Registration:**
   - In the exact same DB transaction as the raw record insert, registers `inbound_record.created` into the Data Plane transactional outbox (`public.outbox`).

---

## Submodule 3: Universal Replica Layer (`replica`)

### Plane Mapping:
- `ip.engine.application.replica` & `ip.engine.domain.models.replica_record`

### Purpose:
Maintains the raw, unadulterated state snapshot of external entities (L2), providing change detection and independent replayability.

### Key Responsibilities:
1. **Replica Worker:**
   - Consumes `inbound_record.created` outbox events.
   - Invokes the pure L2 extraction hook (`TransformerHookPort.extract_replica`) from `ip.application.transformers`.
   - Computes SHA-256 `data_hash` for change detection. If the hash matches the existing record, redundant downstream processing is skipped.
   - Idempotently upserts into `public.replica_records` on the tenant's IP shard keyed by `(tenant_id, connection_id, entity_type, entity_id)`.
2. **Transactional Outbox Registration:**
   - Commits the replica snapshot and registers `replica_record.updated` into the Data Plane outbox.

---

## Submodule 4: Canonical Domain & Tables (`domain`)

### Plane Mapping:
- Canonical Vertical DTOs, SQL Tables & Repositories: `ip.application.domains`
- Pure L2/L3 Data Transformers: `ip.application.transformers`
- Cross-System Global Entity Map (GEM): `ip.engine.domain.models.global_entity_map`

### Purpose:
Defines the canonical industry data models and dedicated relational SQL tables per vertical (Energy MDM/AMI, TMS, Accounting) alongside pure functional transformations.

### Key Responsibilities:
1. **Canonical Domain Models & Dedicated SQL Tables (`ip.application.domains`):**
   - **Energy & Utilities (`domains/energy`):** `CanonicalMeterReadingDTO`, `CanonicalServicePointDTO`, and dedicated relational tables (`public.mdm_meter_readings`, `public.mdm_service_points`) on the tenant's IP shard with Row-Level Security (RLS).
   - **Transportation Management (`domains/tms`):** `CanonicalLoadDTO`, `CanonicalCarrierDTO`, and dedicated relational tables (`public.tms_loads`, `public.tms_carriers`).
2. **Global Entity Map (GEM) Aggregate:**
   - Maintains and resolves cross-system identity relationships:
     $$\text{Source System ID } \longleftrightarrow \text{Canonical ID } \longleftrightarrow \text{Destination System ID}$$
3. **Pure Transformer Implementations (`ip.application.transformers`):**
   - Implements `TransformerHookPort` with zero database or network dependencies.

---

## Submodule 5: Pipeline Engine & Delivery (`engine`)

### Plane Mapping:
- `ip.engine.application.normalization`, `ip.engine.application.stitches`, `ip.engine.application.delivery`, and `ip.application.stitches`

### Purpose:
Orchestrates the transformation, field hydration, and outbound delivery stages (L3–L5), each physically decoupled by the Transactional Outbox pattern.

### Key Responsibilities:
1. **L3 Canonical Normalizer Worker:**
   - Consumes `replica_record.updated` outbox events.
   - Invokes `TransformerHookPort.normalize()` to produce canonical domain records.
   - Persists audit ledger (`public.normalized_records`), upserts into the vertical canonical domain table (e.g., `public.mdm_meter_readings`), updates `public.global_entity_map`, and emits `canonical_record.normalized`.
2. **L4 Outbound Hydrator Worker:**
   - Consumes `canonical_record.normalized` outbox events.
   - Evaluates 80% declarative transformation templates (`public.stitch_rules`) or 20% custom Python workflows (`ip.application.stitches`).
   - Commits state and registers `outbound_dispatch.enqueued` into the outbox.
3. **L5 Delivery Worker:**
   - Consumes `outbound_dispatch.enqueued` outbox events.
   - Acquires token credentials and distributed lock via `TokenManagerPort`.
   - Dispatches outbound HTTP / SFTP / Kafka requests with exponential backoff and circuit breaking.
   - Updates `public.outbound_records` with final response codes and delivery status.

---

## Submodule 6: Support Timeline Ledger (`timeline`)

### Plane Mapping:
- `ip.engine.domain.models.timeline_entry` & `ip.engine.application.timeline`

### Purpose:
Provides real-time, domain-centric visibility for customer service and operational support teams.

### Key Responsibilities:
1. **Seedwork Trace & Lineage Propagation (`TracedAggregateRoot`):**
   - All 5 layer aggregates (`InboundRecord`, `ReplicaRecord`, `NormalizedRecord`, `GlobalEntityMap` + Canonical Domain records, and `OutboundRecord`) inherit from `seedwork.models.TracedAggregateRoot` and propagate `trace_id`, `correlation_id`, `parent_trace_id`, `original_trace_id`, and `replay_count` through every outbox transition (L1 $\rightarrow$ L2 $\rightarrow$ L3 $\rightarrow$ L4 $\rightarrow$ L5).
2. **Immutable Trace Event Ledger (`public.ip_trace_events`):**
   - Persists `seedwork.models.TraceEvent` (`IpTraceEvent`) entries with state transitions (`SUCCESS`, `FAILED`, `RETRIED`) and human-readable operational summaries.
3. **Customer Support Query API:**
   - REST endpoints allowing support agents to query `/timeline?correlation_id=MTR-101` or `/timeline?trace_id=ip_trc_...` and receive an instant journey breakdown in $< 15\text{ms}$.

---

## Submodule 7: AI Source-Introspection Agent (`ai`)

### Plane Mapping:
- `ip.engine.application.ai`

### Purpose:
Enables autonomous AI assistants to inspect real-time state directly in connected source systems.

### Key Responsibilities:
1. **Model Context Protocol (MCP) Tool Suite:**
   - Exposes connector primitives (`read_record`, `query`, `list_objects`) as structured MCP tools.
2. **Live Query Execution:**
   - Queries source systems dynamically via `connectors` to answer customer support prompts (e.g. *"What is the live work order status for Meter MTR-994?"*).
3. **Data Redaction:**
   - Sanitizes PII and credentials prior to feeding external system payloads into LLM context windows.

---

## Submodule 8: Storage & Infrastructure Layer (`storage`)

### Plane Mapping:
- `ip.engine.adapters.outbound.database` & `ip.engine.adapters.outbound.storage`

### Purpose:
Encapsulates all database persistence, SQLAlchemy models, migration scripts, and S3 tiered storage following the platform's **Hybrid Multi-Tenancy Architecture**.

### Key Responsibilities:
1. **Control Plane Repositories (`GlobalSession`, `IpGlobalBase`):**
   - CRUD and state management for `ip.connections`, `ip.connection_catalogs`, `ip.connection_stream_states`, and `ip.outbox` residing on `global_db` under `schema="ip"`.
2. **Dedicated Data Plane Repositories (`TenantSession`, `IpTenantBase`):**
   - High-throughput access to Engine L1–L5 tables (`inbound_records`, `replica_records`, `normalized_records`, `global_entity_map`, `outbound_records`, `ip_trace_events`, `ip_outbox`) and Application Canonical Domain tables (`mdm_meter_readings`, `mdm_service_points`, `tms_loads`, `tms_carriers`) residing in the **`public` schema** of dedicated IP Shards (`ip_shard_1`, `ip_shard_2`, `ip_shard_enterprise_*`).
   - Multi-tenancy on shared standard shards enforced via PostgreSQL Row-Level Security (`platform.current_tenant_id()`).
3. **Dynamic Shard Resolution (`TenantShardResolver`):**
   - Resolves tenant-to-shard DSN mappings dynamically using `ucp.shard_registry` on composite key `(tenant_id, app_id="ip")`.
