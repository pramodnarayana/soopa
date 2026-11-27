"""Zero-AWS, SAVEPOINT-isolated integration tests for EDI Queue-Free HTTPS Dynamic Watch."""

from __future__ import annotations

from contextlib import aclosing
from datetime import UTC, datetime

import httpx
import pytest
from config_sync.adapters.inbound.fastapi_watch_router import create_config_sync_router
from config_sync.domain.enums import ConfigChangeAction
from config_sync.provider import ConfigSyncProvider
from database.models.identity import Tenant
from database.router import DatabaseRouterPort
from edi.adapters.outbound.config_sync.edi_config_catalog_provider import (
    EdiConfigCatalogProvider,
)
from edi.adapters.outbound.config_sync.edi_shard_config_sink import EdiShardConfigSink
from edi.adapters.outbound.database.models import control_plane, data_plane
from edi.adapters.outbound.database.tenant_resolver import SqlAlchemyTenantResolver
from edi.domain.constants import EdiIdPrefix
from edi.domain.enums import EDI_CONFIG_APP_ID
from fastapi import FastAPI
from identity.domain.identity_context import PLATFORM_TENANT_ID
from seedwork import generate_id
from seedwork.domain.types import JsonDict
from sqlalchemy import select
from ucp.domain.constants import LifecycleStatus
from ucp_models.sharding import DatabaseShard, ShardRegistry
from ucp_models.subscriptions import App

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


