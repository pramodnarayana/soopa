# Soopa Integration Platform (`apps/ip`)
## Hands-On Testing Guide: Gear-2 High-Frequency Telemetry Pipeline (L1 $\to$ L5)

- **Document:** Step-by-Step Practical Testing Guide for Gear 2
- **Status:** Approved Production Testing Guide
- **Location:** `apps/ip/docs/gear2_energy_telemetry_testing_guide.md`
- **Bounded Context:** Integration Platform Data Plane (`ip.engine`, high-frequency columnar telemetry)

---

## 1. Overview & Pipeline Architecture

Gear 2 governs all **high-frequency, columnar time-series telemetry** in the Energy sector (automated 15-minute / 5-minute interval smart-meter reads streaming in macro-batches of $10{,}000$ to $50{,}000$ readings per drop).

### The 5-Layer Lifecycle Under Test:
1. **Layer 1 (Ingress Shock-Absorber & Claim-Check):** Streaming Ingress buffers raw compressed drops (JSON, Zstd, or Parquet) into Tiered Object Storage (S3/MinIO `l1_raw/`) and records a `BatchManifestModel` (<10ms HTTP 202 Accepted).
2. **Layer 2 (Vectorized In-Memory Deduplication):** Rust Polars executes SIMD vector deduplication `(source_meter_id, channel_id, interval_end_utc)` in-memory with zero Python dict allocations, checkpointing to `l2_replica/` Parquet.
3. **Layer 3 (Vectorized Normalization & GEM Join):** Fused in-memory Apache Arrow pass performs IEC-61968 CIM unit scaling (`Wh` $\to$ `kWh`), Global Entity Model (GEM) dictionary hash-join, and PyOD/MAD spike quarantine.
4. **Layer 3.5 (Storm Outage Promotion Bridge):** Detects simultaneous $0\text{V}$ voltage drops across meters; if $>25$ meters on a feeder drop to $0\text{V}$, clusters them into one `FeederOutageClusterDetected` event emitted to Gear 1's `P0_CRITICAL` queue (<2s SLA).
5. **Layer 4 (Completeness Gates & Real-Time TOU Rollups):** ClickHouse `AggregatingMergeTree` materializes hourly TOU buckets and 96-slot completeness heatmaps incrementally upon commit.
6. **Layer 5 (Outbound Settlement & Bulk Delivery):** Once completeness reaches $\ge 99.5\%$, exports bulk Parquet to MDMS/Snowflake and records a downstream settlement delivery receipt.

---

## 2. Test Schemas & Formats

### 2.1 Inbound Macro-Batch Ingress Schema (JSON / Parquet)
* **Format:** Array of interval reading records (or Parquet file)
* **Stream Name:** `interval_readings`
* **Sample Array Element:**
```json
[
  {
    "meter_id": "MTR-SMART-9001",
    "feeder_id": "F-NORTH-12",
    "substation_id": "SUB-WEST-01",
    "interval_end": "2026-11-12T12:15:00Z",
    "kwh_delivered": 1.45,
    "kwh_received": 0.0,
    "voltage_v": 240.2,
    "quality": "VALID"
  },
  {
    "meter_id": "MTR-SMART-9002",
    "feeder_id": "F-NORTH-12",
    "substation_id": "SUB-WEST-01",
    "interval_end": "2026-11-12T12:15:00Z",
    "kwh_delivered": 0.98,
    "kwh_received": 0.0,
    "voltage_avg": 240.0,
    "quality": "VALID"
  }
]
```

