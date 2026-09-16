from typing import Protocol

from pubsub.message import SqsMessagePayload


class IdempotencyRepositoryPort(Protocol):
    """
    Generic port for asserting Consumer Idempotency across bounded contexts.
    Concrete adapters should map this to their local database schema
    (e.g., `processed_events` for EDI, etc.).
    """

    async def check_and_record_idempotency(self, payload: SqsMessagePayload) -> bool:
        """
        Atomically extracts the idempotency key from the payload, checks if it was already processed, and if not, records it.

        Returns:
            True: If the event was NOT previously processed and has now been recorded (proceed), or if the payload has no idempotency key (proceed).
            False: If the event WAS already processed (duplicate - skip).
        """
        ...
