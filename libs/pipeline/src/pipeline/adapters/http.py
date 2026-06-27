import httpx
from pipeline.ports.http import HttpDeliveryPort


class HttpxDeliveryAdapter(HttpDeliveryPort):
    """
    Concrete implementation of HttpDeliveryPort using HTTPX.
    """

    def __init__(self, timeout_secs: int = 30):
        self.timeout = timeout_secs

    async def deliver(self, url: str, payload: bytes) -> int:
        async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=False) as client:
            response = await client.post(
                url, content=payload, headers={"Content-Type": "application/json"}
            )
            return response.status_code
