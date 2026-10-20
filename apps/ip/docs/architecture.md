# Soopa Integration Platform (`apps/ip`)
## Enterprise Architecture Specification

- **Status:** Approved Architecture Specification
- **Target Domain:** Energy & Utilities (MDM, AMI, CIS, ERP) + Multi-SaaS
- **Runtime / Language:** Python 3.12+ / FastAPI / SQLAlchemy 2.0 (Async) / Pydantic V2 / Uv
- **Author:** Principal Software Architect
- **Location:** `apps/ip/docs/architecture.md`

---

## 1. Executive Summary & Strategic Objectives

The **Soopa Integration Platform (`apps/ip`)** is an enterprise-grade Integration Platform as a Service (iPaaS) built natively into the `soopa_mono` modular monolith. Sitting directly alongside `apps/edi`, it provides bidirectional, automated, event-driven data synchronization between utility enterprise systems (SAP IS-U, Oracle CC&B), Smart Grid AMI Head-End Systems (Itron, Landis+Gyr, Sensus), file gateways (SFTP), streaming event brokers (Kafka, RabbitMQ), and 500+ commercial cloud APIs (Salesforce, HubSpot, Stripe, ServiceNow, QuickBooks).

### Core Business Objectives:
1. **Designed for Non-Tech Companies:** End users and utility operations teams do not build workflow DAGs or code. The platform executes deterministic, pre-built domain flows ("Stitches") while providing self-service credential setup.
2. **Customer Support Visibility First:** Customer service and operational support teams possess full, real-time observability. Every transaction provides an end-to-end timeline tracing from the inbound gateway to the outbound gateway using **Business Trace IDs** and **Correlation IDs** (e.g., Meter Serial Number, Utility Account Number).
3. **500+ Pluggable Connectors with Dynamic UI:** Support 500+ SaaS applications and protocols without developing 500 custom React forms or maintaining 500 bespoke Python packages. Adding new connectors is data-driven and occurs with **zero platform downtime**.
4. **Staged Transactional Outbox Pipeline:** Every transition (`Gateway -> Replica -> Normalizer -> Hydrator -> Delivery`) is physically decoupled via the **Transactional Outbox Pattern**, guaranteeing zero data loss, fault isolation, independent scalability, and instantaneous replayability.
5. **Autonomous AI Assistance:** In-process AI agents capable of answering operational inquiries in real time (e.g., *"What is the live status of the meter installation for Account #9821?"*) by executing dynamic live queries against connected source systems via the Model Context Protocol (MCP).
6. **Codebase Ownership & Zero Black-Box Lock-in:** Native Python implementation leveraging the best design patterns of open-source projects (**Airbyte**, **Activepieces**, **n8n**) while eliminating heavy external runtimes (such as Airbyte's Java/Temporal engine or n8n's Node.js AST interpreter).

---

## 2. High-Level System Topography

The platform adheres to the **Shopify-style Deployment Strategy** (Single Docker Image, Multiple Container Entrypoints) and **Hexagonal Architecture (Ports and Adapters)**.

```
                                    EXTERNAL TRAFFIC
                                           │
                    ┌──────────────────────┴──────────────────────┐
                    ▼                                             ▼
        [ Inbound Webhooks / APIs ]                     [ SFTP / Kafka / SQS ]
                    │                                             │
                    ▼                                             ▼
         ┌─────────────────────┐                       ┌─────────────────────┐
         │     ip-api          │                       │     ip-worker       │
         │  (HTTP Inbound GW & │                       │  (L1–L5 Staged      │
         │   Control Plane)    │                       │   Outbox Workers)   │
         └──────────┬──────────┘                       └──────────┬──────────┘
                    │                                             │
                    │         ┌─────────────────────────┐         │
                    └────────►│  Centralized Platform   │◄────────┘
                              │  Packages (PubSub, DB)  │
                              └────────────┬────────────┘
                                           │
                         ┌─────────────────┴─────────────────┐
                         ▼                                   ▼
            ┌─────────────────────────┐         ┌─────────────────────────┐
            │   PostgreSQL Database   │         │    AWS S3 / MinIO Blob  │
            │  • Control Plane (ip)   │         │  • Heavy Inbound Payloads│
            │  • Master Replica Store │         │    (≥ 64 KB)            │
            │  • Canonical Domain     │         │  • SFTP Large Batch Dumps│
            │  • Outbox & Timeline    │         └─────────────────────────┘
            └────────────┬────────────┘
                         │
     (Optional Large Enterprise Extension)
                         ▼
            ┌─────────────────────────┐
            │ TimescaleDB / ClickHouse│
            │ • High-Volume AMI Reads │
            │   (Billions/year)       │
            └─────────────────────────┘
```

