"""StitchTaskConfig Aggregate Root representing DAG task runtime execution policies."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import ClassVar

from seedwork.domain.aggregate import AggregateRoot
from seedwork.utils import generate_id

from ip.engine.domain.enums import IpIdPrefix
from ip.engine.domain.stitch.events import (
    StitchTaskConfigDeletedEvent,
    StitchTaskConfigSavedEvent,
)


@dataclass(kw_only=True, eq=False)
class StitchTaskConfig(AggregateRoot):
    """Aggregate Root managing operational runtime policies for an individual DAG node in a Stitch:
    timeouts, exponential backoff retries, concurrency limits, queue priority, and quarantine DLQs.
    """

    ID_PREFIX: ClassVar[str] = IpIdPrefix.STITCH_TASK_CONFIG.value

    id: str
    tenant_id: str
    stitch_id: str
    node_key: str
    timeout_seconds: int = 60
    heartbeat_interval_seconds: int = 15
    max_attempts: int = 5
    initial_delay_seconds: float = 2.0
    backoff_multiplier: float = 2.0
    max_delay_seconds: float = 60.0
    queue_name: str = "default"
    max_in_flight_tasks: int = 3
    failure_disposition: str = "RETRY_THEN_QUARANTINE"
    quarantine_stream_name: str | None = "dead_letter_records"
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    @classmethod
    def create(
        cls,
        *,
        tenant_id: str,
        stitch_id: str,
        node_key: str,
        config_id: str | None = None,
        timeout_seconds: int = 60,
        heartbeat_interval_seconds: int = 15,
        max_attempts: int = 5,
        initial_delay_seconds: float = 2.0,
        backoff_multiplier: float = 2.0,
        max_delay_seconds: float = 60.0,
        queue_name: str = "default",
        max_in_flight_tasks: int = 3,
        failure_disposition: str = "RETRY_THEN_QUARANTINE",
        quarantine_stream_name: str | None = "dead_letter_records",
    ) -> StitchTaskConfig:
        """Factory creating a new StitchTaskConfig aggregate and recording domain event."""
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be greater than 0")
        if heartbeat_interval_seconds <= 0:
            raise ValueError("heartbeat_interval_seconds must be greater than 0")
        if max_attempts <= 0:
            raise ValueError("max_attempts must be greater than 0")
        if max_in_flight_tasks <= 0:
            raise ValueError("max_in_flight_tasks must be greater than 0")

        now_str = datetime.now(UTC).isoformat()
        resolved_id = config_id or generate_id(cls.ID_PREFIX)
        config = cls(
            id=resolved_id,
            tenant_id=tenant_id,
            stitch_id=stitch_id,
            node_key=node_key,
            timeout_seconds=timeout_seconds,
            heartbeat_interval_seconds=heartbeat_interval_seconds,
            max_attempts=max_attempts,
            initial_delay_seconds=initial_delay_seconds,
            backoff_multiplier=backoff_multiplier,
            max_delay_seconds=max_delay_seconds,
            queue_name=queue_name,
            max_in_flight_tasks=max_in_flight_tasks,
            failure_disposition=failure_disposition,
            quarantine_stream_name=quarantine_stream_name,
            created_at=now_str,
            updated_at=now_str,
        )
        config.record_saved()
        return config

    def _apply_timeout_and_heartbeat(
        self,
        timeout: int | None,
        heartbeat: int | None,
    ) -> None:
        if timeout is not None:
            if timeout <= 0:
                raise ValueError("timeout_seconds must be greater than 0")
            self.timeout_seconds = timeout
        if heartbeat is not None:
            if heartbeat <= 0:
                raise ValueError("heartbeat_interval_seconds must be greater than 0")
            self.heartbeat_interval_seconds = heartbeat

    def _apply_retry_policy(
        self,
        attempts: int | None,
        initial_delay: float | None,
        backoff: float | None,
        max_delay: float | None,
    ) -> None:
        if attempts is not None:
            if attempts <= 0:
                raise ValueError("max_attempts must be greater than 0")
            self.max_attempts = attempts
        if initial_delay is not None:
            if initial_delay < 0:
                raise ValueError("initial_delay_seconds cannot be negative")
            self.initial_delay_seconds = initial_delay
        if backoff is not None:
            if backoff < 1.0:
                raise ValueError("backoff_multiplier must be at least 1.0")
            self.backoff_multiplier = backoff
        if max_delay is not None:
            if max_delay < 0:
                raise ValueError("max_delay_seconds cannot be negative")
            self.max_delay_seconds = max_delay

    def _apply_queue_and_concurrency(
        self,
        queue_name: str | None,
        max_in_flight: int | None,
        failure_disposition: str | None,
        quarantine_stream: str | None,
    ) -> None:
        if queue_name is not None and queue_name.strip():
            self.queue_name = queue_name.strip()
        if max_in_flight is not None:
            if max_in_flight <= 0:
                raise ValueError("max_in_flight_tasks must be greater than 0")
            self.max_in_flight_tasks = max_in_flight
        if failure_disposition is not None and failure_disposition.strip():
            self.failure_disposition = failure_disposition.strip()
        if quarantine_stream is not None:
            self.quarantine_stream_name = quarantine_stream.strip() or None

    def update_config(
        self,
        *,
        timeout_seconds: int | None = None,
        heartbeat_interval_seconds: int | None = None,
        max_attempts: int | None = None,
        initial_delay_seconds: float | None = None,
        backoff_multiplier: float | None = None,
        max_delay_seconds: float | None = None,
        queue_name: str | None = None,
        max_in_flight_tasks: int | None = None,
        failure_disposition: str | None = None,
        quarantine_stream_name: str | None = None,
    ) -> None:
        """Updates task runtime execution policies and records the domain event."""
        self._apply_timeout_and_heartbeat(timeout_seconds, heartbeat_interval_seconds)
        self._apply_retry_policy(
            max_attempts, initial_delay_seconds, backoff_multiplier, max_delay_seconds
        )
        self._apply_queue_and_concurrency(
            queue_name, max_in_flight_tasks, failure_disposition, quarantine_stream_name
        )
        self.updated_at = datetime.now(UTC).isoformat()
        self.record_saved()

    def record_saved(self) -> None:
        """Emits StitchTaskConfigSavedEvent."""
        self.add_domain_event(
            StitchTaskConfigSavedEvent(
                config_id=self.id,
                tenant_id=self.tenant_id,
                stitch_id=self.stitch_id,
                node_key=self.node_key,
                timeout_seconds=self.timeout_seconds,
                max_attempts=self.max_attempts,
                max_in_flight_tasks=self.max_in_flight_tasks,
                queue_name=self.queue_name,
            )
        )

    def mark_deleted(self) -> None:
        """Emits StitchTaskConfigDeletedEvent."""
        self.add_domain_event(
            StitchTaskConfigDeletedEvent(
                config_id=self.id,
                tenant_id=self.tenant_id,
                stitch_id=self.stitch_id,
                node_key=self.node_key,
            )
        )
