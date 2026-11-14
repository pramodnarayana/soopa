"""Pure zero-mock Data Mapper unit tests for SqlAlchemyWebhookEndpointRepository."""

from __future__ import annotations

from datetime import UTC, datetime

from ip.engine.adapters.outbound.database.control_plane.webhook_endpoint_repository import (
    SqlAlchemyWebhookEndpointRepository,
)
from ip.engine.adapters.outbound.database.models.control_plane import (
    WebhookEndpointRecord,
    WebhookEventRouteRecord,
)
from ip.engine.domain.webhook.enums import PayloadSemantic, VerificationStrategy


def test_webhook_endpoint_record_to_domain_model_mapping() -> None:
    now = datetime.now(UTC)
    route_rec = WebhookEventRouteRecord(
        id="ip_wrt_01",
        endpoint_id="ip_whk_01",
        event_pattern="order.created",
        payload_semantic="DATA",
        target_pipeline_or_workflow_id="pipe_01",
        description="Order created route",
        priority=100,
        is_active=True,
        created_at=now,
    )
    rec = WebhookEndpointRecord(
        id="ip_whk_01",
        tenant_id="ten_01",
        endpoint_slug="partner-ingest",
        name="Partner Ingress",
        description="Passive partner push endpoint",
        verification_strategy="HMAC_SHA256",
        primary_secret_hash="hash_primary_123",
        secondary_secret_hash="hash_secondary_456",
        secret_rotated_at=now,
        bound_connection_id="ip_conn_01",
        is_active=True,
        created_at=now,
        updated_at=now,
        routes=[route_rec],
    )

    domain = SqlAlchemyWebhookEndpointRepository._to_domain_model(rec)

    assert domain.id == "ip_whk_01"
    assert domain.tenant_id == "ten_01"
    assert domain.endpoint_slug == "partner-ingest"
    assert domain.name == "Partner Ingress"
    assert domain.description == "Passive partner push endpoint"
    assert domain.verification_strategy == VerificationStrategy.HMAC_SHA256
    assert domain.primary_secret_hash == "hash_primary_123"
    assert domain.secondary_secret_hash == "hash_secondary_456"
    assert domain.secret_rotated_at == now.isoformat()
    assert domain.bound_connection_id == "ip_conn_01"
    assert domain.is_active is True
    assert len(domain.event_routes) == 1
    assert domain.event_routes[0].id == "ip_wrt_01"
    assert domain.event_routes[0].event_pattern == "order.created"
    assert domain.event_routes[0].payload_semantic == PayloadSemantic.DATA
    assert domain.event_routes[0].target_pipeline_or_workflow_id == "pipe_01"
