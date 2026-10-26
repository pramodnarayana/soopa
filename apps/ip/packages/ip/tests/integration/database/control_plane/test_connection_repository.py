"""Narrow Integration Tests for SqlAlchemyConnectionRepository against real PostgreSQL."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from database.types import GlobalSession
from ip.engine.adapters.outbound.database.control_plane.connection_repository import (
    SqlAlchemyConnectionRepository,
)
from ip.engine.adapters.outbound.database.models.control_plane import IpOutboxRecord
from ip.engine.domain.enums import (
    AuthType,
    ConnectionStatus,
    IpEventType,
)
from ip.engine.domain.exceptions import DuplicateConnectionFingerprintError, IpErrorCode
from ip.engine.domain.models.connection import Connection
from sqlalchemy import select

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_connection_repository_save_query_and_outbox_draining(
    global_session: GlobalSession,
    seeded_ip_tenant: str,
) -> None:
    repo = SqlAlchemyConnectionRepository(global_session)

    conn = Connection.create(
        tenant_id=seeded_ip_tenant,
        app_id="itron_mdm",
        name="Primary Grid Itron",
        auth_type=AuthType.API_KEY,
        public_config={"endpoint_url": "https://ami.grid-utility.com"},
        encrypted_credentials=b"kid:k1:encrypted_payload",
        endpoint_for_fingerprint="https://ami.grid-utility.com",
    )

    save_res = await repo.save(conn)
    assert save_res.is_ok is True

    fetched = await repo.get_by_id(conn.id)
    assert fetched is not None
    assert fetched.id == conn.id
    assert fetched.tenant_id == seeded_ip_tenant
    assert fetched.name == "Primary Grid Itron"
    assert fetched.status == ConnectionStatus.PENDING_AUTH
    assert fetched.encrypted_credentials == b"kid:k1:encrypted_payload"

    by_fp = await repo.get_by_fingerprint(seeded_ip_tenant, conn.connection_fingerprint)
    assert by_fp is not None
    assert by_fp.id == conn.id

    outbox_stmt = select(IpOutboxRecord).where(
        IpOutboxRecord.tenant_id == seeded_ip_tenant,
        IpOutboxRecord.event_type == IpEventType.CONNECTION_CREATED.value,
    )
    outbox_rows = (await global_session.execute(outbox_stmt)).scalars().all()
    assert len(outbox_rows) == 1
    assert outbox_rows[0].payload["connection_id"] == conn.id


@pytest.mark.asyncio
async def test_connection_partial_unique_index_enforces_active_fingerprint_and_allows_deactivated_replacement(
    global_session: GlobalSession,
    seeded_ip_tenant: str,
) -> None:
    """Verifies PostgreSQL partial index `uq_tenant_active_fingerprint WHERE status != 'DEACTIVATED'`."""
    repo = SqlAlchemyConnectionRepository(global_session)

    conn_1 = Connection.create(
        tenant_id=seeded_ip_tenant,
        app_id="itron_mdm",
        name="Active Connection 1",
        auth_type=AuthType.API_KEY,
        public_config={"endpoint_url": "https://dup.grid-utility.com"},
        encrypted_credentials=b"secret1",
        endpoint_for_fingerprint="https://dup.grid-utility.com",
    )
    res_1 = await repo.save(conn_1)
    assert res_1.is_ok is True

    conn_dup = Connection.create(
        tenant_id=seeded_ip_tenant,
        app_id="itron_mdm",
        name="Duplicate Active Connection",
        auth_type=AuthType.API_KEY,
        public_config={"endpoint_url": "https://dup.grid-utility.com"},
        encrypted_credentials=b"secret2",
        endpoint_for_fingerprint="https://dup.grid-utility.com",
    )
    async with global_session.begin_nested():
        dup_res = await repo.save(conn_dup)
        assert dup_res.is_err is True
        assert isinstance(dup_res.error, DuplicateConnectionFingerprintError)
        assert dup_res.error.code == IpErrorCode.DUPLICATE_FINGERPRINT

    conn_1.deactivate()
    deact_res = await repo.save(conn_1)
    assert deact_res.is_ok is True

    conn_replacement = Connection.create(
        tenant_id=seeded_ip_tenant,
        app_id="itron_mdm",
        name="Replacement Active Connection",
        auth_type=AuthType.API_KEY,
        public_config={"endpoint_url": "https://dup.grid-utility.com"},
        encrypted_credentials=b"secret3",
        endpoint_for_fingerprint="https://dup.grid-utility.com",
    )
    rep_res = await repo.save(conn_replacement)
    assert rep_res.is_ok is True

    active_list = await repo.list_by_tenant(seeded_ip_tenant, status=ConnectionStatus.PENDING_AUTH)
    assert len(active_list) == 1
    assert active_list[0].id == conn_replacement.id


@pytest.mark.asyncio
async def test_connection_repository_get_by_id_for_update_and_update_tokens(
    global_session: GlobalSession,
    seeded_ip_tenant: str,
) -> None:
    """Verifies SELECT ... FOR UPDATE row locking and OAuth2 token rotation persistence."""
    repo = SqlAlchemyConnectionRepository(global_session)

    conn = Connection.create(
        tenant_id=seeded_ip_tenant,
        app_id="salesforce",
        name="Salesforce OAuth Connection",
        auth_type=AuthType.OAUTH2,
        public_config={"token_url": "https://login.salesforce.com/services/oauth2/token"},
        encrypted_credentials=b"kid:k1:initial_oauth_tokens",
        endpoint_for_fingerprint="https://login.salesforce.com",
    )
    save_res = await repo.save(conn)
    assert save_res.is_ok is True

    locked_conn = await repo.get_by_id_for_update(conn.id)
    assert locked_conn is not None
    assert locked_conn.id == conn.id

    new_expires = (datetime.now(tz=UTC) + timedelta(hours=2)).isoformat()
    locked_conn.update_tokens(
        encrypted_credentials=b"kid:k1:rotated_oauth_tokens",
        token_expires_at=new_expires,
    )
    rot_res = await repo.save(locked_conn)
    assert rot_res.is_ok is True

    reloaded = await repo.get_by_id(conn.id)
    assert reloaded is not None
    assert reloaded.encrypted_credentials == b"kid:k1:rotated_oauth_tokens"
    assert reloaded.token_expires_at == new_expires
    assert reloaded.last_refreshed_at is not None
