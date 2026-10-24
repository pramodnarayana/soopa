# Architecture Plan: Engine vs. Application Decoupling
## Enterprise Integration Platform (`apps/ip`)

- **Document:** System Architecture & Directory Taxonomy Plan
- **Focus:** Decoupled Architecture (`ip.engine` vs. `ip.application`), Clean I/O (`connectors`) vs. Data Logic (`transformers`), Canonical Domain Tables in `ip.application.domains`, Hybrid Multi-Tenancy
- **Location:** `apps/ip/docs/platform_vs_application_architecture_plan.md`
- **Status:** Approved Architecture Blueprint

---

## 1. System Taxonomy: Clarifying `core/platform`, `ip.engine`, and `ip.application`

To maintain unambiguous architectural boundaries and eliminate naming collisions across the monorepo, `apps/ip` uses a single `uv` workspace package (`apps/ip/packages/ip`) internally partitioned into `ip.engine` and `ip.application`:

| Layer | Location | Scope | Responsibility |
| :--- | :--- | :--- | :--- |
| **Monorepo Platform** | `core/platform/` | Global (All Apps) | Company-wide shared infrastructure: PostgreSQL pooling (`DatabaseRouter`, `TenantShardResolver`), Identity, KMS Secret Store, S3, SHTTP/SFTP clients. |
| **IP Execution Kernel** | `apps/ip/packages/ip/src/ip/engine/` | Bounded Context (`ip.engine`) | IP SEDA 5-layer pipeline, Control Plane & Data Plane repositories, Transactional Outbox, Auth strategies, Declarative HTTP/SFTP engines, In-memory CEL Evaluator, Hydrator, Timeline Ledger. |
| **IP Application Layer**| `apps/ip/packages/ip/src/ip/application/` | Bounded Context (`ip.application`) | Business intelligence: Canonical Domains & Dedicated SQL Tables (`domains/`), Vendor Connectors & Manifests (`connectors/`), Pure Data Transformers (`transformers/`), and Destination Stitches (`stitches/`). |

---

## 2. The Core Boundary: `ip.engine` (Kernel) vs. `ip.application` (Userland)

```
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                              THE STRICT BOUNDARY SPLIT                                 │
├───────────────────────────────────────────┬────────────────────────────────────────────┤
│ ip.engine (The Kernel)                    │ ip.application (The Userland)              │
├───────────────────────────────────────────┼────────────────────────────────────────────┤
│ • Pure Infrastructure & Orchestration     │ • Pure Business Intelligence & Mapping     │
│ • SEDA 5-Layer Queues & Outbox Engine     │ • Dedicated Canonical Domain SQL Tables    │
│ • Hybrid Multi-Tenancy (Global + Shards)  │ • Vendor I/O Drivers & Catalog Manifests   │
│ • In-Memory CEL Evaluator & Hydrator      │ • Pure Data Transformers (Extract/Norm)    │
│ • Generic Auth, Declarative HTTP & SFTP   │ • Destination Stitches (80/20 Workflows)   │
│ • Immutable, Zero Vertical Business Logic │ • Highly Dynamic, Multi-Sector Evolvable   │
│ • NEVER Imports `ip.application`          │ • Zero DB/Network Handles in Transformers  │
└───────────────────────────────────────────┴────────────────────────────────────────────┘
```

---

## 3. Directory Taxonomy Inside `ip.application`

Inside `apps/ip/packages/ip/src/ip/application/`, responsibilities are strictly separated so that engineers always know where code belongs:

| Directory | Name | Exact Responsibility | Network I/O? | Database Access? |
| :--- | :--- | :--- | :---: | :---: |
| **`domains/`** | Canonical Truth | Defines universal industry DTOs, dedicated relational SQL tables on `IpTenantBase` (`mdm_meter_readings`, `tms_loads`), and typed domain repositories. | **NO** | Repository only |
| **`connectors/`** | Vendor I/O Drivers | Vendor-specific connectors (e.g., `ItronMdmConnector`) and declarative SaaS manifests (`salesforce`, `hubspot`, `stripe`, `servicenow`). | **YES** | **NO** |
| **`transformers/`**| Pure Data Logic | Pure functional transformations implementing `TransformerHookPort`. Extracts generic replicas (`extract_replica`) and maps replicas to canonical DTOs (`normalize`). | **NO** | **NO** |
| **`stitches/`** | Workflows | Destination mapping (Canonical $\to$ Target system). Combines 80% declarative UI rules with 20% bespoke Python scripts. | **NO** | **NO** |

---

