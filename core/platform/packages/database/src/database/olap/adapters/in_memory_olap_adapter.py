"""In-memory OLAP adapter implementing OlapClientPort for fast unit testing."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence

from seedwork.domain.types import JsonValue

from database.olap.ports.olap_client_port import OlapClientPort


class InMemoryOlapAdapter(OlapClientPort):
    """In-memory OLAP store implementing OlapClientPort with basic query support for unit tests."""

    def __init__(self) -> None:
        self.tables: dict[str, list[dict[str, JsonValue]]] = {}
        self.is_connected: bool = True

    async def ping(self) -> bool:
        return self.is_connected

    async def insert_batch(
        self,
        table: str,
        records: Sequence[Mapping[str, JsonValue]],
    ) -> int:
        if table not in self.tables:
            self.tables[table] = []
        for rec in records:
            self.tables[table].append(dict(rec))
        return len(records)

    def _get_table_rows(self, raw_table_name: str) -> list[dict[str, JsonValue]]:
        if raw_table_name in self.tables:
            return self.tables[raw_table_name]
        short_name = raw_table_name.split(".")[-1]
        if short_name in self.tables:
            return self.tables[short_name]
        for key, val in self.tables.items():
            if key.split(".")[-1] == short_name:
                return val
        return []

    async def execute_query(
        self,
        sql: str,
        params: Mapping[str, JsonValue] | None = None,
    ) -> list[dict[str, JsonValue]]:
        normalized = sql.strip().replace("\n", " ")

        # Check for count(*) query
        if "count(*)" in normalized.lower():
            # Extract table name
            match = re.search(r"from\s+([a-zA-Z0-9_\.]+)", normalized, re.IGNORECASE)
            table_name = match.group(1) if match else "default"
            rows = self._get_table_rows(table_name)
            filtered = self._apply_where(rows, normalized, params)
            return [{"count()": len(filtered), "count": len(filtered)}]

        # Standard SELECT query
        match = re.search(r"from\s+([a-zA-Z0-9_\.]+)", normalized, re.IGNORECASE)
        table_name = match.group(1) if match else "default"
        rows = list(self._get_table_rows(table_name))

        # Filter
        rows = self._apply_where(rows, normalized, params)

        # Sort
        order_match = re.search(
            r"order\s+by\s+([a-zA-Z0-9_]+)\s*(asc|desc)?", normalized, re.IGNORECASE
        )
        if order_match:
            col = order_match.group(1)
            descending = (order_match.group(2) or "asc").lower() == "desc"
            rows.sort(key=lambda r: str(r.get(col, "")), reverse=descending)

        # Limit / Offset
        offset = 0
        limit = len(rows)
        offset_match = re.search(r"offset\s+(\d+)", normalized, re.IGNORECASE)
        if offset_match:
            offset = int(offset_match.group(1))

        limit_match = re.search(r"limit\s+(\d+)", normalized, re.IGNORECASE)
        if limit_match:
            limit = int(limit_match.group(1))

        return rows[offset : offset + limit]

    def _apply_where(
        self,
        rows: list[dict[str, JsonValue]],
        sql: str,
        params: Mapping[str, JsonValue] | None,
    ) -> list[dict[str, JsonValue]]:
        where_match = re.search(r"where\s+(.*?)(order\s+by|limit|group\s+by|$)", sql, re.IGNORECASE)
        if not where_match:
            return rows

        where_clause = where_match.group(1).strip()
        filtered = rows

        # Handle simple AND conditions: col = 'val' or col = {param:String} or col = %(param)s
        conditions = re.split(r"\s+and\s+", where_clause, flags=re.IGNORECASE)
        for cond in conditions:
            # Check equality: col = 'value'
            eq_match = re.search(r"([a-zA-Z0-9_]+)\s*=\s*'([^']*)'", cond)
            if eq_match:
                col, val = eq_match.group(1), eq_match.group(2)
                filtered = [r for r in filtered if str(r.get(col)) == val]
                continue

            # Check parameterized equality: col = {param:Type} or %(param)s
            param_match = re.search(
                r"([a-zA-Z0-9_]+)\s*=\s*(?:\{([a-zA-Z0-9_]+):[a-zA-Z0-9_]+\}|%\(([a-zA-Z0-9_]+)\)s)",
                cond,
            )
            if param_match and params:
                col = param_match.group(1)
                param_name = param_match.group(2) or param_match.group(3)
                if param_name in params:
                    expected_val = str(params[param_name])
                    filtered = [r for r in filtered if str(r.get(col)) == expected_val]

        return filtered

    async def close(self) -> None:
        pass
