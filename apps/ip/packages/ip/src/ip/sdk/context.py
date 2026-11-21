"""Typed runtime execution context injected into functional Stitches (Zero Global State)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from seedwork.domain.types import JsonDict

from ip.sdk.contracts import RequestSpec


class StitchHttpPort(Protocol):
    """Port for executing rate-limited, token-bucket HTTP calls inside a Stitch."""

    async def dispatch(
        self,
        *,
        connection_id: str,
        endpoint: str,
        payload: JsonDict,
        method: str = "POST",
        headers: dict[str, str] | None = None,
    ) -> JsonDict:
        """Dispatches an HTTP request through the connection manager."""
        ...

    async def dispatch_spec(
        self,
        *,
        connection_id: str,
        spec: RequestSpec,
    ) -> JsonDict:
        """Dispatches an immutable RequestSpec through the connection manager."""
        ...


class StitchTimeSlicerPort(Protocol):
    """Port for slicing date ranges into atomic partition windows."""

    def slice_daily(
        self,
        start_date: datetime,
        end_date: datetime,
    ) -> tuple[TimeSlice, ...]:
        """Slices a date range into atomic daily intervals."""
        ...


class StitchKafkaPort(Protocol):
    """Port for publishing records to Kafka partition topics."""

    async def publish(
        self,
        *,
        topic: str,
        partition_key: str,
        payload: JsonDict,
        connection_id: str | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        """Publishes a payload to the designated topic using the specified connection alias."""
        ...


class StitchReplicaPort(Protocol):
    """Port for querying local L2 materialized replica state."""

    async def get_by_key(
        self,
        *,
        connection_id: str,
        stream: str,
        record_key: str,
    ) -> JsonDict | None:
        """Queries an L2 replica record by its primary key."""
        ...


@dataclass(frozen=True, kw_only=True)
class TimeSlice:
    """Atomic daily partition slice for date-range windowing."""

    start: datetime
    end: datetime

    @property
    def start_iso(self) -> str:
        return self.start.isoformat()

    @property
    def end_iso(self) -> str:
        return self.end.isoformat()


@dataclass(frozen=True, kw_only=True)
class StitchContext:
    """Execution context injected into functional Stitches.

    Carries tenant identity, tracing, and strongly-typed infrastructure ports
    without requiring global singletons or decorator closures.
    """

    tenant_id: str
    trace_id: str
    now: datetime
    http: StitchHttpPort
    slicer: StitchTimeSlicerPort
    kafka: StitchKafkaPort
    replica: StitchReplicaPort
    connection_id: str | None = None