## 4. Physical Monorepo Directory Structure (`apps/ip/`)

```
apps/ip/
├── docs/
│   ├── architecture.md
│   ├── submodules.md
│   ├── implementation_plan.md
│   └── platform_vs_application_architecture_plan.md
│
└── packages/
    └── ip/
        ├── alembic.global.ini                       # Control Plane migrations (global_db, schema="ip")
        ├── alembic.tenant.ini                       # Data Plane migrations (ip_shard_*, schema="public")
        ├── pyproject.toml                           # name = "ip"
        ├── tests/
        │   ├── unit/
        │   └── integration/
        └── src/
            └── ip/
                ├── __init__.py
                │
                ├── engine/                          # ─── 1. IP EXECUTION KERNEL ───
                │   ├── domain/                      # Kernel Aggregates (Zero vertical business logic)
                │   │   ├── constants.py
                │   │   ├── enums.py
                │   │   ├── errors.py                # First-Class Error Hierarchy (IpError, IpErrorCode, Result[T, E])
                │   │   ├── events.py
                │   │   ├── types.py
                │   │   └── models/
                │   │       ├── catalog.py
                │   │       ├── connection.py        # Connection lifecycle & credentials
                │   │       ├── connector_spec.py
                │   │       ├── inbound_record.py    # L1 Raw Ingestion Aggregate
                │   │       ├── replica_record.py    # L2 Immutable Replica Audit Aggregate
                │   │       ├── normalized_record.py # L3 Immutable Normalization Audit Aggregate
                │   │       ├── global_entity_map.py # L3 Cross-System ID Aggregate (GEM)
                │   │       ├── outbound_record.py   # L5 Delivery Aggregate
                │   │       ├── stream_state.py
                │   │       └── timeline_entry.py    # Business Correlation Ledger Entry
                │   │
                │   ├── ports/                       # Kernel Ports (Hexagonal Boundaries)
                │   │   ├── types.py
                │   │   └── outbound/
                │   │       ├── auth_strategy_port.py
                │   │       ├── catalog_registry_port.py
                │   │       ├── catalog_repository_port.py
                │   │       ├── connection_repository_port.py
                │   │       ├── connector_port.py
                │   │       ├── inbound_record_repository_port.py
                │   │       ├── outbound_record_repository_port.py
                │   │       ├── replica_record_repository_port.py
                │   │       ├── stream_state_repository_port.py
                │   │       ├── tiered_storage_port.py
                │   │       └── transformer_hook_port.py # Pure contract for ip.application.transformers
                │   │
                │   ├── application/                 # Kernel Orchestration Use Cases
                │   │   ├── responses.py
                │   │   ├── catalog/
                │   │   ├── connections/
                │   │   ├── ingress/
                │   │   ├── replica/
                │   │   ├── normalization/
                │   │   ├── stitches/
                │   │   ├── delivery/
                │   │   └── timeline/
                │   │
                │   └── adapters/                    # Concrete Kernel Infrastructure Adapters
                │       └── outbound/
                │           ├── auth/                # API Key, Basic, Bearer, NoAuth, OAuth2 strategies
                │           ├── connectors/          # BaseConnector, DeclarativeHttpConnector, SftpConnector, CatalogRegistry
                │           ├── storage/             # TieredStorageAdapter (<64KB inline vs >=64KB S3)
                │           ├── transformers/        # TransformerRegistry & TransformerBrokerAdapter
                │           └── database/
                │               ├── tenant_resolver.py       # IpTenantResolver (TenantShardResolver for app_slug='ip')
                │               ├── tenant_session_provider.py # IpTenantSessionProvider (RLS-scoped TenantSession)
                │               ├── models/
                │               │   ├── base.py              # IpGlobalBase & IpTenantBase
                │               │   ├── control_plane.py     # Connections, Catalogs, StreamStates, ControlPlane Outbox
                │               │   └── data_plane.py        # Inbound, Replica, Normalized, GEM, Outbound, Timeline, DataPlane Outbox
                │               ├── control_plane/           # Control Plane SQLAlchemy Repositories
                │               ├── data_plane/              # Data Plane SQLAlchemy Repositories
                │               ├── migrations/
                │               │   ├── global/
                │               │   └── tenant/
                │               └── run_migrations.py
                │
                └── application/                     # ─── 2. IP BUSINESS INTEGRATIONS ───
                    ├── domains/                     # CANONICAL STANDARDS & DEDICATED TABLES (IpTenantBase)
                    │   ├── energy/                  # Energy & Utilities Domain (MDM, AMI, CIS)
                    │   │   ├── canonical.py         # CanonicalMeterReadingDTO, CanonicalServicePointDTO
                    │   │   ├── models.py            # MdmMeterReadingRecord, MdmServicePointRecord
                    │   │   └── repository.py        # SqlAlchemyEnergyDomainRepository
                    │   └── tms/                     # Transportation Management System Domain
                    │       ├── canonical.py         # CanonicalLoadDTO, CanonicalCarrierDTO
                    │       ├── models.py            # TmsLoadRecord, TmsCarrierRecord
                    │       └── repository.py        # SqlAlchemyTmsDomainRepository
                    │
                    ├── connectors/                  # VENDOR I/O DRIVERS & DECLARATIVE MANIFESTS
                    │   ├── itron_mdm_connector.py
                    │   ├── registry_loader.py
                    │   └── manifests/
                    │       ├── hubspot.py
                    │       ├── salesforce.py
                    │       ├── servicenow.py
                    │       └── stripe.py
                    │
                    ├── transformers/                # PURE DATA TRANSFORMATIONS (No network, no DB)
                    │   ├── energy/
                    │   │   └── itron_mdm.py
                    │   └── tms/
                    │       └── mercury_gate.py
                    │
                    └── stitches/                    # DESTINATION WORKFLOWS (Canonical -> Target)
                        ├── energy/
                        └── tms/
```

