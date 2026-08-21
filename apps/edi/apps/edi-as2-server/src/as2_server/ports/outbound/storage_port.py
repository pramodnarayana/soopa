from typing import Protocol


class PayloadStoragePort(Protocol):
    async def upload(self, tenant_id: str, message_id: str, payload: bytes) -> str: ...
