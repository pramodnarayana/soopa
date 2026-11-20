"""Strongly-typed DTOs for SliceRange Stitch steps."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from seedwork.domain.types import JsonDict

from ip.engine.domain.exceptions import CodecError, IpError, Result


@dataclass(frozen=True, kw_only=True)
class SliceRangeStepInput:
    """Strongly-typed input DTO for generic range-slicing Stitch steps."""

    start_date: datetime
    end_date: datetime
    target_connections: tuple[str, ...]
    slice_unit: str = "DAYS"
    slice_size: int = 1
    filter_criteria: JsonDict = field(default_factory=dict)
    destination: JsonDict = field(default_factory=dict)

    @staticmethod
    def _parse_dates(data: JsonDict) -> Result[tuple[datetime, datetime], CodecError]:
        raw_start = data.get("start_date") or data.get("range_start") or data.get("from_date")
        raw_end = data.get("end_date") or data.get("range_end") or data.get("to_date")
        if not isinstance(raw_start, str) or not raw_start.strip():
            return Result.err(
                CodecError.with_message(
                    "SliceRangeStepInput requires a valid ISO start_date string."
                )
            )
        if not isinstance(raw_end, str) or not raw_end.strip():
            return Result.err(
                CodecError.with_message("SliceRangeStepInput requires a valid ISO end_date string.")
            )

        try:
            start_dt = datetime.fromisoformat(raw_start.strip().replace("Z", "+00:00"))
            end_dt = datetime.fromisoformat(raw_end.strip().replace("Z", "+00:00"))
        except (ValueError, TypeError) as exc:
            return Result.err(
                CodecError.with_message(
                    f"Failed to parse ISO datetime in SliceRangeStepInput: {exc}"
                )
            )

        if end_dt < start_dt:
            return Result.err(
                CodecError.with_message("end_date must be greater than or equal to start_date.")
            )
        return Result.ok((start_dt, end_dt))

    @staticmethod
    def _parse_connections(data: JsonDict) -> Result[tuple[str, ...], CodecError]:
        raw_conns = (
            data.get("target_connections")
            or data.get("target_connection_ids")
            or data.get("target_connection_id")
            or data.get("hes_connection_ids")
            or data.get("connections")
            or data.get("connection_ids")
            or data.get("connection_id")
        )
        connections: tuple[str, ...]
        if isinstance(raw_conns, str) and raw_conns.strip():
            connections = (raw_conns.strip(),)
        elif isinstance(raw_conns, (list, tuple)):
            connections = tuple(str(c).strip() for c in raw_conns if str(c).strip())
        else:
            connections = ()

        if not connections:
            return Result.err(
                CodecError.with_message(
                    "SliceRangeStepInput requires at least one target connection."
                )
            )
        return Result.ok(connections)

    @classmethod
    def from_payload(cls, data: JsonDict) -> Result[SliceRangeStepInput, IpError]:
        dates_res = cls._parse_dates(data)
        if dates_res.is_err or dates_res.value is None:
            return Result.err(dates_res.error or CodecError.with_message("Invalid date range"))
        start_dt, end_dt = dates_res.value

        conns_res = cls._parse_connections(data)
        if conns_res.is_err or conns_res.value is None:
            return Result.err(
                conns_res.error or CodecError.with_message("Invalid target connections")
            )
        connections = conns_res.value

        raw_unit = str(data.get("slice_unit", "DAYS")).strip().upper()
        if raw_unit not in ("DAY", "DAYS", "HOUR", "HOURS"):
            return Result.err(
                CodecError.with_message(
                    f"Unsupported slice_unit '{raw_unit}', must be DAYS or HOURS."
                )
            )

        raw_size = data.get("slice_size", 1)
        slice_size = (
            int(raw_size) if isinstance(raw_size, (int, float, str)) and int(raw_size) > 0 else 1
        )

        filter_criteria: JsonDict = (
            dict(data["filter_criteria"])
            if "filter_criteria" in data and isinstance(data["filter_criteria"], dict)
            else {}
        )
        raw_dest = data.get("destination")
        destination: JsonDict = dict(raw_dest) if isinstance(raw_dest, dict) else {}
        if "destination_connection_id" in data and "connection_id" not in destination:
            destination["connection_id"] = data["destination_connection_id"]
        if "destination_topic" in data and "topic" not in destination:
            destination["topic"] = data["destination_topic"]

        return Result.ok(
            cls(
                start_date=start_dt,
                end_date=end_dt,
                target_connections=connections,
                slice_unit=raw_unit,
                slice_size=slice_size,
                filter_criteria=filter_criteria,
                destination=destination,
            )
        )


@dataclass(frozen=True, kw_only=True)
class SliceTaskDTO:
    """Discrete sliced sub-task payload for a connection-specific extraction."""

    task_id: str
    connection_id: str
    slice_start: str
    slice_end: str
    filter_criteria: JsonDict = field(default_factory=dict)
    destination: JsonDict = field(default_factory=dict)

    @property
    def target_connection_id(self) -> str:
        """Alias for connection_id (the target connection to extract from)."""
        return self.connection_id

    @property
    def destination_connection_id(self) -> str | None:
        """Destination connection ID if configured in destination dict."""
        val = self.destination.get("connection_id") or self.destination.get(
            "destination_connection_id"
        )
        return str(val) if val is not None else None

    @property
    def destination_topic(self) -> str | None:
        """Destination topic if configured in destination dict."""
        val = self.destination.get("topic") or self.destination.get("destination_topic")
        return str(val) if val is not None else None

    @property
    def start_date(self) -> datetime:
        """Parses slice_start into a datetime object."""
        return datetime.fromisoformat(self.slice_start)

    @property
    def end_date(self) -> datetime:
        """Parses slice_end into a datetime object."""
        return datetime.fromisoformat(self.slice_end)

    def to_payload(self) -> JsonDict:
        return {
            "task_id": self.task_id,
            "connection_id": self.connection_id,
            "slice_start": self.slice_start,
            "slice_end": self.slice_end,
            "filter_criteria": dict(self.filter_criteria),
            "destination": dict(self.destination),
        }

    @classmethod
    def from_payload(cls, data: JsonDict) -> Result[SliceTaskDTO, IpError]:
        task_id = data.get("task_id")
        connection_id = data.get("connection_id")
        slice_start = data.get("slice_start")
        slice_end = data.get("slice_end")
        if (
            not isinstance(task_id, str)
            or not task_id.strip()
            or not isinstance(connection_id, str)
            or not connection_id.strip()
            or not isinstance(slice_start, str)
            or not slice_start.strip()
            or not isinstance(slice_end, str)
            or not slice_end.strip()
        ):
            return Result.err(
                CodecError.with_message(
                    "SliceTaskDTO requires non-empty task_id, connection_id, slice_start, and slice_end."
                )
            )
        raw_filter = data.get("filter_criteria")
        raw_dest = data.get("destination")
        return Result.ok(
            cls(
                task_id=task_id.strip(),
                connection_id=connection_id.strip(),
                slice_start=slice_start.strip(),
                slice_end=slice_end.strip(),
                filter_criteria=dict(raw_filter) if isinstance(raw_filter, dict) else {},
                destination=dict(raw_dest) if isinstance(raw_dest, dict) else {},
            )
        )


@dataclass(frozen=True, kw_only=True)
class SliceRangeStepOutput:
    """Strongly-typed output DTO containing decomposed slice tasks."""

    total_slices: int
    tasks: tuple[SliceTaskDTO, ...]

    def to_payload(self) -> JsonDict:
        return {
            "total_slices": self.total_slices,
            "tasks": [t.to_payload() for t in self.tasks],
        }

    @classmethod
    def from_payload(cls, data: JsonDict) -> Result[SliceRangeStepOutput, IpError]:
        raw_total = data.get("total_slices", 0)
        total_slices = int(raw_total) if isinstance(raw_total, (int, float, str)) else 0
        raw_tasks = data.get("tasks", [])
        tasks_list: list[SliceTaskDTO] = []
        if isinstance(raw_tasks, (list, tuple)):
            for t in raw_tasks:
                if isinstance(t, dict):
                    task_res = SliceTaskDTO.from_payload(t)
                    if task_res.is_err:
                        return Result.err(task_res.unwrap_err())
                    tasks_list.append(task_res.unwrap())
        return Result.ok(
            cls(
                total_slices=total_slices or len(tasks_list),
                tasks=tuple(tasks_list),
            )
        )


__all__ = [
    "SliceRangeStepInput",
    "SliceRangeStepOutput",
    "SliceTaskDTO",
]
