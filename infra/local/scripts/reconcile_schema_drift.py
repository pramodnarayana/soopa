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

import structlog
from database.provider import DatabaseProvider
from seedwork.infra.config import load_repo_env, load_settings_safely
from seedwork.infra.config_models import PlatformDatabaseSettings
from sqlalchemy import text

logger = structlog.get_logger(__name__)


async def reconcile(domain: str = "all") -> None:
    """Applies missing DDL and initial reference data to eliminate schema drift."""
    load_repo_env(override=False)
    settings = load_settings_safely(PlatformDatabaseSettings)
    provider = DatabaseProvider.from_url(settings.global_url)
    target = domain.strip().lower()

    try:
        async with provider.session() as session:
            # 1. IP Domain: connection_stream_state
            if target in ("all", "ip"):
                table_check = await session.execute(
                    text("SELECT to_regclass('ip.connection_stream_state')")
                )
                plural_check = await session.execute(
                    text("SELECT to_regclass('ip.connection_stream_states')")
                )

                if table_check.scalar() is None:
                    if plural_check.scalar() is not None:
                        logger.info(
                            "renaming_table",
                            old_name="ip.connection_stream_states",
                            new_name="ip.connection_stream_state",
                        )
                        await session.execute(
                            text(
                                "ALTER TABLE ip.connection_stream_states RENAME TO connection_stream_state"
                            )
                        )
                    else:
                        logger.info("creating_table", table_name="ip.connection_stream_state")
                        await session.execute(
                            text("""
                            CREATE TABLE IF NOT EXISTS ip.connection_stream_state (
                                id VARCHAR(64) NOT NULL PRIMARY KEY,
                                tenant_id VARCHAR(64) NOT NULL,
                                connection_id VARCHAR(64) NOT NULL REFERENCES ip.connections(id) ON DELETE CASCADE,
                                stream_name VARCHAR(128) NOT NULL,
                                cursor_field VARCHAR(128),
                                cursor_value TEXT,
                                records_synced_count BIGINT NOT NULL DEFAULT 0,
                                last_synced_at TIMESTAMPTZ NOT NULL,
                                CONSTRAINT uq_ip_stream_state_tenant_conn_stream UNIQUE (tenant_id, connection_id, stream_name)
                            );
                            """)
                        )
                        await session.execute(
                            text(
                                "CREATE INDEX IF NOT EXISTS idx_ip_stream_state_conn ON ip.connection_stream_state (tenant_id, connection_id);"
                            )
                        )

                # Reconcile NO_AUTH connections to ACTIVE status
                conn_res = await session.execute(
                    text("""
                    UPDATE ip.connections
                    SET status = 'ACTIVE'
                    WHERE auth_type = 'NO_AUTH' AND status = 'PENDING_AUTH';
                    """)
                )
                if conn_res.rowcount and conn_res.rowcount > 0:
                    logger.info("reconciled_no_auth_connections", activated_count=conn_res.rowcount)

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

            await session.commit()
            if target in ("all", "ip"):
                logger.info("ip_schema_reconciled")
            if target in ("all", "platform", "identity"):
                logger.info("platform_schema_reconciled")
            logger.info("reconcile_schema_drift_completed_successfully", domain=target)
    finally:
        await provider.close()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Reconcile database schema drift for amended single migrations."
    )
    parser.add_argument(
        "--domain",
        default="all",
        choices=["all", "platform", "ip", "identity"],
        help="Target bounded context to reconcile (default: all)",
    )
    args = parser.parse_args()
    asyncio.run(reconcile(domain=args.domain))


if __name__ == "__main__":
    main()
