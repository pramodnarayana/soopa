from typing import Any, Protocol


class DataPlaneOutboxRepositoryPort(Protocol):
    """
    Port for interacting with the Data Plane Outbox for reliable messaging and leasing.
    """

    async def claim_delivery_outbox_event(self, key_str: str) -> str | None:
        """
        Attempts to claim an outbox event for delivery by setting a lease.
        Returns the owner_token if successful, or None if already leased/processed.
        """
        ...

    async def mark_delivery_success(self, key_str: str, owner_token: str) -> None:
        """
        Marks an outbox event as PROCESSED, clearing the lease, and inserts a ProcessedEvent
        for idempotency tracking.
        """
        ...

    async def mark_delivery_failure(self, key_str: str, owner_token: str) -> None:
        """
        Marks an outbox event as FAILED, clearing the lease so it can be retried.
        """
        ...

    async def append_event(
        self, event_type: str, payload: dict[str, Any], idempotency_key: str | None = None
    ) -> None:
        """
        Appends a new event to the Data Plane Outbox.
        """
        ...
