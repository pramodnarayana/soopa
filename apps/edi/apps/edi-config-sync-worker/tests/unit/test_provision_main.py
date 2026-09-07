from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, Mock

import pytest

from config_sync_worker.provision import main as provision_main


@pytest.mark.asyncio
async def test_main_starts_and_stops_outbox_relay(monkeypatch: Any) -> None:
    lifecycle: list[str] = []
    captured: dict[str, Any] = {}

    settings = SimpleNamespace(
        database=SimpleNamespace(global_url="postgresql+asyncpg://db/soopa"),
        aws=SimpleNamespace(
            sns_topic_arn="arn:aws:sns:us-east-1:000000000000:edi-events.fifo",
            resolved_region="us-east-1",
            endpoint_url="http://localstack:4566",
        ),
        sqs=SimpleNamespace(
            provisioning_queue_url="http://localstack:4566/000000000000/provisioning"
        ),
    )

    db_router = Mock()
    db_router.close_all = AsyncMock(side_effect=lambda: lifecycle.append("database_stopped"))
    sqs_manager = Mock(task=None)
    sqs_manager.start.side_effect = lambda: lifecycle.append("sqs_started")
    sqs_manager.stop = AsyncMock(side_effect=lambda: lifecycle.append("sqs_stopped"))
    outbox_relay = Mock()
    outbox_relay.start.side_effect = lambda: lifecycle.append("relay_started")
    outbox_relay.stop = AsyncMock(side_effect=lambda: lifecycle.append("relay_stopped"))
    dispatcher = SimpleNamespace(dispatch_raw=AsyncMock())
    signal_loop = Mock()
    signal_loop.add_signal_handler.side_effect = lambda _signal, callback: callback()

    monkeypatch.setattr(provision_main, "get_settings", lambda: settings)
    monkeypatch.setattr(
        provision_main,
        "DatabaseRouter",
        lambda global_db_url: (
            captured.__setitem__("database_url", global_db_url),
            db_router,
        )[1],
    )
    monkeypatch.setattr(provision_main, "SqlAlchemyTenantAdapter", lambda _router: object())
    monkeypatch.setattr(
        provision_main,
        "SqlAlchemyReplicationAdapter",
        lambda _router, _tenant_adapter: object(),
    )
    monkeypatch.setattr(provision_main, "ProvisioningWorkerService", lambda *_args: object())
    monkeypatch.setattr(provision_main, "DefaultEventTranslator", lambda: object())
    monkeypatch.setattr(
        provision_main,
        "EdiConfigSyncSqsDispatcher",
        lambda **_kwargs: dispatcher,
    )
    monkeypatch.setattr(provision_main, "AwsSqsConsumer", lambda **_kwargs: object())
    monkeypatch.setattr(
        provision_main,
        "SqsConsumerManager",
        lambda **kwargs: (captured.__setitem__("sqs_manager", kwargs), sqs_manager)[1],
    )
    monkeypatch.setattr(
        provision_main,
        "PostgresEdiControlPlaneOutboxRepository",
        lambda router: ("repository", router),
    )
    monkeypatch.setattr(
        provision_main,
        "AwsSnsPublisher",
        lambda **kwargs: captured.setdefault("outbox_publisher", kwargs),
    )
    monkeypatch.setattr(
        provision_main,
        "OutboxProcessorUseCase",
        lambda **kwargs: captured.setdefault("outbox_processor", kwargs),
    )
    monkeypatch.setattr(
        provision_main,
        "PostgresOutboxRelay",
        lambda **kwargs: (captured.__setitem__("outbox_relay", kwargs), outbox_relay)[1],
    )
    monkeypatch.setattr(provision_main.asyncio, "get_running_loop", lambda: signal_loop)

    await provision_main.main()

    assert captured["database_url"] == settings.database.global_url
    assert captured["outbox_publisher"] == {
        "topic_arn": settings.aws.sns_topic_arn,
        "region_name": settings.aws.resolved_region,
        "endpoint_url": settings.aws.endpoint_url,
    }
    assert captured["outbox_processor"]["worker_id"] == "edi_config_sync_worker"
    assert captured["outbox_relay"]["database_url"] == settings.database.global_url
    assert captured["outbox_relay"]["listen_channel"] == "edi_outbox_channel"
    assert lifecycle == [
        "sqs_started",
        "relay_started",
        "relay_stopped",
        "sqs_stopped",
        "database_stopped",
    ]
