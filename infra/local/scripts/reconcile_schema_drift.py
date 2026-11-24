#!/usr/bin/env python3
"""
Enterprise Schema Drift Reconciliation Utility.

Safely reconciles amended single-migration file definitions (such as renamed tables
or added capabilities) directly into the local PostgreSQL database without wiping
developer data or cascading schema destruction.
"""

from __future__ import annotations

import argparse
import asyncio
import os
from collections.abc import Mapping, Sequence

import structlog
from database.provider import DatabaseProvider
from database.shard_discovery import (
    collect_prefixed_shard_overrides,
    fetch_prefixed_shard_urls,
)
from seedwork.infra.config import load_settings_safely
from seedwork.infra.config_models import PlatformDatabaseSettings
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger(__name__)

SUPPORTED_RECONCILE_DOMAINS: tuple[str, ...] = ("all", "platform", "identity", "ip")
RECONCILABLE_APP_DOMAINS: frozenset[str] = frozenset({"ip"})
IP_SHARD_PREFIX = "ip_"
IP_DEFAULT_SHARD_ID = "ip_shard_1"
IP_DEFAULT_DSN_ENV_VAR = "IP_DATABASE_URL"
RECONCILE_BATCH_SIZE = 500
RECONCILE_BATCH_YIELD_SECONDS = 0.1


def validate_reconcile_domain(domain: str) -> str:
    """Normalize and validate ``domain`` against supported reconciliation targets."""
    normalized = domain.strip().lower()
    if normalized not in SUPPORTED_RECONCILE_DOMAINS:
        supported_csv = ", ".join(SUPPORTED_RECONCILE_DOMAINS)
        raise ValueError(
            f"Unsupported reconciliation domain {domain!r}. Supported domains: {supported_csv}"
        )
    return normalized


def _load_database_settings(*, skip_dotenv: bool) -> PlatformDatabaseSettings:
    """Load database settings from process environment, optionally skipping ``.env`` hydration."""
    if skip_dotenv:
        return PlatformDatabaseSettings()
    return load_settings_safely(PlatformDatabaseSettings)


async def _execute_chunked_mutation(
    session: AsyncSession,
    statement_sql: str,
    *,
    batch_size: int = RECONCILE_BATCH_SIZE,
) -> int:
    """Executes a bounded CTE UPDATE/DELETE loop, committing and yielding after every batch."""
    total_affected = 0
    stmt = text(statement_sql)
    while True:
        res = await session.execute(stmt, {"batch_size": batch_size})
        affected = len(res.all())
        await session.commit()
        if affected == 0:
            break
        total_affected += affected
        await asyncio.sleep(RECONCILE_BATCH_YIELD_SECONDS)
    return total_affected


async def resolve_ip_shard_urls(
    global_url: str,
    settings: PlatformDatabaseSettings,
    environ: Mapping[str, str],
) -> list[str]:
    """Discover and deduplicate all IP shard URLs using the migration runner's override logic."""
    overrides = collect_prefixed_shard_overrides(
        environ,
        settings.shard_overrides,
        shard_prefix=IP_SHARD_PREFIX,
        default_shard_id=IP_DEFAULT_SHARD_ID,
        default_dsn_env_var=IP_DEFAULT_DSN_ENV_VAR,
    )
    return await fetch_prefixed_shard_urls(
        global_url,
        overrides,
        shard_prefix=IP_SHARD_PREFIX,
    )


