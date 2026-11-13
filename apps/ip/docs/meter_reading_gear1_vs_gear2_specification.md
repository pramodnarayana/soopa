# Soopa Integration Platform (`apps/ip`)
## Energy Sector Meter Readings: Gear-1 (Transactional) vs. Gear-2 (High-Frequency Columnar Telemetry)

- **Document:** Architectural Specification & Boundary Definition for Energy Meter Readings
- **Status:** Approved Architectural Specification
- **Location:** `apps/ip/docs/meter_reading_gear1_vs_gear2_specification.md`
- **Bounded Context:** Integration Platform Data Plane (`ip.engine`, `ip.solutions.domains.energy`)

---

## 1. Executive Summary: Is "Schema A" Gear 1 or Gear 2?

**Schema A (as defined and tested) is 100% Gear 1 (Transactional Business Flow).**

```json
{
  "meter_serial": "MTR-ENERGY-1001",
  "timestamp": "2026-11-12T12:00:00Z",
  "kwh_delivered": 14.52,
  "kwh_received": 0.0,
  "voltage_avg": 240.1,
  "interval_minutes": 15,
  "service_point_id": "SP-NORTH-401"
}
```

In an electric, water, or gas utility, the semantic event *"Meter $M$ recorded consumption $C$ at time $T$"* exists in **two completely different operational dimensions**:

1. **Gear 1 (Transactional / Event-Driven Meter Readings):**
   - **When a meter reading is tied to a discrete business lifecycle event** (e.g. Move-in / Move-out final billing read, customer care on-demand ping, monthly billing cutoff snapshot, or manual check read).
   - **Scale:** Tens to tens of thousands of records per day.
   - **Processing Engine:** Row-oriented ACID transactions in **PostgreSQL**, transactional outbox events, and Layer 4 **Stitch DAGs** that trigger individual ERP/CIS mutations.
2. **Gear 2 (High-Frequency Columnar Telemetry):**
   - **When smart meters continuously stream automated 15-minute or 5-minute interval pulses 24/7/365** to monitor grid load curves, power quality, and Time-of-Use (TOU) tariff consumption.
   - **Scale:** 500,000 to 5,000,000 smart meters $\times$ 96 intervals/day = **48,000,000 to 480,000,000 intervals every single day**.
   - **Processing Engine:** Vectorized **Apache Arrow + Rust Polars** zero-copy in-memory SIMD pipelines, **S3/MinIO Claim-Check** object drops ($50\text{K}$ rows/file), and **ClickHouse Columnar OLAP** (`ReplacingMergeTree` + `AggregatingMergeTree` materialized views).

---

## 2. Why Two Gears? The Law of Physics in Utility Data

Attempting to process high-frequency smart meter telemetry using standard row-oriented transactional patterns (Gear 1) is a catastrophic anti-pattern that destroys database scalability:

```
┌────────────────────────────────────────────────────────────────────────┐
│  THE GEAR 1 BOTTLENECK UNDER HIGH-FREQUENCY TELEMETRY                  │
│                                                                        │
│  400,000 Smart Meters  x  96 intervals/day = 38.4 MILLION ROWS / DAY   │
│                                                                        │
│  • 38.4 Million row-by-row INSERTs / ON CONFLICT updates per day       │
│  • 38.4 Million B-Tree index traversal locks on PostgreSQL             │
│  • Write-Ahead Logging (WAL) disk IOPS completely saturated            │
│  • Row-by-row Stitch DAG execution creates 38.4M outbox records/day    │
│  • RESULT: PostgreSQL locks freeze, API latency explodes, DB crashes   │
└────────────────────────────────────────────────────────────────────────┘
```

To eliminate this bottleneck, Soopa IP enforces the **Dual-Gear Paradigm**:

