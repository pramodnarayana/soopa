"""Universal Pub/Sub domain enums (core/platform/packages/pubsub)."""

from __future__ import annotations

from enum import StrEnum


class BrokerType(StrEnum):
    """Supported broker protocols across the platform."""

    SQS = "sqs"
    SNS = "sns"
    KAFKA = "kafka"
    AMQP = "amqp"
    MEMORY = "memory"


class ConsumerVerdict(StrEnum):
    """Consumer processing outcome for an AckableMessage."""

    ACK = "ACK"
    NACK = "NACK"
    REJECT = "REJECT"
