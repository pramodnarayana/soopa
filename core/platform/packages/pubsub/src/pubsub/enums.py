from dataclasses import dataclass
from enum import StrEnum

DEFAULT_SQS_NACK_VISIBILITY_SEC: int = 5
MAX_SQS_VISIBILITY_TIMEOUT_SEC: int = 43200


class ConsumerAction(StrEnum):
    ACK = "ACK"
    NACK = "NACK"
    DLQ = "DLQ"


@dataclass(frozen=True)
class ConsumerDecision:
    """First-class consumer verdict supporting dynamic SQS visibility timeout overrides."""

    action: ConsumerAction
    visibility_timeout_seconds: int | None = None


ConsumerOutcome = ConsumerAction | ConsumerDecision

__all__ = [
    "DEFAULT_SQS_NACK_VISIBILITY_SEC",
    "MAX_SQS_VISIBILITY_TIMEOUT_SEC",
    "ConsumerAction",
    "ConsumerDecision",
    "ConsumerOutcome",
]
