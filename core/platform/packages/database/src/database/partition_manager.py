"""
PostgreSQL Declarative Range Partition Provisioning & Non-Blocking Lifecycle Manager.

Keeps active B-Tree indexes inside RAM and eliminates `DELETE` / Autovacuum write
amplification by detaching expired partitions with `CONCURRENTLY` before archival
and `DROP TABLE`, avoiding `ACCESS EXCLUSIVE` locks on hot parent tables.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Protocol

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from database.bulk_ingestor import validate_sql_identifier
from database.constants import PartitionCadence, PartitionDetachStatus

logger = structlog.get_logger(__name__)

ArchivePartitionHook = Callable[[str, str], Awaitable[None]]


@dataclass(frozen=True)
class PartitionSpecDTO:
    """Specification for a single declarative PostgreSQL range partition."""

    schema_name: str
    parent_table: str
    partition_table: str
    range_start: date
    range_end: date


@dataclass(frozen=True)
class PartitionDetachOutcome:
    """First-class result of a non-blocking `DETACH PARTITION CONCURRENTLY` operation."""

    status: PartitionDetachStatus
    schema_name: str
    parent_table: str
    partition_table: str


class PartitionDdlExecutorPort(Protocol):
    """Port abstracting PostgreSQL catalog inspection and autocommit DDL execution."""

    async def partition_exists(self, schema_name: str, partition_table: str) -> bool: ...

    async def execute_ddl(self, sql_statement: str) -> None: ...


class SqlAlchemyPartitionDdlExecutor(PartitionDdlExecutorPort):
    """Executes `DETACH PARTITION CONCURRENTLY` outside transaction blocks via `AUTOCOMMIT`."""

    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def partition_exists(self, schema_name: str, partition_table: str) -> bool:
        safe_schema = validate_sql_identifier(schema_name)
        safe_table = validate_sql_identifier(partition_table)
        stmt = text(
            """
            SELECT EXISTS (
                SELECT 1
                FROM pg_catalog.pg_class c
                JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
                WHERE n.nspname = :schema_name
                  AND c.relname = :table_name
            )
            """
        )
        async with self._engine.connect() as conn:
            result = await conn.execute(
                stmt, {"schema_name": safe_schema, "table_name": safe_table}
            )
            return bool(result.scalar())

    async def execute_ddl(self, sql_statement: str) -> None:
        # PostgreSQL requires `DETACH PARTITION ... CONCURRENTLY` to run in AUTOCOMMIT mode.
        async with self._engine.connect() as conn:
            autocommit_conn = await conn.execution_options(isolation_level="AUTOCOMMIT")
            await autocommit_conn.execute(text(sql_statement))


def build_partition_spec(
    *,
    schema_name: str,
    parent_table: str,
    anchor_date: date,
    cadence: PartitionCadence,
) -> PartitionSpecDTO:
    """Compute canonical partition name and `[range_start, range_end)` bounds."""
    safe_schema = validate_sql_identifier(schema_name)
    safe_parent = validate_sql_identifier(parent_table)

    if cadence == PartitionCadence.DAILY:
        range_start = anchor_date
        range_end = anchor_date + timedelta(days=1)
        suffix = anchor_date.strftime("p%Y%m%d")
    elif cadence == PartitionCadence.WEEKLY:
        iso_weekday = anchor_date.weekday()
        range_start = anchor_date - timedelta(days=iso_weekday)
        range_end = range_start + timedelta(days=7)
        iso_year, iso_week, _ = range_start.isocalendar()
        suffix = f"p{iso_year}w{iso_week:02d}"
    else:
        range_start = date(anchor_date.year, anchor_date.month, 1)
        if anchor_date.month == 12:
            range_end = date(anchor_date.year + 1, 1, 1)
        else:
            range_end = date(anchor_date.year, anchor_date.month + 1, 1)
        suffix = range_start.strftime("p%Y%m")

    partition_table = validate_sql_identifier(f"{safe_parent}_{suffix}")
    return PartitionSpecDTO(
        schema_name=safe_schema,
        parent_table=safe_parent,
        partition_table=partition_table,
        range_start=range_start,
        range_end=range_end,
    )


class RangePartitionLifecycleManager:
    """Manages time-partition creation and zero-lock concurrent partition retirement."""

    def __init__(self, ddl_executor: PartitionDdlExecutorPort) -> None:
        self._ddl = ddl_executor

    async def ensure_partition(self, spec: PartitionSpecDTO) -> None:
        """Idempotently attach a future or current range partition."""
        safe_schema = validate_sql_identifier(spec.schema_name)
        safe_parent = validate_sql_identifier(spec.parent_table)
        safe_part = validate_sql_identifier(spec.partition_table)
        start_iso = spec.range_start.isoformat()
        end_iso = spec.range_end.isoformat()

        ddl = (
            f'CREATE TABLE IF NOT EXISTS "{safe_schema}"."{safe_part}" '
            f'PARTITION OF "{safe_schema}"."{safe_parent}" '
            f"FOR VALUES FROM ('{start_iso}') TO ('{end_iso}')"
        )
        await self._ddl.execute_ddl(ddl)
        logger.info(
            "range_partition_ensured",
            schema_name=safe_schema,
            parent_table=safe_parent,
            partition_table=safe_part,
            range_start=start_iso,
            range_end=end_iso,
        )

    async def retire_partition_non_blocking(
        self,
        *,
        schema_name: str,
        parent_table: str,
        partition_table: str,
        archive_callback: ArchivePartitionHook | None = None,
    ) -> PartitionDetachOutcome:
        """Detach partition with `CONCURRENTLY`, optionally archive to Parquet, then `DROP`."""
        safe_schema = validate_sql_identifier(schema_name)
        safe_parent = validate_sql_identifier(parent_table)
        safe_part = validate_sql_identifier(partition_table)

        exists = await self._ddl.partition_exists(safe_schema, safe_part)
        if not exists:
            logger.info(
                "range_partition_retire_skipped_not_found",
                schema_name=safe_schema,
                parent_table=safe_parent,
                partition_table=safe_part,
            )
            return PartitionDetachOutcome(
                status=PartitionDetachStatus.NOT_FOUND,
                schema_name=safe_schema,
                parent_table=safe_parent,
                partition_table=safe_part,
            )

        detach_sql = (
            f'ALTER TABLE "{safe_schema}"."{safe_parent}" '
            f'DETACH PARTITION "{safe_schema}"."{safe_part}" CONCURRENTLY'
        )
        await self._ddl.execute_ddl(detach_sql)

        if archive_callback is not None:
            await archive_callback(safe_schema, safe_part)

        drop_sql = f'DROP TABLE IF EXISTS "{safe_schema}"."{safe_part}"'
        await self._ddl.execute_ddl(drop_sql)

        logger.info(
            "range_partition_retired",
            schema_name=safe_schema,
            parent_table=safe_parent,
            partition_table=safe_part,
            archived=archive_callback is not None,
        )
        return PartitionDetachOutcome(
            status=PartitionDetachStatus.DETACHED,
            schema_name=safe_schema,
            parent_table=safe_parent,
            partition_table=safe_part,
        )


__all__ = [
    "ArchivePartitionHook",
    "PartitionDdlExecutorPort",
    "PartitionDetachOutcome",
    "PartitionSpecDTO",
    "RangePartitionLifecycleManager",
    "SqlAlchemyPartitionDdlExecutor",
    "build_partition_spec",
]
