"""Provider factory for analytical OLAP clients."""

from __future__ import annotations

import os

from database.olap.adapters.clickhouse_adapter import ClickHouseHttpAdapter
from database.olap.adapters.in_memory_olap_adapter import InMemoryOlapAdapter
from database.olap.ports.olap_client_port import OlapClientPort


class OlapProvider:
    """Factory for resolving and instantiating the OlapClientPort."""

    @staticmethod
    def create_client(
        endpoint_url: str | None = None,
        database: str | None = None,
        user: str | None = None,
        password: str | None = None,
        use_in_memory: bool = False,
    ) -> OlapClientPort:
        if use_in_memory:
            return InMemoryOlapAdapter()

        url = (
            endpoint_url
            or os.getenv("CLICKHOUSE_URL")
            or os.getenv("OLAP_ENDPOINT_URL")
            or "http://localhost:8123"
        )
        db = database or os.getenv("CLICKHOUSE_DATABASE") or os.getenv("OLAP_DATABASE") or "default"
        usr = user or os.getenv("CLICKHOUSE_USER") or os.getenv("OLAP_USER") or "default"
        pwd = password or os.getenv("CLICKHOUSE_PASSWORD") or os.getenv("OLAP_PASSWORD") or ""

        return ClickHouseHttpAdapter(
            endpoint_url=url,
            database=db,
            user=usr,
            password=pwd,
        )
