"""Universal OLAP Analytical Database Capability (ClickHouse / DuckDB)."""

from database.olap.adapters.clickhouse_adapter import ClickHouseHttpAdapter
from database.olap.adapters.in_memory_olap_adapter import InMemoryOlapAdapter
from database.olap.domain.exceptions import (
    OlapConnectionError,
    OlapError,
    OlapQueryError,
)
from database.olap.ports.olap_client_port import OlapClientPort
from database.olap.provider import OlapProvider

__all__ = [
    "ClickHouseHttpAdapter",
    "InMemoryOlapAdapter",
    "OlapClientPort",
    "OlapConnectionError",
    "OlapError",
    "OlapProvider",
    "OlapQueryError",
]
