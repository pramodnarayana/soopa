# Soopa Integration Platform (`apps/ip`)
# Gear 2: High-Frequency Telemetry Pipeline Manual Testing Guide (L1 $\to$ L5)

- **Target System:** Gear 2 High-Frequency Columnar Telemetry Data Plane (`ip.engine`, ClickHouse OLAP)
- **Storage Layer:** S3/MinIO Claim-Check (`l1_raw/`), Rust Polars SIMD (`l2_replica/`), ClickHouse OLAP (`telemetry.meter_interval_readings_local`)
- **Engine:** Vectorized SIMD Deduplication, Arrow GEM Hash-Join, 96-Slot Completeness Heatmap, Hourly TOU Rollups
- **Repository Location:** [`apps/ip/docs/gear2_manual_testing_guide.md`](file:///Users/apple/soopa_mono/apps/ip/docs/gear2_manual_testing_guide.md)

---

## 1. Gear 2 Configuration & Specification Matrix

| Role in Pipeline | Vendor Name | Connection Name | App Catalog ID | Stream Name | Partition / Primary Key | Cursor Field | Target Storage |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **Ingress Stream** | **Landis+Gyr** (Gridstream AMI) | `Landis+Gyr Gridstream AMI` | `universal_simulator` | `interval_readings` | `(source_meter_id, channel_id, interval_end_utc)` | `interval_end` | S3 / MinIO $\to$ ClickHouse `telemetry.meter_interval_readings_local` |

---

## 2. Inbound Macro-Batch Blueprint (`interval_readings`)

* **Vendor:** Landis+Gyr (Product: Gridstream AMI)
* **Connection Name:** `Landis+Gyr Gridstream AMI`
* **Format:** Macro-Batch JSON Array (or Zstd Parquet)
* **Copy-Paste Blueprint:**
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

---

## 3. Step-by-Step API Execution

### Step 1: Ingest Macro-Batch (L1 Shock-Absorber $\to$ S3/MinIO)
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
*Expected Output:* HTTP `202 Accepted` with `batch_id`.

### Step 2: Trigger Vectorized In-Memory Processing (L2 $\to$ L3 $\to$ L4)
```bash
curl -X POST "http://localhost:8000/api/v1/tenants/TENANT_ID/ip/intervals/batches/BATCH_ID/process" \
  -H "Authorization: Bearer YOUR_TOKEN"
```
*Expected Output (Zero-Loss Reconciliation Summary):*
```json
{
  "batch_id": "ip_bat_...",
  "status": "COMPLETED",
  "raw_ingested": 2,
  "duplicates_dropped": 0,
  "valid_canonical": 2,
  "quarantined_held": 0,
  "is_zero_loss_balanced": true
}
```

### Step 3: Query 96-Slot Completeness Heatmap (L4 Aggregations)
```bash
curl -X GET "http://localhost:8000/api/v1/tenants/TENANT_ID/ip/intervals/completeness?date=2026-11-12" \
  -H "Authorization: Bearer YOUR_TOKEN"
```

### Step 4: Record Downstream Settlement Delivery Receipt (L5 Egress)
```bash
curl -X POST "http://localhost:8000/api/v1/tenants/TENANT_ID/ip/intervals/batches/BATCH_ID/receipt" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -d '{
    "delivery_receipt_id": "SETTLE-MDMS-ACK-88910"
  }'
```

---

## 4. Verification Queries

### 1. PostgreSQL Batch Manifest Verification
```sql
SELECT id, stream_name, status, raw_ingested_count, valid_canonical_count, 
       duplicates_dropped_count, quarantined_held_count, delivery_receipt_id 
FROM public.batch_manifests 
WHERE tenant_id = 'TENANT_ID' 
ORDER BY created_at DESC LIMIT 1;
```

### 2. ClickHouse Columnar Verification
In `clickhouse-client`:
```sql
SELECT gem_device_id, source_meter_id, interval_end_utc, scaled_kwh_delivered, voltage_v, quality_status 
FROM telemetry.meter_interval_readings_local 
WHERE tenant_id = 'TENANT_ID' 
ORDER BY interval_end_utc DESC LIMIT 5;
```
