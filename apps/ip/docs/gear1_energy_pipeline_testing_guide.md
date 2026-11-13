# Soopa Integration Platform (`apps/ip`)
## Hands-On Testing Guide: Gear-1 Transactional Energy Pipeline (L1 $\to$ L5)

- **Document:** Step-by-Step Practical Testing Guide for Gear 1
- **Status:** Approved Production Testing Guide
- **Location:** `apps/ip/docs/gear1_energy_pipeline_testing_guide.md`
- **Bounded Context:** Integration Platform Data Plane (`ip.engine`, `ip.solutions.domains.energy`)

---

## 1. Overview & Pipeline Architecture

Gear 1 governs all **transactional, row-oriented, event-driven business flows** in the Energy sector (move-in/move-out final meter reads, customer care dispute pings, monthly billing cutoff snapshots, and service point activations).

### The 5-Layer Lifecycle Under Test:
1. **Layer 1 (Ingress Ledger):** Captures incoming raw reading in `public.inbound_records` (<20ms HTTP 202 Accepted).
2. **Layer 2 (Replica Lake):** Records SHA-256 replica hash in `public.replica_records` for CDC and idempotent deduplication.
3. **Layer 3 (Canonical Normalization):** Maps raw vendor fields into typed domain table `public.mdm_meter_readings` and emits `CanonicalRecordChangedEvent` into the transactional outbox.
4. **Layer 4 (Stitch Orchestration):** Outbox relay triggers the Stitch DAG (`energy.meter_reading_erp_delivery_stitch`), resolving parent steps and staging the outbound delivery record in memory.
5. **Layer 5 (Outbound Egress):** Executes HTTP POST to the Utility ERP destination connector via `DeliverOutboundRecordUseCase`, tracking delivery receipts and idempotency keys.

---

## 2. Test Schemas

### 2.1 Inbound Source Schema (`meter_readings`)
* **Simulated Source:** AMI Head-End / Meter Data Management (Itron OpenWay / Landis+Gyr)
* **Stream Name:** `meter_readings`
* **Simulator Entity Modal Inputs:**
  - **Entity Name:** `meter_readings`
  - **Primary Key:** `meter_serial`
  - **Cursor Field:** `timestamp`
* **JSON Payload (Sample Blueprint):**
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

### 2.2 Outbound Destination Schema (`billing_readings`)
* **Simulated Destination:** Utility CIS / ERP Billing System (SAP S/4HANA / NetSuite)
* **Stream Name:** `billing_readings`
* **Simulator Entity Modal Inputs:**
  - **Entity Name:** `billing_readings`
  - **Primary Key:** `reading_id`
  - **Cursor Field:** `reading_timestamp`
* **JSON Payload (Sample Blueprint):**
```json
{
  "reading_id": "BILL-RDG-1001",
  "meter_serial": "MTR-ENERGY-1001",
  "kwh_delivered": 14.52,
  "reading_timestamp": "2026-11-12T12:00:00Z",
  "service_point_id": "SP-NORTH-401"
}
```

---

## 3. Method A: Automated End-to-End Test Execution

You can run the full, unmocked Gear 1 pipeline test against your local PostgreSQL database with a single CLI command:

### Command:
```bash
.venv/bin/python infra/local/scripts/run_in_test_env.py --domains platform,ip --skip-db-ensure -- \
  .venv/bin/pytest -p no:tach \
  apps/ip/packages/ip/tests/integration/solutions/test_energy_l1_to_l3_simulator_pipeline.py \
  apps/ip/packages/ip/tests/integration/solutions/test_energy_l3_to_l5_delivery_pipeline.py -v
```

