import uuid
from typing import Protocol


class IPayloadStorage(Protocol):
    async def upload(self, tenant_id: uuid.UUID, message_id: str, payload: bytes) -> str: ...
