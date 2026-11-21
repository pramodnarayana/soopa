"""Port protocol for universal analytical OLAP databases (ClickHouse / DuckDB)."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Protocol

from seedwork.domain.types import JsonValue


class OlapClientPort(Protocol):
    """Abstract outbound port for executing high-speed queries and batch inserts in OLAP systems."""

    async def execute_query(
        self,
        sql: str,
        params: Mapping[str, JsonValue] | None = None,
    ) -> list[dict[str, JsonValue]]:
        """Executes an analytical SQL query and returns rows as dictionaries."""
        ...

    async def insert_batch(
        self,
        table: str,
        records: Sequence[Mapping[str, JsonValue]],
    ) -> int:
        """Bulk inserts a batch of record mappings into the specified OLAP table.

        Returns the number of records inserted.
        """
        ...

    async def ping(self) -> bool:
        """Checks connectivity to the OLAP cluster."""
        ...

    async def close(self) -> None:
        """Closes underlying client sessions and connection pools."""
        ...