### Expected Output:
```text
apps/ip/tests/integration/solutions/test_energy_l1_to_l3_simulator_pipeline.py::test_energy_l1_to_l3_simulator_pull_sync_pipeline PASSED
apps/ip/tests/integration/solutions/test_energy_l1_to_l3_simulator_pipeline.py::test_energy_l1_to_l3_push_webhook_out_of_order_reference_resolution PASSED
apps/ip/tests/integration/solutions/test_energy_l3_to_l5_delivery_pipeline.py::test_energy_l3_to_l5_stitch_orchestration_outbound_delivery PASSED
apps/ip/tests/integration/solutions/test_energy_l3_to_l5_delivery_pipeline.py::test_energy_l3_to_l5_idempotent_reconciliation_loop_suppression PASSED

============================== 4 passed in 7.30s ===============================
```

---

## 4. Method B: Step-by-Step Manual REST API Testing (via cURL)

Use this method to manually feed data into the running API server and observe transitions.

### Step 1: Create Source Connection (Universal Simulator)
```bash
curl -X POST "http://localhost:8000/api/v1/tenants/TENANT_ID/ip/connections" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -d '{
    "app_id": "universal_simulator",
    "name": "Itron AMI Simulator",
    "auth_type": "NO_AUTH",
    "public_config": {"seed": 3001, "records_per_pull": 5},
    "raw_credentials": {},
    "endpoint_for_fingerprint": "Itron AMI Simulator"
  }'
```
*Note the returned `id` as `SOURCE_CONN_ID`.*

### Step 2: Register Source Entity Blueprint
```bash
curl -X POST "http://localhost:8000/api/v1/tenants/TENANT_ID/ip/connections/SOURCE_CONN_ID/simulator/entities" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -d '{
    "entity_name": "meter_readings",
    "primary_key_field": "meter_serial",
    "cursor_field": "timestamp",
    "sample_blueprint": {
      "meter_serial": "MTR-ENERGY-1001",
      "timestamp": "2026-11-12T12:00:00Z",
      "kwh_delivered": 14.52,
      "kwh_received": 0.0,
      "voltage_avg": 240.1,
      "interval_minutes": 15,
      "service_point_id": "SP-NORTH-401"
    },
    "records_per_pull": 5
  }'
```

### Step 3: Trigger Ingress (Push Webhook $\to$ L1)
```bash
curl -X POST "http://localhost:8000/api/v1/ip/ingress/TENANT_SLUG/universal_simulator/SOURCE_CONN_ID?stream=meter_readings" \
  -H "Content-Type: application/json" \
  -H "X-Correlation-ID: corr_manual_001" \
  -d '{
    "meter_serial": "MTR-ENERGY-1001",
    "timestamp": "2026-11-12T12:00:00Z",
    "kwh_delivered": 14.52,
    "kwh_received": 0.0,
    "voltage_avg": 240.1,
    "interval_minutes": 15,
    "service_point_id": "SP-NORTH-401"
  }'
```
*Response: HTTP 202 Accepted with assigned `record_id`.*

### Step 4: Create Destination Connection (ERP Simulator)
```bash
curl -X POST "http://localhost:8000/api/v1/tenants/TENANT_ID/ip/connections" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -d '{
    "app_id": "universal_simulator",
    "name": "Utility CIS ERP Simulator",
    "auth_type": "NO_AUTH",
    "public_config": {"seed": 3002, "records_per_pull": 5},
    "raw_credentials": {},
    "endpoint_for_fingerprint": "Utility CIS ERP Simulator"
  }'
```
*Note the returned `id` as `DEST_CONN_ID`.*

### Step 5: Register Destination Entity Blueprint
```bash
curl -X POST "http://localhost:8000/api/v1/tenants/TENANT_ID/ip/connections/DEST_CONN_ID/simulator/entities" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -d '{
    "entity_name": "billing_readings",
    "primary_key_field": "reading_id",
    "cursor_field": "reading_timestamp",
    "sample_blueprint": {
      "reading_id": "BILL-RDG-1001",
      "meter_serial": "MTR-ENERGY-1001",
      "kwh_delivered": 14.52,
      "reading_timestamp": "2026-11-12T12:00:00Z",
      "service_point_id": "SP-NORTH-401"
    },
    "records_per_pull": 5
  }'
```