---

## 5. The Transformer Contract (`TransformerHookPort`)

Defined in `ip.engine.ports.outbound.transformer_hook_port`, implemented in `ip.application.transformers`. It strictly enforces:
1. **Zero Database Handles:** Transformers NEVER receive `db_session`, `connection`, or `transaction`.
2. **Zero Network Calls:** Transformers are pure in-memory data transformers ($f(\text{in}) \to \text{out}$).
3. **Strongly Typed DTOs:** Boundary data is strictly passed via `@dataclass(frozen=True)` DTOs using `JsonDict` / `JsonValue`.

```python
from dataclasses import dataclass
from typing import Protocol
from ip.engine.domain.enums import NormalizedEntityType
from seedwork.domain.types import JsonDict, JsonValue

@dataclass(frozen=True)
class ExtractedReplicaDTO:
    """Stable entity identity extracted from raw vendor payload."""
    entity_type: str
    entity_id: str
    data: JsonDict

@dataclass(frozen=True)
class NormalizedRecordDTO:
    """Canonical domain record produced by L3 normalization."""
    canonical_type: NormalizedEntityType
    source_id: str
    data: JsonDict

class TransformerHookPort(Protocol):
    """The strict boundary contract every Transformer must satisfy."""

    def extract_replica(
        self,
        payload: JsonValue,
        context: JsonDict | None = None,
    ) -> ExtractedReplicaDTO | None:
        """
        L2 Extraction Hook.
        One generic function per vendor (NOT per object).
        Extracts entity_type, entity_id, and unmutated attribute dictionary.
        """
        ...

    def normalize(
        self,
        replica: ExtractedReplicaDTO,
    ) -> NormalizedRecordDTO | None:
        """
        L3 Normalization Hook.
        Dispatches to domain canonical transformers.
        """
        ...
```

---

## 6. Hybrid Multi-Tenancy & Canonical Domain Tables

1. **Control Plane (`global_db`, schema `ip`):**
   - Stores `ip.connections`, `ip.connection_catalogs`, `ip.connection_stream_states`, and `ip.outbox`.
   - Migrated via `alembic.global.ini`.
2. **Data Plane (`ip_shard_*`, schema `public` with RLS):**
   - Stores both **`ip.engine` pipeline tables** (`inbound_records`, `replica_records`, `normalized_records`, `global_entity_map`, `outbound_records`, `ip_trace_events`, `ip_outbox`) AND **`ip.application.domains` canonical tables** (`mdm_meter_readings`, `mdm_service_points`, `tms_loads`, `tms_carriers`).
   - All 5 layer aggregates inherit from `seedwork.models.TracedAggregateRoot` and all 5 layer tables carry the standard trace lineage columns (`trace_id`, `correlation_id`, `parent_trace_id`, `original_trace_id`, `replay_count`), draining `seedwork.models.TraceEvent` entries into `ip_trace_events`.
   - All Data Plane and Canonical Domain tables inherit from `IpTenantBase` and enforce tenant isolation via PostgreSQL Row-Level Security (`tenant_id = current_setting('platform.current_tenant_id')`).
   - Migrated across all registered IP shards via `alembic.tenant.ini` and `run_migrations.py`.
