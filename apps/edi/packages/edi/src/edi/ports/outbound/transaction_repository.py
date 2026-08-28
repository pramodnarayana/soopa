from collections.abc import Sequence
from typing import Any, Protocol


class TransactionRepositoryPort(Protocol):
    """
    Port for the Data Plane transaction repository, handling Operational Data.
    """

    async def create_edi_message(self, tenant_id: str, payload: dict[str, Any]) -> str:
        """
        Saves a new EdiMessage record to the Data Plane.
        """
        ...

    async def publish_outbox_event(
        self, tenant_id: str, event_type: str, payload: Any, idempotency_key: str | None
    ) -> str:
        """
        Publishes an event to the outbox for background processing.
        """
        ...

    async def create_edi_json(self, tenant_id: str, payload: dict[str, Any]) -> str:
        """
        Saves a new EdiJson record to the Data Plane.
        """
        ...

    async def create_api_gateway(self, tenant_id: str, payload: dict[str, Any]) -> str:
        """
        Saves a new ApiGateway record to the Data Plane.
        """
        ...

    async def list_transactions(
        self,
        tenant_id: str,
        limit: int = 50,
        offset: int = 0,
        partner_id: str | None = None,
        transaction_type: str | None = None,
        direction: str | None = None,
    ) -> Sequence[Any]:
        """
        Lists transactions joined across Data Plane tables.
        """
        ...

    async def explorer_list_edi_messages(
        self, tenant_id: str, filters: list[dict[str, Any]], limit: int = 50, offset: int = 0
    ) -> Sequence[Any]:
        """
        Dynamically query EdiMessage for the data explorer.
        """
        ...

    async def explorer_list_edi_json(
        self, tenant_id: str, filters: list[dict[str, Any]], limit: int = 50, offset: int = 0
    ) -> Sequence[Any]:
        """
        Dynamically query EdiJson for the data explorer.
        """
        ...

    async def get_transaction(self, tenant_id: str, trace_id: str) -> Any | None:
        """
        Retrieves a single trace lifecycle spanning EdiMessage, EdiJson, and ApiGateway.
        """
        ...

    async def get_transaction_thread(self, tenant_id: str, key: str, value: str) -> Sequence[Any]:
        """
        Retrieves a chronological thread of documents sharing a specific business metadata key/value.
        """
        ...

    async def get_existing_trace_ids(self, tenant_id: str, trace_ids: list[str]) -> set[str]:
        """
        Takes a list of trace_ids and returns the subset that actually exist in the DB.
        """
        ...