---

## 5. PostgreSQL Verification Queries (Layer-by-Layer)

Connect to the tenant database shard via `psql` to inspect the physical rows:

### 1. Verify Layer 1 (Raw Ingress Journal)
```sql
SELECT id, stream_name, payload_hash, length(raw_payload) AS bytes, created_at
FROM public.inbound_records
WHERE tenant_id = 'TENANT_ID'
ORDER BY created_at DESC LIMIT 5;
```
*Check: Record exists with status `RECEIVED`.*

### 2. Verify Layer 2 (Replica Lake & Deduplication)
```sql
SELECT id, stream_name, record_key, replica_hash, cdc_operation, updated_at
FROM public.replica_records
WHERE tenant_id = 'TENANT_ID'
ORDER BY updated_at DESC LIMIT 5;
```
*Check: `record_key = 'MTR-ENERGY-1001:2026-11-12T12:00:00Z'` and valid `replica_hash`.*

### 3. Verify Layer 3 (Normalized Canonical Table)
```sql
SELECT id, meter_serial_number, reading_timestamp, kwh_delivered, quality_flag, trace_id
FROM public.mdm_meter_readings
WHERE tenant_id = 'TENANT_ID'
ORDER BY reading_timestamp DESC LIMIT 5;
```
*Check: Row exists with `kwh_delivered = 14.52` and `quality_flag = 'VALIDATED'`.*

### 4. Verify Layer 4 (Stitch Workflow DAG Run)
```sql
SELECT id, workflow_id, status, triggered_by, started_at, finished_at
FROM public.workflow_runs
WHERE tenant_id = 'TENANT_ID'
ORDER BY started_at DESC LIMIT 5;

SELECT node_key, status, retry_count, finished_at
FROM public.workflow_step_runs
WHERE tenant_id = 'TENANT_ID'
ORDER BY finished_at DESC LIMIT 10;
```
*Check: `status = 'COMPLETED'` on `workflow_runs`, and steps `prepare_erp_dispatch` & `dispatch_erp_reading` both have `status = 'SUCCEEDED'`.*

### 5. Verify Layer 5 (Outbound Egress Delivery)
```sql
SELECT id, connection_id, stream_name, idempotency_key, status, response_status_code, delivered_at
FROM public.outbound_records
WHERE tenant_id = 'TENANT_ID'
ORDER BY created_at DESC LIMIT 5;
```
*Check: `status = 'DELIVERED'` and `response_status_code = 200`.*

### 6. Verify Complete Traceability (Audit Timeline)
```sql
SELECT event_type, layer, entity_id, latency_ms, created_at
FROM public.ip_trace_events
WHERE tenant_id = 'TENANT_ID'
ORDER BY created_at ASC;
```
*Check: Full audit trail displays: `INBOUND_INGESTED` $\to$ `REPLICA_STAGED` $\to$ `CANONICAL_COMMITTED` $\to$ `STITCH_STEP_SUCCEEDED` $\to$ `OUTBOUND_DISPATCH_DELIVERED`.*

---

## 6. Pass/Fail Assertion Checklist

| Verification Point | Success Criterion |
| :--- | :--- |
| **L1 Ingress Response** | Returns HTTP `202 Accepted` with valid `record_id` in `<20ms`. |
| **L2 Deduplication** | Identical payload sent twice updates `replica_records` without duplicate primary key errors. |
| **L3 Normalization** | Record appears in `mdm_meter_readings` with exact numerical precision ($14.52\text{ kWh}$). |
| **L4 Stitch Execution** | Workflow run finishes with `COMPLETED`; zero unhandled exceptions. |
| **L5 Egress Delivery** | Outbound record has `status = 'DELIVERED'`. Re-sending with same `idempotency_key` short-circuits with `was_deduplicated = true`. |