---

## 3. Open-Source Architectural Synthesis

We borrow proven patterns from open-source automation leaders without importing their heavy external runtimes:

| Open-Source Project | What We Adopt | What We Explicitly Reject |
| :--- | :--- | :--- |
| **Airbyte** | **Connector Protocol Specification**: The core primitives: `spec()` (config schema), `check()` (health validation), `discover()` (stream introspection), `read()` / `write()` (data streaming). | **Airbyte Java Server & Temporal Workers**: Multi-gigabyte container-per-sync overhead, high memory footprint, and slow cold-starts. |
| **Activepieces** | **Action Engine & Dynamic Credential Schemas**: Discriminated property models (`shortText`, `secretText`, `dropdown`, `oauth2`), dynamic modal generation, and an authenticated HTTP execution shim. | **Activepieces UI & Canvas**: Generic consumer drag-and-drop canvas unsuitable for deterministic, regulated enterprise utility compliance. |
| **n8n** | **Audit Timeline & Cryptographic Ciphers**: n8n’s execution history model and AES-256 envelope encryption pattern for credentials at rest. | **n8n Workflow Execution Engine**: Arbitrary JavaScript expression evaluation in-memory (`$json["..."]`), violating enterprise static typing. |

---

## 4. 500+ App Connections Architecture & Lifecycle

To support 500+ connectors alongside enterprise protocols (Kafka, SFTP, RabbitMQ), we divide the connector engine into three tiers:

```
┌────────────────────────────────────────────────────────────────────────┐
│                        CONNECTOR ENGINE                                │
├──────────────────────────┬─────────────────────────┬───────────────────┤
│ 1. Declarative HTTP      │ 2. Native Protocols     │ 3. Custom Python  │
│    (90% of SaaS apps)    │    (Streaming & Files)  │    (Legacy/Bespoke)│
├──────────────────────────┼─────────────────────────┼───────────────────┤
│ • Salesforce, HubSpot,   │ • Kafka, RabbitMQ       │ • Itron AMI       │
│   Stripe, QuickBooks     │ • SFTP, AWS S3          │ • SAP RFC         │
│ • JSON/OpenAPI manifests │ • Async event listeners │ • Specialized SDK │
└──────────────────────────┴─────────────────────────┴───────────────────┘
```

### 4.1. Three-Tier Connector Strategy

1. **Declarative HTTP Action Engine (90% of SaaS Apps):**
   - A single, generic Python execution engine (`DeclarativeHttpConnector`) driven by declarative JSON/YAML schemas or imported **OpenAPI 3.0 specs**.
   - Encapsulates base URLs, auth parameter injection, pagination rules (cursor, page offset, token), and response record selectors.
   - **Zero-Downtime Deployments:** New SaaS applications can be added to the catalog at runtime via administrative API or database seed without rebuilding or restarting application containers.

2. **Native Protocol Connectors (Streaming & File Brokers):**
   - Built directly on enterprise async libraries:
     - **Message Brokers:** Apache Kafka (`aiokafka`), RabbitMQ (`aio-pika`), AWS SQS.
     - **File Transfer:** SFTP (`asyncssh`), AWS S3 / MinIO.
     - **Webhook Ingress:** Generic HTTP listener with cryptographic signature verification (HMAC, JWT).

3. **Custom Python Connectors (Escape Hatch):**
   - Pure Python classes implementing the `ConnectorPort` protocol for complex, proprietary protocols (e.g. Itron OpenWay Riva AMI, Landis+Gyr Gridstream, SAP RFC).

---

### 4.2. Dynamic UI Generation Schema (Self-Service Connection Modal)

To support 500+ applications without creating 500 custom React forms, the backend serves a declarative **Connection Property Schema**. The frontend UI dynamically renders the appropriate modal fields.

