import logging

from pipeline.ports.http import HttpDeliveryPort
from pipeline.ports.repository import RepositoryPort
from pipeline.ports.storage import StoragePort

logger = logging.getLogger(__name__)


class DeliveryService:
    """
    Pure domain service for orchestrating delivery of payloads (JSON or EDI).
    Follows Hexagonal Architecture.
    """

    def __init__(
        self,
        storage: StoragePort,
        repository: RepositoryPort,
        http_delivery: HttpDeliveryPort,
    ) -> None:
        self.storage = storage
        self.repository = repository
        self.http_delivery = http_delivery

    async def deliver(self, trace_id: str, target_url: str) -> None:
        """
        Delivers a payload to the external trading partner or integration platform.
        """
        logger.info(f"Starting delivery pipeline for trace_id={trace_id} to target={target_url}")

        if not await self.repository.claim_api_payload(trace_id):
            logger.warning(f"Could not claim trace_id={trace_id} (already claimed or terminal).")
            return

        api_payload = await self.repository.get_api_payload(trace_id)
        if not api_payload:
            raise ValueError(f"No API Payload found for trace_id={trace_id}")

        try:
            # 1. Download payload from S3
            s3_uri = api_payload["s3_key"]
            raw_payload = await self.storage.download(s3_uri)

            # 2. Perform HTTP POST
            status_code = await self.http_delivery.deliver(url=target_url, payload=raw_payload)
        except Exception as e:
            await self.repository.update_api_payload_status(trace_id, "FAILED")
            logger.exception(f"Delivery failed for trace_id={trace_id}")
            raise RuntimeError(f"Delivery failed due to exception: {e}") from e

        if 200 <= status_code < 300:
            # 3. Update DB status to DELIVERED
            await self.repository.update_api_payload_status(trace_id, "DELIVERED")
            logger.info(f"Successfully delivered trace_id={trace_id} with status {status_code}")
        else:
            # Update DB status to FAILED
            await self.repository.update_api_payload_status(trace_id, "FAILED")
            logger.error(f"Failed to deliver trace_id={trace_id}. HTTP Status: {status_code}")
            raise RuntimeError(f"Delivery failed with HTTP status {status_code}")
