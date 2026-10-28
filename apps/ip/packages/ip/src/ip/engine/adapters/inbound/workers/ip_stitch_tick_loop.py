"""Multi-shard Layer-4 Stitch worker tick loop for IP."""

from __future__ import annotations

import asyncio
import contextlib

import structlog
from ip.engine.application.use_cases.stitch.execute_stitch_worker_tick_use_case import (
    ExecuteStitchWorkerTickCommand,
    StitchWorkerTickResultDTO,
)
from ip.engine.application.worker_ports import IpStitchWorkerTickExecutorPort

logger = structlog.get_logger(__name__)


class IpMultiShardStitchTickLoop:
    """Background loop that continuously wakes expired IP Stitch `SLEEP` timers and `RETRY_BACKOFF` steps."""

    def __init__(
        self,
        *,
        tick_executor: IpStitchWorkerTickExecutorPort,
        worker_id: str = "ip-orchestrator-worker",
        free_slots: int = 20,
        interval_seconds: float = 2.0,
    ) -> None:
        self._tick_executor = tick_executor
        self._worker_id = worker_id
        self._free_slots = max(1, free_slots)
        self._interval_seconds = max(0.05, interval_seconds)
        self.is_running: bool = False
        self._stop_event = asyncio.Event()
        self._task: asyncio.Task[None] | None = None

    def background_tasks(self) -> list[asyncio.Task[None]]:
        """Returns active background tasks for supervisor monitoring."""
        return [self._task] if self._task is not None else []

    def start(self) -> None:
        """Starts the asynchronous Stitch tick loop."""
        if not self.is_running:
            self.is_running = True
            self._stop_event.clear()
            self._task = asyncio.create_task(self._run_loop())
            logger.info(
                "ip_stitch_tick_loop_started",
                worker_id=self._worker_id,
                free_slots=self._free_slots,
                interval_seconds=self._interval_seconds,
            )

    async def stop(self) -> None:
        """Gracefully stops the Stitch tick loop."""
        self.is_running = False
        self._stop_event.set()
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None
        logger.info("ip_stitch_tick_loop_stopped", worker_id=self._worker_id)

    async def run_single_tick(self) -> StitchWorkerTickResultDTO | None:
        """Executes one Stitch worker tick across all active shards."""
        res = await self._tick_executor.execute(
            ExecuteStitchWorkerTickCommand(
                worker_id=self._worker_id,
                free_slots=self._free_slots,
            )
        )
        if res.is_err:
            logger.error(
                "ip_stitch_tick_failed",
                worker_id=self._worker_id,
                error=res.unwrap_err().message,
            )
            return None
        return res.unwrap()

    async def _run_loop(self) -> None:
        while self.is_running:
            try:
                dto = await self.run_single_tick()
                has_more = dto is not None and bool(
                    dto.completed_step_ids or dto.woken_timer_step_ids
                )
                if has_more and self.is_running:
                    await asyncio.sleep(0)
                    continue
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception(
                    "ip_stitch_tick_loop_unhandled_error",
                    worker_id=self._worker_id,
                )

            if self.is_running:
                with contextlib.suppress(asyncio.TimeoutError, TimeoutError):
                    await asyncio.wait_for(
                        self._stop_event.wait(),
                        timeout=self._interval_seconds,
                    )


__all__ = ["IpMultiShardStitchTickLoop"]