#### Property Schema Contract:
```json
{
  "appId": "salesforce",
  "displayName": "Salesforce CRM",
  "authType": "OAUTH2",
  "properties": [
    {
      "name": "instanceUrl",
      "label": "Login Instance URL",
      "type": "shortText",
      "required": true,
      "default": "https://login.salesforce.com",
      "description": "Use https://test.salesforce.com for sandbox environments."
    },
    {
      "name": "environment",
      "label": "Environment",
      "type": "dropdown",
      "required": true,
      "options": [
        {"label": "Production", "value": "production"},
        {"label": "Sandbox", "value": "sandbox"}
      ]
    },
    {
      "name": "oauth",
      "label": "Salesforce Authorization",
      "type": "oauth2",
      "required": true,
      "oauthConfig": {
        "authUrl": "https://login.salesforce.com/services/oauth2/authorize",
        "tokenUrl": "https://login.salesforce.com/services/oauth2/token",
        "scopes": ["api", "refresh_token", "offline_access"]
      }
    }
  ]
}
```

---

### 4.3. Supported Authentication Strategies & Centralized Token Manager

1. **No Auth:** Internal message brokers and open endpoints.
2. **Basic Auth:** Base64-encoded `username:password` for legacy utility APIs.
3. **Bearer / API Key:** Header-injected (`Authorization: Bearer <token>` or `X-API-Key`).
4. **OAuth2 (Authorization Code & Client Credentials):**
   - **Centralized Token Manager:** Workers never refresh tokens concurrently. When a token is within 5 minutes of expiry, the worker acquires a Redis distributed lock (`redlock`), calls the refresh endpoint, updates `ip.connections`, and releases the lock.
5. **mTLS (Mutual TLS):** Client certificate, private key, and CA bundle for Smart Grid AMI head-ends.
6. **Custom Multi-Header / Signature:** HMAC request signing for enterprise utility gateways.

---

### 4.4. Control Plane Database Schema (`ip.connections` & `ip.connection_catalogs`)

```sql
CREATE SCHEMA IF NOT EXISTS ip;

CREATE TYPE ip.auth_type AS ENUM (
    'NO_AUTH', 'BASIC_AUTH', 'BEARER_TOKEN', 'API_KEY', 'OAUTH2', 'MTLS', 'CUSTOM'
);

CREATE TYPE ip.connection_status AS ENUM (
    'PENDING_AUTH', 'ACTIVE', 'ERROR', 'DEACTIVATED'
);

CREATE TABLE ip.connection_catalogs (
    app_id VARCHAR(64) PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    category VARCHAR(64) NOT NULL,                      -- 'CRM', 'AMI', 'ERP', 'FILE_TRANSFER'
    icon_url VARCHAR(512),
    spec JSONB NOT NULL,                                -- Declarative UI Property Schema
    connector_type VARCHAR(32) NOT NULL,                -- 'DECLARATIVE_HTTP', 'NATIVE_PROTOCOL', 'CUSTOM_PYTHON'
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE ip.connections (
    id VARCHAR(64) PRIMARY KEY,                         -- conn_<os.urandom(12).hex()>
    tenant_id UUID NOT NULL,
    app_id VARCHAR(64) NOT NULL REFERENCES ip.connection_catalogs(app_id),
    name VARCHAR(255) NOT NULL,
    auth_type ip.auth_type NOT NULL,
    public_config JSONB NOT NULL DEFAULT '{}'::jsonb,   -- host, port, base_url, scopes, client_id
    encrypted_credentials BYTEA,                        -- AES-256-GCM encrypted payload
    key_encryption_version INT NOT NULL DEFAULT 1,
    token_expires_at TIMESTAMPTZ,
    last_refreshed_at TIMESTAMPTZ,
    connection_fingerprint VARCHAR(64) NOT NULL,        -- SHA-256(tenant_id + app_id + external_endpoint)
    status ip.connection_status NOT NULL DEFAULT 'PENDING_AUTH',
    last_error_code VARCHAR(64),
    last_error_message TEXT,
    last_checked_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    deactivated_at TIMESTAMPTZ,
    CONSTRAINT uq_tenant_fingerprint_status UNIQUE (tenant_id, connection_fingerprint, status)
);

CREATE INDEX idx_connections_tenant ON ip.connections (tenant_id, status);
CREATE INDEX idx_connections_token_refresh ON ip.connections (status, token_expires_at)
    WHERE status = 'ACTIVE' AND token_expires_at IS NOT NULL;
```

