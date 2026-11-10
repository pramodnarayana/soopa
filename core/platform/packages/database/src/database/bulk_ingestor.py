"""
High-Velocity Bulk Record Ingestor (`bulk_ingestor`).

Provides capability-named batch persistence (`1,000-50,000` rows per commit)
inside an RLS-isolated session (`platform.current_tenant_id`), keeping callers
decoupled from underlying binary wire transport mechanics.
"""

from __future__ import annotations

import re
import secrets
from collections.abc import Sequence
from datetime import date, datetime
from datetime import time as dt_time
from decimal import Decimal
from typing import Final, Protocol
from uuid import UUID

import structlog
from sqlalchemy import text

from database.constants import MAX_PG_IDENTIFIER_LENGTH
from database.types import TenantSession

logger = structlog.get_logger(__name__)

_PG_IDENTIFIER_RE: Final[re.Pattern[str]] = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")
BulkScalarValue = (
    str | int | float | bool | bytes | Decimal | date | datetime | dt_time | UUID | None
)


def validate_sql_identifier(identifier: str) -> str:
    """Strictly validate a schema, table, or column identifier against injection."""
    if (
        not identifier
        or len(identifier) > MAX_PG_IDENTIFIER_LENGTH
        or _PG_IDENTIFIER_RE.match(identifier) is None
    ):
        raise ValueError(f"Unsafe SQL identifier: '{identifier}'")
    return identifier


class BulkRecordIngestorPort(Protocol):
    """Abstract capability Port for high-throughput micro-batch persistence."""

    async def ingest_batch(
        self,
        *,
        tenant_id: str,
        table_name: str,
        columns: Sequence[str],
        records: Sequence[Sequence[BulkScalarValue]],
        schema_name: str = "public",
    ) -> int: ...


class SqlAlchemyBulkRecordIngestor(BulkRecordIngestorPort):
    """Streams bulk tuples over the underlying driver binary protocol in an RLS transaction."""

    def __init__(self, session: TenantSession) -> None:
        self._session = session

    async def ingest_batch(
        self,
        *,
        tenant_id: str,
        table_name: str,
        columns: Sequence[str],
        records: Sequence[Sequence[BulkScalarValue]],
        schema_name: str = "public",
    ) -> int:
        safe_schema = validate_sql_identifier(schema_name)
        safe_table = validate_sql_identifier(table_name)
        safe_columns = [validate_sql_identifier(col) for col in columns]

        if not records:
            logger.debug(
                "bulk_record_batch_skipped_empty",
                tenant_id=tenant_id,
                schema_name=safe_schema,
                table_name=safe_table,
            )
            return 0
        if not safe_columns:
            raise ValueError("columns must be non-empty for bulk ingestion")

        await self._session.execute(
            text("SELECT set_config('platform.current_tenant_id', :tenant_id, true)"),
            {"tenant_id": tenant_id},
        )
        sa_conn = await self._session.connection()
        raw_conn = await sa_conn.get_raw_connection()
        driver_conn = raw_conn.driver_connection
        if driver_conn is None:
            raise RuntimeError("Underlying asyncpg driver connection is unavailable")

        if safe_schema == "pg_temp":
            await driver_conn.copy_records_to_table(
                safe_table,
                records=records,
                columns=safe_columns,
                schema_name=safe_schema,
            )
        else:
            safe_base = safe_table[:47]
            staging_table = f"_stage_{safe_base}_{secrets.token_hex(4)}"
            await self._session.execute(
                text(
                    f'CREATE TEMP TABLE "{staging_table}" '
                    f'(LIKE "{safe_schema}"."{safe_table}" INCLUDING DEFAULTS) ON COMMIT DROP'
                )
            )
            try:
                await driver_conn.copy_records_to_table(
                    staging_table,
                    records=records,
                    columns=safe_columns,
                    schema_name="pg_temp",
                )
                cols_clause = ", ".join(f'"{c}"' for c in safe_columns)
                await self._session.execute(
                    text(
                        f'INSERT INTO "{safe_schema}"."{safe_table}" ({cols_clause}) '  # noqa: S608 - Dynamic SQL uses pre-validated identifiers to preserve RLS evaluation
                        f'SELECT {cols_clause} FROM "{staging_table}"'
                    )
                )
            finally:
                await self._session.execute(text(f'DROP TABLE IF EXISTS "{staging_table}"'))
        row_count = len(records)
        logger.info(
            "bulk_record_batch_ingested",
            tenant_id=tenant_id,
            schema_name=safe_schema,
            table_name=safe_table,
            row_count=row_count,
        )
        return row_count


__all__ = [
    "BulkRecordIngestorPort",
    "SqlAlchemyBulkRecordIngestor",
    "validate_sql_identifier",
]
