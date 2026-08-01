import asyncio
import logging

import asyncpg

from worker.adapters.listen_notify_outbox_adapter import ListenNotifyOutboxAdapter

logger = logging.getLogger(__name__)


async def run_sweeper(db_url: str, adapter: ListenNotifyOutboxAdapter) -> None:
    """
    A simple background job to sweep the Control Plane Outbox for abandoned PENDING events
    that might have been missed by the real-time Postgres NOTIFY listener.
    """
    logger.info("[Sweeper] Started background sweeper task")
    pool = None
    try:
        asyncpg_url = db_url.replace("postgresql+asyncpg://", "postgresql://")
        pool = await asyncpg.create_pool(asyncpg_url)

        while True:
            try:
                async with pool.acquire() as connection:
                    rows = await connection.fetch(
                        "SELECT id FROM edi.outbox WHERE status = 'PENDING' AND created_at < NOW() - INTERVAL '1 minute'"
                    )
                    if rows:
                        logger.info(
                            f"[Sweeper] Found {len(rows)} abandoned PENDING events. Pushing to adapter queue."
                        )
                    for row in rows:
                        adapter.queue.put_nowait(str(row["id"]))

                await asyncio.sleep(60)  # Sweep every 60 seconds
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.exception(f"[Sweeper] Error in sweep: {e}")
    finally:
        if pool:
            await pool.close()