```mermaid
flowchart TD
    subgraph Sources["External Utility Sources"]
        AMI_PULSE["Continuous 15-Min Smart Meter Pulses (96/day/meter)"]
        BIZ_EVENTS["Business Events (Move-Out Read, Dispute Ping, Billing Cutoff)"]
    end

    subgraph Gear2["Gear 2: High-Frequency Columnar Plane (ClickHouse + Polars)"]
        G2_L1["L1: S3/MinIO Parquet Drop (50K rows/drop)"]
        G2_L2["L2: Vectorized Dedup in Polars SIMD"]
        G2_L3["L3: Arrow GEM Hash-Join + Spike Quarantine"]
        G2_L4["L4: 96-Slot Completeness Gate & TOU Rollups"]
        G2_L5["L5: Bulk Parquet to MDMS / Chunked OData to SAP"]
        G2_L1 --> G2_L2 --> G2_L3 --> G2_L4 --> G2_L5
    end

    subgraph Gear1["Gear 1: Transactional Business Plane (PostgreSQL + Stitches)"]
        G1_L1["L1: PostgreSQL inbound_records (ACID Journal)"]
        G1_L2["L2: PostgreSQL replica_records (CDC & Hash Dedup)"]
        G1_L3["L3: PostgreSQL mdm_meter_readings (Domain Model)"]
        G1_L4["L4: Layer 4 Stitch DAG Orchestration Engine"]
        G1_L5["L5: DeliverOutboundRecordUseCase (ERP Egress)"]
        G1_L1 --> G1_L2 --> G1_L3 --> G1_L4 --> G1_L5
    end

    AMI_PULSE -->|Streaming Edge| G2_L1
    BIZ_EVENTS -->|Ingress REST / Webhook| G1_L1

    G2_L3 -.->|L3.5 Storm Outage Bridge: Voltage=0V Cluster > 25 Meters| G1_L1
```

---

## 3. Side-by-Side Comparison: Gear 1 vs. Gear 2 for Meter Readings

| Architectural Dimension | **Gear 1: Transactional Reading** (What We Tested) | **Gear 2: High-Frequency Telemetry** |
| :--- | :--- | :--- |
| **Typical Use Cases** | Move-in/Move-out final reads, customer care dispute pings, monthly billing reconciliation snapshots, work order verification reads. | 15-minute / 5-minute automated interval collection, DER solar generation monitoring, EV charging telemetry, sub-minute transformer load profiling. |
| **Ingress Modality (L1)** | Direct HTTP REST/Webhook or Pull Poller $\to$ `public.inbound_records` journal table in PostgreSQL. | Stateless Streaming Ingress Edge $\to$ S3/MinIO raw Zstd/Parquet macro-batch ($50{,}000$ intervals/file) + SQS Claim-Check pointer. |
| **Deduplication (L2)** | Row-level SHA-256 hash match against `public.replica_records` in PostgreSQL. | Vectorized composite key `(source_meter_id, channel_id, interval_end_utc)` in-memory deduplication via Rust Polars. |
| **Normalization (L3)** | [`ProcessInboundRangeUseCase`](apps/ip/packages/ip/src/ip/engine/application/use_cases/normalization/process_inbound_range_use_case.py) maps raw JSON into [`NormalizedRecordModel`](apps/ip/packages/ip/src/ip/engine/adapters/outbound/database/models/data_plane.py) and typed [`MdmMeterReadingRecord`](apps/ip/packages/ip/src/ip/solutions/domains/energy/models/meter_reading.py) in PostgreSQL. | Fused in-memory Apache Arrow pass: IEC-61968 CIM unit scaling (`Wh` $\to$ `kWh`), Global Entity Model (GEM) dictionary hash-join, and PyOD / rolling MAD spike quarantine. |
| **Storage Destination** | **PostgreSQL** tenant shard (`mdm_meter_readings` table with B-Tree indexes). | **ClickHouse** cluster (`ip_intervals.interval_readings_15m` with `ReplacingMergeTree`). |
| **Routing / Orchestration (L4)** | **Stitch DAGs**: In-memory task workflows evaluated per event (`prepare_erp_dispatch` $\to$ `dispatch_erp_reading`). | **Completeness Gates & TOU Materialized Views**: ClickHouse `AggregatingMergeTree` computes 96-slot completeness heatmaps and TOU billing buckets in real time. |
| **Outbound Delivery (L5)** | [`DeliverOutboundRecordUseCase`](apps/ip/packages/ip/src/ip/engine/application/use_cases/delivery/deliver_outbound_record_use_case.py): Single HTTP mutations to NetSuite/SAP with per-record idempotency key deduplication. | Bulk Parquet exports to MDMS/Snowflake or chunked ($500$-meter) OData `$batch` requests to SAP S/4HANA CIS. |
| **Throughput Capacity** | $100$ to $2{,}000$ records / sec per worker. | **$> 2{,}000{,}000$ intervals / sec per worker core** (SIMD compiled). |
| **Query Latency** | $5\text{ms} - 25\text{ms}$ (B-Tree indexed single-row lookup). | **$< 20\text{ms}$ across billions of intervals** (ClickHouse zone-maps and sparse primary index). |