---

### 4.5. Soft-Deactivation & Fingerprint Re-linking

- **Deactivate:** Deleting a connection updates `status = 'DEACTIVATED'` and sets `deactivated_at = NOW()`. Data schemas, historical replication tables, and audit logs are permanently preserved.
- **Re-link:** When an identical connection is created later, the system detects matching `connection_fingerprint`, automatically reactivating the previous connection and linking back to the existing schema and audit history.

---

## 5. The 5-Stage Decoupled Execution Pipeline (Transactional Outbox)

The execution engine follows the **Staged Event-Driven Architecture (SEDA)**. Every single layer transition commits its state and registers an event in the **Transactional Outbox** within the exact same database transaction.

```
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                                STAGED EXECUTION PIPELINE                               │
├────────────────────────────────────────────────────────────────────────────────────────┤
│                                                                                        │
│   [ External Ingress (Webhook / Kafka / Poller) ]                                      │
│                         │                                                              │
│                         ▼                                                              │
│   ┌───────────────────────────────────────────┐                                        │
│   │ Stage 1: Inbound Gateway (L1)             │ ──► Reply HTTP 202 Accepted (<20ms)   │
│   │   • Persist raw payload (or S3 pointer)   │                                        │
│   │   • Commit & emit: inbound_record.created │                                        │
│   └─────────────────────┬─────────────────────┘                                        │
│                         │ (Transactional Outbox)                                       │
│                         ▼                                                              │
│   ┌───────────────────────────────────────────┐                                        │
│   │ Stage 2: Universal Replica Worker (L2)    │                                        │
│   │   • Parse vendor-specific structure       │                                        │
│   │   • Upsert into replica_entities (SHA-256)│                                        │
│   │   • Commit & emit: replica_entity.updated │                                        │
│   └─────────────────────┬─────────────────────┘                                        │
│                         │ (Transactional Outbox)                                       │
│                         ▼                                                              │
│   ┌───────────────────────────────────────────┐                                        │
│   │ Stage 3: Canonical Normalizer Worker (L3) │                                        │
│   │   • Map to Domain Canonical Model (CIM)   │                                        │
│   │   • Bind/Resolve Global Entity Map (GEM)  │                                        │
│   │   • Commit & emit: entity.normalized      │                                        │
│   └─────────────────────┬─────────────────────┘                                        │
│                         │ (Transactional Outbox)                                       │
│                         ▼                                                              │
│   ┌───────────────────────────────────────────┐                                        │
│   │ Stage 4: Outbound Hydrator Worker (L4)    │                                        │
│   │   • Query field_mappings / "Stitches"     │                                        │
│   │   • Hydrate target destination payload    │                                        │
│   │   • Commit & emit: dispatch.enqueued      │                                        │
│   └─────────────────────┬─────────────────────┘                                        │
│                         │ (Transactional Outbox)                                       │
│                         ▼                                                              │
│   ┌───────────────────────────────────────────┐                                        │
│   │ Stage 5: Outbound Delivery Worker (L5)    │ ──► Target System (SAP / SFTP / Kafka) │
│   │   • Acquire auth token / distributed lock │                                        │
│   │   • Dispatch HTTP / SFTP with backoff     │                                        │
│   │   • Record final delivery status in ledger│                                        │
│   └───────────────────────────────────────────┘                                        │
│                                                                                        │
│   ══════════════════════════════════════════════════════════════════════════════════   │
│   Cross-Cutting: Every stage writes to ip_data.business_timeline_ledger                │
│   linked by business_trace_id and business_correlation_id                              │
└────────────────────────────────────────────────────────────────────────────────────────┘
```

### Why the Staged Outbox Pattern is the Gold Standard:
1. **Absolute Fault Isolation:** If SAP is down or a normalization rule encounters an unmapped field in Stage 3, Stage 1 (Ingestion) and Stage 2 (Replica) **remain 100% committed**. The external source system never experiences a failure, and incoming data is never dropped.
2. **Instant Replayability (Rewind & Rerun):** If mapping logic is corrected or an outage is resolved, operations can replay events straight from the `replica_entities` table without contacting external vendors.
3. **One-to-Many Fan-Out:** A single `replica_entity.updated` event can trigger multiple independent downstream normalizers, analytics, or external workflows ("Stitches") concurrently.
4. **Independent Horizontal Scaling:** Ingress (I/O bound) can run on lightweight containers, Normalization (CPU bound) on compute-optimized nodes, and Delivery (network/rate-limit bound) on throttled workers.

