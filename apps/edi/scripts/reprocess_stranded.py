import asyncio

import structlog
from database.router import DatabaseRouter
from dotenv import load_dotenv
from edi.config.settings import get_settings
from edi.domain.enums import PipelineEventType
from seedwork.id_registry import SystemIdPrefix
from seedwork.utils import generate_deterministic_id
from sqlalchemy import text

load_dotenv()
logger = structlog.get_logger(__name__)


async def reprocess_stranded_messages() -> None:
    """Finds EDI messages stuck in PENDING_DELIVERY and injects a DELIVERY_REQUESTED into the outbox."""
    logger.info("Starting reprocessing of stranded EDI messages...")
    settings = get_settings()

    db_router = DatabaseRouter(
        global_db_url=settings.database.global_url,
        shard_overrides=settings.database.shard_overrides,
    )

    total_reprocessed = 0
    try:
        shards = await db_router.get_all_shards()

        for shard_key, shard_url in shards:
            engine = await db_router.get_engine(shard_key, shard_url)
            async with engine.begin() as conn:
                result = await conn.execute(
                    text("SELECT trace_id FROM edi_messages WHERE status = 'PENDING_DELIVERY'")
                )
                rows = result.fetchall()
                for row in rows:
                    trace_id = row[0]
                    deliver_key = generate_deterministic_id(
                        SystemIdPrefix.IDEMPOTENCY, trace_id, "DELIVER_RETRY_MANUAL"
                    )

                    # Ensure we create a new outbox event to be picked up by the delivery worker/sweeper
                    result = await conn.execute(
                        text("""
                        INSERT INTO outbox
                        (id, event_type, payload, status, created_at, updated_at, attempts, idempotency_key)
                        VALUES (:id, :event_type, :payload, 'PENDING', NOW(), NOW(), 0, :idempotency_key)
                        ON CONFLICT (id) DO NOTHING
                        RETURNING id
                        """),
                        {
                            "id": deliver_key,
                            "event_type": PipelineEventType.DELIVERY_REQUESTED.value,
                            "payload": f'{{"trace_id": "{trace_id}"}}',
                            "idempotency_key": deliver_key,
                        },
                    )
                    if result.fetchone():
                        total_reprocessed += 1
                        logger.info("reprocessed_stranded_message", trace_id=trace_id)

        logger.info("reprocessing_complete", total_reprocessed=total_reprocessed)
    except Exception:
        logger.exception("Reprocessing failed")
        raise
    finally:
        await db_router.close_all()


if __name__ == "__main__":
    asyncio.run(reprocess_stranded_messages())
