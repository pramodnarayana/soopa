"""ConnectionPolicy Aggregate Root representing operational constraints and physical traffic limits."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import ClassVar

from seedwork.domain.aggregate import AggregateRoot
from seedwork.domain.types import JsonDict
from seedwork.utils import generate_id

from ip.engine.domain.connection.events import (
    ConnectionPolicyDeletedEvent,
    ConnectionPolicySavedEvent,
)
from ip.engine.domain.enums import IpIdPrefix


@dataclass(kw_only=True, eq=False)
class ConnectionPolicy(AggregateRoot):
    """Aggregate Root managing operational traffic constraints, slicing boundaries,
    concurrency ceilings, and blackout maintenance windows for a specific Connection.
    """

    ID_PREFIX: ClassVar[str] = IpIdPrefix.CONNECTION_POLICY.value

    id: str
    tenant_id: str
    connection_id: str
    max_query_window_days: int = 1
    max_query_window_hours: int | None = None
    min_query_window_minutes: int = 15
    max_entities_per_call: int = 100
    max_records_per_batch: int = 10000
    max_concurrency: int = 2
    rate_limit_rpm: int = 60
    cooldown_seconds_between_calls: float = 0.0
    supports_wildcard_queries: bool = False
    blackout_cron_schedule: str | None = None
    blackout_duration_minutes: int = 0
    vendor_quirks: JsonDict = field(default_factory=dict)
    is_enabled: bool = True
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    @classmethod
    def create(
        cls,
        *,
        tenant_id: str,
        connection_id: str,
        policy_id: str | None = None,
        max_query_window_days: int = 1,
        max_query_window_hours: int | None = None,
        min_query_window_minutes: int = 15,
        max_entities_per_call: int = 100,
        max_records_per_batch: int = 10000,
        max_concurrency: int = 2,
        rate_limit_rpm: int = 60,
        cooldown_seconds_between_calls: float = 0.0,
        supports_wildcard_queries: bool = False,
        blackout_cron_schedule: str | None = None,
        blackout_duration_minutes: int = 0,
        vendor_quirks: JsonDict | None = None,
        is_enabled: bool = True,
    ) -> ConnectionPolicy:
        """Factory creating a new ConnectionPolicy aggregate and recording domain event."""
        if max_query_window_days <= 0:
            raise ValueError("max_query_window_days must be greater than 0")
        if min_query_window_minutes <= 0:
            raise ValueError("min_query_window_minutes must be greater than 0")
        if max_entities_per_call <= 0:
            raise ValueError("max_entities_per_call must be greater than 0")
        if max_records_per_batch <= 0:
            raise ValueError("max_records_per_batch must be greater than 0")
        if max_concurrency <= 0:
            raise ValueError("max_concurrency must be greater than 0")
        if rate_limit_rpm <= 0:
            raise ValueError("rate_limit_rpm must be greater than 0")

        now_str = datetime.now(UTC).isoformat()
        resolved_id = policy_id or generate_id(cls.ID_PREFIX)
        policy = cls(
            id=resolved_id,
            tenant_id=tenant_id,
            connection_id=connection_id,
            max_query_window_days=max_query_window_days,
            max_query_window_hours=max_query_window_hours,
            min_query_window_minutes=min_query_window_minutes,
            max_entities_per_call=max_entities_per_call,
            max_records_per_batch=max_records_per_batch,
            max_concurrency=max_concurrency,
            rate_limit_rpm=rate_limit_rpm,
            cooldown_seconds_between_calls=max(0.0, cooldown_seconds_between_calls),
            supports_wildcard_queries=supports_wildcard_queries,
            blackout_cron_schedule=blackout_cron_schedule,
            blackout_duration_minutes=max(0, blackout_duration_minutes),
            vendor_quirks=dict(vendor_quirks or {}),
            is_enabled=is_enabled,
            created_at=now_str,
            updated_at=now_str,
        )
        policy.record_saved()
        return policy

    def _apply_query_window_updates(
        self,
        days: int | None,
        hours: int | None,
        minutes: int | None,
    ) -> None:
        if days is not None:
            if days <= 0:
                raise ValueError("max_query_window_days must be greater than 0")
            self.max_query_window_days = days
        if hours is not None:
            self.max_query_window_hours = hours
        if minutes is not None:
            if minutes <= 0:
                raise ValueError("min_query_window_minutes must be greater than 0")
            self.min_query_window_minutes = minutes

    def _apply_throughput_updates(
        self,
        entities: int | None,
        records: int | None,
        concurrency: int | None,
        rate_limit: int | None,
        cooldown: float | None,
    ) -> None:
        if entities is not None:
            if entities <= 0:
                raise ValueError("max_entities_per_call must be greater than 0")
            self.max_entities_per_call = entities
        if records is not None:
            if records <= 0:
                raise ValueError("max_records_per_batch must be greater than 0")
            self.max_records_per_batch = records
        if concurrency is not None:
            if concurrency <= 0:
                raise ValueError("max_concurrency must be greater than 0")
            self.max_concurrency = concurrency
        if rate_limit is not None:
            if rate_limit <= 0:
                raise ValueError("rate_limit_rpm must be greater than 0")
            self.rate_limit_rpm = rate_limit
        if cooldown is not None:
            self.cooldown_seconds_between_calls = max(0.0, cooldown)

    def _apply_operational_updates(
        self,
        supports_wildcard: bool | None,
        blackout_cron: str | None,
        blackout_duration: int | None,
        vendor_quirks: JsonDict | None,
        is_enabled: bool | None,
    ) -> None:
        if supports_wildcard is not None:
            self.supports_wildcard_queries = supports_wildcard
        if blackout_cron is not None:
            self.blackout_cron_schedule = blackout_cron
        if blackout_duration is not None:
            self.blackout_duration_minutes = max(0, blackout_duration)
        if vendor_quirks is not None:
            self.vendor_quirks = dict(vendor_quirks)
        if is_enabled is not None:
            self.is_enabled = is_enabled

    def update_policy(
        self,
        *,
        max_query_window_days: int | None = None,
        max_query_window_hours: int | None = None,
        min_query_window_minutes: int | None = None,
        max_entities_per_call: int | None = None,
        max_records_per_batch: int | None = None,
        max_concurrency: int | None = None,
        rate_limit_rpm: int | None = None,
        cooldown_seconds_between_calls: float | None = None,
        supports_wildcard_queries: bool | None = None,
        blackout_cron_schedule: str | None = None,
        blackout_duration_minutes: int | None = None,
        vendor_quirks: JsonDict | None = None,
        is_enabled: bool | None = None,
    ) -> None:
        """Updates operational policy limits and records the domain event."""
        self._apply_query_window_updates(
            max_query_window_days, max_query_window_hours, min_query_window_minutes
        )
        self._apply_throughput_updates(
            max_entities_per_call,
            max_records_per_batch,
            max_concurrency,
            rate_limit_rpm,
            cooldown_seconds_between_calls,
        )
        self._apply_operational_updates(
            supports_wildcard_queries,
            blackout_cron_schedule,
            blackout_duration_minutes,
            vendor_quirks,
            is_enabled,
        )
        self.updated_at = datetime.now(UTC).isoformat()
        self.record_saved()

    def record_saved(self) -> None:
        """Emits ConnectionPolicySavedEvent."""
        self.add_domain_event(
            ConnectionPolicySavedEvent(
                policy_id=self.id,
                tenant_id=self.tenant_id,
                connection_id=self.connection_id,
                max_query_window_days=self.max_query_window_days,
                max_entities_per_call=self.max_entities_per_call,
                max_concurrency=self.max_concurrency,
                rate_limit_rpm=self.rate_limit_rpm,
                is_enabled=self.is_enabled,
            )
        )

    def mark_deleted(self) -> None:
        """Emits ConnectionPolicyDeletedEvent."""
        self.add_domain_event(
            ConnectionPolicyDeletedEvent(
                policy_id=self.id,
                tenant_id=self.tenant_id,
                connection_id=self.connection_id,
            )
        )