---

## 6. Comprehensive Multi-Layer Database Architecture: Hybrid Multi-Tenancy (DD)

The Integration Platform implements a **Hybrid Multi-Tenancy Architecture** based on Domain-Driven Design (DDD). We strictly separate administrative configuration from high-throughput pipeline execution across two distinct database planes:

```
                      ┌──────────────────────────────────────────────┐
                      │                 Unified API                  │
                      └──────────────┬───────────────────────────────┘
                                     │
                 ┌───────────────────┴───────────────────┐
                 ▼                                       ▼
    ┌─────────────────────────┐             ┌─────────────────────────┐
    │   Global Database       │             │   Dedicated IP Shards   │
    │   (Control Plane)       │             │   (Data Plane)          │
    │   via GlobalSession     │             │   via TenantSession     │
    ├─────────────────────────┤             ├─────────────────────────┤
    │ Schema: ucp             │             │ Database: ip_shard_1    │
    │ Schema: edi             │             │ Database: ip_shard_2    │
    │ Schema: ip              │             │ Database: ip_shard_ent* │
    │   - connections         │             │                         │
    │   - connection_catalogs │             │ Schema: public (with RLS)
    │   - outbox              │             │   - inbound_records     │
    │                         │             │   - replica_entities    │
    │                         │             │   - canonical_entities  │
    │                         │             │   - global_entity_map   │
    │                         │             │   - field_mappings      │
    │                         │             │   - outbound_dispatches │
    │                         │             │   - timeline_ledger     │
    └─────────────────────────┘             └─────────────────────────┘
```

### 6.1. Control Plane (`ip` Schema in `global_db`)
- **Location:** The shared `global_db` instance under the dedicated `ip` schema.
- **Access:** Injected as `GlobalSession` via `DatabaseRouterPort.get_global_session()`.
- **Scope:** Administrative configuration, connection endpoints, envelope-encrypted credentials (AES-256-GCM), discovered catalog schemas, and connection lifecycle outbox events.
- **Tables:**
  - `ip.connections`
  - `ip.connection_catalogs`
  - `ip.outbox`

### 6.2. Data Plane (`public` Schema in Dedicated `ip_shard` Databases)
- **Location:** Dedicated IP Shard databases (`ip_shard_1`, `ip_shard_2`, `ip_shard_enterprise_<tenant>`). **This shard database is dedicated solely to IP and is never shared with EDI, UCP, or other applications.**
- **Schema:** All IP pipeline execution tables reside in the **`public` schema** of each IP shard.
- **Multi-Tenancy Isolation:**
  - **Standard Tier:** Multiple tenants share a pooled shard (e.g. `ip_shard_1`), strictly isolated via PostgreSQL **Row-Level Security (RLS)** using `platform.current_tenant_id()`.
  - **Enterprise Tier:** High-throughput enterprise tenants are allocated dedicated, isolated shard database instances (e.g. `ip_shard_enterprise_acme`).
- **Dynamic Shard Resolution:**
  - The platform routes requests dynamically via `ucp.shard_registry` on the composite key `(tenant_id, app_id="ip")`:
    ```sql
    SELECT s.name, s.dsn
    FROM ucp.shard_registry r
    JOIN ucp.database_shards s ON r.shard_id = s.id
    JOIN ucp.apps a ON r.app_id = a.id
    WHERE r.tenant_id = :tenant_id AND a.slug = 'ip';
    ```
- **Zero Cross-Database Foreign Keys:** Because Control Plane and Data Plane live on separate physical databases, Data Plane tables reference connections and tenants using logical string identifiers (`connection_id VARCHAR(64)`, `tenant_id VARCHAR(128)`) without physical database foreign keys.

### 6.3. Data Plane Shard DDL (`public` Schema)

