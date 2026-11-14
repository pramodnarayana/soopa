"""Unit tests for WebhookEndpoint aggregate root and WebhookEventRoute entity."""

from __future__ import annotations

from ip.engine.domain.webhook.endpoint import WebhookEndpoint
from ip.engine.domain.webhook.enums import PayloadSemantic, VerificationStrategy
from ip.engine.domain.webhook.events import (
    WebhookEndpointCreatedEvent,
    WebhookEndpointDeactivatedEvent,
    WebhookSecretRotatedEvent,
)
from ip.engine.domain.webhook.route import WebhookEventRoute


def test_create_webhook_endpoint_aggregate() -> None:
    endpoint = WebhookEndpoint.create(
        tenant_id="tenant_partner",
        endpoint_slug="partner-webhook",
        name="Partner Webhook",
        primary_secret_hash="whsec_12345",
        verification_strategy=VerificationStrategy.SHARED_HEADER_SECRET,
    )

    assert endpoint.id.startswith("ip_whk_")
    assert endpoint.endpoint_slug == "partner-webhook"
    assert endpoint.is_active is True
    assert endpoint.primary_secret_hash == "whsec_12345"
    assert endpoint.secondary_secret_hash is None

    events = endpoint.domain_events
    assert len(events) == 1
    assert isinstance(events[0], WebhookEndpointCreatedEvent)
    assert events[0].endpoint_slug == "partner-webhook"


def test_match_route_priority_with_patterns() -> None:
    endpoint = WebhookEndpoint.create(
        tenant_id="tenant_partner",
        endpoint_slug="partner-webhook",
        name="Partner Webhook",
        primary_secret_hash="sec",
    )

    route_command = WebhookEventRoute(
        id="ip_wrt_1",
        endpoint_id=endpoint.id,
        event_pattern="historical_extract.request",
        payload_semantic=PayloadSemantic.COMMAND,
        target_pipeline_or_workflow_id="command_pull_dag",
        priority=10,
    )
    route_data_prefix = WebhookEventRoute(
        id="ip_wrt_2",
        endpoint_id=endpoint.id,
        event_pattern="telemetry.*",
        payload_semantic=PayloadSemantic.DATA,
        target_pipeline_or_workflow_id="stream_pipeline",
        priority=50,
    )
    route_wildcard = WebhookEventRoute(
        id="ip_wrt_3",
        endpoint_id=endpoint.id,
        event_pattern="*",
        payload_semantic=PayloadSemantic.DATA,
        target_pipeline_or_workflow_id="default_pipeline",
        priority=999,
    )

    endpoint.add_event_route(route_command)
    endpoint.add_event_route(route_data_prefix)
    endpoint.add_event_route(route_wildcard)

    # 1. Exact match command
    m1 = endpoint.match_route("historical_extract.request")
    assert m1 is not None
    assert m1.id == "ip_wrt_1"
    assert m1.payload_semantic == PayloadSemantic.COMMAND

    # 2. Prefix wildcard match
    m2 = endpoint.match_route("telemetry.batch")
    assert m2 is not None
    assert m2.id == "ip_wrt_2"
    assert m2.payload_semantic == PayloadSemantic.DATA

    # 3. Fallback to default wildcard
    m3 = endpoint.match_route("unrecognized_event_type")
    assert m3 is not None
    assert m3.id == "ip_wrt_3"

    # 4. None discriminator matches wildcard
    m4 = endpoint.match_route(None)
    assert m4 is not None
    assert m4.id == "ip_wrt_3"


def test_rotate_secret_transitions_old_secret_to_secondary() -> None:
    endpoint = WebhookEndpoint.create(
        tenant_id="tenant_1",
        endpoint_slug="vendor-a",
        name="Vendor A",
        primary_secret_hash="initial_secret",
    )

    endpoint.rotate_secret("rotated_secret")

    assert endpoint.primary_secret_hash == "rotated_secret"
    assert endpoint.secondary_secret_hash == "initial_secret"
    assert endpoint.secret_rotated_at is not None

    events = [e for e in endpoint.domain_events if isinstance(e, WebhookSecretRotatedEvent)]
    assert len(events) == 1
    assert events[0].endpoint_id == endpoint.id


def test_deactivate_endpoint() -> None:
    endpoint = WebhookEndpoint.create(
        tenant_id="tenant_1",
        endpoint_slug="vendor-a",
        name="Vendor A",
        primary_secret_hash="initial_secret",
    )

    endpoint.deactivate()
    assert endpoint.is_active is False

    events = [e for e in endpoint.domain_events if isinstance(e, WebhookEndpointDeactivatedEvent)]
    assert len(events) == 1
