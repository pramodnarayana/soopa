"""Domain-level inbound worker ports for IP Engine."""

from __future__ import annotations

from collections.abc import Callable

from ip.engine.domain.models.stream_definition import StreamDefinition

IpStreamDefinitionResolver = Callable[[str, str, str], StreamDefinition | None]

__all__ = [
    "IpStreamDefinitionResolver",
]
