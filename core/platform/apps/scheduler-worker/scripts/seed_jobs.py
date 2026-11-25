"""Platform Scheduler & Pub/Sub Bootstrap Seeder.

Idempotently seeds:
1. `platform_queue_cleanup` scheduled retention job in `scheduling.scheduled_jobs`.
2. Canonical topic subscriptions in `pubsub.platform_topic_subscriptions` (matching `infra/topology.json`)
   to eliminate cold-start pub/sub fan-out race conditions before workers boot.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import structlog
from config_sync.domain.enums import ConfigSyncJobName
from database.models.scheduling import ScheduledJob
from database.provider import DatabaseProvider
from pubsub.adapters.database.sqlalchemy_database_queue_repository import (
    SqlAlchemyDatabaseQueueRepository,
)
from pubsub.domain.enums import PubSubJobName
from scheduler.domain.constants import JobStatus
from sqlalchemy.dialects.postgresql import insert as pg_insert

from scheduler_worker.config.settings import get_settings

logger = structlog.get_logger(__name__)


def _find_topology_path() -> Path:
    current = Path(__file__).resolve().parent
    for _ in range(10):
        candidate = current / "infra" / "topology.json"
        if candidate.is_file():
            return candidate
        current = current.parent
    raise FileNotFoundError("Could not locate infra/topology.json for topic subscription seeding.")


def _extract_event_type_patterns(filter_policy: object) -> tuple[str, ...] | None:
    if not isinstance(filter_policy, dict):
        return None
    raw_entries = filter_policy.get("event_type")
    if not isinstance(raw_entries, list):
        return None
    patterns: list[str] = []
    for entry in raw_entries:
        if isinstance(entry, str) and entry:
            patterns.append(entry)
        elif isinstance(entry, dict):
            prefix = entry.get("prefix")
            if isinstance(prefix, str) and prefix:
                patterns.append(prefix)
    return tuple(patterns) if patterns else None


def load_canonical_topic_subscriptions(
    topology_path: Path | None = None,
) -> tuple[tuple[str, str, tuple[str, ...] | None], ...]:
    """Loads canonical `(topic_name, target_queue, event_types)` tuples from `infra/topology.json` (SSOT)."""
    resolved_path = topology_path or _find_topology_path()
    data = json.loads(resolved_path.read_text(encoding="utf-8"))
    fifo_queues: set[str] = {
        str(q["name"])
        for q in data.get("queues", [])
        if isinstance(q, dict) and q.get("fifo") and q.get("name")
    }
    subscriptions: list[tuple[str, str, tuple[str, ...] | None]] = []
    for sub in data.get("subscriptions", []):
        if not isinstance(sub, dict):
            continue
        topic_name = str(sub.get("topic", "")).strip()
        queue_logical = str(sub.get("queue", "")).strip()
        if not topic_name or not queue_logical:
            continue
        physical_queue = f"{queue_logical}.fifo" if queue_logical in fifo_queues else queue_logical
        patterns = _extract_event_type_patterns(sub.get("filterPolicy"))
        subscriptions.append((topic_name, physical_queue, patterns))
    return tuple(subscriptions)


async def main() -> None:
    settings = get_settings()
    provider = DatabaseProvider.from_url(settings.database_url)
    queue_repo = SqlAlchemyDatabaseQueueRepository(session_factory=provider.session)
    canonical_subscriptions = load_canonical_topic_subscriptions()

    canonical_jobs: tuple[tuple[str, str, int], ...] = (
        (PubSubJobName.PLATFORM_QUEUE_CLEANUP.value, "0 * * * *", 7),
        (ConfigSyncJobName.CONFIG_CHANGELOG_CLEANUP.value, "0 3 * * *", 30),
    )

    try:
        async with provider.session() as session:
            logger.info("platform_scheduler_seed_starting")
            for job_name, cron_expr, retention_days in canonical_jobs:
                name_hash = hashlib.sha256(job_name.encode()).hexdigest()[:24]
                job_id = f"job_{name_hash}"
                stmt = (
                    pg_insert(ScheduledJob)
                    .values(
                        id=job_id,
                        name=job_name,
                        app_namespace="platform",
                        payload={"retention_days": retention_days},
                        status=JobStatus.PENDING.value,
                        cron_expression=cron_expr,
                        target_queue=None,
                        retry_count=0,
                        max_retries=3,
                        next_run_at=datetime.now(UTC),
                    )
                    .on_conflict_do_update(
                        index_elements=[ScheduledJob.id],
                        set_={
                            "name": job_name,
                            "app_namespace": "platform",
                            "cron_expression": cron_expr,
                            "next_run_at": datetime.now(UTC),
                        },
                    )
                )
                await session.execute(stmt)
                logger.info(
                    "platform_scheduler_seed_job_upserted", job_id=job_id, job_name=job_name
                )
            await session.commit()

        for topic_name, target_queue, event_types in canonical_subscriptions:
            await queue_repo.register_subscription(
                topic_name=topic_name,
                target_queue=target_queue,
                event_types=event_types,
            )

        logger.info(
            "platform_scheduler_seed_completed",
            subscription_count=len(canonical_subscriptions),
        )
    except Exception:
        logger.exception("platform_scheduler_seed_failed")
        sys.exit(1)
    finally:
        await provider.close()


if __name__ == "__main__":
    asyncio.run(main())
