"""Universal Pub/Sub domain exceptions."""

from __future__ import annotations


class PubSubError(Exception):
    """Base exception for all pubsub domain errors."""


class PublisherError(PubSubError):
    """Raised when message publishing fails."""


class ConsumerError(PubSubError):
    """Raised when message consumption fails."""


class UnsupportedBrokerSchemeError(PubSubError):
    """Raised when an unhandled or invalid URI scheme is requested."""

    def __init__(self, scheme: str) -> None:
        super().__init__(
            f"Unsupported broker scheme: '{scheme}'. Supported schemes: sqs://, sns://, kafka://, amqp://, memory://"
        )
        self.scheme = scheme
