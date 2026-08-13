import os
import uuid
from collections.abc import AsyncGenerator
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from database.connection import DatabaseRouter
from platform_orm.models.identity import Tenant
from sqlalchemy import select
from sqlalchemy.engine.url import make_url
from ucp_models.infrastructure import DatabaseShard, ShardRegistry
from ucp_models.subscriptions import App

from worker.adapters.sqs_poller import poll_sqs_queue
from worker.core.security import validate_target_url
from worker.core.tenant_resolver import TenantResolver
from worker.data.handlers import process_pipeline_event

raw_global_url = os.getenv(
    "DATABASE_URL", "postgresql://ucp_admin:ucp_password@localhost:5432/ucp_global"
)
parsed_global_url = make_url(raw_global_url).set(drivername="postgresql+asyncpg")
GLOBAL_DB_URL = os.getenv("DB_GLOBAL_URL", parsed_global_url.render_as_string(hide_password=False))

raw_shard_1_url = os.getenv(
    "SHARD_1_URL", "postgresql://edi:edi_password@localhost:5433/edi_shard_1"
)
parsed_shard_1_url = make_url(raw_shard_1_url).set(drivername="postgresql+asyncpg")
SHARD_1_URL = os.getenv("DB_SHARD_1_URL", parsed_shard_1_url.render_as_string(hide_password=False))


def test_validate_target_url(monkeypatch: MagicMock) -> None:
    import worker.core.security

    monkeypatch.setattr(worker.core.security, "IS_DEV", False)

    def mock_getaddrinfo(host: str, *args: Any, **kwargs: Any) -> list[tuple[None, None, None, None, tuple[str, int]]]:
        if host == "example.com":
            return [(None, None, None, None, ("93.184.216.34", 80))]
        return [(None, None, None, None, (host, 80))]

    with patch("socket.getaddrinfo", side_effect=mock_getaddrinfo):
        assert validate_target_url("http://example.com") is True
        assert validate_target_url("http://127.0.0.1") is False
        assert validate_target_url("ftp://example.com") is False
        assert validate_target_url("http://") is False
        assert validate_target_url("http://192.168.1.1") is False
        assert validate_target_url("http://10.0.0.1") is False

    with patch("socket.getaddrinfo", side_effect=Exception("mock err")):
        assert validate_target_url("http://example.com") is False


@pytest.fixture
async def router() -> "AsyncGenerator[DatabaseRouter, None]":
    db_router = DatabaseRouter(GLOBAL_DB_URL, pool_size=2, max_overflow=2)
    yield db_router
    await db_router.close_all()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_process_pipeline_event_no_message(router: DatabaseRouter) -> None:
    # Setup TenantResolver double (since we don't want to seed global DB for this simple test)
    resolver = AsyncMock()
    resolver.resolve.return_value = ("shard_1", SHARD_1_URL)

    # Executing process_pipeline_event with a trace_id that doesn't exist
    # It will connect to the real test DB (shard_1), try to fetch the message, and fail.
    with pytest.raises(Exception, match=""):
        await process_pipeline_event(
            trace_id="nonexistent-trace-id",
            event_type="INBOUND",
            payload={"direction": "INBOUND"},
            tenant_id="999",
            resolver=resolver,
            db_router=router,
            s3_bucket="test-bucket",
            aws_endpoint=None,
        )


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.integration
async def test_tenant_resolver_integration(router: DatabaseRouter) -> None:
    """
    Real narrow integration test. Connects to the database and tests real behavior.
    """
    global_gen = router.get_global_session()
    global_session = await global_gen.__anext__()

    suffix = str(uuid.uuid4())[:8]
    shard_name = f"test_shard_{suffix}"
    tenant_name = f"Test Tenant_{suffix}"

    # 1. Insert a shard and a tenant into the real DB
    shard = DatabaseShard(id=f"shd_{suffix}", name=shard_name, dsn=SHARD_1_URL)
    global_session.add(shard)
    await global_session.commit()

    tenant = Tenant(id=f"ten_{suffix}", name=tenant_name, idp_tenant_id=f"idp_{suffix}")
    global_session.add(tenant)
    await global_session.commit()

    app_res = await global_session.execute(select(App).where(App.slug == "edi"))
    edi_app = app_res.scalars().first()
    created_edi_app = False
    if not edi_app:
        created_edi_app = True
        edi_app = App(id=f"app_{suffix}", name="EDI", slug="edi")
        global_session.add(edi_app)
        await global_session.commit()

    tenant_shard = ShardRegistry(
        tenant_id=tenant.id,
        app_id=edi_app.id,
        shard_id=shard.id,
    )
    global_session.add(tenant_shard)
    await global_session.commit()

    tenant_id = tenant.id
    await global_gen.aclose()

    # 2. Use the resolver
    resolver = TenantResolver(db_router=router, ttl_secs=300)

    try:
        # Resolving once should hit DB
        resolved_shard_name, shard_dsn = await resolver.resolve(tenant_id)
        assert resolved_shard_name == shard_name
        assert shard_dsn == SHARD_1_URL

        # Resolving again should hit cache
        resolved_shard_name2, _shard_dsn2 = await resolver.resolve(tenant_id)
        assert resolved_shard_name2 == shard_name
    finally:
        # Cleanup
        global_gen2 = router.get_global_session()
        global_session2 = await global_gen2.__anext__()

        app_res = await global_session2.execute(select(App).where(App.slug == "edi"))
        edi_app = app_res.scalars().first()
        assert edi_app is not None

        tenant_shard_to_delete = await global_session2.get(ShardRegistry, (tenant_id, edi_app.id))
        if tenant_shard_to_delete:
            await global_session2.delete(tenant_shard_to_delete)
            await global_session2.flush()

        if created_edi_app:
            app_to_delete = await global_session2.get(App, edi_app.id)
            if app_to_delete:
                await global_session2.delete(app_to_delete)
                await global_session2.flush()

        tenant_to_delete = await global_session2.get(Tenant, tenant_id)
        if tenant_to_delete:
            await global_session2.delete(tenant_to_delete)
            await global_session2.flush()

        shard_to_delete = await global_session2.get(DatabaseShard, shard.id)
        if shard_to_delete:
            await global_session2.delete(shard_to_delete)

        await global_session2.commit()
        await global_gen2.aclose()


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.integration
async def test_tenant_resolver_not_found(router: DatabaseRouter) -> None:
    """
    Test TenantResolver when a tenant is not found in the live DB.
    """
    resolver = TenantResolver(db_router=router, ttl_secs=300)
    with pytest.raises(ValueError, match="Tenant -999 not found in Global DB"):
        await resolver.resolve("-999")