### 2.2 ClickHouse Physical Storage DDL (`telemetry.meter_interval_readings_local`)
```sql
CREATE TABLE telemetry.meter_interval_readings_local (
    tenant_id UUID,
    connection_id UUID,
    gem_device_id UUID,
    source_meter_id LowCardinality(String),
    feeder_id LowCardinality(String),
    substation_id LowCardinality(String),
    tariff_bucket Enum8('PEAK' = 1, 'SHOULDER' = 2, 'OFF_PEAK' = 3),
    quality_status Enum8('VALID' = 1, 'ESTIMATED_VEE' = 2, 'QUARANTINED_SPIKE' = 6),
    interval_end_utc DateTime64(3, 'UTC'),
    scaled_kwh_delivered Decimal64(6) CODEC(ZSTD(3)),
    scaled_kwh_received Decimal64(6) CODEC(ZSTD(3)),
    voltage_v Decimal32(3) CODEC(ZSTD(3)),
    source_batch_id UUID,
    updated_at_utc DateTime64(3, 'UTC')
)
ENGINE = ReplicatedReplacingMergeTree(updated_at_utc)
PARTITION BY toYYYYMM(interval_end_utc)
ORDER BY (tenant_id, gem_device_id, interval_end_utc);
```

---

## 3. Method A: Automated Integration Test Execution

You can run the full Gear 2 interval streams test suite against your local test environment with a single command:

### Command:
```bash
.venv/bin/python infra/local/scripts/run_in_test_env.py --domains platform,ip --skip-db-ensure -- \
  .venv/bin/pytest -p no:tach apps/ip/packages/ip/tests/integration/test_interval_streams_pipeline.py -v
```

### Key Tests Verified in Suite:
1. `test_buffer_raw_interval_batch_creates_manifest_in_cold_storage`: Verifies L1 Ingress shock absorber, SHA-256 calculation, and `BatchManifestModel` creation.
2. `test_process_interval_batch_executes_zero_loss_reconciliation`: Verifies the **Zero-Loss Accounting Invariant** (`raw == valid + duplicates_dropped + quarantined`).
3. `test_process_interval_batch_detects_and_promotes_outage_clusters`: Verifies L3.5 Storm Outage Bridge (detects $\ge 25$ simultaneous $0\text{V}$ readings and publishes `P0_CRITICAL` event to Gear 1).
4. `test_interval_rollup_queries_and_completeness_matrix`: Verifies ClickHouse / Rollup repository queries return 96-slot completeness matrices and TOU aggregations.

---

## 4. Method B: Step-by-Step Manual REST API Testing (via cURL)

Ensure the backend server is running (`localhost:8000`).

### Step 1: Ingest High-Frequency Macro-Batch (L1 Ingress $\to$ S3/MinIO)
Drop a macro-batch of interval readings into the ingress buffer:
```bash
curl -X POST "http://localhost:8000/api/v1/tenants/TENANT_ID/ip/intervals/ingress/CONNECTION_ID?stream=interval_readings" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -d '[
    {
      "meter_id": "MTR-SMART-9001",
      "feeder_id": "F-NORTH-12",
      "substation_id": "SUB-WEST-01",
      "interval_end": "2026-11-12T12:15:00Z",
      "kwh_delivered": 1.45,
      "voltage_v": 240.2
    },
    {
      "meter_id": "MTR-SMART-9002",
      "feeder_id": "F-NORTH-12",
      "substation_id": "SUB-WEST-01",
      "interval_end": "2026-11-12T12:15:00Z",
      "kwh_delivered": 0.98,
      "voltage_v": 240.0
    }
  ]'
```
*Response returns HTTP 202 Accepted:*
```json
{
  "batch_id": "ip_bat_a1b2c3d4e5f6",
  "connection_id": "ip_conn_...",
  "stream_name": "interval_readings",
  "raw_count": 2,
  "payload_sha256": "8f4a...",
  "l1_raw_uri": "s3://soopa-ip-raw/tenants/.../l1_raw/batch_a1b2c3d4e5f6.json",
  "status": "BUFFERED",
  "trace_id": "ip_trc_..."
}
```
*Note the returned `batch_id`.*

---

### Step 2: Trigger Vectorized In-Memory Processing (L2 $\to$ L3 $\to$ L4)
Trigger the columnar worker to process the buffered macro-batch:
```bash
curl -X POST "http://localhost:8000/api/v1/tenants/TENANT_ID/ip/intervals/batches/BATCH_ID/process" \
  -H "Authorization: Bearer YOUR_TOKEN"
```
*Response returns the Zero-Loss Accounting Summary:*
```json
{
  "batch_id": "ip_bat_a1b2c3d4e5f6",
  "status": "COMPLETED",
  "raw_ingested": 2,
  "duplicates_dropped": 0,
  "valid_canonical": 2,
  "quarantined_held": 0,
  "is_zero_loss_balanced": true,
  "promoted_outage_clusters": [],
  "l2_replica_uri": "s3://.../l2_replica/batch_a1b2c3d4e5f6.parquet",
  "l3_canonical_uri": "s3://.../l3_canonical/batch_a1b2c3d4e5f6.parquet"
}
```

