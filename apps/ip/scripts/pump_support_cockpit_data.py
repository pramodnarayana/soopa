"""Gold-Standard Seed Script for Customer Support Cockpit & Operational Observability.

Idempotently pumps rich, enterprise-grade test data across:
1. Control Plane metadata in global_db (ip schema):
   - Connections (Shopify, SAP S/4HANA, Oracle MDM, Acme API)
   - Connection Entities (orders, invoices, interval_readings)
   - Connection Policies (rate limits, concurrency windows)
   - Sync Runs (completed incremental syncs with telemetry)
   - Mapping Specs (Shopify Invoices to SAP BAPI)
   - Stitches (Shopify to SAP, AMI Interval Settlement, Partner EDI)
   - Stitch Task Configs (DAG node execution policies)
   - Transformations (Active & Shadow versions)

2. Data Plane transactional records in ip_shard (public schema):
   - Inbound Records (Layer 1 raw wire payloads)
   - Replica Records (Layer 2 parsed JSON replicas with versioning)
   - Normalized Records (Layer 3 universal canonical index)
   - Global Entity Map (Layer 4 identity crosswalk between Shopify and SAP)
   - Outbound Records (Layer 5 egress records with failed 503 transient error and replay)
   - Trace Events (Full audit timeline from received to delivery failure and replay)
   - Workflow Runs & Step Runs (Durable Layer 4 DAG execution ledger)
   - Batch Manifests (Zero-loss high-frequency interval macro-batches)

Populates for both the active authenticated tenant ('iam_ten_752f7997d2ecf38fd8dfe2dfce9043e5')
and standard UI test fixture tenant ('ten_9f8e7d6c5b4a3f2e1d0c9b8a').
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
from datetime import UTC, datetime, timedelta

import asyncpg
import structlog

logger = structlog.get_logger(__name__)

ACTIVE_TENANT_ID = "iam_ten_752f7997d2ecf38fd8dfe2dfce9043e5"
SEED_TENANT_ID = "ten_9f8e7d6c5b4a3f2e1d0c9b8a"
TARGET_TENANTS = [ACTIVE_TENANT_ID, SEED_TENANT_ID]

GLOBAL_DB_URL = os.environ.get(
    "DATABASE_URL", "postgresql://ucp_admin:ucp_password@localhost:5432/global_db"
).replace("postgresql+asyncpg://", "postgresql://")

IP_SHARD_URL = os.environ.get(
    "IP_DATABASE_URL", "postgresql://ip:ip_password@localhost:5434/ip_shard"
).replace("postgresql+asyncpg://", "postgresql://")


async def _seed_tenants_and_shards(conn: asyncpg.Connection, naive_now: datetime) -> None:
    for t_id, slug, name in [
        (ACTIVE_TENANT_ID, "greatlakes", "Greatlakes"),
        (SEED_TENANT_ID, "acme-enterprise", "Acme Enterprise"),
    ]:
        await conn.execute(
            """
            INSERT INTO identity.tenants (id, slug, name, status, created_at, updated_at)
            VALUES ($1, $2, $3, 'active', $4, $4)
            ON CONFLICT (id) DO UPDATE SET
                slug = EXCLUDED.slug,
                name = EXCLUDED.name,
                status = 'active',
                updated_at = EXCLUDED.updated_at;
            """,
            t_id,
            slug,
            name,
            naive_now,
        )
        logger.info("control_plane_tenant_ensured", tenant_id=t_id, slug=slug)

    await conn.execute(
        """
        INSERT INTO ucp.apps (id, slug, name, description, created_at, updated_at)
        VALUES ('app_ip_core', 'ip', 'Integration Platform', 'Enterprise Integration Platform (iPaaS)', $1, $1)
        ON CONFLICT (slug) DO UPDATE SET
            name = EXCLUDED.name,
            description = EXCLUDED.description,
            updated_at = EXCLUDED.updated_at;
        """,
        naive_now,
    )
    logger.info("control_plane_app_ensured", app_id="app_ip_core")

    await conn.execute(
        """
        INSERT INTO ucp.database_shards (id, name, dsn, routing_strategy, status, created_at, updated_at)
        VALUES ('ip_shard_1', 'IP Shard (ip_shard_1)', 'postgresql+asyncpg://ip:ip_password@localhost:5434/ip_shard', 'tenant_registry', 'active', $1, $1)
        ON CONFLICT (id) DO UPDATE SET
            name = EXCLUDED.name,
            dsn = EXCLUDED.dsn,
            status = 'active',
            updated_at = EXCLUDED.updated_at;
        """,
        naive_now,
    )

    for t_id in TARGET_TENANTS:
        await conn.execute(
            """
            INSERT INTO ucp.app_subscriptions (tenant_id, app_id, tier, status, created_at, updated_at)
            VALUES ($1, 'app_ip_core', 'standard', 'active', $2, $2)
            ON CONFLICT (tenant_id, app_id) DO UPDATE SET status = 'active', updated_at = EXCLUDED.updated_at;
            """,
            t_id,
            naive_now,
        )
        await conn.execute(
            """
            INSERT INTO ucp.shard_registry (tenant_id, app_id, shard_id, status, created_at, updated_at)
            VALUES ($1, 'app_ip_core', 'ip_shard_1', 'active', $2, $2)
            ON CONFLICT (tenant_id, app_id) DO UPDATE SET shard_id = 'ip_shard_1', status = 'active', updated_at = EXCLUDED.updated_at;
            """,
            t_id,
            naive_now,
        )
        logger.info("control_plane_tenant_shard_bound", tenant_id=t_id, shard_id="ip_shard_1")


async def _seed_connections(conn: asyncpg.Connection, now: datetime) -> None:
    connections_data = [
        (
            "conn_shopify_source_01",
            "shopify",
            "Shopify Store (US-East)",
            "OAUTH2",
            json.dumps({"shop_domain": "corp-store.myshopify.com", "api_version": "2026-10"}),
            "fp_shopify_useast_01",
            "ACTIVE",
        ),
        (
            "conn_sap_dest_01",
            "sap_s4hana",
            "SAP S/4HANA ERP",
            "API_KEY",
            json.dumps({"base_url": "https://sap-gateway.corp.example.com", "client": "100"}),
            "fp_sap_s4hana_corp",
            "ACTIVE",
        ),
        (
            "conn_oracle_mdm_01",
            "oracle_mdm",
            "Oracle MDM HES Gateway",
            "NO_AUTH",
            json.dumps({"endpoint": "https://hes-oracle.grid.example.com/api/v2"}),
            "fp_oracle_mdm_hes",
            "ACTIVE",
        ),
        (
            "conn_acme_source_01",
            "acme_source",
            "Acme Ingestion API",
            "OAUTH2",
            json.dumps({"base_url": "https://api.acme.example.com"}),
            "fp_acme_source_01",
            "ACTIVE",
        ),
    ]

    for t_id in TARGET_TENANTS:
        for c_id, app_id, name, auth_type, pub_cfg, fp, status in connections_data:
            scoped_fp = f"{t_id[:8]}_{fp}"
            await conn.execute(
                """
                INSERT INTO ip.connections (
                    id, tenant_id, app_id, name, auth_type, public_config,
                    encrypted_credentials, key_encryption_version, connection_fingerprint,
                    status, created_at, updated_at
                )
                VALUES ($1, $2, $3, $4, $5, $6::jsonb, NULL, 1, $7, $8, $9, $9)
                ON CONFLICT (id) DO UPDATE SET
                    name = EXCLUDED.name,
                    status = EXCLUDED.status,
                    public_config = EXCLUDED.public_config,
                    updated_at = EXCLUDED.updated_at;
                """,
                c_id if t_id == ACTIVE_TENANT_ID else f"{c_id}_{t_id[:8]}",
                t_id,
                app_id,
                name,
                auth_type,
                pub_cfg,
                scoped_fp,
                status,
                now,
            )
        logger.info("control_plane_connections_seeded", tenant_id=t_id, count=4)


async def _seed_connection_entities(conn: asyncpg.Connection, now: datetime) -> None:
    for t_id in TARGET_TENANTS:
        shopify_conn = (
            "conn_shopify_source_01"
            if t_id == ACTIVE_TENANT_ID
            else f"conn_shopify_source_01_{t_id[:8]}"
        )
        oracle_conn = (
            "conn_oracle_mdm_01" if t_id == ACTIVE_TENANT_ID else f"conn_oracle_mdm_01_{t_id[:8]}"
        )
        acme_conn = (
            "conn_acme_source_01" if t_id == ACTIVE_TENANT_ID else f"conn_acme_source_01_{t_id[:8]}"
        )

        entities = [
            (
                f"ent_orders_{t_id[:8]}",
                shopify_conn,
                "orders",
                "INCREMENTAL",
                "every_15m",
                148200,
                ["order_id"],
                "updated_at",
            ),
            (
                f"ent_invoices_{t_id[:8]}",
                shopify_conn,
                "invoices",
                "INCREMENTAL",
                "every_1h",
                84350,
                ["invoice_id"],
                "created_at",
            ),
            (
                f"ent_customers_{t_id[:8]}",
                shopify_conn,
                "customers",
                "INCREMENTAL",
                "every_1h",
                52100,
                ["customer_id"],
                "updated_at",
            ),
            (
                f"ent_intervals_{t_id[:8]}",
                oracle_conn,
                "interval_readings",
                "INCREMENTAL",
                "every_15m",
                2450000,
                ["reading_id", "interval_end_utc"],
                "interval_end_utc",
            ),
            (
                f"ent_shipments_{t_id[:8]}",
                acme_conn,
                "shipment_loads",
                "INCREMENTAL",
                "every_30m",
                18400,
                ["load_id"],
                "updated_at",
            ),
        ]

        for ent_id, c_id, s_name, sync_mode, sched, cnt, pk, cursor in entities:
            await conn.execute(
                """
                INSERT INTO ip.connection_entities (
                    id, tenant_id, connection_id, stream_name, sync_mode,
                    schedule, sync_from, is_enabled, primary_key, fields_schema,
                    cursor_field, cursor_value, records_synced_count, last_synced_at,
                    created_at, updated_at
                )
                VALUES (
                    $1, $2, $3, $4, $5, $6, 'ALL', true, $7::jsonb, '{}'::jsonb,
                    $8, '2026-11-23T11:00:00Z', $9, $10, $10, $10
                )
                ON CONFLICT (tenant_id, connection_id, stream_name) DO UPDATE SET
                    records_synced_count = EXCLUDED.records_synced_count,
                    last_synced_at = EXCLUDED.last_synced_at,
                    updated_at = EXCLUDED.updated_at;
                """,
                ent_id,
                t_id,
                c_id,
                s_name,
                sync_mode,
                sched,
                json.dumps(pk),
                cursor,
                cnt,
                now,
            )
        logger.info("control_plane_connection_entities_seeded", tenant_id=t_id, count=len(entities))


async def _seed_sync_runs(conn: asyncpg.Connection, now: datetime) -> None:
    for t_id in TARGET_TENANTS:
        shopify_conn = (
            "conn_shopify_source_01"
            if t_id == ACTIVE_TENANT_ID
            else f"conn_shopify_source_01_{t_id[:8]}"
        )
        sync_runs = [
            (
                f"sync_orders_01_{t_id[:8]}",
                shopify_conn,
                "orders",
                "INCREMENTAL",
                12,
                "SUCCEEDED",
                1250,
                512000,
                "trc_inv_99882_err",
            ),
            (
                f"sync_invoices_01_{t_id[:8]}",
                shopify_conn,
                "invoices",
                "INCREMENTAL",
                14,
                "SUCCEEDED",
                420,
                198000,
                "trc_inv_99881_ok",
            ),
        ]
        for run_id, c_id, stream, kind, gen, status, rec_cnt, byte_cnt, trc in sync_runs:
            await conn.execute(
                """
                INSERT INTO ip.sync_runs (
                    id, tenant_id, connection_id, stream, kind, generation_id,
                    status, start_checkpoint, end_checkpoint, pages_synced,
                    records_synced, bytes_synced, retries_count, trace_id,
                    started_at, finished_at, created_at
                )
                VALUES (
                    $1, $2, $3, $4, $5, $6, $7,
                    '2026-11-23T10:00:00Z', '2026-11-23T11:00:00Z', 4,
                    $8, $9, 0, $10,
                    $11, $11, $11
                )
                ON CONFLICT (id) DO UPDATE SET
                    records_synced = EXCLUDED.records_synced,
                    bytes_synced = EXCLUDED.bytes_synced;
                """,
                run_id,
                t_id,
                c_id,
                stream,
                kind,
                gen,
                status,
                rec_cnt,
                byte_cnt,
                trc,
                now - timedelta(minutes=15),
            )
        logger.info("control_plane_sync_runs_seeded", tenant_id=t_id, count=len(sync_runs))


async def _seed_mapping_specs(conn: asyncpg.Connection, now: datetime) -> None:
    for t_id in TARGET_TENANTS:
        sap_conn = (
            "conn_sap_dest_01" if t_id == ACTIVE_TENANT_ID else f"conn_sap_dest_01_{t_id[:8]}"
        )
        map_id = f"map_shopify_sap_inv_{t_id[:8]}"
        rules = [
            {"sourceField": "invoiceNumber", "targetField": "refDoc", "transform": "DIRECT"},
            {"sourceField": "total", "targetField": "grossAmount", "transform": "NUMERIC"},
            {"sourceField": "currency", "targetField": "currencyCode", "transform": "UPPERCASE"},
            {"sourceField": "customerRef", "targetField": "customerId", "transform": "DIRECT"},
        ]
        await conn.execute(
            """
            INSERT INTO ip.mapping_specs (
                id, tenant_id, name, description, source_type,
                target_connection_id, target_entity_name, version,
                rules, is_active, created_at, updated_at
            )
            VALUES (
                $1, $2, 'Shopify Invoices to SAP BAPI',
                'Transforms canonical invoice events into SAP S/4HANA BAPI invoice structures',
                'canonical.invoice.v1', $3, 'invoices', 1,
                $4::jsonb, true, $5, $5
            )
            ON CONFLICT (tenant_id, target_connection_id, target_entity_name, version)
            DO UPDATE SET rules = EXCLUDED.rules, updated_at = EXCLUDED.updated_at;
            """,
            map_id,
            t_id,
            sap_conn,
            json.dumps(rules),
            now,
        )
        logger.info("control_plane_mapping_specs_seeded", tenant_id=t_id, map_id=map_id)


async def _seed_stitches_and_configs(conn: asyncpg.Connection, now: datetime) -> None:
    for t_id in TARGET_TENANTS:
        map_id = f"map_shopify_sap_inv_{t_id[:8]}"
        stitches = [
            (
                f"stc_shopify_to_sap_{t_id[:8]}",
                "canonical.invoice.v1",
                "workflow.shopify_orders_to_sap",
                "Shopify Orders to SAP S/4HANA",
                "Validates inbound canonical invoices, runs GEM customer crosswalk, and delivers to SAP S/4HANA.",
                map_id,
            ),
            (
                f"stc_ami_interval_settlement_{t_id[:8]}",
                "canonical.device.telemetry.reading",
                "energy.meter_reading_erp_sync_stitch",
                "AMI 15-Minute Interval Settlement & Billing",
                "Aggregates 96-window interval readings, reconciles TOU tariff blocks, and pushes settlement rollups.",
                None,
            ),
            (
                f"stc_partner_edi_sync_{t_id[:8]}",
                "canonical.order.v1",
                "tms.load_tender_erp_sync_stitch",
                "B2B Partner EDI 850 Order Sync",
                "Translates incoming purchase orders into standard carrier transport tenders.",
                None,
            ),
        ]
        for s_id, event_type, wf_id, name, desc, m_id in stitches:
            await conn.execute(
                """
                INSERT INTO ip.stitches (
                    id, tenant_id, canonical_event_type, target_workflow_id,
                    name, description, mapping_spec_id, filter_conditions,
                    is_active, created_at, updated_at
                )
                VALUES (
                    $1, $2, $3, $4, $5, $6, $7, '{}'::jsonb, true, $8, $8
                )
                ON CONFLICT (id, tenant_id) DO UPDATE SET
                    name = EXCLUDED.name,
                    description = EXCLUDED.description,
                    mapping_spec_id = EXCLUDED.mapping_spec_id,
                    target_workflow_id = EXCLUDED.target_workflow_id,
                    is_active = true,
                    updated_at = EXCLUDED.updated_at;
                """,
                s_id,
                t_id,
                event_type,
                wf_id,
                name,
                desc,
                m_id,
                now,
            )

        stitch_id = f"stc_shopify_to_sap_{t_id[:8]}"
        tasks = [
            (f"stc_cfg_val_{t_id[:8]}", stitch_id, "validate_payload", 30, "ip-dp-default"),
            (f"stc_cfg_norm_{t_id[:8]}", stitch_id, "normalize_entities", 30, "ip-dp-default"),
            (f"stc_cfg_gem_{t_id[:8]}", stitch_id, "gem_crosswalk", 15, "ip-dp-default"),
            (f"stc_cfg_out_{t_id[:8]}", stitch_id, "outbound_http", 60, "ip-dp-outbound"),
        ]
        for cfg_id, stch_id, node_key, timeout, queue in tasks:
            await conn.execute(
                """
                INSERT INTO ip.stitch_task_configs (
                    id, tenant_id, stitch_id, node_key, timeout_seconds,
                    heartbeat_interval_seconds, max_attempts, initial_delay_seconds,
                    backoff_multiplier, max_delay_seconds, queue_name, max_in_flight_tasks,
                    failure_disposition, created_at, updated_at
                )
                VALUES (
                    $1, $2, $3, $4, $5, 10, 3, 1.0, 2.0, 30.0, $6, 10, 'RETRY', $7, $7
                )
                ON CONFLICT (tenant_id, stitch_id, node_key) DO UPDATE SET
                    timeout_seconds = EXCLUDED.timeout_seconds,
                    queue_name = EXCLUDED.queue_name;
                """,
                cfg_id,
                t_id,
                stch_id,
                node_key,
                timeout,
                queue,
                now,
            )
        logger.info("control_plane_stitches_seeded", tenant_id=t_id, count=len(stitches))


async def _seed_transformations(conn: asyncpg.Connection, now: datetime) -> None:
    for t_id in TARGET_TENANTS:
        shopify_conn = (
            "conn_shopify_source_01"
            if t_id == ACTIVE_TENANT_ID
            else f"conn_shopify_source_01_{t_id[:8]}"
        )
        oracle_conn = (
            "conn_oracle_mdm_01" if t_id == ACTIVE_TENANT_ID else f"conn_oracle_mdm_01_{t_id[:8]}"
        )
        transforms = [
            (f"trn_orders_{t_id[:8]}", shopify_conn, "orders", "shopify.orders.to_gem", 1, 2),
            (
                f"trn_invoices_{t_id[:8]}",
                shopify_conn,
                "invoices",
                "shopify.invoices.to_gem",
                1,
                None,
            ),
            (
                f"trn_intervals_{t_id[:8]}",
                oracle_conn,
                "interval_readings",
                "hes.interval.to_cim",
                1,
                None,
            ),
        ]
        for trn_id, c_id, stream, trans_id, v, shadow_v in transforms:
            await conn.execute(
                """
                INSERT INTO ip.transformations (
                    id, tenant_id, connection_id, stream, transformation_id,
                    transformation_version, mode, shadow_transformation_version,
                    created_at, updated_at
                )
                VALUES ($1, $2, $3, $4, $5, $6, 'ACTIVE', $7, $8, $8)
                ON CONFLICT (id) DO UPDATE SET
                    mode = 'ACTIVE',
                    shadow_transformation_version = EXCLUDED.shadow_transformation_version,
                    updated_at = EXCLUDED.updated_at;
                """,
                trn_id,
                t_id,
                c_id,
                stream,
                trans_id,
                v,
                shadow_v,
                now,
            )
        logger.info("control_plane_transformations_seeded", tenant_id=t_id, count=len(transforms))


async def pump_global_control_plane(conn: asyncpg.Connection) -> None:
    logger.info("control_plane_seeding_started")
    naive_now = datetime.now()
    now = datetime.now(UTC)

    await _seed_tenants_and_shards(conn, naive_now)
    await _seed_connections(conn, now)
    await _seed_connection_entities(conn, now)
    await _seed_sync_runs(conn, now)
    await _seed_mapping_specs(conn, now)
    await _seed_stitches_and_configs(conn, now)
    await _seed_transformations(conn, now)
    logger.info("control_plane_seeding_completed")


async def _cleanup_tenant_data(conn: asyncpg.Connection) -> None:
    for t_id in TARGET_TENANTS:
        await conn.execute("DELETE FROM public.ip_batch_manifests WHERE tenant_id = $1", t_id)
        await conn.execute("DELETE FROM public.workflow_step_runs WHERE tenant_id = $1", t_id)
        await conn.execute("DELETE FROM public.workflow_runs WHERE tenant_id = $1", t_id)
        await conn.execute("DELETE FROM public.ip_trace_events WHERE tenant_id = $1", t_id)
        await conn.execute("DELETE FROM public.outbound_records WHERE tenant_id = $1", t_id)
        await conn.execute("DELETE FROM public.global_entity_map WHERE tenant_id = $1", t_id)
        await conn.execute("DELETE FROM public.normalized_records WHERE tenant_id = $1", t_id)
        await conn.execute("DELETE FROM public.replica_records WHERE tenant_id = $1", t_id)
        await conn.execute("DELETE FROM public.inbound_records WHERE tenant_id = $1", t_id)
        logger.info("data_plane_tenant_cleaned", tenant_id=t_id)


async def _seed_inbound_records(conn: asyncpg.Connection, now: datetime) -> None:
    for t_id in TARGET_TENANTS:
        shopify_conn = (
            "conn_shopify_source_01"
            if t_id == ACTIVE_TENANT_ID
            else f"conn_shopify_source_01_{t_id[:8]}"
        )
        oracle_conn = (
            "conn_oracle_mdm_01" if t_id == ACTIVE_TENANT_ID else f"conn_oracle_mdm_01_{t_id[:8]}"
        )
        acme_conn = (
            "conn_acme_source_01" if t_id == ACTIVE_TENANT_ID else f"conn_acme_source_01_{t_id[:8]}"
        )
        inbound_records = [
            (
                f"inb_inv_99882_{t_id[:8]}",
                shopify_conn,
                "shopify",
                "invoices",
                "trc_inv_99882_err",
                "INV-99882",
                json.dumps(
                    {
                        "content-type": "application/json",
                        "x-shopify-topic": "invoices/create",
                        "x-shopify-hmac-sha256": "4a7b9c...[REDACTED]",
                    }
                ),
                json.dumps(
                    {
                        "invoice_id": "INV-99882",
                        "order_number": "ORD-7719",
                        "customer": {
                            "email": "sarah.connor@cyberdyne.example.com",
                            "account_id": "CUST-8841",
                        },
                        "billing_address": {
                            "city": "Los Angeles",
                            "state": "CA",
                            "country": "US",
                        },
                        "line_items": [
                            {
                                "sku": "SKU-TURBO-01",
                                "description": "Hydraulic Actuator Unit",
                                "quantity": 2,
                                "unit_price": 725.00,
                            }
                        ],
                        "total_amount": 1450.00,
                        "currency": "USD",
                        "created_at": "2026-11-23T11:45:00Z",
                    }
                ),
                482,
                hashlib.sha256(b"inb_99882").hexdigest(),
                202,
                11,
                now - timedelta(minutes=30),
            ),
            (
                f"inb_inv_99881_{t_id[:8]}",
                shopify_conn,
                "shopify",
                "invoices",
                "trc_inv_99881_ok",
                "INV-99881",
                json.dumps({"content-type": "application/json"}),
                json.dumps(
                    {
                        "invoice_id": "INV-99881",
                        "order_number": "ORD-7718",
                        "customer": {"email": "john.doe@example.org", "account_id": "CUST-1022"},
                        "total_amount": 850.00,
                        "currency": "USD",
                    }
                ),
                320,
                hashlib.sha256(b"inb_99881").hexdigest(),
                202,
                9,
                now - timedelta(minutes=45),
            ),
            (
                f"inb_ord_7719_{t_id[:8]}",
                shopify_conn,
                "shopify",
                "orders",
                "trc_ord_7719_ok",
                "ORD-7719",
                json.dumps({"content-type": "application/json", "x-shopify-topic": "orders/paid"}),
                json.dumps(
                    {
                        "order_id": "ORD-7719",
                        "customer": {
                            "email": "orders@atlaslogistics.com",
                            "name": "Atlas Logistics Corp",
                        },
                        "total_price": 3450.00,
                        "currency": "USD",
                        "financial_status": "paid",
                        "line_items": [
                            {"title": "High-Pressure Seal Kit", "quantity": 3, "price": 1150.00}
                        ],
                    }
                ),
                410,
                hashlib.sha256(b"inb_ord_7719").hexdigest(),
                202,
                12,
                now - timedelta(minutes=35),
            ),
            (
                f"inb_ord_7720_{t_id[:8]}",
                shopify_conn,
                "shopify",
                "orders",
                "trc_ord_7720_ok",
                "ORD-7720",
                json.dumps({"content-type": "application/json", "x-shopify-topic": "orders/paid"}),
                json.dumps(
                    {
                        "order_id": "ORD-7720",
                        "customer": {
                            "email": "billing@summitglobal.org",
                            "name": "Summit Global Trade",
                        },
                        "total_price": 1820.50,
                        "currency": "USD",
                        "financial_status": "paid",
                    }
                ),
                335,
                hashlib.sha256(b"inb_ord_7720").hexdigest(),
                202,
                10,
                now - timedelta(minutes=50),
            ),
            (
                f"inb_read_1001_{t_id[:8]}",
                oracle_conn,
                "oracle_mdm",
                "interval_readings",
                "trc_read_1001_ok",
                "READ-MTR-1001",
                json.dumps({"content-type": "application/json"}),
                json.dumps(
                    {
                        "meter_id": "MTR-GLK-9901",
                        "reading_value": 48.75,
                        "uom": "kWh",
                        "interval_start": "2026-11-23T11:00:00Z",
                    }
                ),
                280,
                hashlib.sha256(b"inb_read_1001").hexdigest(),
                202,
                8,
                now - timedelta(minutes=15),
            ),
            (
                f"inb_load_4401_{t_id[:8]}",
                acme_conn,
                "acme_source",
                "shipment_loads",
                "trc_load_4401_ok",
                "LOAD-4401",
                json.dumps({"content-type": "application/json"}),
                json.dumps(
                    {
                        "tender_id": "TND-88201",
                        "load_id": "LOAD-4401",
                        "origin_city": "Chicago, IL",
                        "destination_city": "Atlanta, GA",
                        "carrier": "Schneider Freight",
                    }
                ),
                340,
                hashlib.sha256(b"inb_load_4401").hexdigest(),
                202,
                11,
                now - timedelta(minutes=20),
            ),
            (
                f"inb_ord_7721_{t_id[:8]}",
                shopify_conn,
                "shopify",
                "orders",
                "trc_ord_7721_err",
                "ORD-7721",
                json.dumps({"content-type": "application/json", "x-shopify-topic": "orders/paid"}),
                json.dumps(
                    {
                        "order_id": "ORD-7721",
                        "customer": {
                            "email": "procurement@meridian.io",
                            "name": "Meridian Dynamics",
                        },
                        "total_price": 490.00,
                        "currency": "USD",
                        "financial_status": "pending",
                    }
                ),
                310,
                hashlib.sha256(b"inb_ord_7721").hexdigest(),
                202,
                12,
                now - timedelta(minutes=65),
            ),
            (
                f"inb_load_4402_{t_id[:8]}",
                acme_conn,
                "acme_source",
                "shipment_loads",
                "trc_load_4402_err",
                "LOAD-4402",
                json.dumps({"content-type": "application/json"}),
                json.dumps(
                    {
                        "tender_id": "TND-88202",
                        "load_id": "LOAD-4402",
                        "origin_city": "Dallas, TX",
                        "destination_city": "Denver, CO",
                        "carrier": "Swift Logistics",
                    }
                ),
                355,
                hashlib.sha256(b"inb_load_4402").hexdigest(),
                202,
                14,
                now - timedelta(minutes=55),
            ),
        ]

        for (
            inb_id,
            c_id,
            app,
            strm,
            trc,
            corr,
            req_h,
            req_b,
            sz,
            sha,
            st_code,
            dur,
            recv,
        ) in inbound_records:
            await conn.execute(
                """
                INSERT INTO public.inbound_records (
                    id, tenant_id, connection_id, app_id, stream_name, batch_id,
                    batch_seq, causation_depth, ingestion_mode, sync_run_id,
                    generation_id, external_event_id, request_headers, request_body,
                    request_s3_key, request_size_bytes, request_sha256,
                    response_status_code, response_headers, response_body,
                    response_s3_key, duration_ms, received_at, trace_id,
                    correlation_id, parent_trace_id, original_trace_id, replay_count
                )
                VALUES (
                    $1, $2, $3, $4, $5, '', 0, 0, 'WEBHOOK', NULL,
                    1, $6, $7::jsonb, $8::jsonb, NULL, $9, $10,
                    $11, '{"x-trace-id": "accepted"}'::jsonb, '{"accepted": true}'::jsonb,
                    NULL, $12, $13, $14, $6, NULL, $14, 0
                )
                ON CONFLICT (id, received_at) DO UPDATE SET
                    request_body = EXCLUDED.request_body,
                    duration_ms = EXCLUDED.duration_ms;
                """,
                inb_id,
                t_id,
                c_id,
                app,
                strm,
                corr,
                req_h,
                req_b,
                sz,
                sha,
                st_code,
                dur,
                recv,
                trc,
            )
        logger.info("data_plane_inbound_records_seeded", tenant_id=t_id, count=len(inbound_records))


async def _seed_replica_records(conn: asyncpg.Connection, now: datetime) -> None:
    for t_id in TARGET_TENANTS:
        shopify_conn = (
            "conn_shopify_source_01"
            if t_id == ACTIVE_TENANT_ID
            else f"conn_shopify_source_01_{t_id[:8]}"
        )
        oracle_conn = (
            "conn_oracle_mdm_01" if t_id == ACTIVE_TENANT_ID else f"conn_oracle_mdm_01_{t_id[:8]}"
        )
        acme_conn = (
            "conn_acme_source_01" if t_id == ACTIVE_TENANT_ID else f"conn_acme_source_01_{t_id[:8]}"
        )
        replica_records = [
            (
                f"rep_inv_99882_{t_id[:8]}",
                shopify_conn,
                "invoices",
                "INV-99882",
                ["INV-99882"],
                json.dumps(
                    {
                        "invoice_id": "INV-99882",
                        "order_number": "ORD-7719",
                        "customer_id": "CUST-8841",
                        "total_amount": 1450.00,
                        "currency": "USD",
                        "status": "APPROVED",
                    }
                ),
                f"inb_inv_99882_{t_id[:8]}",
                "trc_inv_99882_err",
                "INV-99882",
                now - timedelta(minutes=30),
            ),
            (
                f"rep_inv_99881_{t_id[:8]}",
                shopify_conn,
                "invoices",
                "INV-99881",
                ["INV-99881"],
                json.dumps(
                    {
                        "invoice_id": "INV-99881",
                        "order_number": "ORD-7718",
                        "customer_id": "CUST-1022",
                        "total_amount": 850.00,
                        "currency": "USD",
                        "status": "APPROVED",
                    }
                ),
                f"inb_inv_99881_{t_id[:8]}",
                "trc_inv_99881_ok",
                "INV-99881",
                now - timedelta(minutes=45),
            ),
            (
                f"rep_ord_7719_{t_id[:8]}",
                shopify_conn,
                "orders",
                "ORD-7719",
                ["ORD-7719"],
                json.dumps(
                    {
                        "order_id": "ORD-7719",
                        "customer_name": "Atlas Logistics Corp",
                        "email": "orders@atlaslogistics.com",
                        "total": 3450.00,
                        "currency": "USD",
                        "status": "PAID",
                    }
                ),
                f"inb_ord_7719_{t_id[:8]}",
                "trc_ord_7719_ok",
                "ORD-7719",
                now - timedelta(minutes=35),
            ),
            (
                f"rep_read_1001_{t_id[:8]}",
                oracle_conn,
                "interval_readings",
                "READ-MTR-1001",
                ["READ-MTR-1001"],
                json.dumps(
                    {
                        "reading_id": "READ-MTR-1001",
                        "meter_id": "MTR-GLK-9901",
                        "kwh": 48.75,
                        "interval_end_utc": "2026-11-23T11:15:00Z",
                    }
                ),
                f"inb_read_1001_{t_id[:8]}",
                "trc_read_1001_ok",
                "READ-MTR-1001",
                now - timedelta(minutes=15),
            ),
            (
                f"rep_load_4401_{t_id[:8]}",
                acme_conn,
                "shipment_loads",
                "LOAD-4401",
                ["LOAD-4401"],
                json.dumps(
                    {
                        "load_id": "LOAD-4401",
                        "tender_id": "TND-88201",
                        "origin": "Chicago, IL",
                        "destination": "Atlanta, GA",
                        "carrier": "Schneider Freight",
                    }
                ),
                f"inb_load_4401_{t_id[:8]}",
                "trc_load_4401_ok",
                "LOAD-4401",
                now - timedelta(minutes=20),
            ),
            (
                f"rep_ord_7720_{t_id[:8]}",
                shopify_conn,
                "orders",
                "ORD-7720",
                ["ORD-7720"],
                json.dumps(
                    {
                        "order_id": "ORD-7720",
                        "customer_name": "Summit Global Trade",
                        "email": "billing@summitglobal.org",
                        "total": 1820.50,
                        "currency": "USD",
                        "status": "PAID",
                    }
                ),
                f"inb_ord_7720_{t_id[:8]}",
                "trc_ord_7720_ok",
                "ORD-7720",
                now - timedelta(minutes=50),
            ),
            (
                f"rep_ord_7721_{t_id[:8]}",
                shopify_conn,
                "orders",
                "ORD-7721",
                ["ORD-7721"],
                json.dumps(
                    {
                        "order_id": "ORD-7721",
                        "customer_name": "Meridian Dynamics",
                        "email": "procurement@meridian.io",
                        "total": 490.00,
                        "currency": "USD",
                        "status": "PENDING",
                    }
                ),
                f"inb_ord_7721_{t_id[:8]}",
                "trc_ord_7721_err",
                "ORD-7721",
                now - timedelta(minutes=65),
            ),
            (
                f"rep_load_4402_{t_id[:8]}",
                acme_conn,
                "shipment_loads",
                "LOAD-4402",
                ["LOAD-4402"],
                json.dumps(
                    {
                        "load_id": "LOAD-4402",
                        "tender_id": "TND-88202",
                        "origin": "Dallas, TX",
                        "destination": "Denver, CO",
                        "carrier": "Swift Logistics",
                    }
                ),
                f"inb_load_4402_{t_id[:8]}",
                "trc_load_4402_err",
                "LOAD-4402",
                now - timedelta(minutes=55),
            ),
        ]

        for rep_id, c_id, strm, r_key, pk_vals, data, inb_id, trc, corr, seen in replica_records:
            d_hash = hashlib.sha256(data.encode()).hexdigest()
            await conn.execute(
                """
                INSERT INTO public.replica_records (
                    id, tenant_id, connection_id, stream, record_key,
                    primary_key_values, cursor_value, cursor_kind, data,
                    data_hash, version, generation_id, last_seen_generation,
                    first_seen_at, extracted_at, updated_at, deleted_at,
                    source_inbound_record_id, trace_id, correlation_id,
                    parent_trace_id, original_trace_id, replay_count
                )
                VALUES (
                    $1, $2, $3, $4, $5, $6::jsonb, $5, 'STRING', $7::jsonb,
                    $8, 1, 1, 1, $9, $9, $9, NULL, $10, $11, $12, NULL, $11, 0
                )
                ON CONFLICT (tenant_id, connection_id, stream, record_key) DO UPDATE SET
                    data = EXCLUDED.data,
                    data_hash = EXCLUDED.data_hash,
                    updated_at = EXCLUDED.updated_at;
                """,
                rep_id,
                t_id,
                c_id,
                strm,
                r_key,
                json.dumps(pk_vals),
                data,
                d_hash,
                seen,
                inb_id,
                trc,
                corr,
            )
        logger.info("data_plane_replica_records_seeded", tenant_id=t_id, count=len(replica_records))


async def _seed_normalized_records(conn: asyncpg.Connection, now: datetime) -> None:
    for t_id in TARGET_TENANTS:
        shopify_conn = (
            "conn_shopify_source_01"
            if t_id == ACTIVE_TENANT_ID
            else f"conn_shopify_source_01_{t_id[:8]}"
        )
        oracle_conn = (
            "conn_oracle_mdm_01" if t_id == ACTIVE_TENANT_ID else f"conn_oracle_mdm_01_{t_id[:8]}"
        )
        acme_conn = (
            "conn_acme_source_01" if t_id == ACTIVE_TENANT_ID else f"conn_acme_source_01_{t_id[:8]}"
        )
        normalized_records = [
            # Invoices (Shopify)
            (
                f"nrm_inv_99882_{t_id[:8]}",
                shopify_conn,
                "canonical.invoice.v1",
                "INV-99882",
                json.dumps(
                    {
                        "invoiceNumber": "INV-99882",
                        "orderNumber": "ORD-7719",
                        "currency": "USD",
                        "subtotal": 1450.00,
                        "tax": 0.00,
                        "total": 1450.00,
                        "customerRef": "CUST-8841",
                        "customerName": "Acme Industrial Technologies",
                        "customerEmail": "billing@acmeindustrial.com",
                        "issueDate": (now - timedelta(days=3)).strftime("%Y-%m-%d"),
                        "dueDate": (now + timedelta(days=27)).strftime("%Y-%m-%d"),
                        "paymentTerms": "Net 30",
                        "status": "APPROVED",
                        "itemCount": 2,
                        "items": [
                            {
                                "sku": "HW-SENS-01",
                                "description": "Industrial Smart Telemetry Sensor Module",
                                "quantity": 2,
                                "unitPrice": 600.00,
                                "total": 1200.00,
                            },
                            {
                                "sku": "SRV-CALIB",
                                "description": "Precision Factory Calibration & Certification",
                                "quantity": 1,
                                "unitPrice": 250.00,
                                "total": 250.00,
                            },
                        ],
                    }
                ),
                "trc_inv_99882_err",
                "INV-99882",
                now - timedelta(minutes=29),
            ),
            (
                f"nrm_inv_99881_{t_id[:8]}",
                shopify_conn,
                "canonical.invoice.v1",
                "INV-99881",
                json.dumps(
                    {
                        "invoiceNumber": "INV-99881",
                        "orderNumber": "ORD-7718",
                        "currency": "USD",
                        "subtotal": 850.00,
                        "tax": 0.00,
                        "total": 850.00,
                        "customerRef": "CUST-1022",
                        "customerName": "Global Energy Grid Ltd",
                        "customerEmail": "invoices@globalenergygrid.com",
                        "issueDate": (now - timedelta(days=4)).strftime("%Y-%m-%d"),
                        "dueDate": (now + timedelta(days=26)).strftime("%Y-%m-%d"),
                        "paymentTerms": "Net 30",
                        "status": "APPROVED",
                        "itemCount": 1,
                        "items": [
                            {
                                "sku": "SUB-SAAS-ENT",
                                "description": "Enterprise Telemetry Stream Processing (Monthly)",
                                "quantity": 1,
                                "unitPrice": 850.00,
                                "total": 850.00,
                            },
                        ],
                    }
                ),
                "trc_inv_99881_ok",
                "INV-99881",
                now - timedelta(minutes=44),
            ),
            # Orders (Shopify)
            (
                f"nrm_ord_7719_{t_id[:8]}",
                shopify_conn,
                "canonical.order.v1",
                "ORD-7719",
                json.dumps(
                    {
                        "orderNumber": "ORD-7719",
                        "customerRef": "CUST-8841",
                        "customer": "Atlas Logistics Corp",
                        "email": "orders@atlaslogistics.com",
                        "total": 3450.00,
                        "currency": "USD",
                        "financial_status": "PAID",
                        "fulfillment_status": "UNFULFILLED",
                        "line_items_count": 3,
                    }
                ),
                "trc_ord_7719_ok",
                "ORD-7719",
                now - timedelta(minutes=35),
            ),
            (
                f"nrm_ord_7720_{t_id[:8]}",
                shopify_conn,
                "canonical.order.v1",
                "ORD-7720",
                json.dumps(
                    {
                        "orderNumber": "ORD-7720",
                        "customerRef": "CUST-1022",
                        "customer": "Summit Global Trade",
                        "email": "billing@summitglobal.org",
                        "total": 1820.50,
                        "currency": "USD",
                        "financial_status": "PAID",
                        "fulfillment_status": "FULFILLED",
                        "line_items_count": 2,
                    }
                ),
                "trc_ord_7720_ok",
                "ORD-7720",
                now - timedelta(minutes=50),
            ),
            (
                f"nrm_ord_7721_{t_id[:8]}",
                shopify_conn,
                "canonical.order.v1",
                "ORD-7721",
                json.dumps(
                    {
                        "orderNumber": "ORD-7721",
                        "customerRef": "CUST-9904",
                        "customer": "Meridian Dynamics",
                        "email": "procurement@meridian.io",
                        "total": 490.00,
                        "currency": "USD",
                        "financial_status": "PENDING",
                        "fulfillment_status": "UNFULFILLED",
                        "line_items_count": 1,
                    }
                ),
                "trc_ord_7721_err",
                "ORD-7721",
                now - timedelta(minutes=65),
            ),
            # Interval Readings (Oracle MDM)
            (
                f"nrm_read_1001_{t_id[:8]}",
                oracle_conn,
                "canonical.energy.interval_reading.v1",
                "READ-MTR-1001",
                json.dumps(
                    {
                        "meter_id": "MTR-GLK-9901",
                        "reading_value": 48.75,
                        "uom": "kWh",
                        "interval_start": "2026-11-23T11:00:00Z",
                        "interval_end": "2026-11-23T11:15:00Z",
                        "quality": "ACTUAL",
                        "settlement_status": "SETTLED",
                    }
                ),
                "trc_read_1001_ok",
                "READ-MTR-1001",
                now - timedelta(minutes=15),
            ),
            (
                f"nrm_read_1002_{t_id[:8]}",
                oracle_conn,
                "canonical.energy.interval_reading.v1",
                "READ-MTR-1002",
                json.dumps(
                    {
                        "meter_id": "MTR-GLK-9902",
                        "reading_value": 62.10,
                        "uom": "kWh",
                        "interval_start": "2026-11-23T11:00:00Z",
                        "interval_end": "2026-11-23T11:15:00Z",
                        "quality": "ACTUAL",
                        "settlement_status": "SETTLED",
                    }
                ),
                "trc_read_1002_ok",
                "READ-MTR-1002",
                now - timedelta(minutes=15),
            ),
            # Shipment Loads (Acme TMS)
            (
                f"nrm_load_4401_{t_id[:8]}",
                acme_conn,
                "canonical.tms.shipment_load.v1",
                "LOAD-4401",
                json.dumps(
                    {
                        "tender_id": "TND-88201",
                        "load_id": "LOAD-4401",
                        "origin_city": "Chicago, IL",
                        "destination_city": "Atlanta, GA",
                        "carrier": "Schneider Freight",
                        "equipment_type": "53FT_DRY_VAN",
                        "weight_lbs": 38400,
                        "status": "DISPATCHED",
                    }
                ),
                "trc_load_4401_ok",
                "LOAD-4401",
                now - timedelta(minutes=20),
            ),
            (
                f"nrm_load_4402_{t_id[:8]}",
                acme_conn,
                "canonical.tms.shipment_load.v1",
                "LOAD-4402",
                json.dumps(
                    {
                        "tender_id": "TND-88202",
                        "load_id": "LOAD-4402",
                        "origin_city": "Dallas, TX",
                        "destination_city": "Denver, CO",
                        "carrier": "Swift Logistics",
                        "equipment_type": "REEFER",
                        "weight_lbs": 42100,
                        "status": "DELIVERED",
                    }
                ),
                "trc_load_4402_err",
                "LOAD-4402",
                now - timedelta(minutes=55),
            ),
        ]

        for nrm_id, c_id, can_type, src_id, c_data, trc, corr, norm_at in normalized_records:
            await conn.execute(
                """
                INSERT INTO public.normalized_records (
                    id, tenant_id, connection_id, canonical_type, source_id,
                    canonical_data, normalized_at, trace_id, correlation_id,
                    parent_trace_id, original_trace_id, replay_count
                )
                VALUES ($1, $2, $3, $4, $5, $6::jsonb, $7, $8, $9, NULL, $8, 0)
                ON CONFLICT (id) DO UPDATE SET
                    canonical_data = EXCLUDED.canonical_data,
                    normalized_at = EXCLUDED.normalized_at;
                """,
                nrm_id,
                t_id,
                c_id,
                can_type,
                src_id,
                c_data,
                norm_at,
                trc,
                corr,
            )
        logger.info(
            "data_plane_normalized_records_seeded", tenant_id=t_id, count=len(normalized_records)
        )


async def _seed_gem_records(conn: asyncpg.Connection, now: datetime) -> None:
    for t_id in TARGET_TENANTS:
        shopify_conn = (
            "conn_shopify_source_01"
            if t_id == ACTIVE_TENANT_ID
            else f"conn_shopify_source_01_{t_id[:8]}"
        )
        sap_conn = (
            "conn_sap_dest_01" if t_id == ACTIVE_TENANT_ID else f"conn_sap_dest_01_{t_id[:8]}"
        )
        acme_conn = (
            "conn_acme_source_01" if t_id == ACTIVE_TENANT_ID else f"conn_acme_source_01_{t_id[:8]}"
        )
        gem_records = [
            (
                f"gem_inv_99882_{t_id[:8]}",
                "domain.invoice",
                "gem_doc_inv_99882",
                shopify_conn,
                "INV-99882",
                sap_conn,
                "SAP-BAPI-DOC-99882",
                "trc_inv_99882_err",
                "INV-99882",
            ),
            (
                f"gem_inv_99881_{t_id[:8]}",
                "domain.invoice",
                "gem_doc_inv_99881",
                shopify_conn,
                "INV-99881",
                sap_conn,
                "SAP-BAPI-DOC-99881",
                "trc_inv_99881_ok",
                "INV-99881",
            ),
            (
                f"gem_dev_9001_{t_id[:8]}",
                "domain.device",
                "gem_dev_9001",
                "conn_oracle_mdm_01"
                if t_id == ACTIVE_TENANT_ID
                else f"conn_oracle_mdm_01_{t_id[:8]}",
                "DEV-ALPHA-9001",
                sap_conn,
                "SAP-EQUIP-9001",
                "trc_inv_99882_err",
                "DEV-ALPHA-9001",
            ),
            (
                f"gem_ord_7719_{t_id[:8]}",
                "domain.order",
                "gem_doc_ord_7719",
                shopify_conn,
                "ORD-7719",
                sap_conn,
                "SAP-SO-771901",
                "trc_ord_7719_ok",
                "ORD-7719",
            ),
            (
                f"gem_ord_7720_{t_id[:8]}",
                "domain.order",
                "gem_doc_ord_7720",
                shopify_conn,
                "ORD-7720",
                sap_conn,
                "SAP-SO-772002",
                "trc_ord_7720_ok",
                "ORD-7720",
            ),
            (
                f"gem_ord_7721_{t_id[:8]}",
                "domain.order",
                "gem_doc_ord_7721",
                shopify_conn,
                "ORD-7721",
                sap_conn,
                "SAP-SO-772103",
                "trc_ord_7721_err",
                "ORD-7721",
            ),
            (
                f"gem_load_4401_{t_id[:8]}",
                "domain.logistics",
                "gem_doc_load_4401",
                acme_conn,
                "LOAD-4401",
                sap_conn,
                "SAP-TM-TOR-4401",
                "trc_load_4401_ok",
                "LOAD-4401",
            ),
            (
                f"gem_load_4402_{t_id[:8]}",
                "domain.logistics",
                "gem_doc_load_4402",
                acme_conn,
                "LOAD-4402",
                sap_conn,
                "SAP-TM-TOR-4402",
                "trc_load_4402_err",
                "LOAD-4402",
            ),
        ]

        for gem_id, domain, can_id, src_conn, src_ent, dst_conn, dst_ent, trc, corr in gem_records:
            await conn.execute(
                """
                INSERT INTO public.global_entity_map (
                    id, tenant_id, entity_domain, canonical_id, source_connection_id,
                    source_entity_id, dest_connection_id, dest_entity_id, created_at,
                    trace_id, correlation_id, parent_trace_id, original_trace_id, replay_count
                )
                VALUES (
                    $1, $2, $3, $4, $5, $6, $7, $8, $9,
                    $10, $11, NULL, $10, 0
                )
                ON CONFLICT (tenant_id, entity_domain, source_connection_id, source_entity_id)
                DO UPDATE SET
                    canonical_id = EXCLUDED.canonical_id,
                    dest_connection_id = EXCLUDED.dest_connection_id,
                    dest_entity_id = EXCLUDED.dest_entity_id;
                """,
                gem_id,
                t_id,
                domain,
                can_id,
                src_conn,
                src_ent,
                dst_conn,
                dst_ent,
                now - timedelta(minutes=28),
                trc,
                corr,
            )
        logger.info("data_plane_gem_records_seeded", tenant_id=t_id, count=len(gem_records))


async def _seed_outbound_records(conn: asyncpg.Connection, now: datetime) -> None:
    for t_id in TARGET_TENANTS:
        sap_conn = (
            "conn_sap_dest_01" if t_id == ACTIVE_TENANT_ID else f"conn_sap_dest_01_{t_id[:8]}"
        )
        outbound_records = [
            (
                f"out_inv_99882_err_{t_id[:8]}",
                sap_conn,
                "sap_s4hana",
                "canonical_invoices",
                "CREATE",
                "idem_sap_inv_99882",
                "https://sap-gateway.corp.example.com/sap/bc/bapi/invoice/post",
                "POST",
                json.dumps(
                    {
                        "content-type": "application/json",
                        "x-trace-id": "trc_inv_99882_err",
                        "authorization": "[REDACTED]",
                    }
                ),
                json.dumps(
                    {
                        "sapDocumentHeader": {
                            "docType": "KR",
                            "companyCode": "1000",
                            "refDoc": "INV-99882",
                            "currency": "USD",
                        },
                        "grossAmount": 1450.00,
                        "customer": "CUST-8841",
                        "lineItems": [
                            {
                                "item": 1,
                                "sku": "SKU-TURBO-01",
                                "qty": 2,
                                "rate": 725.00,
                            }
                        ],
                    }
                ),
                256,
                hashlib.sha256(b"out_req_99882").hexdigest(),
                503,
                json.dumps(
                    {
                        "server": "SAP NetWeaver Application Server 7.53",
                        "retry-after": "30",
                        "content-type": "application/json",
                    }
                ),
                json.dumps(
                    {
                        "fault": {
                            "code": "BAPI_GW_503",
                            "message": "Service Unavailable: SAP gateway under maintenance window",
                            "retryAfterSeconds": 30,
                        }
                    }
                ),
                1420,
                1,
                "FAILED",
                "TRANSIENT",
                30,
                "503 Service Unavailable: SAP gateway under maintenance window",
                now - timedelta(minutes=27),
                "trc_inv_99882_err",
                "INV-99882",
                None,
                "trc_inv_99882_err",
                0,
            ),
            (
                f"out_inv_99882_rep_{t_id[:8]}",
                sap_conn,
                "sap_s4hana",
                "canonical_invoices",
                "CREATE",
                "idem_sap_inv_99882_rep",
                "https://sap-gateway.corp.example.com/sap/bc/bapi/invoice/post",
                "POST",
                json.dumps(
                    {"content-type": "application/json", "x-trace-id": "trc_inv_99882_replay"}
                ),
                json.dumps(
                    {
                        "sapDocumentHeader": {
                            "docType": "KR",
                            "companyCode": "1000",
                            "refDoc": "INV-99882",
                        },
                        "grossAmount": 1450.00,
                    }
                ),
                256,
                hashlib.sha256(b"out_req_99882_rep").hexdigest(),
                200,
                json.dumps({"content-type": "application/json"}),
                json.dumps(
                    {
                        "sapDocumentNumber": "SAP-DOC-44810-KR",
                        "status": "POSTED",
                        "postingDate": "2026-11-23",
                    }
                ),
                185,
                1,
                "DELIVERED",
                None,
                None,
                None,
                now - timedelta(minutes=22),
                "trc_inv_99882_replay",
                "INV-99882",
                "trc_inv_99882_err",
                "trc_inv_99882_err",
                1,
            ),
            (
                f"out_inv_99881_ok_{t_id[:8]}",
                sap_conn,
                "sap_s4hana",
                "canonical_invoices",
                "CREATE",
                "idem_sap_inv_99881",
                "https://sap-gateway.corp.example.com/sap/bc/bapi/invoice/post",
                "POST",
                json.dumps({"content-type": "application/json"}),
                json.dumps({"grossAmount": 850.00, "refDoc": "INV-99881"}),
                198,
                hashlib.sha256(b"out_req_99881").hexdigest(),
                200,
                json.dumps({"content-type": "application/json"}),
                json.dumps({"sapDocumentNumber": "SAP-DOC-44809-KR", "status": "POSTED"}),
                145,
                1,
                "DELIVERED",
                None,
                None,
                None,
                now - timedelta(minutes=42),
                "trc_inv_99881_ok",
                "INV-99881",
                None,
                "trc_inv_99881_ok",
                0,
            ),
            (
                f"out_ord_7719_ok_{t_id[:8]}",
                sap_conn,
                "sap_s4hana",
                "orders",
                "CREATE",
                "idem_sap_ord_7719",
                "https://sap-gateway.corp.example.com/sap/bc/bapi/salesorder/create",
                "POST",
                json.dumps({"content-type": "application/json"}),
                json.dumps({"orderNumber": "ORD-7719", "total": 3450.00}),
                210,
                hashlib.sha256(b"out_req_ord_7719").hexdigest(),
                200,
                json.dumps({"content-type": "application/json"}),
                json.dumps({"salesOrderNumber": "SAP-SO-771901", "status": "CONFIRMED"}),
                160,
                1,
                "DELIVERED",
                None,
                None,
                None,
                now - timedelta(minutes=34),
                "trc_ord_7719_ok",
                "ORD-7719",
                None,
                "trc_ord_7719_ok",
                0,
            ),
            (
                f"out_ord_7720_ok_{t_id[:8]}",
                sap_conn,
                "sap_s4hana",
                "orders",
                "CREATE",
                "idem_sap_ord_7720",
                "https://sap-gateway.corp.example.com/sap/bc/bapi/salesorder/create",
                "POST",
                json.dumps({"content-type": "application/json"}),
                json.dumps({"orderNumber": "ORD-7720", "total": 1820.50}),
                195,
                hashlib.sha256(b"out_req_ord_7720").hexdigest(),
                200,
                json.dumps({"content-type": "application/json"}),
                json.dumps({"salesOrderNumber": "SAP-SO-772002", "status": "CONFIRMED"}),
                150,
                1,
                "DELIVERED",
                None,
                None,
                None,
                now - timedelta(minutes=49),
                "trc_ord_7720_ok",
                "ORD-7720",
                None,
                "trc_ord_7720_ok",
                0,
            ),
            (
                f"out_read_1001_ok_{t_id[:8]}",
                sap_conn,
                "sap_s4hana",
                "interval_readings",
                "SETTLE",
                "idem_sap_read_1001",
                "https://sap-gateway.corp.example.com/sap/bc/bapi/energy/settle",
                "POST",
                json.dumps({"content-type": "application/json"}),
                json.dumps({"meterId": "MTR-GLK-9901", "kwh": 48.75}),
                180,
                hashlib.sha256(b"out_req_read_1001").hexdigest(),
                200,
                json.dumps({"content-type": "application/json"}),
                json.dumps({"settlementBatchId": "SETTLE-POOL-1001", "status": "SETTLED"}),
                120,
                1,
                "DELIVERED",
                None,
                None,
                None,
                now - timedelta(minutes=14),
                "trc_read_1001_ok",
                "READ-MTR-1001",
                None,
                "trc_read_1001_ok",
                0,
            ),
            (
                f"out_load_4401_ok_{t_id[:8]}",
                sap_conn,
                "sap_s4hana",
                "shipment_loads",
                "TENDER",
                "idem_sap_load_4401",
                "https://sap-gateway.corp.example.com/sap/bc/bapi/tms/tender",
                "POST",
                json.dumps({"content-type": "application/json"}),
                json.dumps({"loadId": "LOAD-4401", "carrier": "Schneider Freight"}),
                225,
                hashlib.sha256(b"out_req_load_4401").hexdigest(),
                200,
                json.dumps({"content-type": "application/json"}),
                json.dumps({"tenderConfirmation": "TND-CONF-4401", "status": "ACCEPTED"}),
                175,
                1,
                "DELIVERED",
                None,
                None,
                None,
                now - timedelta(minutes=19),
                "trc_load_4401_ok",
                "LOAD-4401",
                None,
                "trc_load_4401_ok",
                0,
            ),
            (
                f"out_ord_7721_err_{t_id[:8]}",
                sap_conn,
                "sap_s4hana",
                "orders",
                "CREATE",
                "idem_sap_ord_7721",
                "https://sap-gateway.corp.example.com/sap/bc/bapi/salesorder/create",
                "POST",
                json.dumps({"content-type": "application/json", "x-trace-id": "trc_ord_7721_err"}),
                json.dumps(
                    {"orderNumber": "ORD-7721", "total": 490.00, "customer": "Meridian Dynamics"}
                ),
                215,
                hashlib.sha256(b"out_req_ord_7721").hexdigest(),
                504,
                json.dumps(
                    {
                        "server": "SAP NetWeaver Application Server",
                        "content-type": "application/json",
                    }
                ),
                json.dumps(
                    {
                        "fault": {
                            "code": "BAPI_GATEWAY_TIMEOUT",
                            "message": "504 Gateway Timeout: SAP Sales Order service did not respond within 30000ms",
                        }
                    }
                ),
                30020,
                1,
                "FAILED",
                "TIMEOUT",
                60,
                "504 Gateway Timeout: SAP Sales Order service did not respond within 30000ms",
                now - timedelta(minutes=64),
                "trc_ord_7721_err",
                "ORD-7721",
                None,
                "trc_ord_7721_err",
                0,
            ),
            (
                f"out_load_4402_err_{t_id[:8]}",
                sap_conn,
                "sap_s4hana",
                "shipment_loads",
                "TENDER",
                "idem_sap_load_4402",
                "https://sap-gateway.corp.example.com/sap/bc/bapi/tms/tender",
                "POST",
                json.dumps({"content-type": "application/json", "x-trace-id": "trc_load_4402_err"}),
                json.dumps({"loadId": "LOAD-4402", "carrier": "Swift Logistics"}),
                230,
                hashlib.sha256(b"out_req_load_4402").hexdigest(),
                500,
                json.dumps({"content-type": "application/json"}),
                json.dumps(
                    {
                        "fault": {
                            "code": "SAP_TM_ERR_500",
                            "message": "500 Internal Server Error: SAP TM Carrier validation failed for Swift Logistics",
                        }
                    }
                ),
                210,
                1,
                "FAILED",
                "FATAL",
                None,
                "500 Internal Server Error: SAP TM Carrier validation failed for Swift Logistics",
                now - timedelta(minutes=54),
                "trc_load_4402_err",
                "LOAD-4402",
                None,
                "trc_load_4402_err",
                0,
            ),
        ]

        for (
            out_id,
            c_id,
            app,
            strm,
            op,
            idem,
            target,
            method,
            req_h,
            req_b,
            sz,
            sha,
            st_code,
            resp_h,
            resp_b,
            dur,
            att,
            st,
            fail_cat,
            retry_sec,
            err_msg,
            sent,
            trc,
            corr,
            p_trc,
            o_trc,
            rep_cnt,
        ) in outbound_records:
            await conn.execute(
                """
                INSERT INTO public.outbound_records (
                    id, tenant_id, connection_id, app_id, stream_name, operation,
                    idempotency_key, external_record_id, target_url, http_method,
                    request_headers, request_body, request_s3_key, request_size_bytes,
                    request_sha256, response_status_code, response_headers, response_body,
                    response_s3_key, duration_ms, attempt_number, conflict_strategy,
                    status, failure_category, retry_after_seconds, error_message,
                    causation_depth, sent_at, trace_id, correlation_id,
                    parent_trace_id, original_trace_id, replay_count
                )
                VALUES (
                    $1, $2, $3, $4, $5, $6, $7, NULL, $8, $9,
                    $10::jsonb, $11::jsonb, NULL, $12, $13, $14,
                    $15::jsonb, $16::jsonb, NULL, $17, $18, 'FAIL',
                    $19, $20, $21, $22, 0, $23, $24, $25,
                    $26, $27, $28
                )
                ON CONFLICT (id, sent_at) DO UPDATE SET
                    status = EXCLUDED.status,
                    response_status_code = EXCLUDED.response_status_code,
                    failure_category = EXCLUDED.failure_category,
                    retry_after_seconds = EXCLUDED.retry_after_seconds,
                    error_message = EXCLUDED.error_message;
                """,
                out_id,
                t_id,
                c_id,
                app,
                strm,
                op,
                idem,
                target,
                method,
                req_h,
                req_b,
                sz,
                sha,
                st_code,
                resp_h,
                resp_b,
                dur,
                att,
                st,
                fail_cat,
                retry_sec,
                err_msg,
                sent,
                trc,
                corr,
                p_trc,
                o_trc,
                rep_cnt,
            )
        logger.info(
            "data_plane_outbound_records_seeded", tenant_id=t_id, count=len(outbound_records)
        )


async def _seed_trace_events(conn: asyncpg.Connection, now: datetime) -> None:
    for t_id in TARGET_TENANTS:
        trace_events = [
            (
                f"tev_01_{t_id[:8]}",
                "trc_inv_99882_err",
                "INV-99882",
                "RECEIVED",
                "IP_INGRESS_GATEWAY",
                {"mode": "WEBHOOK"},
                now - timedelta(minutes=30),
            ),
            (
                f"tev_02_{t_id[:8]}",
                "trc_inv_99882_err",
                "INV-99882",
                "REPLICATED",
                "IP_REPLICA_WORKER",
                {"version": 1},
                now - timedelta(minutes=29, seconds=55),
            ),
            (
                f"tev_03_{t_id[:8]}",
                "trc_inv_99882_err",
                "INV-99882",
                "NORMALIZED",
                "IP_NORMALIZATION_WORKER",
                {"canonical_type": "canonical.invoice.v1"},
                now - timedelta(minutes=29),
            ),
            (
                f"tev_04_{t_id[:8]}",
                "trc_inv_99882_err",
                "INV-99882",
                "GEM_MAPPED",
                "IP_GEM_RESOLVER",
                {"canonical_id": "gem_doc_inv_99882"},
                now - timedelta(minutes=28),
            ),
            (
                f"tev_05_{t_id[:8]}",
                "trc_inv_99882_err",
                "INV-99882",
                "DELIVERY_ATTEMPTED",
                "IP_OUTBOUND_DISPATCHER",
                {"target": "SAP"},
                now - timedelta(minutes=27, seconds=2),
            ),
            (
                f"tev_06_{t_id[:8]}",
                "trc_inv_99882_err",
                "INV-99882",
                "DELIVERY_FAILED",
                "IP_OUTBOUND_DISPATCHER",
                {"status_code": 503, "failure_category": "TRANSIENT", "retry_after": 30},
                now - timedelta(minutes=27),
            ),
            (
                f"tev_07_{t_id[:8]}",
                "trc_inv_99882_replay",
                "INV-99882",
                "REPLAY_REQUESTED",
                "SUPPORT_OPERATOR",
                {"reason": "Transient 503 maintenance retry", "parent_trace": "trc_inv_99882_err"},
                now - timedelta(minutes=23),
            ),
            (
                f"tev_08_{t_id[:8]}",
                "trc_inv_99882_replay",
                "INV-99882",
                "DELIVERY_ATTEMPTED",
                "IP_OUTBOUND_DISPATCHER",
                {"target": "SAP", "attempt": 1},
                now - timedelta(minutes=22, seconds=5),
            ),
            (
                f"tev_09_{t_id[:8]}",
                "trc_inv_99882_replay",
                "INV-99882",
                "DELIVERED",
                "IP_OUTBOUND_DISPATCHER",
                {"status_code": 200, "sap_doc": "SAP-DOC-44810-KR"},
                now - timedelta(minutes=22),
            ),
            (
                f"tev_10_{t_id[:8]}",
                "trc_inv_99881_ok",
                "INV-99881",
                "RECEIVED",
                "IP_INGRESS_GATEWAY",
                {"mode": "WEBHOOK"},
                now - timedelta(minutes=45),
            ),
            (
                f"tev_10b_{t_id[:8]}",
                "trc_inv_99881_ok",
                "INV-99881",
                "REPLICATED",
                "IP_REPLICA_WORKER",
                {"version": 1},
                now - timedelta(minutes=44, seconds=50),
            ),
            (
                f"tev_10c_{t_id[:8]}",
                "trc_inv_99881_ok",
                "INV-99881",
                "NORMALIZED",
                "IP_NORMALIZATION_WORKER",
                {"canonical_type": "canonical.invoice.v1"},
                now - timedelta(minutes=44),
            ),
            (
                f"tev_10d_{t_id[:8]}",
                "trc_inv_99881_ok",
                "INV-99881",
                "GEM_MAPPED",
                "IP_GEM_RESOLVER",
                {"canonical_id": "gem_doc_inv_99881"},
                now - timedelta(minutes=43),
            ),
            (
                f"tev_10e_{t_id[:8]}",
                "trc_inv_99881_ok",
                "INV-99881",
                "DELIVERY_ATTEMPTED",
                "IP_OUTBOUND_DISPATCHER",
                {"target": "SAP"},
                now - timedelta(minutes=42, seconds=30),
            ),
            (
                f"tev_11_{t_id[:8]}",
                "trc_inv_99881_ok",
                "INV-99881",
                "DELIVERED",
                "IP_OUTBOUND_DISPATCHER",
                {"status_code": 200, "sap_doc": "SAP-DOC-44809-KR"},
                now - timedelta(minutes=42),
            ),
            (
                f"tev_12_{t_id[:8]}",
                "trc_ord_7719_ok",
                "ORD-7719",
                "RECEIVED",
                "IP_INGRESS_GATEWAY",
                {"mode": "WEBHOOK"},
                now - timedelta(minutes=35),
            ),
            (
                f"tev_12b_{t_id[:8]}",
                "trc_ord_7719_ok",
                "ORD-7719",
                "REPLICATED",
                "IP_REPLICA_WORKER",
                {"version": 1},
                now - timedelta(minutes=34, seconds=50),
            ),
            (
                f"tev_12c_{t_id[:8]}",
                "trc_ord_7719_ok",
                "ORD-7719",
                "NORMALIZED",
                "IP_NORMALIZATION_WORKER",
                {"canonical_type": "canonical.order.v1"},
                now - timedelta(minutes=34, seconds=30),
            ),
            (
                f"tev_12d_{t_id[:8]}",
                "trc_ord_7719_ok",
                "ORD-7719",
                "GEM_MAPPED",
                "IP_GEM_RESOLVER",
                {"canonical_id": "gem_doc_ord_7719"},
                now - timedelta(minutes=34, seconds=10),
            ),
            (
                f"tev_13_{t_id[:8]}",
                "trc_ord_7719_ok",
                "ORD-7719",
                "DELIVERED",
                "IP_OUTBOUND_DISPATCHER",
                {"status_code": 200, "sap_so": "SAP-SO-771901"},
                now - timedelta(minutes=34),
            ),
            (
                f"tev_13a_{t_id[:8]}",
                "trc_ord_7720_ok",
                "ORD-7720",
                "RECEIVED",
                "IP_INGRESS_GATEWAY",
                {"mode": "WEBHOOK"},
                now - timedelta(minutes=50),
            ),
            (
                f"tev_13b_{t_id[:8]}",
                "trc_ord_7720_ok",
                "ORD-7720",
                "REPLICATED",
                "IP_REPLICA_WORKER",
                {"version": 1},
                now - timedelta(minutes=49, seconds=50),
            ),
            (
                f"tev_13c_{t_id[:8]}",
                "trc_ord_7720_ok",
                "ORD-7720",
                "NORMALIZED",
                "IP_NORMALIZATION_WORKER",
                {"canonical_type": "canonical.order.v1"},
                now - timedelta(minutes=49, seconds=30),
            ),
            (
                f"tev_13d_{t_id[:8]}",
                "trc_ord_7720_ok",
                "ORD-7720",
                "GEM_MAPPED",
                "IP_GEM_RESOLVER",
                {"canonical_id": "gem_doc_ord_7720"},
                now - timedelta(minutes=49, seconds=10),
            ),
            (
                f"tev_13e_{t_id[:8]}",
                "trc_ord_7720_ok",
                "ORD-7720",
                "DELIVERED",
                "IP_OUTBOUND_DISPATCHER",
                {"status_code": 200, "sap_so": "SAP-SO-772002"},
                now - timedelta(minutes=49),
            ),
            (
                f"tev_13f_{t_id[:8]}",
                "trc_ord_7721_err",
                "ORD-7721",
                "RECEIVED",
                "IP_INGRESS_GATEWAY",
                {"mode": "WEBHOOK"},
                now - timedelta(minutes=65),
            ),
            (
                f"tev_13g_{t_id[:8]}",
                "trc_ord_7721_err",
                "ORD-7721",
                "REPLICATED",
                "IP_REPLICA_WORKER",
                {"version": 1},
                now - timedelta(minutes=64, seconds=50),
            ),
            (
                f"tev_13h_{t_id[:8]}",
                "trc_ord_7721_err",
                "ORD-7721",
                "NORMALIZED",
                "IP_NORMALIZATION_WORKER",
                {"canonical_type": "canonical.order.v1"},
                now - timedelta(minutes=64, seconds=30),
            ),
            (
                f"tev_13i_{t_id[:8]}",
                "trc_ord_7721_err",
                "ORD-7721",
                "GEM_MAPPED",
                "IP_GEM_RESOLVER",
                {"canonical_id": "gem_doc_ord_7721"},
                now - timedelta(minutes=64, seconds=10),
            ),
            (
                f"tev_13j_{t_id[:8]}",
                "trc_ord_7721_err",
                "ORD-7721",
                "DELIVERY_ATTEMPTED",
                "IP_OUTBOUND_DISPATCHER",
                {"target": "SAP"},
                now - timedelta(minutes=64),
            ),
            (
                f"tev_13k_{t_id[:8]}",
                "trc_ord_7721_err",
                "ORD-7721",
                "DELIVERY_FAILED",
                "IP_OUTBOUND_DISPATCHER",
                {
                    "status_code": 504,
                    "failure_category": "TIMEOUT",
                    "error": "504 Gateway Timeout: SAP Sales Order service did not respond within 30000ms",
                },
                now - timedelta(minutes=63, seconds=30),
            ),
            (
                f"tev_14_{t_id[:8]}",
                "trc_read_1001_ok",
                "READ-MTR-1001",
                "RECEIVED",
                "IP_INGRESS_GATEWAY",
                {"mode": "POLL"},
                now - timedelta(minutes=15),
            ),
            (
                f"tev_15_{t_id[:8]}",
                "trc_read_1001_ok",
                "READ-MTR-1001",
                "DELIVERED",
                "IP_OUTBOUND_DISPATCHER",
                {"status_code": 200, "pool_id": "SETTLE-POOL-1001"},
                now - timedelta(minutes=14),
            ),
            (
                f"tev_16_{t_id[:8]}",
                "trc_load_4401_ok",
                "LOAD-4401",
                "RECEIVED",
                "IP_INGRESS_GATEWAY",
                {"mode": "API"},
                now - timedelta(minutes=20),
            ),
            (
                f"tev_16b_{t_id[:8]}",
                "trc_load_4401_ok",
                "LOAD-4401",
                "REPLICATED",
                "IP_REPLICA_WORKER",
                {"version": 1},
                now - timedelta(minutes=19, seconds=50),
            ),
            (
                f"tev_16c_{t_id[:8]}",
                "trc_load_4401_ok",
                "LOAD-4401",
                "NORMALIZED",
                "IP_NORMALIZATION_WORKER",
                {"canonical_type": "canonical.tms.shipment_load.v1"},
                now - timedelta(minutes=19, seconds=30),
            ),
            (
                f"tev_16d_{t_id[:8]}",
                "trc_load_4401_ok",
                "LOAD-4401",
                "GEM_MAPPED",
                "IP_GEM_RESOLVER",
                {"canonical_id": "gem_doc_load_4401"},
                now - timedelta(minutes=19, seconds=10),
            ),
            (
                f"tev_17_{t_id[:8]}",
                "trc_load_4401_ok",
                "LOAD-4401",
                "DELIVERED",
                "IP_OUTBOUND_DISPATCHER",
                {"status_code": 200, "tender_conf": "TND-CONF-4401"},
                now - timedelta(minutes=19),
            ),
            (
                f"tev_17a_{t_id[:8]}",
                "trc_load_4402_err",
                "LOAD-4402",
                "RECEIVED",
                "IP_INGRESS_GATEWAY",
                {"mode": "API"},
                now - timedelta(minutes=55),
            ),
            (
                f"tev_17b_{t_id[:8]}",
                "trc_load_4402_err",
                "LOAD-4402",
                "REPLICATED",
                "IP_REPLICA_WORKER",
                {"version": 1},
                now - timedelta(minutes=54, seconds=50),
            ),
            (
                f"tev_17c_{t_id[:8]}",
                "trc_load_4402_err",
                "LOAD-4402",
                "NORMALIZED",
                "IP_NORMALIZATION_WORKER",
                {"canonical_type": "canonical.tms.shipment_load.v1"},
                now - timedelta(minutes=54, seconds=30),
            ),
            (
                f"tev_17d_{t_id[:8]}",
                "trc_load_4402_err",
                "LOAD-4402",
                "GEM_MAPPED",
                "IP_GEM_RESOLVER",
                {"canonical_id": "gem_doc_load_4402"},
                now - timedelta(minutes=54, seconds=10),
            ),
            (
                f"tev_17e_{t_id[:8]}",
                "trc_load_4402_err",
                "LOAD-4402",
                "DELIVERY_ATTEMPTED",
                "IP_OUTBOUND_DISPATCHER",
                {"target": "SAP"},
                now - timedelta(minutes=54),
            ),
            (
                f"tev_17f_{t_id[:8]}",
                "trc_load_4402_err",
                "LOAD-4402",
                "DELIVERY_FAILED",
                "IP_OUTBOUND_DISPATCHER",
                {
                    "status_code": 500,
                    "failure_category": "FATAL",
                    "error": "500 Internal Server Error: SAP TM Carrier validation failed for Swift Logistics",
                },
                now - timedelta(minutes=53, seconds=45),
            ),
        ]

        for tev_id, trc, corr, evt_type, actor, meta, ts in trace_events:
            await conn.execute(
                """
                INSERT INTO public.ip_trace_events (
                    id, tenant_id, trace_id, correlation_id, event_type,
                    actor, metadata_, created_at
                )
                VALUES ($1, $2, $3, $4, $5, $6, $7::jsonb, $8)
                ON CONFLICT (id, created_at) DO UPDATE SET
                    event_type = EXCLUDED.event_type,
                    metadata_ = EXCLUDED.metadata_;
                """,
                tev_id,
                t_id,
                trc,
                corr,
                evt_type,
                actor,
                json.dumps(meta),
                ts,
            )
        logger.info("data_plane_trace_events_seeded", tenant_id=t_id, count=len(trace_events))


async def _seed_workflow_runs(conn: asyncpg.Connection, now: datetime) -> None:
    for t_id in TARGET_TENANTS:
        wf_runs = [
            (
                f"run_inv_99882_{t_id[:8]}",
                "workflow.shopify_orders_to_sap",
                1,
                "WAITING",
                "INV-99882",
                "idem_inv_99882",
                "trc_inv_99882_err",
                "INV-99882",
                0,
                "RATE_LIMITED",
                "503 Service Unavailable: SAP gateway under maintenance window",
                now - timedelta(minutes=30),
                now - timedelta(minutes=30),
            ),
            (
                f"run_inv_99882_rep_{t_id[:8]}",
                "workflow.shopify_orders_to_sap",
                1,
                "SUCCEEDED",
                "INV-99882",
                "idem_inv_99882_rep",
                "trc_inv_99882_replay",
                "INV-99882",
                1,
                None,
                None,
                now - timedelta(minutes=23),
                now - timedelta(minutes=22),
            ),
            (
                f"run_inv_99881_{t_id[:8]}",
                "workflow.shopify_orders_to_sap",
                1,
                "SUCCEEDED",
                "INV-99881",
                "idem_inv_99881",
                "trc_inv_99881_ok",
                "INV-99881",
                0,
                None,
                None,
                now - timedelta(minutes=45),
                now - timedelta(minutes=42),
            ),
            (
                f"run_ord_7719_{t_id[:8]}",
                "workflow.shopify_orders_to_sap",
                1,
                "SUCCEEDED",
                "ORD-7719",
                "idem_ord_7719",
                "trc_ord_7719_ok",
                "ORD-7719",
                0,
                None,
                None,
                now - timedelta(minutes=35),
                now - timedelta(minutes=34),
            ),
            (
                f"run_ord_7720_{t_id[:8]}",
                "workflow.shopify_orders_to_sap",
                1,
                "SUCCEEDED",
                "ORD-7720",
                "idem_ord_7720",
                "trc_ord_7720_ok",
                "ORD-7720",
                0,
                None,
                None,
                now - timedelta(minutes=50),
                now - timedelta(minutes=49),
            ),
            (
                f"run_ord_7721_{t_id[:8]}",
                "workflow.shopify_orders_to_sap",
                1,
                "FAILED",
                "ORD-7721",
                "idem_ord_7721",
                "trc_ord_7721_err",
                "ORD-7721",
                0,
                "GATEWAY_TIMEOUT",
                "504 Gateway Timeout: SAP Sales Order service did not respond within 30000ms",
                now - timedelta(minutes=65),
                now - timedelta(minutes=64),
            ),
            (
                f"run_load_4401_{t_id[:8]}",
                "workflow.tms_shipments_to_sap",
                1,
                "SUCCEEDED",
                "LOAD-4401",
                "idem_load_4401",
                "trc_load_4401_ok",
                "LOAD-4401",
                0,
                None,
                None,
                now - timedelta(minutes=20),
                now - timedelta(minutes=19),
            ),
            (
                f"run_load_4402_{t_id[:8]}",
                "workflow.tms_shipments_to_sap",
                1,
                "FAILED",
                "LOAD-4402",
                "idem_load_4402",
                "trc_load_4402_err",
                "LOAD-4402",
                0,
                "CARRIER_VALIDATION_FAILED",
                "500 Internal Server Error: SAP TM Carrier validation failed for Swift Logistics",
                now - timedelta(minutes=55),
                now - timedelta(minutes=54),
            ),
        ]

        for (
            run_id,
            wf_id,
            v,
            st,
            con_key,
            idem_key,
            trc,
            corr,
            rep_cnt,
            fail_c,
            fail_d,
            created,
            started,
        ) in wf_runs:
            await conn.execute(
                """
                INSERT INTO public.workflow_runs (
                    id, tenant_id, workflow_id, workflow_version, status,
                    priority, concurrency_key, idempotency_key, parent_run_id,
                    trace_id, correlation_id, parent_trace_id, original_trace_id,
                    replay_count, failure_code, failure_detail, created_at,
                    started_at, finished_at
                )
                VALUES (
                    $1, $2, $3, $4, $5, 1, $6, $7, NULL,
                    $8, $9, NULL, $8, $10, $11, $12, $13,
                    $14, NULL
                )
                ON CONFLICT (id, created_at) DO UPDATE SET
                    status = EXCLUDED.status,
                    failure_code = EXCLUDED.failure_code,
                    failure_detail = EXCLUDED.failure_detail;
                """,
                run_id,
                t_id,
                wf_id,
                v,
                st,
                con_key,
                idem_key,
                trc,
                corr,
                rep_cnt,
                fail_c,
                fail_d,
                created,
                started,
            )

            step_nodes = [
                ("validate_payload", "SUCCEEDED", None, None),
                ("normalize_entities", "SUCCEEDED", None, None),
                ("gem_crosswalk", "SUCCEEDED", None, None),
                (
                    "outbound_http",
                    "WAITING" if st == "WAITING" else "SUCCEEDED",
                    fail_c if st == "WAITING" else None,
                    fail_d if st == "WAITING" else None,
                ),
            ]
            for node_key, s_st, s_fail_c, s_fail_d in step_nodes:
                sr_id = f"sr_{run_id}_{node_key}"
                await conn.execute(
                    """
                    INSERT INTO public.workflow_step_runs (
                        id, run_id, run_created_at, tenant_id, node_key,
                        status, retry_count, app_retry_count, internal_retry_count,
                        iteration_count, failure_code, failure_detail,
                        created_at, finished_at
                    )
                    VALUES (
                        $1, $2, $3, $4, $5,
                        $6, 0, 0, $7, 1, $8, $9,
                        $3, $10
                    )
                    ON CONFLICT (id, created_at) DO UPDATE SET
                        status = EXCLUDED.status,
                        failure_code = EXCLUDED.failure_code,
                        failure_detail = EXCLUDED.failure_detail;
                    """,
                    sr_id,
                    run_id,
                    created,
                    t_id,
                    node_key,
                    s_st,
                    1 if s_st == "WAITING" else 0,
                    s_fail_c,
                    s_fail_d,
                    started if s_st == "SUCCEEDED" else None,
                )
        logger.info("data_plane_workflow_runs_seeded", tenant_id=t_id, count=len(wf_runs))


async def _seed_batch_manifests(conn: asyncpg.Connection, now: datetime) -> None:
    for t_id in TARGET_TENANTS:
        oracle_conn = (
            "conn_oracle_mdm_01" if t_id == ACTIVE_TENANT_ID else f"conn_oracle_mdm_01_{t_id[:8]}"
        )
        batch_manifests = [
            (
                f"ip_bch_20261123_001_{t_id[:8]}",
                oracle_conn,
                "interval_readings",
                "P1_LIVE",
                "COMPLETED",
                "s3://ip-tiers/l1/interval_bch_001.json",
                "s3://ip-tiers/l2/interval_bch_001.parquet",
                "s3://ip-tiers/l3/interval_bch_001.parquet",
                hashlib.sha256(b"bch_001").hexdigest(),
                412000,
                now - timedelta(hours=2),
                now - timedelta(hours=1),
                96,
                0,
                95,
                1,
                "SETTLE-RCPT-20261123-01",
                "trc_inv_99882_err",
                now - timedelta(hours=1),
            ),
            (
                f"ip_bch_20261123_002_{t_id[:8]}",
                oracle_conn,
                "interval_readings",
                "P1_LIVE",
                "COMPLETED",
                "s3://ip-tiers/l1/interval_bch_002.json",
                "s3://ip-tiers/l2/interval_bch_002.parquet",
                "s3://ip-tiers/l3/interval_bch_002.parquet",
                hashlib.sha256(b"bch_002").hexdigest(),
                398000,
                now - timedelta(hours=3),
                now - timedelta(hours=2),
                96,
                0,
                96,
                0,
                "SETTLE-RCPT-20261123-02",
                "trc_inv_99881_ok",
                now - timedelta(hours=2),
            ),
            (
                f"ip_bch_99887766554433221100_{t_id[:8]}",
                oracle_conn,
                "interval_readings",
                "P1_LIVE",
                "COMPLETED",
                "s3://ip-tiers/l1/seed_bch_9988.json",
                "s3://ip-tiers/l2/seed_bch_9988.parquet",
                "s3://ip-tiers/l3/seed_bch_9988.parquet",
                hashlib.sha256(b"bch_seed_9988").hexdigest(),
                512000,
                datetime(2026, 10, 29, 0, 0, tzinfo=UTC),
                datetime(2026, 10, 29, 23, 59, 59, tzinfo=UTC),
                96,
                0,
                95,
                1,
                "SETTLE-RCPT-20261029-01",
                "trc_inv_99882_err",
                datetime(2026, 10, 29, 8, 0, tzinfo=UTC),
            ),
        ]

        for (
            b_id,
            c_id,
            strm,
            lane,
            st,
            l1,
            l2,
            l3,
            sha,
            sz,
            w_start,
            w_end,
            raw_cnt,
            dup_cnt,
            valid_cnt,
            quar_cnt,
            rcpt,
            trc,
            completed,
        ) in batch_manifests:
            await conn.execute(
                """
                INSERT INTO public.ip_batch_manifests (
                    id, tenant_id, connection_id, app_id, stream_name,
                    priority_lane, payload_format, status, l1_raw_uri,
                    l2_replica_uri, l3_canonical_uri, inline_payload,
                    payload_sha256, payload_size_bytes, window_start_utc,
                    window_end_utc, raw_ingested_count, duplicates_dropped_count,
                    valid_canonical_count, quarantined_held_count,
                    promoted_outage_clusters_count, delivery_receipt_id,
                    error_message, created_at, completed_at, trace_id, correlation_id
                )
                VALUES (
                    $1, $2, $3, 'oracle_mdm', $4,
                    $5, 'JSON_ARRAY', $6, $7,
                    $8, $9, NULL,
                    $10, $11, $12,
                    $13, $14, $15,
                    $16, $17,
                    0, $18,
                    NULL, $12, $19, $20, $1
                )
                ON CONFLICT (tenant_id, connection_id, payload_sha256) DO UPDATE SET
                    status = EXCLUDED.status,
                    valid_canonical_count = EXCLUDED.valid_canonical_count,
                    quarantined_held_count = EXCLUDED.quarantined_held_count,
                    delivery_receipt_id = EXCLUDED.delivery_receipt_id;
                """,
                b_id,
                t_id,
                c_id,
                strm,
                lane,
                st,
                l1,
                l2,
                l3,
                sha,
                sz,
                w_start,
                w_end,
                raw_cnt,
                dup_cnt,
                valid_cnt,
                quar_cnt,
                rcpt,
                completed,
                trc,
            )
        logger.info("data_plane_batch_manifests_seeded", tenant_id=t_id, count=len(batch_manifests))


async def pump_tenant_data_plane(conn: asyncpg.Connection) -> None:
    logger.info("data_plane_seeding_started")
    await _cleanup_tenant_data(conn)
    now = datetime(2026, 11, 23, 12, 0, 0, tzinfo=UTC)

    await _seed_inbound_records(conn, now)
    await _seed_replica_records(conn, now)
    await _seed_normalized_records(conn, now)
    await _seed_gem_records(conn, now)
    await _seed_outbound_records(conn, now)
    await _seed_trace_events(conn, now)
    await _seed_workflow_runs(conn, now)
    await _seed_batch_manifests(conn, now)
    logger.info("data_plane_seeding_completed")


async def main() -> None:
    logger.info("connecting_global_db", url=GLOBAL_DB_URL)
    conn_global = await asyncpg.connect(GLOBAL_DB_URL)
    try:
        await pump_global_control_plane(conn_global)
    finally:
        await conn_global.close()

    logger.info("connecting_ip_shard", url=IP_SHARD_URL)
    conn_ip = await asyncpg.connect(IP_SHARD_URL)
    try:
        await pump_tenant_data_plane(conn_ip)
    finally:
        await conn_ip.close()

    logger.info("support_cockpit_data_pump_succeeded")


if __name__ == "__main__":
    asyncio.run(main())