```sql
-- ============================================================================
-- LAYER 1: INBOUND RAW AUDIT EVIDENCE (Partitioned by Month)
-- ============================================================================
CREATE TABLE public.inbound_records (
    id VARCHAR(64) NOT NULL,                            -- inb_<os.urandom(12).hex()>
    tenant_id VARCHAR(128) NOT NULL,
    connection_id VARCHAR(64) NOT NULL,                 -- Logical ref to ip.connections(id)
    business_trace_id VARCHAR(64) NOT NULL,
    business_correlation_id VARCHAR(255),
    raw_payload JSONB,                                  -- Populated if size < 64 KB
    s3_key VARCHAR(512),                                -- Populated if size >= 64 KB
    payload_size_bytes INT NOT NULL,
    payload_sha256 VARCHAR(64) NOT NULL,
    headers JSONB NOT NULL DEFAULT '{}'::jsonb,
    received_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (id, received_at)
) PARTITION BY RANGE (received_at);

-- Monthly partition template for high-throughput append logs
CREATE TABLE public.inbound_records_default
    PARTITION OF public.inbound_records DEFAULT;

CREATE INDEX idx_inbound_trace ON public.inbound_records (tenant_id, business_trace_id);
CREATE INDEX idx_inbound_corr ON public.inbound_records (tenant_id, business_correlation_id);

-- Enable RLS for standard shared shards
ALTER TABLE public.inbound_records ENABLE ROW LEVEL SECURITY;
CREATE POLICY inbound_tenant_isolation ON public.inbound_records
    USING (tenant_id = platform.current_tenant_id() OR platform.bypass_rls());

-- ============================================================================
-- LAYER 2: UNIVERSAL SOURCE STATE REPLICA
-- ============================================================================
CREATE TABLE public.replica_entities (
    tenant_id VARCHAR(128) NOT NULL,
    connection_id VARCHAR(64) NOT NULL,                 -- Logical ref to ip.connections(id)
    stream_name VARCHAR(128) NOT NULL,                  -- 'meters', 'service_points', 'invoices'
    source_record_id VARCHAR(255) NOT NULL,             -- External primary key
    data JSONB NOT NULL,                                -- Parsed, structured source JSON
    data_hash VARCHAR(64) NOT NULL,                     -- SHA-256 for change detection (dedup)
    synced_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (tenant_id, connection_id, stream_name, source_record_id)
);

CREATE INDEX idx_replica_gin ON public.replica_entities USING GIN (data);

ALTER TABLE public.replica_entities ENABLE ROW LEVEL SECURITY;
CREATE POLICY replica_tenant_isolation ON public.replica_entities
    USING (tenant_id = platform.current_tenant_id() OR platform.bypass_rls());

-- ============================================================================
-- LAYER 3: CANONICAL DOMAIN ENTITIES & GLOBAL ENTITY MAP (GEM)
-- ============================================================================
CREATE TABLE public.canonical_entities (
    id VARCHAR(64) PRIMARY KEY,                         -- can_<os.urandom(12).hex()>
    tenant_id VARCHAR(128) NOT NULL,
    entity_domain VARCHAR(64) NOT NULL,                 -- 'ENERGY_METER', 'USAGE_POINT', 'INVOICE'
    canonical_data JSONB NOT NULL,                      -- Strongly-typed CIM / standard model
    version INT NOT NULL DEFAULT 1,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE public.global_entity_map (
    id VARCHAR(64) PRIMARY KEY,                         -- gem_<os.urandom(12).hex()>
    tenant_id VARCHAR(128) NOT NULL,
    entity_domain VARCHAR(64) NOT NULL,
    canonical_id VARCHAR(64) NOT NULL REFERENCES public.canonical_entities(id) ON DELETE CASCADE,
    source_connection_id VARCHAR(64) NOT NULL,
    source_entity_id VARCHAR(255) NOT NULL,             -- e.g. Itron 'MTR-101'
    dest_connection_id VARCHAR(64) NOT NULL,
    dest_entity_id VARCHAR(255) NOT NULL,               -- e.g. SAP 'EQUIP-9988'
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_gem_link UNIQUE (
        tenant_id, entity_domain, source_connection_id, source_entity_id, dest_connection_id
    )
);

CREATE INDEX idx_gem_lookup ON public.global_entity_map (
    tenant_id, entity_domain, dest_connection_id, dest_entity_id
);

ALTER TABLE public.canonical_entities ENABLE ROW LEVEL SECURITY;
CREATE POLICY canonical_tenant_isolation ON public.canonical_entities
    USING (tenant_id = platform.current_tenant_id() OR platform.bypass_rls());

ALTER TABLE public.global_entity_map ENABLE ROW LEVEL SECURITY;
CREATE POLICY gem_tenant_isolation ON public.global_entity_map
    USING (tenant_id = platform.current_tenant_id() OR platform.bypass_rls());

-- ============================================================================
-- LAYER 4: FIELD MAPPINGS & STITCHES (Customer Transformation Templates)
-- ============================================================================
CREATE TABLE public.field_mappings (
    id VARCHAR(64) PRIMARY KEY,                         -- map_<os.urandom(12).hex()>
    tenant_id VARCHAR(128) NOT NULL,
    name VARCHAR(255) NOT NULL,
    source_domain VARCHAR(64) NOT NULL,                 -- 'ENERGY_METER'
    target_app_id VARCHAR(64) NOT NULL,                 -- 'sap_isu'
    target_action VARCHAR(64) NOT NULL,                 -- 'create_device'
    mapping_template JSONB NOT NULL,                    -- Template with dynamic expressions
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

ALTER TABLE public.field_mappings ENABLE ROW LEVEL SECURITY;
CREATE POLICY field_mappings_tenant_isolation ON public.field_mappings
    USING (tenant_id = platform.current_tenant_id() OR platform.bypass_rls());

-- ============================================================================
-- LAYER 5: OUTBOUND DISPATCHES (Delivery Ledger)
-- ============================================================================
CREATE TYPE public.dispatch_status AS ENUM (
    'PENDING', 'PROCESSING', 'DELIVERED', 'FAILED', 'RETRY_SCHEDULED'
);

CREATE TABLE public.outbound_dispatches (
    id VARCHAR(64) PRIMARY KEY,                         -- dsp_<os.urandom(12).hex()>
    tenant_id VARCHAR(128) NOT NULL,
    business_trace_id VARCHAR(64) NOT NULL,
    target_connection_id VARCHAR(64) NOT NULL,
    target_action VARCHAR(64) NOT NULL,
    payload JSONB NOT NULL,
    status public.dispatch_status NOT NULL DEFAULT 'PENDING',
    attempt_count INT NOT NULL DEFAULT 0,
    max_retries INT NOT NULL DEFAULT 5,
    next_retry_at TIMESTAMPTZ,
    last_response_code INT,
    last_error_message TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    delivered_at TIMESTAMPTZ
);

CREATE INDEX idx_dispatches_pending ON public.outbound_dispatches (status, next_retry_at)
    WHERE status IN ('PENDING', 'RETRY_SCHEDULED');

ALTER TABLE public.outbound_dispatches ENABLE ROW LEVEL SECURITY;
CREATE POLICY dispatches_tenant_isolation ON public.outbound_dispatches
    USING (tenant_id = platform.current_tenant_id() OR platform.bypass_rls());

-- ============================================================================
-- CROSS-CUTTING: CUSTOMER SUPPORT TIMELINE LEDGER
-- ============================================================================
CREATE TABLE public.business_timeline_ledger (
    id VARCHAR(64) PRIMARY KEY,                         -- tml_<os.urandom(12).hex()>
    tenant_id VARCHAR(128) NOT NULL,
    business_trace_id VARCHAR(64) NOT NULL,
    business_correlation_id VARCHAR(255) NOT NULL,      -- 'MTR-54012', 'ACC-9821'
    layer VARCHAR(32) NOT NULL,                         -- 'L1_INGEST', 'L2_REPLICA', 'L3_NORM', 'L4_HYDRATE', 'L5_DELIVER'
    status VARCHAR(32) NOT NULL,                        -- 'SUCCESS', 'FAILED', 'RETRIED'
    summary_message TEXT NOT NULL,                      -- Human-readable message for support desk
    error_details JSONB,
    occurred_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_timeline_lookup ON public.business_timeline_ledger (
    tenant_id, business_correlation_id, occurred_at DESC
);
CREATE INDEX idx_timeline_trace ON public.business_timeline_ledger (
    tenant_id, business_trace_id, occurred_at ASC
);

ALTER TABLE public.business_timeline_ledger ENABLE ROW LEVEL SECURITY;
CREATE POLICY timeline_tenant_isolation ON public.business_timeline_ledger
    USING (tenant_id = platform.current_tenant_id() OR platform.bypass_rls());
```