---

### Step 3: Query Zero-Missing-Data Reconciliation
Inspect the Command Center Zero Missing Data Guarantee summary:
```bash
curl -X GET "http://localhost:8000/api/v1/tenants/TENANT_ID/ip/intervals/reconciliation" \
  -H "Authorization: Bearer YOUR_TOKEN"
```
*Returns aggregate counts showing:* `raw_ingested == duplicates_dropped + valid_canonical + quarantined_held` *(0 unaccounted drops)*.

---

### Step 4: Query 96-Slot Completeness Heatmap (L4 Aggregations)
```bash
curl -X GET "http://localhost:8000/api/v1/tenants/TENANT_ID/ip/intervals/completeness?date=2026-11-12" \
  -H "Authorization: Bearer YOUR_TOKEN"
```
*Returns 96-slot completeness percentage per substation/feeder.*

---

### Step 5: Record Downstream Settlement Delivery Receipt (L5 Egress)
```bash
curl -X POST "http://localhost:8000/api/v1/tenants/TENANT_ID/ip/intervals/batches/BATCH_ID/receipt" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -d '{
    "delivery_receipt_id": "SETTLE-MDMS-ACK-88910"
  }'
```
*Response confirms settlement receipt recorded on the batch manifest.*

---

## 5. Verification Queries & Storage Inspection

### 1. Verify Batch Manifest in PostgreSQL
```sql
SELECT id, stream_name, status, raw_ingested_count, valid_canonical_count, 
       duplicates_dropped_count, quarantined_held_count, delivery_receipt_id, completed_at
FROM public.batch_manifests
WHERE tenant_id = 'TENANT_ID'
ORDER BY created_at DESC LIMIT 5;
```
*Assertion: `status = 'COMPLETED'` and `raw_ingested_count == valid_canonical_count + duplicates_dropped_count + quarantined_held_count`.*

### 2. Verify ClickHouse Interval Table (Zero-Loss Columnar Storage)
In `clickhouse-client`:
```sql
SELECT gem_device_id, interval_end_utc, scaled_kwh_delivered, voltage_v, quality_status
FROM telemetry.meter_interval_readings_local
WHERE tenant_id = 'TENANT_ID'
ORDER BY interval_end_utc DESC LIMIT 10;
```

### 3. Verify ClickHouse Real-Time Pre-Aggregated Hourly TOU View
```sql
SELECT hour_start_utc, count() AS interval_count, sum(total_kwh_delivered) AS total_kwh
FROM telemetry.hourly_interval_rollups_local
WHERE tenant_id = 'TENANT_ID'
GROUP BY hour_start_utc
ORDER BY hour_start_utc DESC LIMIT 5;
```

---

## 6. Pass/Fail Assertion Checklist

| Verification Point | Success Criterion |
| :--- | :--- |
| **L1 Ingress Throughput** | HTTP `202 Accepted` returned in $<10\text{ms}$ with S3 raw URI assigned. |
| **Zero-Loss Accounting** | `is_zero_loss_balanced == true` (`raw == valid + duplicates + quarantined`). Any variance halts batch with `P0_CRITICAL` alert. |
| **L2 Deduplication** | Ingesting duplicate batch sets `duplicates_dropped_count` equal to duplicate rows, with zero database lock errors. |
| **L3.5 Storm Outage Bridge** | Feeding $>25$ simultaneous $0\text{V}$ readings populates `promoted_outage_clusters` and enqueues 1 consolidated event to Gear 1. |
| **L4 Query Latency** | 96-slot completeness and TOU rollup queries return in $<25\text{ms}$ via ClickHouse `AggregatingMergeTree`. |
