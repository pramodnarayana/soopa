"""Universal Pub/Sub domain enums (core/platform/packages/pubsub)."""

from __future__ import annotations

from enum import StrEnum


class BrokerType(StrEnum):
    """Supported broker protocols across the platform."""

    DB = "db"
    OUTBOX = "outbox"
    POSTGRES = "postgres"
    SQS = "sqs"
    SNS = "sns"
    KAFKA = "kafka"
    AMQP = "amqp"
    MEMORY = "memory"


DATABASE_QUEUE_SCHEMES: tuple[str, ...] = (
    f"{BrokerType.DB.value}://",
    f"{BrokerType.OUTBOX.value}://",
    f"{BrokerType.POSTGRES.value}://",
)

AMQP_QUEUE_SCHEMES: tuple[str, ...] = (
    f"{BrokerType.AMQP.value}://",
    "amqps://",
)

DATABASE_TOPIC_PREFIX = "topic/"


class PubSubJobName(StrEnum):
    """Scheduled maintenance job names owned by the Pub/Sub platform capability."""

    PLATFORM_QUEUE_CLEANUP = "platform_queue_cleanup"


class PlatformTopicName(StrEnum):
    """Canonical logical pub/sub topic names matching infra/topology.json."""

    PLATFORM_EVENTS = "platform-events-topic"
    IP_EVENTS = "ip-events-topic"


def is_database_queue_uri(uri: str | None) -> bool:
    """Returns True if the URI targets the Single-Queue PostgreSQL Engine (`db://`, `outbox://`, `postgres://`)."""
    if not uri:
        return False
    return uri.strip().lower().startswith(DATABASE_QUEUE_SCHEMES)


def is_database_topic_uri(uri: str | None) -> bool:
    """Returns True if the URI targets a decoupled PostgreSQL pub/sub topic (`db://topic/<name>`)."""
    if not is_database_queue_uri(uri) or uri is None:
        return False
    normalized = normalize_database_queue_name(uri)
    return normalized.lower().startswith(DATABASE_TOPIC_PREFIX)


def normalize_database_queue_name(uri: str) -> str:
    """Extracts the canonical logical queue name from a database queue URI."""
    clean = uri.strip()
    lower = clean.lower()
    for prefix in DATABASE_QUEUE_SCHEMES:
        if lower.startswith(prefix):
            clean = clean[len(prefix) :]
            break
    return clean.strip("/") or "default"


def normalize_database_topic_name(uri: str) -> str:
    """Extracts the canonical topic name from `db://topic/<name>` or bare `<name>`."""
    clean = normalize_database_queue_name(uri)
    if clean.lower().startswith(DATABASE_TOPIC_PREFIX):
        clean = clean[len(DATABASE_TOPIC_PREFIX) :]
    return clean.strip("/") or "default"


class ConsumerVerdict(StrEnum):
    """Consumer processing outcome for an AckableMessage."""

    ACK = "ACK"
    NACK = "NACK"
    REJECT = "REJECT"


class PayloadDispatchMode(StrEnum):
    """Explicit delivery contract for DirectHandlerOutboxPublisher handlers (no runtime reflection)."""

    JSON_DICT = "json_dict"
    ACKABLE_MESSAGE = "ackable_message"
