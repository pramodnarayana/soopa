"""ClickHouse HTTP analytical database adapter implementing OlapClientPort."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence

import httpx
import structlog
from seedwork.domain.types import JsonValue

from database.olap.domain.exceptions import OlapConnectionError, OlapQueryError
from database.olap.ports.olap_client_port import OlapClientPort

logger = structlog.get_logger(__name__)


class ClickHouseHttpAdapter(OlapClientPort):
    """High-throughput ClickHouse OLAP adapter communicating over HTTP.

    Supports sub-20ms sparse index lookups and streaming JSONEachRow micro-batch inserts.
    """

    def __init__(
        self,
        endpoint_url: str = "http://localhost:8123",
        database: str = "default",
        user: str = "default",
        password: str = "",
        timeout_seconds: float = 30.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._endpoint_url = endpoint_url.rstrip("/")
        self._database = database
        self._user = user
        self._password = password
        self._timeout_seconds = timeout_seconds
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(timeout=timeout_seconds)

    def _headers(self) -> dict[str, str]:
        headers: dict[str, str] = {
            "X-ClickHouse-Database": self._database,
        }
        if self._user:
            headers["X-ClickHouse-User"] = self._user
        if self._password:
            headers["X-ClickHouse-Key"] = self._password
        return headers

    async def ping(self) -> bool:
        try:
            resp = await self._client.get(
                f"{self._endpoint_url}/ping",
                headers=self._headers(),
                timeout=5.0,
            )
            return resp.status_code == 200 and resp.text.strip() == "Ok."
        except (httpx.HTTPError, OSError) as exc:
            logger.warning("clickhouse_ping_failed", error=str(exc))
            return False

    async def execute_query(
        self,
        sql: str,
        params: Mapping[str, JsonValue] | None = None,
    ) -> list[dict[str, JsonValue]]:
        url_params: dict[str, str] = {
            "database": self._database,
            "default_format": "JSON",
        }
        if params:
            for k, v in params.items():
                url_params[f"param_{k}"] = json.dumps(v) if isinstance(v, (dict, list)) else str(v)

        try:
            response = await self._client.post(
                self._endpoint_url,
                params=url_params,
                headers=self._headers(),
                content=sql.encode("utf-8"),
            )
        except httpx.RequestError as exc:
            raise OlapConnectionError(f"ClickHouse connection failed: {exc}") from exc

        if response.status_code != 200:
            error_body = response.text
            raise OlapQueryError(
                f"ClickHouse query error ({response.status_code}): {error_body}",
                query=sql,
            )

        try:
            data = response.json()
            raw_rows = data.get("data", [])
            results: list[dict[str, JsonValue]] = []
            for row in raw_rows:
                if isinstance(row, dict):
                    results.append(row)
            return results
        except Exception as exc:
            raise OlapQueryError(
                f"Failed to parse ClickHouse JSON response: {exc}", query=sql
            ) from exc

    async def insert_batch(
        self,
        table: str,
        records: Sequence[Mapping[str, JsonValue]],
    ) -> int:
        if not records:
            return 0

        # ClickHouse JSONEachRow: newline-delimited JSON objects
        lines = [json.dumps(dict(rec)) for rec in records]
        body = "\n".join(lines).encode("utf-8")

        url_params = {
            "database": self._database,
            "query": f"INSERT INTO {table} FORMAT JSONEachRow",
        }

        try:
            response = await self._client.post(
                self._endpoint_url,
                params=url_params,
                headers=self._headers(),
                content=body,
            )
        except httpx.RequestError as exc:
            raise OlapConnectionError(f"ClickHouse batch insert connection failed: {exc}") from exc

        if response.status_code != 200:
            raise OlapQueryError(
                f"ClickHouse batch insert failed ({response.status_code}): {response.text}",
                query=f"INSERT INTO {table}",
            )

        return len(records)

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()
