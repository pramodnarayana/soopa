from collections.abc import Callable
from typing import Any

import structlog

from worker.adapters.inbound.workers.edi_data_plane_events_sqs_consumer import (
    EdiDataPlaneEventMessage,
)

logger = structlog.get_logger(__name__)


class EdiDataPlaneRouteRegistry:
    def __init__(self) -> None:
        self._registry: dict[tuple[str, str | None], Callable[..., Any]] = {}

    def register(self, event_type: str, direction: str | None, factory: Callable[..., Any]) -> None:
        """
        Registers a factory function to be called when an event matching the
        (event_type, direction) is routed.
        """
        self._registry[(event_type, direction)] = factory

    async def route(self, event: EdiDataPlaneEventMessage, uow_factory: Callable[..., Any]) -> None:
        """
        Looks up the registered factory and executes it.
        Raises ValueError if no matching route is found.
        """
        direction = event.payload.get("direction")
        key = (event.event_type, direction)

        # Fallback to a generic route if specific direction route doesn't exist
        if key not in self._registry:
            key = (event.event_type, None)

        factory = self._registry.get(key)
        if not factory:
            logger.error(
                "data_plane_route_registry.no_route_found",
                event_type=event.event_type,
                direction=direction,
                trace_id=event.trace_id,
                tenant_id=event.tenant_id,
            )
            raise ValueError(f"No route registered for {event.event_type} {direction}")

        await factory(event, uow_factory)