### 6.4. Enterprise Robustness Pillars
1. **Centralized Platform Resolver (`TenantShardResolver`):** Cached resolution of `(tenant_id, app_id="ip")` ensures workers never query `global_db` per ingested record.
2. **Declarative Partitioning & Pruning:** High-volume telemetry in `inbound_records` uses range partitioning by month, eliminating vacuum bloat by dropping expired partitions with instantaneous DDL (`DROP TABLE`).
3. **Dedicated Shard Migration Runner:** `platform_migrator migrate --domain ip` runs global migrations on `global_db` (`ip` schema) and dynamically iterates over all active IP shards discovered via `ShardRegistry` to apply `public` schema migrations.
4. **Isolated Connection Pools:** Shard connection pools are allocated dynamically via `DatabaseRouter` with tier-specific sizing (e.g. 20 connections for shared standard shards, dedicated pools for enterprise shards).

---

## 7. Customer Support Timeline & Business Correlation

Customer support teams cannot troubleshoot using low-level technical distributed tracing IDs (like OpenTelemetry span IDs). They require a **Domain Timeline View** indexed by business identifiers:

### The Timeline Query Contract:
When a customer calls with a query regarding Meter `MTR-101`, the support representative searches for `correlation_id = MTR-101`. The API returns an instantaneous journey:

| Step | Timestamp | Layer | Status | Summary Message |
| :--- | :--- | :--- | :--- | :--- |
| 1 | `14:00:01.102` | **L1 Ingest** | `SUCCESS` | Inbound reading received from Itron AMI (HTTP 202, Trace `TR-991`) |
| 2 | `14:00:01.350` | **L2 Replica** | `SUCCESS` | Updated replica snapshot for Itron Meter `MTR-101` |
| 3 | `14:00:01.410` | **L3 Normalize**| `SUCCESS` | Normalized to CIM Meter Reading & bound to SAP Equipment `EQUIP-5542` |
| 4 | `14:00:01.520` | **L4 Hydrate** | `SUCCESS` | Hydrated SAP BAPI payload via "Itron to SAP Daily Read" Stitch |
| 5 | `14:00:02.110` | **L5 Delivery**| `SUCCESS` | Successfully delivered to SAP IS-U endpoint (HTTP 201 Created) |

---

## 8. Autonomous AI Source-Introspection Architecture (MCP)

To enable support agents to ask questions such as:
> *"What happened to the customer request for new meter installation #MTR-994?"*

The system embeds a **Model Context Protocol (MCP)** tool caller that queries the connected source system in real time rather than relying on stale database caches:

```
[ Customer Support Chat UI ]
             │
             ▼
    [ AI Copilot Agent ]
             │
             ├─► Detects requirement for live data from SAP IS-U
             ▼
  [ MCP Tool: connector_query ]
             │
             ├─► Loads AuthenticatedClient for SAP Connection
             ▼
    [ SAP IS-U BAPI Call ] ──► Returns live status: "Technician Dispatched - En Route"
             │
             ▼
 [ AI Formatted Answer ] ──► "Technician dispatched today at 1:30 PM. Work Order #WO-4481 is active."
```

---

## 9. Security, Governance & Enterprise Compliance

1. **Zero Raw Token Exposure:** Action and connector codes never receive decrypted OAuth secrets. Decryption occurs only at the HTTP client injection layer immediately before executing outgoing requests.
2. **Key Rotation & Envelope Encryption:** Connection credentials use AES-256-GCM. The Key Encryption Key (KEK) is managed via AWS KMS.
3. **Structured JSON Logging:** Python `structlog` injected via `ILogger` port. String interpolation in logs is strictly prohibited. Every log binds `tenant_id`, `connection_id`, and `business_trace_id`.
4. **Zero-Mock Pure Testing:** Domain business logic and canonical normalizers are tested with 100% pure unit tests without mocks. Integration tests utilize PostgreSQL nested transactions (`SAVEPOINT`) with automatic rollbacks.
