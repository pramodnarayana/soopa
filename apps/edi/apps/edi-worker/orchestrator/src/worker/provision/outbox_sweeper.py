import asyncio

import asyncpg
import structlog

from worker.adapters.listen_notify_outbox_adapter import ListenNotifyOutboxAdapter

logger = structlog.get_logger(__name__)

# Backoff configuration
INITIAL_BACKOFF = 1.0  # 1 second
MAX_BACKOFF = 300.0  # 5 minutes
BACKOFF_MULTIPLIER = 2.0
NORMAL_SWEEP_INTERVAL = 60.0  # 60 seconds


async def run_sweeper(db_url: str, adapter: ListenNotifyOutboxAdapter) -> None:
    """
    A simple background job to sweep the Control Plane Outbox for abandoned PENDING events
    that might have been missed by the real-time Postgres NOTIFY listener.
    """
    logger.info("sweeper_started", target="edi.outbox")
    pool = None
    failure_backoff = INITIAL_BACKOFF

    try:
        asyncpg_url = db_url.replace("postgresql+asyncpg://", "postgresql://")
        pool = await asyncpg.create_pool(asyncpg_url)

        while True:
            try:
                async with pool.acquire() as connection:
                    # Atomically claim eligible events by updating their status to PROCESSING
                    # This prevents concurrent sweepers or workers from claiming the same event
                    async with connection.transaction():
                        claimed_ids = await connection.fetch(
                            """
                            UPDATE edi.outbox
                            SET status = 'PROCESSING'
                            WHERE id IN (
                                SELECT id FROM edi.outbox
                                WHERE status = 'PENDING'
                                AND created_at < NOW() - INTERVAL '1 minute'
                                FOR UPDATE SKIP LOCKED
                                LIMIT 100
                            )
                            RETURNING id
                            """
                        )

                    if claimed_ids:
                        logger.info(
                            "swept_abandoned_pending_events",
                            count=len(claimed_ids),
                            target="edi.outbox",
                        )
                        for row in claimed_ids:
                            adapter.queue.put_nowait(str(row["id"]))

                # Reset backoff after successful sweep
                failure_backoff = INITIAL_BACKOFF
                await asyncio.sleep(NORMAL_SWEEP_INTERVAL)
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("sweeper_run_loop_error")

                # Apply exponential backoff with jitter
                import secrets

                jitter = secrets.SystemRandom().uniform(0, 0.1 * failure_backoff)
                delay = min(failure_backoff + jitter, MAX_BACKOFF)
                logger.warning("sweeper_retrying", delay=delay)
                await asyncio.sleep(delay)
                # Increase backoff for next failure
                failure_backoff = min(failure_backoff * BACKOFF_MULTIPLIER, MAX_BACKOFF)
    finally:
        if pool:
            await pool.close()
