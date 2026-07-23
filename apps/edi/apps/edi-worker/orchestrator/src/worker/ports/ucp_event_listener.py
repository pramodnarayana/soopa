from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Protocol

from event_message import EventMessage

# Aliasing to maintain existing contract name for the adapter
UcpEventMessage = EventMessage

class UcpEventListenerPort(Protocol):
    @asynccontextmanager
    async def process_next_event(self) -> AsyncGenerator[UcpEventMessage | None, None]:
        """
        Yields the next available UCP event message.
        If processing completes without exception, the adapter should acknowledge (delete) the message.
        If an exception is raised, the adapter should not acknowledge the message (e.g. DLQ or retry).
        Yields None if no messages are available.
        """
        yield None
