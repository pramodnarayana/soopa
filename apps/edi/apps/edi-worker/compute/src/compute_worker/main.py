import asyncio

from dotenv import load_dotenv

load_dotenv()

import structlog
from transformer.application.use_cases import ProcessInboundEdiUseCase
from transformer.domain.models import ParsedEdiPayload
from transformer.infrastructure.adapters.bots_adapter import BotsEDIAdapter

from compute_worker.worker import SQSComputeWorker

# Configure logging so it prints beautifully to the terminal
logger = structlog.get_logger("worker_runner")


# Create local mock implementations of the outbound ports
class MockStoragePort:
    async def get_raw_payload(self, s3_uri: str) -> bytes:
        logger.info("[Storage] Fetching raw EDI bytes from S3: {s3_uri}", s3_uri=s3_uri)
        return b"ISA*00*..."


class MockRepositoryPort:
    async def save_parsed_payload(self, trace_id: str, payload: ParsedEdiPayload) -> None:
        logger.info(
            "[Database] Successfully saved transformed payload for trace {trace_id}",
            trace_id=trace_id,
        )


async def main() -> None:
    logger.info("Initializing Hexagonal Components...")

    transformer = BotsEDIAdapter()

    # 2. Instantiate the Mock Ports
    storage = MockStoragePort()
    repository = MockRepositoryPort()

    # 3. Inject them into the core business Use Case
    use_case = ProcessInboundEdiUseCase(
        storage_port=storage, transformer_port=transformer, repository_port=repository
    )

    # 4. Start the SQS Worker Loop
    queue_url = "http://localhost:4566/000000000000/TransformComputeQueue"
    worker = SQSComputeWorker(
        use_case=use_case, queue_url=queue_url, endpoint_url="http://localhost:4566"
    )

    logger.info("✅ Transformer Worker is running! Press Ctrl+C to stop.")
    await worker.start()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Worker stopped by user.")
