"""Universal Pub/Sub domain exceptions."""

from __future__ import annotations

from collections.abc import Sequence


class PubSubError(Exception):
    """Base exception for all pubsub domain errors."""


class PublisherError(PubSubError):
    """Raised when message publishing fails."""


class ConsumerError(PubSubError):
    """Raised when message consumption fails."""


class UnsupportedBrokerSchemeError(PubSubError):
    """Raised when an unhandled or invalid URI scheme is requested."""

    def __init__(
        self,
        scheme: str,
        *,
        supported_prefixes: Sequence[str] = (),
    ) -> None:
        suffix = (
            f" Supported prefixes: {', '.join(supported_prefixes)}" if supported_prefixes else ""
        )
        super().__init__(f"Unsupported broker scheme: '{scheme}'.{suffix}")
        self.scheme = scheme
        self.supported_prefixes = tuple(supported_prefixes)


class InvalidBrokerTransportError(PubSubError):
    """Raised when an unrecognized PUBSUB_TRANSPORT policy value is supplied."""

    def __init__(self, *, transport: str, reason: str) -> None:
        super().__init__(reason)
        self.transport = transport
        self.reason = reason


class BrokerTransportMismatchError(PubSubError):
    """Raised when a queue/topic URI conflicts with the configured PUBSUB_TRANSPORT policy."""

    def __init__(self, *, transport: str, uri: str, remedy: str) -> None:
        super().__init__(f"PUBSUB_TRANSPORT='{transport}' forbids broker URI '{uri}'. {remedy}")
        self.transport = transport
        self.uri = uri
        self.remedy = remedy
