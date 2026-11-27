"""Unit tests for UCP Jobs Worker container OutboxDrainRelay wiring."""

from __future__ import annotations

import pytest
from outbox.adapters.inbound.outbox_drain_relay import OutboxDrainRelay
from pubsub.config import PlatformPubSubSettings
from seedwork.infra.config_models import PlatformDatabaseSettings
from ucp.config.settings import AppSettings, SqsSettings, UcpAwsSettings
from ucp.domain.constants import UcpOutboxSource

from ucp_jobs_worker.bootstrap.container import WorkerContainer


@pytest.mark.asyncio
async def test_ucp_worker_container_wires_outbox_drain_relay() -> None:
    settings = AppSettings(
        database=PlatformDatabaseSettings(global_url="sqlite+aiosqlite:///:memory:"),
        aws=UcpAwsSettings(sns_tenant_events_topic_arn="db://platform-events-topic"),
        sqs=SqsSettings(
            ucp_identity_sync_queue_url="db://ucp-identity-sync-queue",
            ucp_jobs_queue_url="db://ucp-jobs-queue",
        ),
        pubsub=PlatformPubSubSettings(transport="db"),
    )
    container = WorkerContainer(settings)
    try:
        container.wire()
        assert isinstance(container.outbox_relay, OutboxDrainRelay)
        assert container.outbox_relay.relay_name == UcpOutboxSource.UCP.value
    finally:
        await container.dispose()
