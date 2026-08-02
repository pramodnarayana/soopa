from typing import Protocol


class IPayloadStorage(Protocol):
    async def upload(self, tenant_id: str, message_id: str, payload: bytes) -> str: ...