---

## 4. How the Schemas Physically Differ

### 4.1 Gear 1: Row-Oriented JSON Payload
In Gear 1, each reading is a self-contained, strongly-typed JSON document evaluated as an atomic business event:

```json
{
  "meter_serial": "MTR-ENERGY-1001",
  "timestamp": "2026-11-12T12:00:00Z",
  "kwh_delivered": 14.52,
  "kwh_received": 0.0,
  "voltage_avg": 240.1,
  "interval_minutes": 15,
  "service_point_id": "SP-NORTH-401"
}
```

* **Simulator Entity Modal Inputs:**
  - **Entity Name:** `meter_readings`
  - **Primary Key:** `meter_serial`
  - **Cursor Field:** `timestamp`
* **Storage in PostgreSQL (`mdm_meter_readings`):**
  - Primary Key: `(id, reading_timestamp)`
  - Foreign Reference: `service_point_id` references `mdm_service_points.id`
  - Traceability: `trace_id`, `source_replica_id`, `source_connection_id` stored directly on the row.

---

### 4.2 Gear 2: Columnar Apache Arrow / Parquet Schema (Target Architecture)
In the target Gear 2 architecture, readings are **never unpacked into individual row-level Python dicts**. Instead, they are streamed as contiguous vectors in Apache Arrow columnar memory directly from Parquet into ClickHouse:

```
+--------------------------------------------------------------------------------------------------------------------------------+
| Column Name            | Arrow Data Type              | ClickHouse Column Type                  | Compression Codec           |
+------------------------+------------------------------+-----------------------------------------+-----------------------------+
| tenant_id              | pa.binary(16) / UUID         | LowCardinality(String)                  | ZSTD(1)                     |
| connection_id          | pa.binary(16) / UUID         | LowCardinality(String)                  | ZSTD(1)                     |
| gem_device_id          | pa.binary(16) / UUID         | LowCardinality(String)                  | ZSTD(1)                     |
| source_meter_id        | pa.string()                  | LowCardinality(String)                  | ZSTD(1)                     |
| feeder_id              | pa.string()                  | LowCardinality(String)                  | ZSTD(1)                     |
| tariff_bucket          | pa.string()                  | LowCardinality(String)                  | ZSTD(1)                     |
| quality_status         | pa.string()                  | LowCardinality(String)                  | ZSTD(1)                     |
| interval_end_utc       | pa.timestamp('ms', 'UTC')    | DateTime64(3, 'UTC')                    | DoubleDelta                 |
| scaled_kwh_delivered   | pa.decimal128(18, 4)         | Decimal64(4)                            | ZSTD(3)                     |
| scaled_kwh_received    | pa.decimal128(18, 4)         | Decimal64(4)                            | ZSTD(3)                     |
| voltage_v              | pa.float32()                 | Float32                                 | ZSTD(3)                     |
| source_batch_id        | pa.string()                  | LowCardinality(String)                  | ZSTD(1)                     |
| updated_at_utc         | pa.timestamp('ms', 'UTC')    | DateTime64(3, 'UTC')                    | DoubleDelta (Deduplication) |
+--------------------------------------------------------------------------------------------------------------------------------+
```

* **Current Implementation Note:** In the current implementation, `VectorizedIntervalBatchNormalizerAdapter` parses JSON macro-batches into internal records and converts Parquet inputs via `table.to_pydict()` iterating over rows in Python memory for zero-loss deduplication and VEE validation. The target architecture replaces this loop with zero-copy C++ Arrow vector operations and Polars SIMD expressions.

---

## 5. How Gear 1 and Gear 2 Cooperate (The Bridge)