async def test_process_delivery_no_message(router: DatabaseRouter) -> None:
    from worker.data.handlers import process_delivery

    resolver = AsyncMock()
    resolver.resolve.return_value = ("shard_1", SHARD_1_URL)

    with pytest.raises(Exception, match=""):
        await process_delivery(
            trace_id="nonexistent-trace-id",
            event_type="DELIVER",
            payload={},
            tenant_id="999",
            resolver=resolver,
            db_router=router,
            s3_bucket="test-bucket",
            aws_endpoint=None,
        )


@pytest.mark.asyncio
async def test_poll_sqs_queue() -> None:
    # Test the infrastructure polling loop.
    # We mock aioboto3 to return 1 message, then raise ValueError to break the infinite loop.
    mock_sqs = AsyncMock()
    mock_sqs.get_queue_url.return_value = {"QueueUrl": "http://queue"}

    # We yield one valid message, then one poison pill, then an exception to exit
    mock_sqs.receive_message.side_effect = [
        {
            "Messages": [
                {
                    "ReceiptHandle": "1",
                    "Body": '{"payload": {"trace_id": "123"}, "tenant_id": "999"}',
                }
            ]
        },
        {"Messages": [{"ReceiptHandle": "2", "Body": "not json"}]},
        {"Messages": [{"ReceiptHandle": "3", "Body": '{"payload": {}, "tenant_id": null}'}]},
        ValueError("stop loop"),
    ]

    class MockClientContext:
        async def __aenter__(self) -> Any:
            return mock_sqs

        async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
            pass

    mock_session = MagicMock()
    mock_session.client.return_value = MockClientContext()

    mock_processor = AsyncMock()

    with (
        patch("worker.adapters.sqs_poller.aioboto3.Session", return_value=mock_session),
        patch(
            "worker.adapters.sqs_poller.asyncio.sleep",
            side_effect=Exception("Break out of retry loop"),
        ),
    ):
        try:
            await poll_sqs_queue(
                "test-queue",
                processor_func=mock_processor,
                aws_endpoint=None,
            )
        except Exception as e:
            if str(e) != "Break out of retry loop":
                raise

    # Ensure processor was called for both valid and poison message (since validation moved to main.py wrappers)
    assert mock_processor.call_count == 2
    assert mock_processor.call_args_list[0][0][0]["payload"]["trace_id"] == "123"

    # Ensure all 3 messages were deleted (1 success, 2 poison)
    assert mock_sqs.delete_message.call_count == 3


@pytest.mark.asyncio
@pytest.mark.integration
async def test_main_execution_loop() -> None:
    from worker.data.main import main

    with (
        patch("worker.data.main.asyncio.create_task") as mock_create_task,
        patch("worker.data.main.asyncio.gather", new_callable=AsyncMock) as mock_gather,
        patch("worker.data.main.DatabaseRouter"),
        patch("worker.data.main.TenantResolver"),
        patch("worker.data.main.SqsPublisherAdapter"),
        patch("worker.data.main.poll_sqs_queue", new_callable=AsyncMock),
    ):
        await main()

        assert mock_create_task.call_count >= 3
        mock_gather.assert_awaited()