@pytest.mark.integration
async def test_edi_dynamic_watch_syncs_topological_and_shared_platform_entities_to_shard(
    test_db_router: DatabaseRouterPort,
) -> None:
    """Proves EDI Control Plane -> SSE Watch -> EdiShardConfigSink replicates topological & shared rows."""
    tenant_id = f"ten_edi_dw_{generate_id('t')}"
    local_partner_id = generate_id(EdiIdPrefix.EDI_AS2_PARTNER.value)
    remote_partner_id = generate_id(EdiIdPrefix.EDI_AS2_PARTNER.value)
    partnership_id = generate_id(EdiIdPrefix.EDI_AS2_PARTNERSHIP.value)

    # 1. Seed Tenant, EDI Shard Registration, Shared PLATFORM_TENANT_ID Partner, Tenant Partner, and Child Partnership
    async with test_db_router.global_session_scope() as session:
        edi_app = (await session.execute(select(App).where(App.slug == "edi"))).scalar_one_or_none()
        if edi_app is None:
            edi_app = App(
                id="app_edi_core",
                slug="edi",
                name="EDI",
                description="EDI Gateway",
            )
            session.add(edi_app)
            await session.flush()

        shard = (await session.execute(select(DatabaseShard).limit(1))).scalar_one_or_none()
        assert shard is not None, "Expected at least one seeded test DatabaseShard"

        session.add(
            Tenant(
                id=tenant_id,
                name="EDI Watch Tenant",
                slug=f"edi-watch-{tenant_id}",
                status=LifecycleStatus.ACTIVE.value,
            )
        )
        await session.flush()
        session.add(
            ShardRegistry(
                tenant_id=tenant_id,
                app_id=edi_app.id,
                shard_id=shard.id,
            )
        )

        now = datetime.now(UTC)
        # Shared platform AS2 partner (PLATFORM_TENANT_ID) + tenant remote partner + child partnership FK
        session.add(
            control_plane.AS2Partner(
                id=local_partner_id,
                tenant_id=PLATFORM_TENANT_ID,
                name="Soopa Shared Hub",
                as2_id=f"SOOPA_HUB_{local_partner_id}",
                is_local=True,
                active=True,
                created_at=now,
                updated_at=now,
            )
        )
        session.add(
            control_plane.AS2Partner(
                id=remote_partner_id,
                tenant_id=tenant_id,
                name="Acme Partner",
                as2_id=f"ACME_{remote_partner_id}",
                url="https://as2.acme.example/receive",
                is_local=False,
                active=True,
                created_at=now,
                updated_at=now,
            )
        )
        await session.flush()
        session.add(
            control_plane.AS2Partnership(
                id=partnership_id,
                tenant_id=tenant_id,
                name="Soopa <-> Acme",
                local_partner_id=local_partner_id,
                remote_partner_id=remote_partner_id,
                active=True,
                created_at=now,
                updated_at=now,
            )
        )
        await session.commit()

    # 2. Wire Universal Watch Gateway with PLATFORM_TENANT_ID included in shared_tenant_ids
    shared_tenants: tuple[str, ...] = (PLATFORM_TENANT_ID,)
    changelog_repo = ConfigSyncProvider.create_changelog_repository(
        session_factory=test_db_router.global_session_scope,
        shared_tenant_ids=shared_tenants,
    )
    edi_provider = EdiConfigCatalogProvider(
        session_factory=test_db_router.global_session_scope,
        changelog_repo=changelog_repo,
    )
    broadcaster = ConfigSyncProvider.create_broadcaster(
        broadcast_tenant_ids=shared_tenants,
    )
    stream_uc = ConfigSyncProvider.create_stream_use_case(
        providers=[edi_provider],
        broadcaster=broadcaster,
    )
    app = FastAPI()
    app.include_router(
        create_config_sync_router(
            use_case_provider=lambda: stream_uc,
            internal_bearer_token="edi-watch-test-token",
        )
    )
    transport = httpx.ASGITransport(app=app)
    watch_client = ConfigSyncProvider.create_sse_watch_client(
        base_url="http://edi-watch.internal",
        bearer_token="edi-watch-test-token",
        http_transport=transport,
    )
    tenant_resolver = SqlAlchemyTenantResolver(test_db_router)
    sink = EdiShardConfigSink(
        db_router=test_db_router,
        tenant_port=tenant_resolver,
        tenant_id=tenant_id,
    )

    # 3. Cold-start snapshot fetch & topological upsert into real EDI Tenant Shard DB
    snap_res = await watch_client.fetch_snapshot(app_id=EDI_CONFIG_APP_ID, tenant_id=tenant_id)
    assert snap_res.is_ok
    await sink.apply_snapshot(snap_res.unwrap())

    shard_name, shard_dsn = await tenant_resolver.resolve_shard(tenant_id)
    async with aclosing(test_db_router.get_tenant_session(tenant_id, shard_name, shard_dsn)) as gen:
        dp_session = await gen.__anext__()
        dp_local = await dp_session.get(data_plane.AS2Partner, local_partner_id)
        dp_remote = await dp_session.get(data_plane.AS2Partner, remote_partner_id)
        dp_partnership = await dp_session.get(data_plane.AS2Partnership, partnership_id)
        assert dp_local is not None and dp_local.tenant_id == PLATFORM_TENANT_ID
        assert dp_remote is not None and dp_remote.name == "Acme Partner"
        assert dp_partnership is not None and dp_partnership.remote_partner_id == remote_partner_id

    # 4. Shared PLATFORM_TENANT_ID delta mutation fans out to tenant_id catch-up & updates shard DB!
    updated_payload: JsonDict = {
        "id": local_partner_id,
        "tenant_id": PLATFORM_TENANT_ID,
        "name": "Soopa Shared Hub v2",
        "as2_id": f"SOOPA_HUB_{local_partner_id}",
        "is_local": True,
        "active": True,
    }
    shared_delta = await changelog_repo.append_change(
        app_id=EDI_CONFIG_APP_ID,
        tenant_id=PLATFORM_TENANT_ID,
        entity_type="as2_partner",
        entity_id=local_partner_id,
        action=ConfigChangeAction.UPSERT,
        payload=updated_payload,
    )
    tenant_deltas = await edi_provider.get_deltas_since(
        tenant_id=tenant_id,
        since_cursor=snap_res.unwrap().cursor,
    )
    assert any(d.version == shared_delta.version for d in tenant_deltas)

    await sink.apply_delta(shared_delta)

    async with aclosing(test_db_router.get_tenant_session(tenant_id, shard_name, shard_dsn)) as gen:
        dp_session = await gen.__anext__()
        refreshed_local = await dp_session.get(data_plane.AS2Partner, local_partner_id)
        assert refreshed_local is not None
        assert refreshed_local.name == "Soopa Shared Hub v2"
