import asyncio
import contextlib
import functools

import structlog
from pubsub.aws.aws_sqs_consumer import AwsSqsConsumer

from ucp_worker.bootstrap.container import WorkerContainer
from ucp_worker.scheduled_jobs_handler import process_scheduled_job

logger = structlog.get_logger(__name__)


async def main() -> None:
    logger.info("Starting UCP Worker...")

    container = WorkerContainer()
    container.wire()

    scheduled_jobs_processor = functools.partial(process_scheduled_job, registry=container.registry)

    consumer = AwsSqsConsumer(
        queue_name="ucp-jobs.fifo",
        endpoint_url=container.settings.aws_endpoint_url,
    )

    async def poll_loop() -> None:
        try:
            async with consumer as active_consumer:
                while True:
                    async with active_consumer.poll_raw_message() as body:
                        if body:
                            await scheduled_jobs_processor(body)
        except asyncio.CancelledError:
            pass
        except Exception:
            logger.exception("ucp_jobs_polling_task_exited_with_exception")
            raise

    jobs_task = asyncio.create_task(poll_loop())

    if container.outbox_relay:
        container.outbox_relay.start()
        logger.info("ucp_outbox_relay_started_in_worker")

    if container.events_consumer:
        container.events_consumer.start()
        logger.info("ucp_event_sqs_consumer_started_in_worker")

    try:
        await asyncio.gather(jobs_task)
    finally:
        logger.info("Shutting down UCP worker tasks gracefully...")
        jobs_task.cancel()

        if container.outbox_relay:
            await container.outbox_relay.stop()

        if container.events_consumer:
            await container.events_consumer.stop()

        with contextlib.suppress(asyncio.CancelledError):
            await asyncio.gather(jobs_task, return_exceptions=True)

        await container.dispose()


if __name__ == "__main__":
    asyncio.run(main())