async def _reconcile_ucp_cellular_sharding(session: AsyncSession) -> None:
    """Idempotently reconciles Cellular CQRS columns and virtual bucket assignments in `ucp`."""
    await session.execute(
        text("ALTER TABLE ucp.database_shards ADD COLUMN IF NOT EXISTS reader_dsn VARCHAR(1024);")
    )
    await session.execute(
        text(
            "ALTER TABLE ucp.database_shards ADD COLUMN IF NOT EXISTS routing_strategy VARCHAR(50) NOT NULL DEFAULT 'tenant_registry';"
        )
    )
    await session.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS ucp.virtual_bucket_assignments (
                id VARCHAR(128) NOT NULL PRIMARY KEY,
                app_id VARCHAR(128) NOT NULL REFERENCES ucp.apps(id) ON DELETE CASCADE,
                bucket_start INTEGER NOT NULL,
                bucket_end INTEGER NOT NULL,
                shard_id VARCHAR(128) NOT NULL REFERENCES ucp.database_shards(id) ON DELETE CASCADE,
                created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL,
                updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL,
                CONSTRAINT uq_virtual_bucket_app_start UNIQUE (app_id, bucket_start),
                CONSTRAINT ck_virtual_bucket_bounds CHECK (
                    bucket_start >= 0 AND bucket_end >= bucket_start AND bucket_end < 4096
                )
            );
            """
        )
    )


async def _reconcile_ip_shard(shard_url: str) -> None:
    """Applies idempotent Gear-1 Data Plane DDL and RLS policies on the IP tenant shard."""
    shard_provider = DatabaseProvider.from_url(shard_url)
    try:
        async with shard_provider.session() as shard_session:
            await shard_session.execute(
                text(
                    "ALTER TABLE public.inbound_records ADD COLUMN IF NOT EXISTS batch_id VARCHAR(64);"
                )
            )
            await shard_session.execute(
                text(
                    "ALTER TABLE public.inbound_records ADD COLUMN IF NOT EXISTS batch_seq INTEGER;"
                )
            )
            await shard_session.commit()

            await _execute_chunked_mutation(
                shard_session,
                """
                WITH batch AS (
                    SELECT id
                    FROM public.inbound_records
                    WHERE batch_id IS NULL
                    LIMIT :batch_size
                    FOR UPDATE SKIP LOCKED
                )
                UPDATE public.inbound_records AS target
                SET batch_id = target.id
                FROM batch
                WHERE target.id = batch.id
                RETURNING target.id;
                """,
            )
            await _execute_chunked_mutation(
                shard_session,
                """
                WITH batch AS (
                    SELECT id
                    FROM public.inbound_records
                    WHERE batch_seq IS NULL
                    LIMIT :batch_size
                    FOR UPDATE SKIP LOCKED
                )
                UPDATE public.inbound_records AS target
                SET batch_seq = 0
                FROM batch
                WHERE target.id = batch.id
                RETURNING target.id;
                """,
            )

            await shard_session.execute(
                text(
                    "ALTER TABLE public.inbound_records ADD COLUMN IF NOT EXISTS causation_depth INTEGER NOT NULL DEFAULT 0;"
                )
            )
            await shard_session.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS ix_inbound_records_batch_range ON public.inbound_records (tenant_id, batch_id, id);"
                )
            )
            await shard_session.execute(
                text(
                    "ALTER TABLE public.outbound_records ADD COLUMN IF NOT EXISTS conflict_strategy VARCHAR(32) NOT NULL DEFAULT 'FAIL';"
                )
            )
            await shard_session.execute(
                text(
                    "ALTER TABLE public.outbound_records ADD COLUMN IF NOT EXISTS causation_depth INTEGER NOT NULL DEFAULT 0;"
                )
            )
            await shard_session.execute(
                text("""
                CREATE TABLE IF NOT EXISTS public.quarantine_records (
                    id VARCHAR(64) NOT NULL PRIMARY KEY,
                    tenant_id VARCHAR(128) NOT NULL,
                    connection_id VARCHAR(64) NOT NULL,
                    outbound_record_id VARCHAR(64) NOT NULL,
                    stream_name VARCHAR(128) NOT NULL,
                    idempotency_key VARCHAR(255),
                    trace_id VARCHAR(64) NOT NULL,
                    correlation_id VARCHAR(255),
                    failure_category VARCHAR(64) NOT NULL,
                    error_code VARCHAR(64),
                    error_message TEXT NOT NULL,
                    response_status_code INTEGER,
                    attempt_count INTEGER NOT NULL DEFAULT 1,
                    request_body JSONB,
                    request_s3_key VARCHAR(512),
                    response_body JSONB,
                    response_s3_key VARCHAR(512),
                    quarantined_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                );
                """)
            )
            await shard_session.execute(
                text(
                    "ALTER TABLE public.quarantine_records ADD COLUMN IF NOT EXISTS idempotency_key VARCHAR(255);"
                )
            )
            await shard_session.execute(
                text(
                    "ALTER TABLE public.quarantine_records ADD COLUMN IF NOT EXISTS error_code VARCHAR(64);"
                )
            )
            await shard_session.execute(
                text(
                    "ALTER TABLE public.quarantine_records ADD COLUMN IF NOT EXISTS attempt_count INTEGER NOT NULL DEFAULT 1;"
                )
            )
            await shard_session.execute(
                text(
                    "ALTER TABLE public.quarantine_records ADD COLUMN IF NOT EXISTS request_s3_key VARCHAR(512);"
                )
            )
            await shard_session.execute(
                text(
                    "ALTER TABLE public.quarantine_records ADD COLUMN IF NOT EXISTS response_body JSONB;"
                )
            )
            await shard_session.execute(
                text(
                    "ALTER TABLE public.quarantine_records ADD COLUMN IF NOT EXISTS response_s3_key VARCHAR(512);"
                )
            )
            await shard_session.execute(
                text("ALTER TABLE public.quarantine_records DROP COLUMN IF EXISTS operation;")
            )
            await shard_session.commit()

            has_legacy_attempts = await shard_session.execute(
                text("""
                SELECT 1 FROM information_schema.columns
                WHERE table_schema = 'public'
                  AND table_name = 'quarantine_records'
                  AND column_name = 'attempts'
                LIMIT 1;
                """)
            )
            if has_legacy_attempts.scalar() is not None:
                await _execute_chunked_mutation(
                    shard_session,
                    """
                    WITH batch AS (
                        SELECT id
                        FROM public.quarantine_records
                        WHERE attempts IS NOT NULL
                          AND (attempt_count IS NULL OR attempt_count = 1)
                          AND attempt_count IS DISTINCT FROM attempts
                        LIMIT :batch_size
                        FOR UPDATE SKIP LOCKED
                    )
                    UPDATE public.quarantine_records AS target
                    SET attempt_count = target.attempts
                    FROM batch
                    WHERE target.id = batch.id
                    RETURNING target.id;
                    """,
                )
                await shard_session.execute(
                    text("ALTER TABLE public.quarantine_records DROP COLUMN IF EXISTS attempts;")
                )
                await shard_session.commit()

            await shard_session.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS idx_quarantine_tenant_time ON public.quarantine_records (tenant_id, quarantined_at);"
                )
            )
            await shard_session.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS idx_quarantine_outbound ON public.quarantine_records (tenant_id, outbound_record_id);"
                )
            )
            await shard_session.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS idx_quarantine_trace ON public.quarantine_records (tenant_id, trace_id);"
                )
            )
            await shard_session.execute(
                text("ALTER TABLE public.quarantine_records ENABLE ROW LEVEL SECURITY;")
            )
            await shard_session.execute(
                text(
                    "DROP POLICY IF EXISTS tenant_isolation_quarantine_records ON public.quarantine_records;"
                )
            )
            await shard_session.execute(
                text("""
                CREATE POLICY tenant_isolation_quarantine_records ON public.quarantine_records
                    USING (tenant_id = current_setting('platform.current_tenant_id', true));
                """)
            )
            await shard_session.execute(
                text("""
                CREATE TABLE IF NOT EXISTS public.ip_batch_manifests (
                    id VARCHAR(64) NOT NULL PRIMARY KEY,
                    tenant_id VARCHAR(128) NOT NULL,
                    connection_id VARCHAR(64) NOT NULL,
                    app_id VARCHAR(64) NOT NULL DEFAULT '',
                    stream_name VARCHAR(128) NOT NULL,
                    priority_lane VARCHAR(32) NOT NULL DEFAULT 'P1_LIVE',
                    payload_format VARCHAR(32) NOT NULL DEFAULT 'JSON_ARRAY',
                    status VARCHAR(32) NOT NULL DEFAULT 'INGESTED',
                    l1_raw_uri TEXT NOT NULL,
                    l2_replica_uri TEXT,
                    l3_canonical_uri TEXT,
                    inline_payload JSONB,
                    payload_sha256 VARCHAR(64) NOT NULL,
                    payload_size_bytes BIGINT NOT NULL DEFAULT 0,
                    window_start_utc TIMESTAMPTZ NOT NULL,
                    window_end_utc TIMESTAMPTZ NOT NULL,
                    raw_ingested_count BIGINT NOT NULL,
                    duplicates_dropped_count BIGINT NOT NULL DEFAULT 0,
                    valid_canonical_count BIGINT NOT NULL DEFAULT 0,
                    quarantined_held_count BIGINT NOT NULL DEFAULT 0,
                    promoted_outage_clusters_count INTEGER NOT NULL DEFAULT 0,
                    delivery_receipt_id VARCHAR(128),
                    error_message TEXT,
                    trace_id VARCHAR(64) NOT NULL,
                    correlation_id VARCHAR(255),
                    parent_trace_id VARCHAR(64),
                    original_trace_id VARCHAR(64),
                    replay_count INTEGER NOT NULL DEFAULT 0,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    completed_at TIMESTAMPTZ,
                    CONSTRAINT uq_ip_batch_manifests_sha256 UNIQUE (tenant_id, connection_id, payload_sha256),
                    CONSTRAINT chk_ip_batch_zero_loss_reconciliation CHECK (
                        status <> 'COMPLETED'
                        OR raw_ingested_count = (duplicates_dropped_count + valid_canonical_count + quarantined_held_count)
                    )
                );
                """)
            )
            await shard_session.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS idx_ip_batch_manifests_tenant_conn ON public.ip_batch_manifests (tenant_id, connection_id, created_at);"
                )
            )
            await shard_session.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS idx_ip_batch_manifests_trace ON public.ip_batch_manifests (tenant_id, trace_id);"
                )
            )
            await shard_session.execute(
                text("ALTER TABLE public.ip_batch_manifests ENABLE ROW LEVEL SECURITY;")
            )
            await shard_session.execute(
                text("ALTER TABLE public.ip_batch_manifests FORCE ROW LEVEL SECURITY;")
            )
            await shard_session.execute(
                text(
                    "DROP POLICY IF EXISTS tenant_isolation_ip_batch_manifests ON public.ip_batch_manifests;"
                )
            )
            await shard_session.execute(
                text("""
                CREATE POLICY tenant_isolation_ip_batch_manifests ON public.ip_batch_manifests
                    USING (tenant_id = current_setting('platform.current_tenant_id', true));
                """)
            )

            await shard_session.execute(
                text("""
                CREATE TABLE IF NOT EXISTS public.ip_replay_ledger (
                    id VARCHAR(64) NOT NULL PRIMARY KEY,
                    tenant_id VARCHAR(128) NOT NULL,
                    actor VARCHAR(128) NOT NULL,
                    target_type VARCHAR(64) NOT NULL,
                    target_id VARCHAR(128) NOT NULL,
                    target_stage VARCHAR(64) NOT NULL,
                    trace_id VARCHAR(64) NOT NULL,
                    idempotency_key VARCHAR(128) NOT NULL,
                    reason TEXT NOT NULL,
                    payload_override JSONB,
                    status VARCHAR(32) NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL,
                    completed_at TIMESTAMPTZ,
                    CONSTRAINT uq_ip_replay_idempotency UNIQUE (tenant_id, idempotency_key)
                );
                """)
            )
            await shard_session.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS idx_ip_replay_target ON public.ip_replay_ledger (tenant_id, target_type, target_id);"
                )
            )
            await shard_session.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS idx_ip_replay_actor ON public.ip_replay_ledger (tenant_id, actor, created_at);"
                )
            )
            await shard_session.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS idx_ip_replay_trace ON public.ip_replay_ledger (tenant_id, trace_id);"
                )
            )
            await shard_session.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS idx_ip_replay_status ON public.ip_replay_ledger (tenant_id, status, created_at);"
                )
            )
            await shard_session.execute(
                text("ALTER TABLE public.ip_replay_ledger ENABLE ROW LEVEL SECURITY;")
            )
            await shard_session.execute(
                text("ALTER TABLE public.ip_replay_ledger FORCE ROW LEVEL SECURITY;")
            )
            await shard_session.execute(
                text(
                    "DROP POLICY IF EXISTS tenant_isolation_ip_replay_ledger ON public.ip_replay_ledger;"
                )
            )
            await shard_session.execute(
                text("""
                CREATE POLICY tenant_isolation_ip_replay_ledger ON public.ip_replay_ledger
                    USING (tenant_id = current_setting('platform.current_tenant_id', true));
                """)
            )

            await shard_session.execute(
                text("""
                CREATE TABLE IF NOT EXISTS public.mdm_billing_readings (
                    id VARCHAR(64) NOT NULL,
                    tenant_id VARCHAR(128) NOT NULL,
                    trace_id VARCHAR(64) NOT NULL,
                    correlation_id VARCHAR(255),
                    parent_trace_id VARCHAR(64),
                    original_trace_id VARCHAR(64),
                    replay_count INTEGER NOT NULL DEFAULT 0,
                    source_connection_id VARCHAR(64) NOT NULL,
                    source_replica_id VARCHAR(64) NOT NULL,
                    transformation_id VARCHAR(128) NOT NULL DEFAULT 'energy.sap_billing_reading',
                    transformation_version INTEGER NOT NULL DEFAULT 1,
                    reading_id VARCHAR(128) NOT NULL,
                    meter_serial_number VARCHAR(128) NOT NULL,
                    service_point_id VARCHAR(128),
                    reading_timestamp TIMESTAMPTZ NOT NULL,
                    kwh_delivered FLOAT NOT NULL,
                    quality_flag VARCHAR(32) NOT NULL DEFAULT 'VALIDATED',
                    recorded_at TIMESTAMPTZ NOT NULL,
                    PRIMARY KEY (id, reading_timestamp)
                );
                """)
            )
            await shard_session.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS idx_mdm_billing_meter_ts ON public.mdm_billing_readings (tenant_id, meter_serial_number, reading_timestamp);"
                )
            )
            await shard_session.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS idx_mdm_billing_sp ON public.mdm_billing_readings (tenant_id, service_point_id);"
                )
            )
            await shard_session.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS idx_mdm_billing_trace ON public.mdm_billing_readings (tenant_id, trace_id);"
                )
            )
            await shard_session.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS idx_mdm_billing_reading_id ON public.mdm_billing_readings (tenant_id, reading_id);"
                )
            )
            await shard_session.execute(
                text("ALTER TABLE public.mdm_billing_readings ENABLE ROW LEVEL SECURITY;")
            )
            await shard_session.execute(
                text("ALTER TABLE public.mdm_billing_readings FORCE ROW LEVEL SECURITY;")
            )
            await shard_session.execute(
                text(
                    "DROP POLICY IF EXISTS tenant_isolation_mdm_billing_readings ON public.mdm_billing_readings;"
                )
            )
            await shard_session.execute(
                text("""
                CREATE POLICY tenant_isolation_mdm_billing_readings ON public.mdm_billing_readings
                    USING (tenant_id = current_setting('platform.current_tenant_id', true));
                """)
            )

            # Durable Workflow Orchestration Engine (13 tables)
            for stmt in (
                """
                CREATE TABLE IF NOT EXISTS public.workflow_runs (
                    id VARCHAR(64) NOT NULL,
                    tenant_id VARCHAR(128) NOT NULL,
                    workflow_id VARCHAR(128) NOT NULL,
                    workflow_version INTEGER NOT NULL,
                    status VARCHAR(32) NOT NULL,
                    priority SMALLINT NOT NULL DEFAULT 2,
                    concurrency_key VARCHAR(255),
                    idempotency_key VARCHAR(255) NOT NULL,
                    parent_run_id VARCHAR(64),
                    trace_id VARCHAR(64) NOT NULL,
                    correlation_id VARCHAR(255),
                    parent_trace_id VARCHAR(64),
                    original_trace_id VARCHAR(64),
                    replay_count INTEGER NOT NULL DEFAULT 0,
                    failure_code VARCHAR(64),
                    failure_detail TEXT,
                    created_at TIMESTAMPTZ NOT NULL,
                    started_at TIMESTAMPTZ,
                    finished_at TIMESTAMPTZ,
                    PRIMARY KEY (id, created_at)
                );
                """,
                "CREATE INDEX IF NOT EXISTS idx_wf_runs_active_conc ON public.workflow_runs (tenant_id, workflow_id, concurrency_key) WHERE status IN ('QUEUED', 'RUNNING', 'WAITING');",
                "CREATE INDEX IF NOT EXISTS idx_wf_runs_trace ON public.workflow_runs (tenant_id, trace_id);",
                "CREATE INDEX IF NOT EXISTS idx_wf_runs_corr ON public.workflow_runs (tenant_id, correlation_id);",
                "CREATE INDEX IF NOT EXISTS idx_wf_runs_parent ON public.workflow_runs (tenant_id, parent_run_id);",
                "CREATE INDEX IF NOT EXISTS idx_wf_runs_orig_trace ON public.workflow_runs (tenant_id, original_trace_id);",
                """
                CREATE TABLE IF NOT EXISTS public.workflow_step_runs (
                    id VARCHAR(64) NOT NULL,
                    run_id VARCHAR(64) NOT NULL,
                    run_created_at TIMESTAMPTZ NOT NULL,
                    tenant_id VARCHAR(128) NOT NULL,
                    node_key VARCHAR(128) NOT NULL,
                    status VARCHAR(32) NOT NULL,
                    retry_count INTEGER NOT NULL DEFAULT 0,
                    app_retry_count INTEGER NOT NULL DEFAULT 0,
                    internal_retry_count INTEGER NOT NULL DEFAULT 0,
                    iteration_count INTEGER NOT NULL DEFAULT 0,
                    failure_code VARCHAR(64),
                    failure_detail TEXT,
                    created_at TIMESTAMPTZ NOT NULL,
                    finished_at TIMESTAMPTZ,
                    PRIMARY KEY (id, created_at),
                    CONSTRAINT uq_wf_step_run_node UNIQUE (run_id, node_key, created_at)
                );
                """,
                "CREATE INDEX IF NOT EXISTS idx_wf_step_runs_run ON public.workflow_step_runs (tenant_id, run_id);",
                """
                CREATE TABLE IF NOT EXISTS public.workflow_active_leases (
                    step_run_id VARCHAR(64) NOT NULL,
                    step_created_at TIMESTAMPTZ NOT NULL,
                    retry_count INTEGER NOT NULL,
                    run_id VARCHAR(64) NOT NULL,
                    tenant_id VARCHAR(128) NOT NULL,
                    worker_id VARCHAR(128) NOT NULL,
                    lease_expires_at TIMESTAMPTZ NOT NULL,
                    timeout_at TIMESTAMPTZ NOT NULL,
                    evicted_at TIMESTAMPTZ,
                    PRIMARY KEY (step_run_id, step_created_at, retry_count)
                );
                """,
                "CREATE INDEX IF NOT EXISTS idx_wf_active_leases_expiry ON public.workflow_active_leases (lease_expires_at);",
                "CREATE INDEX IF NOT EXISTS idx_wf_active_leases_timeout ON public.workflow_active_leases (timeout_at);",
                """
                CREATE TABLE IF NOT EXISTS public.workflow_step_attempts (
                    id VARCHAR(64) NOT NULL,
                    step_run_id VARCHAR(64) NOT NULL,
                    tenant_id VARCHAR(128) NOT NULL,
                    retry_count INTEGER NOT NULL,
                    app_retry_count INTEGER NOT NULL,
                    internal_retry_count INTEGER NOT NULL,
                    worker_id VARCHAR(128) NOT NULL,
                    status VARCHAR(32) NOT NULL,
                    is_app_error BOOLEAN,
                    outcome_code VARCHAR(64),
                    outcome_detail TEXT,
                    started_at TIMESTAMPTZ NOT NULL,
                    finished_at TIMESTAMPTZ,
                    PRIMARY KEY (id, started_at)
                );
                """,
                "CREATE INDEX IF NOT EXISTS idx_wf_step_attempts_step ON public.workflow_step_attempts (tenant_id, step_run_id);",
                """
                CREATE TABLE IF NOT EXISTS public.workflow_payloads (
                    tenant_id VARCHAR(128) NOT NULL,
                    owner_id VARCHAR(64) NOT NULL,
                    owner_created_at TIMESTAMPTZ NOT NULL,
                    payload_type VARCHAR(32) NOT NULL,
                    location VARCHAR(16) NOT NULL,
                    inline_content JSONB,
                    external_ref VARCHAR(512),
                    payload_reference_id VARCHAR(64),
                    payload_reference_created_at TIMESTAMPTZ,
                    size_bytes INTEGER NOT NULL DEFAULT 0,
                    updated_at TIMESTAMPTZ NOT NULL,
                    PRIMARY KEY (tenant_id, owner_id, owner_created_at, payload_type)
                );
                """,
                """
                CREATE TABLE IF NOT EXISTS public.workflow_idempotency_keys (
                    tenant_id VARCHAR(128) NOT NULL,
                    workflow_id VARCHAR(128) NOT NULL,
                    key VARCHAR(255) NOT NULL,
                    claimed_by_run_id VARCHAR(64) NOT NULL,
                    eviction_policy VARCHAR(32) NOT NULL DEFAULT 'TTL',
                    expires_at TIMESTAMPTZ NOT NULL,
                    updated_at TIMESTAMPTZ NOT NULL,
                    PRIMARY KEY (tenant_id, workflow_id, key)
                );
                """,
                "CREATE INDEX IF NOT EXISTS idx_wf_idempotency_expires ON public.workflow_idempotency_keys (expires_at);",
                """
                CREATE TABLE IF NOT EXISTS public.workflow_matches (
                    id VARCHAR(64) PRIMARY KEY,
                    tenant_id VARCHAR(128) NOT NULL,
                    run_id VARCHAR(64) NOT NULL,
                    step_run_id VARCHAR(64) NOT NULL,
                    step_created_at TIMESTAMPTZ NOT NULL,
                    node_key VARCHAR(128) NOT NULL,
                    kind VARCHAR(32) NOT NULL,
                    existing_data JSONB NOT NULL DEFAULT '{}'::jsonb,
                    is_satisfied BOOLEAN NOT NULL DEFAULT FALSE,
                    resolved_action VARCHAR(32),
                    created_at TIMESTAMPTZ NOT NULL
                );
                """,
                "CREATE INDEX IF NOT EXISTS idx_wf_matches_run ON public.workflow_matches (tenant_id, run_id);",
                """
                CREATE TABLE IF NOT EXISTS public.workflow_match_conditions (
                    match_id VARCHAR(64) NOT NULL,
                    id VARCHAR(64) NOT NULL,
                    tenant_id VARCHAR(128) NOT NULL,
                    or_group_id VARCHAR(64) NOT NULL,
                    condition_kind VARCHAR(32) NOT NULL,
                    event_key VARCHAR(128) NOT NULL,
                    event_resource_hint VARCHAR(255),
                    predicate_id VARCHAR(128),
                    readable_data_key VARCHAR(128) NOT NULL,
                    action VARCHAR(32) NOT NULL,
                    is_satisfied BOOLEAN NOT NULL DEFAULT FALSE,
                    matched_data JSONB,
                    timeout_at TIMESTAMPTZ,
                    created_at TIMESTAMPTZ NOT NULL,
                    PRIMARY KEY (match_id, id)
                );
                """,
                "CREATE INDEX IF NOT EXISTS idx_wf_match_cond_event ON public.workflow_match_conditions (tenant_id, condition_kind, event_key, event_resource_hint) WHERE NOT is_satisfied;",
                "CREATE INDEX IF NOT EXISTS idx_wf_match_cond_timeout ON public.workflow_match_conditions (timeout_at) WHERE NOT is_satisfied AND timeout_at IS NOT NULL;",
                """
                CREATE TABLE IF NOT EXISTS public.workflow_queue_items (
                    id BIGSERIAL PRIMARY KEY,
                    tenant_id VARCHAR(128) NOT NULL,
                    run_id VARCHAR(64) NOT NULL,
                    step_run_id VARCHAR(64) NOT NULL,
                    step_created_at TIMESTAMPTZ NOT NULL,
                    retry_count INTEGER NOT NULL DEFAULT 0,
                    item_kind VARCHAR(32) NOT NULL,
                    queue_name VARCHAR(64) NOT NULL,
                    priority SMALLINT NOT NULL DEFAULT 2,
                    available_at TIMESTAMPTZ NOT NULL,
                    enqueued_at TIMESTAMPTZ NOT NULL,
                    concurrency_key VARCHAR(255),
                    rate_limit_key VARCHAR(255),
                    rate_limit_units INTEGER NOT NULL DEFAULT 1
                );
                """,
                "CREATE INDEX IF NOT EXISTS idx_wf_queue_poll ON public.workflow_queue_items (queue_name, available_at, tenant_id, priority, id);",
                """
                CREATE TABLE IF NOT EXISTS public.workflow_paused_queue_items (
                    id BIGSERIAL PRIMARY KEY,
                    tenant_id VARCHAR(128) NOT NULL,
                    rate_limit_key VARCHAR(255) NOT NULL,
                    run_id VARCHAR(64) NOT NULL,
                    step_run_id VARCHAR(64) NOT NULL,
                    step_created_at TIMESTAMPTZ NOT NULL,
                    retry_count INTEGER NOT NULL DEFAULT 0,
                    queue_name VARCHAR(64) NOT NULL,
                    priority SMALLINT NOT NULL DEFAULT 2,
                    requeue_after TIMESTAMPTZ NOT NULL,
                    concurrency_key VARCHAR(255),
                    rate_limit_units INTEGER NOT NULL DEFAULT 1,
                    created_at TIMESTAMPTZ NOT NULL
                );
                """,
                "CREATE INDEX IF NOT EXISTS idx_wf_paused_queue_unpause ON public.workflow_paused_queue_items (requeue_after, tenant_id, rate_limit_key);",
                """
                CREATE TABLE IF NOT EXISTS public.workflow_queue_cursors (
                    queue_name VARCHAR(64) PRIMARY KEY,
                    last_serviced_tenant_id VARCHAR(128) NOT NULL DEFAULT '',
                    min_unprocessed_id BIGINT NOT NULL DEFAULT 0,
                    updated_at TIMESTAMPTZ NOT NULL
                );
                """,
                """
                CREATE TABLE IF NOT EXISTS public.workflow_concurrency_slots (
                    sort_id BIGINT GENERATED ALWAYS AS IDENTITY NOT NULL,
                    tenant_id VARCHAR(128) NOT NULL,
                    strategy_id VARCHAR(64) NOT NULL,
                    concurrency_key VARCHAR(255) NOT NULL,
                    run_id VARCHAR(64) NOT NULL,
                    step_run_id VARCHAR(64) NOT NULL,
                    step_created_at TIMESTAMPTZ NOT NULL,
                    retry_count INTEGER NOT NULL DEFAULT 0,
                    priority SMALLINT NOT NULL DEFAULT 2,
                    is_filled BOOLEAN NOT NULL DEFAULT FALSE,
                    next_strategy_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
                    queue_name VARCHAR(64) NOT NULL DEFAULT 'default',
                    rate_limit_key VARCHAR(255),
                    rate_limit_units INTEGER NOT NULL DEFAULT 1,
                    acquired_at TIMESTAMPTZ,
                    created_at TIMESTAMPTZ NOT NULL,
                    PRIMARY KEY (sort_id, tenant_id, strategy_id, step_run_id, step_created_at, retry_count)
                );
                """,
                "CREATE INDEX IF NOT EXISTS idx_wf_conc_slots_eval ON public.workflow_concurrency_slots (tenant_id, strategy_id, concurrency_key, is_filled, sort_id);",
                """
                CREATE TABLE IF NOT EXISTS public.workflow_rate_limit_buckets (
                    tenant_id VARCHAR(128) NOT NULL,
                    rate_limit_key VARCHAR(255) NOT NULL,
                    capacity INTEGER NOT NULL,
                    refill_per_second FLOAT NOT NULL,
                    tokens FLOAT NOT NULL,
                    refilled_at TIMESTAMPTZ NOT NULL,
                    paused_at TIMESTAMPTZ,
                    paused_until TIMESTAMPTZ,
                    PRIMARY KEY (tenant_id, rate_limit_key)
                );
                """,
            ):
                await shard_session.execute(text(stmt))

            orchestration_rls_tables = (
                "workflow_runs",
                "workflow_step_runs",
                "workflow_active_leases",
                "workflow_step_attempts",
                "workflow_payloads",
                "workflow_idempotency_keys",
                "workflow_matches",
                "workflow_match_conditions",
                "workflow_queue_items",
                "workflow_paused_queue_items",
                "workflow_concurrency_slots",
                "workflow_rate_limit_buckets",
            )
            for tbl in orchestration_rls_tables:
                await shard_session.execute(
                    text(f"ALTER TABLE public.{tbl} ENABLE ROW LEVEL SECURITY;")
                )
                await shard_session.execute(
                    text(f"DROP POLICY IF EXISTS tenant_isolation_{tbl} ON public.{tbl};")
                )
                await shard_session.execute(
                    text(f"""
                    CREATE POLICY tenant_isolation_{tbl} ON public.{tbl}
                        USING (tenant_id = current_setting('platform.current_tenant_id', true));
                    """)
                )
            await shard_session.commit()
    finally:
        await shard_provider.close()


async def reconcile(domain: str = "all", *, skip_dotenv: bool = False) -> None:
    """Applies missing DDL and initial reference data to eliminate schema drift."""
    target = validate_reconcile_domain(domain)
    settings = _load_database_settings(skip_dotenv=skip_dotenv)
    provider = DatabaseProvider.from_url(settings.global_url)

    try:
        async with provider.session() as session:
            # 1. IP Domain: connection_entities (unified subscription + sync watermark table)
            if target in ("all", "ip"):
                await session.execute(
                    text("""
                    CREATE TABLE IF NOT EXISTS ip.connection_entities (
                        id VARCHAR(64) NOT NULL PRIMARY KEY,
                        tenant_id VARCHAR(64) NOT NULL,
                        connection_id VARCHAR(64) NOT NULL REFERENCES ip.connections(id) ON DELETE CASCADE,
                        stream_name VARCHAR(128) NOT NULL,
                        sync_mode VARCHAR(32) NOT NULL DEFAULT 'INCREMENTAL',
                        schedule VARCHAR(32) NOT NULL DEFAULT 'manual',
                        sync_from VARCHAR(32) NOT NULL DEFAULT 'all',
                        sync_from_at TIMESTAMPTZ,
                        is_enabled BOOLEAN NOT NULL DEFAULT TRUE,
                        primary_key JSONB NOT NULL DEFAULT '[]'::jsonb,
                        fields_schema JSONB NOT NULL DEFAULT '[]'::jsonb,
                        cursor_field VARCHAR(128),
                        cursor_value TEXT,
                        records_synced_count BIGINT NOT NULL DEFAULT 0,
                        last_synced_at TIMESTAMPTZ,
                        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        CONSTRAINT uq_ip_connection_entities_tenant_conn_stream
                            UNIQUE (tenant_id, connection_id, stream_name)
                    );
                    """)
                )
                await session.execute(
                    text(
                        "CREATE INDEX IF NOT EXISTS idx_ip_connection_entities_conn ON ip.connection_entities (tenant_id, connection_id);"
                    )
                )
                await session.execute(
                    text(
                        "CREATE INDEX IF NOT EXISTS idx_ip_connection_entities_due_schedule ON ip.connection_entities (schedule) WHERE is_enabled = true AND schedule != 'manual';"
                    )
                )

                # Migrate any legacy stream_state rows before dropping obsolete tables
                await session.execute(
                    text("""
                    DO $$
                    BEGIN
                        IF EXISTS (
                            SELECT 1 FROM information_schema.tables
                            WHERE table_schema = 'ip' AND table_name = 'connection_stream_state'
                        ) THEN
                            INSERT INTO ip.connection_entities (
                                id, tenant_id, connection_id, stream_name,
                                cursor_field, cursor_value, records_synced_count,
                                last_synced_at, created_at, updated_at
                            )
                            SELECT
                                s.id, s.tenant_id, s.connection_id, s.stream_name,
                                s.cursor_field, s.cursor_value, s.records_synced_count,
                                s.last_synced_at, COALESCE(s.last_synced_at, NOW()), COALESCE(s.last_synced_at, NOW())
                            FROM ip.connection_stream_state s
                            INNER JOIN ip.connections c ON c.id = s.connection_id
                            ON CONFLICT (tenant_id, connection_id, stream_name) DO NOTHING;
                            DROP TABLE ip.connection_stream_state CASCADE;
                        END IF;
                        IF EXISTS (
                            SELECT 1 FROM information_schema.tables
                            WHERE table_schema = 'ip' AND table_name = 'connection_stream_states'
                        ) THEN
                            DROP TABLE ip.connection_stream_states CASCADE;
                        END IF;
                        IF EXISTS (
                            SELECT 1 FROM information_schema.tables
                            WHERE table_schema = 'ip' AND table_name = 'connection_catalogs'
                        ) THEN
                            DROP TABLE ip.connection_catalogs CASCADE;
                        END IF;
                    END $$;
                    """)
                )
                await session.commit()

                # Reconcile NO_AUTH connections to ACTIVE status in chunks and enforce DB CheckConstraint
                activated_count = await _execute_chunked_mutation(
                    session,
                    """
                    WITH batch AS (
                        SELECT id
                        FROM ip.connections
                        WHERE auth_type = 'NO_AUTH' AND status = 'PENDING_AUTH'
                        LIMIT :batch_size
                        FOR UPDATE SKIP LOCKED
                    )
                    UPDATE ip.connections AS target
                    SET status = 'ACTIVE', updated_at = NOW()
                    FROM batch
                    WHERE target.id = batch.id
                    RETURNING target.id;
                    """,
                )
                if activated_count > 0:
                    logger.info("reconciled_no_auth_connections", activated_count=activated_count)

                await session.execute(
                    text("""
                    DO $$
                    BEGIN
                        IF NOT EXISTS (
                            SELECT 1
                            FROM pg_constraint c
                            JOIN pg_namespace n ON n.oid = c.connamespace
                            WHERE n.nspname = 'ip'
                              AND c.conname = 'ck_ip_connections_no_auth_not_pending'
                        ) THEN
                            ALTER TABLE ip.connections
                            ADD CONSTRAINT ck_ip_connections_no_auth_not_pending
                            CHECK (NOT (auth_type = 'NO_AUTH' AND status = 'PENDING_AUTH'));
                        END IF;
                    END
                    $$;
                    """)
                )

                await session.execute(
                    text(
                        "ALTER TABLE ip.stitches ADD COLUMN IF NOT EXISTS filter_conditions JSONB NOT NULL DEFAULT '{}'::jsonb;"
                    )
                )

                await session.execute(text("DROP TABLE IF EXISTS ip.simulator_sandboxes CASCADE;"))
                await session.execute(
                    text("""
                    DO $$
                    BEGIN
                        IF EXISTS (
                            SELECT 1 FROM information_schema.tables
                            WHERE table_schema = 'ip' AND table_name = 'simulator_entities'
                        ) AND NOT EXISTS (
                            SELECT 1 FROM information_schema.columns
                            WHERE table_schema = 'ip'
                              AND table_name = 'simulator_entities'
                              AND column_name = 'connection_id'
                        ) THEN
                            DROP TABLE ip.simulator_entities CASCADE;
                        END IF;
                    END $$;
                    """)
                )
                await session.execute(
                    text("""
                    CREATE TABLE IF NOT EXISTS ip.simulator_entities (
                        id VARCHAR(64) NOT NULL PRIMARY KEY,
                        tenant_id VARCHAR(64) NOT NULL,
                        connection_id VARCHAR(64) NOT NULL REFERENCES ip.connections(id) ON DELETE CASCADE,
                        entity_name VARCHAR(128) NOT NULL,
                        primary_key_field VARCHAR(128) NOT NULL,
                        cursor_field VARCHAR(128) NOT NULL,
                        push_mode VARCHAR(32) NOT NULL DEFAULT 'RANDOM_BURST',
                        push_config JSONB NOT NULL DEFAULT '{}'::jsonb,
                        records_per_pull INTEGER NOT NULL DEFAULT 25,
                        cursor_step_seconds INTEGER NOT NULL DEFAULT 60,
                        velocity_mode VARCHAR(32) NOT NULL DEFAULT 'ENTITY_TRANSACTIONAL',
                        sample_blueprint JSONB NOT NULL,
                        inferred_json_schema JSONB NOT NULL,
                        chaos_policy JSONB NOT NULL DEFAULT '{}'::jsonb,
                        version INTEGER NOT NULL DEFAULT 1,
                        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        CONSTRAINT uq_ip_simulator_entity_conn_name UNIQUE (tenant_id, connection_id, entity_name)
                    );
                    """)
                )
                await session.execute(
                    text("""
                    ALTER TABLE ip.simulator_entities
                    ADD COLUMN IF NOT EXISTS push_mode VARCHAR(32) NOT NULL DEFAULT 'RANDOM_BURST',
                    ADD COLUMN IF NOT EXISTS push_config JSONB NOT NULL DEFAULT '{}'::jsonb;
                    """)
                )
                await session.commit()

                await _execute_chunked_mutation(
                    session,
                    """
                    WITH batch AS (
                        SELECT se.id
                        FROM ip.simulator_entities AS se
                        WHERE NOT EXISTS (
                            SELECT 1 FROM ip.connections AS c WHERE c.id = se.connection_id
                        )
                        LIMIT :batch_size
                        FOR UPDATE SKIP LOCKED
                    )
                    DELETE FROM ip.simulator_entities AS target
                    USING batch
                    WHERE target.id = batch.id
                    RETURNING target.id;
                    """,
                )

                await session.execute(
                    text("""
                    DO $$
                    BEGIN
                        IF NOT EXISTS (
                            SELECT 1
                            FROM pg_constraint c
                            JOIN pg_class rel ON rel.oid = c.conrelid
                            JOIN pg_namespace n ON n.oid = rel.relnamespace
                            WHERE n.nspname = 'ip'
                              AND rel.relname = 'simulator_entities'
                              AND c.contype = 'f'
                        ) THEN
                            ALTER TABLE ip.simulator_entities
                                ADD CONSTRAINT fk_ip_simulator_entities_connection_id
                                FOREIGN KEY (connection_id)
                                REFERENCES ip.connections(id)
                                ON DELETE CASCADE;
                        END IF;
                    END $$;
                    """)
                )
                await session.execute(
                    text(
                        "ALTER TABLE ip.simulator_entities ALTER COLUMN cursor_field DROP DEFAULT;"
                    )
                )
                await session.execute(
                    text("DROP INDEX IF EXISTS ip.idx_ip_simulator_entities_tenant_sandbox;")
                )
                await session.execute(
                    text(
                        "CREATE INDEX IF NOT EXISTS idx_ip_simulator_entities_tenant_conn ON ip.simulator_entities (tenant_id, connection_id);"
                    )
                )
                await session.commit()

                await _execute_chunked_mutation(
                    session,
                    """
                    WITH batch AS (
                        SELECT id
                        FROM ip.connections
                        WHERE public_config ? 'streams'
                        LIMIT :batch_size
                        FOR UPDATE SKIP LOCKED
                    )
                    UPDATE ip.connections AS target
                    SET public_config = target.public_config - 'streams'
                    FROM batch
                    WHERE target.id = batch.id
                    RETURNING target.id;
                    """,
                )

                await session.execute(
                    text("""
                    DO $$
                    BEGIN
                        IF to_regclass('ip.alembic_version') IS NOT NULL
                           AND to_regclass('ip.connections') IS NOT NULL THEN
                            INSERT INTO ip.alembic_version (version_num)
                            SELECT '0001_initial_global_schema'
                            WHERE EXISTS (
                                SELECT 1 FROM ip.alembic_version
                                WHERE version_num = '0001_universal_simulator_schema'
                            )
                            ON CONFLICT (version_num) DO NOTHING;
                        END IF;
                    END $$;
                    """)
                )
                await session.commit()

            # 2. Platform Domain: Identity capabilities & RBAC
            if target in ("all", "platform", "identity"):
                logger.info("ensuring_identity_capabilities_table")
                await session.execute(
                    text("""
                    CREATE TABLE IF NOT EXISTS identity.capabilities (
                        code VARCHAR(128) NOT NULL PRIMARY KEY,
                        domain VARCHAR(64) NOT NULL,
                        resource VARCHAR(64) NOT NULL,
                        action VARCHAR(32) NOT NULL,
                        display_name VARCHAR(255) NOT NULL,
                        description VARCHAR(1024) NOT NULL,
                        is_sensitive BOOLEAN NOT NULL DEFAULT FALSE,
                        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                    );
                    """)
                )
                await session.execute(
                    text(
                        "CREATE INDEX IF NOT EXISTS ix_identity_capabilities_domain ON identity.capabilities (domain)"
                    )
                )
                await session.execute(
                    text(
                        "CREATE INDEX IF NOT EXISTS ix_capabilities_domain_resource ON identity.capabilities (domain, resource)"
                    )
                )

                # Seed capabilities
                logger.info("seeding_identity_capabilities")
                await session.execute(
                    text("""
                    INSERT INTO identity.capabilities (code, domain, resource, action, display_name, description, is_sensitive, created_at, updated_at)
                    VALUES
                        ('platform:admin', 'platform', 'platform', 'admin', 'Platform Administration', 'Full administrative control over the entire platform.', TRUE, NOW(), NOW()),
                        ('tenant:admin', 'tenant', 'tenant', 'admin', 'Tenant Administration', 'Full administrative control over a specific tenant.', TRUE, NOW(), NOW()),
                        ('tenant_settings:read', 'tenant', 'settings', 'read', 'View Tenant Settings', 'View configuration and general settings for the tenant.', FALSE, NOW(), NOW()),
                        ('tenant_settings:write', 'tenant', 'settings', 'write', 'Manage Tenant Settings', 'Update configuration and general settings for the tenant.', FALSE, NOW(), NOW()),
                        ('users:read', 'identity', 'users', 'read', 'View Users', 'View user accounts and tenant memberships.', FALSE, NOW(), NOW()),
                        ('users:write', 'identity', 'users', 'write', 'Manage Users', 'Create, update, or deactivate tenant users.', FALSE, NOW(), NOW()),
                        ('roles:read', 'identity', 'roles', 'read', 'View Roles', 'View system and custom roles and their assigned capabilities.', FALSE, NOW(), NOW()),
                        ('roles:write', 'identity', 'roles', 'write', 'Manage Roles', 'Create, modify, and assign custom roles.', FALSE, NOW(), NOW()),
                        ('api_keys:read', 'identity', 'api_keys', 'read', 'View API Keys', 'Inspect configured API keys and tokens.', FALSE, NOW(), NOW()),
                        ('api_keys:write', 'identity', 'api_keys', 'write', 'Manage API Keys', 'Generate or revoke API keys and tokens.', TRUE, NOW(), NOW()),
                        ('webhooks:read', 'integration', 'webhooks', 'read', 'View Webhooks', 'View outgoing webhook subscriptions and delivery logs.', FALSE, NOW(), NOW()),
                        ('webhooks:write', 'integration', 'webhooks', 'write', 'Manage Webhooks', 'Configure webhook endpoints and subscriptions.', FALSE, NOW(), NOW()),
                        ('invoices:read', 'billing', 'invoices', 'read', 'View Invoices', 'View billing invoices and payment receipts.', FALSE, NOW(), NOW()),
                        ('invoices:write', 'billing', 'invoices', 'write', 'Manage Invoices', 'Update billing and invoice settings.', FALSE, NOW(), NOW()),
                        ('ip:records:canonical:read', 'ip', 'records:canonical', 'read', 'View Canonical Records (L3) & GEM', 'View business-ready normalized data and global entity identity crosswalks.', FALSE, NOW(), NOW()),
                        ('ip:records:raw:read', 'ip', 'records:raw', 'read', 'View Raw Wire (L1) & Staging (L2)', 'Inspect raw incoming payload streams and universal staging replicas.', TRUE, NOW(), NOW()),
                        ('ip:traces:read', 'ip', 'traces', 'read', 'View Traces & Waterfalls', 'Inspect integration pipeline execution traces, waterfalls, and status logs.', FALSE, NOW(), NOW()),
                        ('ip:sync:trigger', 'ip', 'sync', 'execute', 'Trigger Batch Sync', 'Execute on-demand batch synchronization jobs between external apps and canonical models.', FALSE, NOW(), NOW()),
                        ('ip:flows:read', 'ip', 'flows', 'read', 'View Integration Flows', 'View integration flow diagrams, stages, and transformations.', FALSE, NOW(), NOW()),
                        ('ip:flows:write', 'ip', 'flows', 'write', 'Manage Integration Flows', 'Author, edit, and publish integration flow pipelines.', FALSE, NOW(), NOW()),
                        ('ip:flows:execute', 'ip', 'flows', 'execute', 'Execute Integration Flows', 'Manually trigger execution runs of integration flows.', FALSE, NOW(), NOW())
                    ON CONFLICT (code) DO UPDATE SET
                        display_name = EXCLUDED.display_name,
                        description = EXCLUDED.description,
                        is_sensitive = EXCLUDED.is_sensitive,
                        updated_at = NOW();
                    """)
                )

                # Roles with CustomerSupport and Customer, plus updated Viewer role
                logger.info("upserting_identity_roles")
                await session.execute(
                    text("""
                    INSERT INTO identity.roles (id, tenant_id, name, description, capabilities, created_at, updated_at)
                    VALUES
                        ('rol_1d55e88863640224', 'ten_000000000000000000000000', 'Viewer', 'Read-only access to a specific tenant.', ARRAY['tenant_settings:read', 'users:read', 'roles:read', 'api_keys:read', 'webhooks:read', 'invoices:read', 'ip:records:canonical:read', 'ip:traces:read'], NOW(), NOW()),
                        ('rol_c58e771032bf4aa1', 'ten_000000000000000000000000', 'CustomerSupport', 'Customer Support with diagnostic access including L1, L2, L3 records and Traces.', ARRAY['ip:records:canonical:read', 'ip:records:raw:read', 'ip:traces:read', 'ip:sync:trigger', 'ip:flows:read'], NOW(), NOW()),
                        ('rol_e93f882143cc5bb2', 'ten_000000000000000000000000', 'Customer', 'Customer role with restricted view (L3 normalized data, GEM crosswalk, and Traces only).', ARRAY['ip:records:canonical:read', 'ip:traces:read', 'ip:flows:read'], NOW(), NOW())
                    ON CONFLICT (tenant_id, name) DO UPDATE SET
                        description = EXCLUDED.description,
                        capabilities = EXCLUDED.capabilities,
                        updated_at = NOW();
                    """)
                )
                await _reconcile_ucp_cellular_sharding(session)

            await session.commit()
            if target in ("all", "ip"):
                shard_urls = await resolve_ip_shard_urls(
                    settings.global_url,
                    settings,
                    os.environ,
                )
                for shard_url in shard_urls:
                    await _reconcile_ip_shard(shard_url)
                logger.info("ip_schema_reconciled", shards_reconciled=len(shard_urls))
            if target in ("all", "platform", "identity"):
                logger.info("platform_schema_reconciled")
            logger.info("reconcile_schema_drift_completed_successfully", domain=target)
    finally:
        await provider.close()


def _parse_cli_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Reconcile database schema drift for amended single migrations."
    )
    parser.add_argument(
        "--domain",
        default="all",
        type=lambda raw: raw.strip().lower(),
        choices=SUPPORTED_RECONCILE_DOMAINS,
        help="Target bounded context to reconcile (default: all)",
    )
    parser.add_argument(
        "--skip-dotenv",
        action="store_true",
        help="Do not load .env / SOOPA_ENV_FILE from disk; rely strictly on process environment",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> None:
    args = _parse_cli_args(argv)
    asyncio.run(reconcile(domain=args.domain, skip_dotenv=args.skip_dotenv))


if __name__ == "__main__":
    main()
