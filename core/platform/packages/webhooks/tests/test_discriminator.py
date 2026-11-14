"""Unit tests for the 3-Tier event discriminator resolution."""

from __future__ import annotations

from webhooks.receivers.guards.discriminator import resolve_event_discriminator


def test_tier1_header_discrimination() -> None:
    # X-Event-Type
    headers = {"X-Event-Type": "meter_readings.batch"}
    assert resolve_event_discriminator(headers, None, {}) == "meter_readings.batch"

    # ce-type (CloudEvents)
    headers = {"ce-type": "io.soopa.energy.reading"}
    assert resolve_event_discriminator(headers, None, {}) == "io.soopa.energy.reading"

    # X-Action
    headers = {"x-action": "disconnect.execute"}
    assert resolve_event_discriminator(headers, None, {}) == "disconnect.execute"

    # X-Command
    headers = {"X-Command": "historical_extract.request"}
    assert resolve_event_discriminator(headers, None, {}) == "historical_extract.request"


def test_tier2_body_discrimination() -> None:
    headers: dict[str, str] = {}

    # event_type field in body
    body = {"event_type": "billing_determinants"}
    assert resolve_event_discriminator(headers, body, {}) == "billing_determinants"

    # action field in body
    body = {"action": "sync_inventory"}
    assert resolve_event_discriminator(headers, body, {}) == "sync_inventory"

    # type field in body
    body = {"type": "customer.subscription.created"}
    assert resolve_event_discriminator(headers, body, {}) == "customer.subscription.created"

    # command field in body
    body = {"command": "recalculate_taxes"}
    assert resolve_event_discriminator(headers, body, {}) == "recalculate_taxes"


def test_tier3_query_param_discrimination() -> None:
    headers: dict[str, str] = {}
    body: dict[str, object] = {}

    # ?event=...
    query = {"event": "meter_drop"}
    assert resolve_event_discriminator(headers, body, query) == "meter_drop"

    # ?action=...
    query = {"action": "bulk_upload"}
    assert resolve_event_discriminator(headers, body, query) == "bulk_upload"


def test_tier_precedence_order() -> None:
    # Tier 1 beats Tier 2 and Tier 3
    headers = {"X-Event-Type": "tier1_event"}
    body = {"event_type": "tier2_event"}
    query = {"event": "tier3_event"}
    assert resolve_event_discriminator(headers, body, query) == "tier1_event"

    # Tier 2 beats Tier 3
    assert resolve_event_discriminator({}, body, query) == "tier2_event"

    # Tier 3 evaluates when Tier 1 & 2 absent
    assert resolve_event_discriminator({}, {}, query) == "tier3_event"


def test_fallback_to_none_for_wildcard() -> None:
    assert resolve_event_discriminator({}, None, {}) is None
    assert resolve_event_discriminator({"content-type": "application/json"}, {}, {}) is None