The two gears do not operate in isolated silos; they communicate through two enterprise architectural bridges:

```mermaid
sequenceDiagram
    autonumber
    participant AMI as AMI Smart Meter Head-End
    participant G2 as Gear 2 (Columnar Worker)
    participant S3 as S3 / ClickHouse OLAP
    participant G1_Q as Gear 1 P0 Ingress Queue
    participant G1 as Gear 1 (Transactional Worker)
    participant ERP as Utility ERP / OMS

    Note over AMI,G2: Routine Telemetry (48M reads/day)
    AMI->>G2: Push 50,000 15-minute interval readings (Batch #902)
    G2->>G2: Polars SIMD Vector Normalization & GEM Join
    
    rect rgb(255, 243, 224)
        Note over G2,G1: Real-Time L3.5 Outage Bridge (<2s SLA)
        G2->>G2: Scan finds 32 meters with voltage_v == 0.0 on Feeder F-09
        G2->>G2: Spatial Storm Grouping collapses 32 reads into 1 Outage Cluster Event
        G2->>G1_Q: Publish FeederOutageClusterDetected to P0 Critical Queue
        G1_Q-->>G1: Gear 1 Worker claims P0 ticket immediately
        G1->>ERP: Create Outage Trouble Ticket in OMS & Alert Dispatch Crew (<1.8s E2E!)
    end

    G2->>S3: Insert Arrow Batch into ClickHouse & S3 Parquet
    Note over S3,ERP: L4/L5 Billing Cycle Completeness Gate
    S3->>ERP: Once 96-slot completeness reaches >=99.5%, export billing rollups to ERP
```

1. **The Inbound Master Data Bridge (Gear 1 $\to$ Gear 2):**
   - Gear 1 maintains the master catalog of service points, meters, customers, and tariff contracts in PostgreSQL.
   - Gear 2 periodically caches this relational lookup as an in-memory Arrow Dictionary (`ArrowGemDictionaryCache`). When $50{,}000$ raw Itron meter serial numbers arrive in Gear 2, Polars executes an in-memory hash-join in **`4ms`**, enriching all $50{,}000$ intervals with their canonical `gem_device_id` and SAP account numbers with zero database queries.
2. **The Real-Time Emergency Exception Bridge (Gear 2 $\to$ Gear 1):**
   - If an AMI storm drops hundreds of meters to $0\text{V}$ (power outage), Gear 2 does **not** flood Gear 1 with hundreds of thousands of individual meter tickets.
   - Instead, Gear 2's **Spatial Storm Grouping** clusters simultaneous $0\text{V}$ readings by `(feeder_id, transformer_id)`, emitting a single summarized `FeederOutageClusterDetected` event onto Gear 1's **`P0_CRITICAL` queue**.
   - Gear 1 claims the P0 event in $<2$ seconds, executes an Outage Stitch DAG, and creates an Outage Management System (OMS) work order.

---

## 6. Summary Matrix

| Question | Answer |
| :--- | :--- |
| **Is Schema A Gear 1 or Gear 2?** | **Gear 1.** It is structured as an individual, row-oriented JSON document processed through PostgreSQL ACID transactions and Stitch DAG orchestration. |
| **Can the same meter reading travel through Gear 2?** | **Yes.** If it is part of the automated 15-minute interval streaming schedule, it travels through Gear 2 as a columnar Apache Arrow vector into ClickHouse without touching PostgreSQL. |
| **Which one did we test in our integration suites?** | **Gear 1.** [`test_energy_l1_to_l3_simulator_pipeline.py`](file:///Users/apple/soopa_mono/apps/ip/packages/ip/tests/integration/solutions/test_energy_l1_to_l3_simulator_pipeline.py) and [`test_energy_l3_to_l5_delivery_pipeline.py`](file:///Users/apple/soopa_mono/apps/ip/packages/ip/tests/integration/solutions/test_energy_l3_to_l5_delivery_pipeline.py) tested the transactional PostgreSQL + Stitch DAG pipeline. |
| **Are the two gears decoupled?** | **Yes.** Pure PostgreSQL for transactional business entities; pure ClickHouse + Arrow/Polars for high-frequency telemetry. Zero shared locks, zero architectural leakage. |
