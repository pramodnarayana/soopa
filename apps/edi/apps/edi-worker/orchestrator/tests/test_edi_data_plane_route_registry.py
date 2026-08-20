from unittest.mock import AsyncMock, MagicMock

import pytest

from worker.adapters.inbound.workers.edi_data_plane_events_sqs_consumer import (
    EdiDataPlaneEventMessage,
)
from worker.core.edi_data_plane_route_registry import EdiDataPlaneRouteRegistry

pytestmark = pytest.mark.asyncio


async def test_route_registry_success() -> None:
    """Test that a registered route is successfully found and executed."""
    registry = EdiDataPlaneRouteRegistry()
    mock_factory = AsyncMock()

    # Register an INBOUND TRANSFORM_EVENT route
    registry.register("TRANSFORM_EVENT", "INBOUND", mock_factory)

    event = EdiDataPlaneEventMessage(
        trace_id="trace123",
        tenant_id="tenant123",
        event_type="TRANSFORM_EVENT",
        payload={"direction": "INBOUND"},
        idempotency_key=None,
    )
    mock_uow_factory = MagicMock()

    await registry.route(event, mock_uow_factory)

    mock_factory.assert_called_once_with(event, mock_uow_factory)


async def test_route_registry_fallback_to_none_direction() -> None:
    """Test that if a direction is provided but not specifically mapped, it falls back to None."""
    registry = EdiDataPlaneRouteRegistry()
    mock_factory = AsyncMock()

    # Register a generic DELIVER_EVENT route without direction
    registry.register("DELIVER_EVENT", None, mock_factory)

    event = EdiDataPlaneEventMessage(
        trace_id="trace123",
        tenant_id="tenant123",
        event_type="DELIVER_EVENT",
        payload={"direction": "OUTBOUND"},  # OUTBOUND is in the payload
        idempotency_key=None,
    )
    mock_uow_factory = MagicMock()

    await registry.route(event, mock_uow_factory)

    mock_factory.assert_called_once_with(event, mock_uow_factory)


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
    mock_uow_factory = MagicMock()

    with pytest.raises(ValueError, match="No route registered for UNKNOWN_EVENT None"):
        await registry.route(event, mock_uow_factory)
