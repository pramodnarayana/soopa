import asyncio
import logging
import sys

from transformer.application.use_cases import ProcessInboundEdiUseCase
from transformer.domain.models import ParsedEdiPayload
from transformer.infrastructure.adapters.bots_adapter import BotsEDIAdapter
from transformer.worker import SQSTransformerWorker

# Configure logging so it prints beautifully to the terminal
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("worker_runner")


# Create local mock implementations of the outbound ports
class MockStoragePort:
    async def get_raw_payload(self, s3_uri: str) -> bytes:
        logger.info(f"[Storage] Fetching raw EDI bytes from S3: {s3_uri}")
        return b"ISA*00*..."


class MockRepositoryPort:
    async def save_parsed_payload(self, trace_id: str, payload: ParsedEdiPayload) -> None:
        logger.info(f"[Database] Successfully saved transformed payload for trace {trace_id}")


async def main() -> None:
    logger.info("Initializing Hexagonal Components...")

    # 1. Instantiate the Anti-Corruption Layer adapter
    translator = BotsEDIAdapter()

    # 2. Instantiate the Mock Ports
    storage = MockStoragePort()
    repository = MockRepositoryPort()

    # 3. Inject them into the core business Use Case
    use_case = ProcessInboundEdiUseCase(
        storage_port=storage, translator_port=translator, repository_port=repository
    )

    # 4. Start the SQS Worker Loop
    queue_url = "http://localhost:4566/000000000000/EdiTransformerQueue"
    worker = SQSTransformerWorker(
        use_case=use_case, queue_url=queue_url, endpoint_url="http://localhost:4566"
    )

    logger.info("✅ Transformer Worker is running! Press Ctrl+C to stop.")
    await worker.start()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Worker stopped by user.")
