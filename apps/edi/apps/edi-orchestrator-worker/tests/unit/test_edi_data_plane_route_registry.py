from typing import Any

import pytest

from worker.adapters.inbound.workers.edi_data_plane_event_dispatcher import (
    EdiDataPlaneEventMessage,
)
from worker.domain.edi_data_plane_route_registry import EdiDataPlaneRouteRegistry

pytestmark = pytest.mark.asyncio


async def test_route_registry_success() -> None:
    """Test that a registered route is successfully found and executed."""
    registry = EdiDataPlaneRouteRegistry()

    events_routed = []

    async def real_factory(evt: EdiDataPlaneEventMessage, uow_fact: Any) -> None:
        events_routed.append((evt, uow_fact))

    # Register an INBOUND TRANSFORM_EVENT route
    registry.register("TRANSFORM_EVENT", "INBOUND", real_factory)

    event = EdiDataPlaneEventMessage(
        trace_id="trace123",
        tenant_id="tenant123",
        event_type="TRANSFORM_EVENT",
        payload={"direction": "INBOUND"},
        idempotency_key=None,
    )

    def real_uow_factory() -> None:
        pass

    await registry.route(event, real_uow_factory)

    assert len(events_routed) == 1
    assert events_routed[0][0] == event
    assert events_routed[0][1] == real_uow_factory


async def test_route_registry_fallback_to_none_direction() -> None:
    """Test that if a direction is provided but not specifically mapped, it falls back to None."""
    registry = EdiDataPlaneRouteRegistry()

    events_routed = []

    async def real_factory(evt: EdiDataPlaneEventMessage, uow_fact: Any) -> None:
        events_routed.append((evt, uow_fact))

    # Register a generic DELIVER_EVENT route without direction
    registry.register("DELIVER_EVENT", None, real_factory)

    event = EdiDataPlaneEventMessage(
        trace_id="trace123",
        tenant_id="tenant123",
        event_type="DELIVER_EVENT",
        payload={"direction": "OUTBOUND"},  # OUTBOUND is in the payload
        idempotency_key=None,
    )

    def real_uow_factory() -> None:
        pass

    await registry.route(event, real_uow_factory)

    assert len(events_routed) == 1
    assert events_routed[0][0] == event
    assert events_routed[0][1] == real_uow_factory


async def test_route_registry_no_route_found() -> None:
    """Test that routing an unregistered event raises a ValueError."""
    registry = EdiDataPlaneRouteRegistry()
    # empty registry

    event = EdiDataPlaneEventMessage(
        trace_id="trace123",
        tenant_id="tenant123",
        event_type="UNKNOWN_EVENT",
        payload={},
        idempotency_key=None,
    )

    def real_uow_factory() -> None:
        pass

    with pytest.raises(ValueError, match="No route registered for UNKNOWN_EVENT None"):
        await registry.route(event, real_uow_factory)
