from __future__ import annotations

from datetime import date

import pytest

from database.bulk_ingestor import validate_sql_identifier
from database.constants import PartitionCadence, PartitionDetachStatus
from database.partition_manager import (
    RangePartitionLifecycleManager,
    build_partition_spec,
)


class _FakeDdlExecutor:
    def __init__(
        self,
        existing_partitions: set[str] | None = None,
        attachments: dict[str, tuple[bool, bool]] | None = None,
    ) -> None:
        self.existing: set[str] = set(existing_partitions or set())
        self.attachments: dict[str, tuple[bool, bool]] = dict(attachments or {})
        self.statements: list[str] = []

    async def partition_exists(self, schema_name: str, partition_table: str) -> bool:
        return f"{schema_name}.{partition_table}" in self.existing

    async def get_partition_attachment(
        self, schema_name: str, parent_table: str, partition_table: str
    ) -> tuple[bool, bool]:
        return self.attachments.get(
            f"{schema_name}.{parent_table}->{partition_table}",
            (True, False),
        )

    async def execute_ddl(self, sql_statement: str) -> None:
        self.statements.append(sql_statement)


def test_build_partition_spec_generates_deterministic_bounds() -> None:
    daily = build_partition_spec(
        schema_name="public",
        parent_table="outbox_messages",
        anchor_date=date(2026, 11, 10),
        cadence=PartitionCadence.DAILY,
    )
    assert daily.partition_table == "outbox_messages_p20261110"
    assert daily.range_start == date(2026, 11, 10)
    assert daily.range_end == date(2026, 11, 11)

    monthly = build_partition_spec(
        schema_name="notifications",
        parent_table="notification_records",
        anchor_date=date(2026, 12, 19),
        cadence=PartitionCadence.MONTHLY,
    )
    assert monthly.partition_table == "notification_records_p202612"
    assert monthly.range_start == date(2026, 12, 1)
    assert monthly.range_end == date(2027, 1, 1)

    monthly_june = build_partition_spec(
        schema_name="notifications",
        parent_table="notification_records",
        anchor_date=date(2026, 6, 15),
        cadence=PartitionCadence.MONTHLY,
    )
    assert monthly_june.range_end == date(2026, 7, 1)

    weekly = build_partition_spec(
        schema_name="public",
        parent_table="workflow_runs",
        anchor_date=date(2026, 11, 12),
        cadence=PartitionCadence.WEEKLY,
    )
    assert weekly.partition_table == "workflow_runs_p2026w46"
    assert weekly.range_start == date(2026, 11, 9)
    assert weekly.range_end == date(2026, 11, 16)


def test_validate_sql_identifier_blocks_unsafe_names() -> None:
    assert validate_sql_identifier("outbox_messages_p20261110") == "outbox_messages_p20261110"
    with pytest.raises(ValueError, match="Unsafe SQL identifier"):
        validate_sql_identifier("outbox; DROP TABLE users;--")
    with pytest.raises(ValueError, match="Unsafe SQL identifier"):
        validate_sql_identifier("a" * 64)


@pytest.mark.asyncio
async def test_partition_lifecycle_detaches_concurrently_before_drop() -> None:
    executor = _FakeDdlExecutor(existing_partitions={"public.outbox_messages_p20261001"})
    manager = RangePartitionLifecycleManager(ddl_executor=executor)

    spec = build_partition_spec(
        schema_name="public",
        parent_table="outbox_messages",
        anchor_date=date(2026, 11, 10),
        cadence=PartitionCadence.DAILY,
    )
    await manager.ensure_partition(spec)
    assert "CREATE TABLE IF NOT EXISTS" in executor.statements[0]
    assert "PARTITION OF" in executor.statements[0]

    archived: list[str] = []

    async def _archive_hook(schema_name: str, partition_table: str) -> None:
        archived.append(f"{schema_name}.{partition_table}")

    outcome = await manager.retire_partition_non_blocking(
        schema_name="public",
        parent_table="outbox_messages",
        partition_table="outbox_messages_p20261001",
        archive_callback=_archive_hook,
    )
    assert outcome.status == PartitionDetachStatus.DETACHED
    assert archived == ["public.outbox_messages_p20261001"]
    assert (
        executor.statements[1]
        == 'ALTER TABLE "public"."outbox_messages" DETACH PARTITION "public"."outbox_messages_p20261001" CONCURRENTLY'
    )
    assert executor.statements[2] == 'DROP TABLE IF EXISTS "public"."outbox_messages_p20261001"'

    missing_outcome = await manager.retire_partition_non_blocking(
        schema_name="public",
        parent_table="outbox_messages",
        partition_table="outbox_messages_p19990101",
    )
    assert missing_outcome.status == PartitionDetachStatus.NOT_FOUND


@pytest.mark.asyncio
async def test_partition_lifecycle_finalizes_pending_detach() -> None:
    executor = _FakeDdlExecutor(
        existing_partitions={"public.outbox_messages_p20260901"},
        attachments={"public.outbox_messages->outbox_messages_p20260901": (True, True)},
    )
    manager = RangePartitionLifecycleManager(ddl_executor=executor)

    outcome = await manager.retire_partition_non_blocking(
        schema_name="public",
        parent_table="outbox_messages",
        partition_table="outbox_messages_p20260901",
    )
    assert outcome.status == PartitionDetachStatus.DETACHED
    assert (
        executor.statements[0]
        == 'ALTER TABLE "public"."outbox_messages" DETACH PARTITION "public"."outbox_messages_p20260901" FINALIZE'
    )
    assert executor.statements[1] == 'DROP TABLE IF EXISTS "public"."outbox_messages_p20260901"'


@pytest.mark.asyncio
async def test_partition_lifecycle_drops_already_detached_partition() -> None:
    executor = _FakeDdlExecutor(
        existing_partitions={"public.outbox_messages_p20260801"},
        attachments={"public.outbox_messages->outbox_messages_p20260801": (False, False)},
    )
    manager = RangePartitionLifecycleManager(ddl_executor=executor)

    outcome = await manager.retire_partition_non_blocking(
        schema_name="public",
        parent_table="outbox_messages",
        partition_table="outbox_messages_p20260801",
    )
    assert outcome.status == PartitionDetachStatus.DETACHED
    assert len(executor.statements) == 1
    assert executor.statements[0] == 'DROP TABLE IF EXISTS "public"."outbox_messages_p20260801"'
