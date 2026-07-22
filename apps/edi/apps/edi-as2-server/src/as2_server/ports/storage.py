from typing import Protocol


class IPayloadStorage(Protocol):
    async def upload(self, tenant_id: int, message_id: str, payload: bytes) -> str: ...
