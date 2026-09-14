from collections.abc import Awaitable, Callable
from typing import Any, Protocol

from seedwork.domain.types import JsonDict


class RoutableEvent(Protocol):
    """Structural protocol satisfied by EventEnvelope and EdiDataPlaneEventMessage."""

    event_type: str
    payload: JsonDict


class EdiDataPlaneRouteRegistry:
    def __init__(self) -> None:
        self._registry: dict[tuple[str, str | None], Callable[..., Awaitable[Any]]] = {}

    def register(
        self,
        event_type: str,
        direction: str | None,
        factory: Callable[..., Awaitable[Any]],
    ) -> None:
        """
        Registers a factory function to be called when an event matching the
        (event_type, direction) is routed.
        """
        self._registry[(event_type, direction)] = factory

    async def route(self, event: RoutableEvent, uow_factory: Callable[..., object]) -> None:
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
            raise ValueError(f"No route registered for {event.event_type} {direction}")

        await factory(event, uow_factory)
