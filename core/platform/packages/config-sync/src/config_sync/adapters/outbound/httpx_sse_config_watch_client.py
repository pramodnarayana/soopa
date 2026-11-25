"""Outbound HTTPS/SSE Dynamic Watch client implementing ConfigWatchClientPort."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from dataclasses import dataclass

import httpx
import structlog
from seedwork.domain.exceptions import Result
from seedwork.domain.types import JsonDict

from config_sync.domain.dtos import (
    ConfigDeltaEvent,
    ConfigEntityRecord,
    ConfigSnapshot,
    ConfigSyncError,
    ConfigWatchHeartbeat,
)
from config_sync.domain.enums import (
    ConfigChangeAction,
    ConfigSyncErrorCode,
    ConfigWatchEventType,
)
from config_sync.ports.config_watch_client_port import ConfigWatchClientPort, WatchStreamItem

logger = structlog.get_logger(__name__)


@dataclass
class _SnapshotAccumulator:
    app_id: str
    tenant_id: str
    base_version: int
    entities: list[ConfigEntityRecord]


def _http_status_to_error_code(status_code: int) -> ConfigSyncErrorCode:
    if status_code in (401, 403):
        return ConfigSyncErrorCode.UNAUTHORIZED
    if status_code == 404:
        return ConfigSyncErrorCode.UNKNOWN_APP
    return ConfigSyncErrorCode.STREAM_DISCONNECTED


def _parse_entity_record(raw: object) -> ConfigEntityRecord | None:
    if not isinstance(raw, dict):
        return None
    entity_type = raw.get("entity_type")
    entity_id = raw.get("entity_id")
    tenant_id = raw.get("tenant_id")
    checksum = raw.get("checksum")
    payload = raw.get("payload")
    if (
        not isinstance(entity_type, str)
        or not isinstance(entity_id, str)
        or not isinstance(tenant_id, str)
        or not isinstance(checksum, str)
        or not isinstance(payload, dict)
    ):
        return None
    return ConfigEntityRecord(
        entity_type=entity_type,
        entity_id=entity_id,
        tenant_id=tenant_id,
        checksum=checksum,
        payload=dict(payload),
    )


def _parse_delta(data: JsonDict) -> Result[ConfigDeltaEvent, ConfigSyncError]:
    raw_version = data.get("version")
    if not isinstance(raw_version, int):
        return Result.fail(
            ConfigSyncError(
                code=ConfigSyncErrorCode.INVALID_FRAME,
                message=f"Delta version must be int, got {type(raw_version).__name__}.",
            )
        )
    raw_payload = data.get("payload")
    if not isinstance(raw_payload, dict):
        return Result.fail(
            ConfigSyncError(
                code=ConfigSyncErrorCode.INVALID_FRAME,
                message="Delta payload must be a JSON object.",
            )
        )
    try:
        action = ConfigChangeAction(str(data.get("action", "")))
    except ValueError:
        return Result.fail(
            ConfigSyncError(
                code=ConfigSyncErrorCode.INVALID_FRAME,
                message=f"Unsupported delta action: {data.get('action')!r}.",
            )
        )
    return Result.ok(
        ConfigDeltaEvent(
            event_id=str(data.get("event_id", "")),
            app_id=str(data.get("app_id", "")),
            tenant_id=str(data.get("tenant_id", "")),
            entity_type=str(data.get("entity_type", "")),
            entity_id=str(data.get("entity_id", "")),
            action=action,
            version=raw_version,
            checksum=str(data.get("checksum", "")),
            payload=dict(raw_payload),
        )
    )


class HttpxSseConfigWatchClient(ConfigWatchClientPort):
    """Outbound-only HTTPS (Port 443) Server-Sent Events watch client for Data Plane shards.

    Treats all known HTTP and framing errors as first-class `ConfigSyncError` values
    (never raising exceptions for expected HTTP 4xx/5xx or malformed payload outcomes).
    """

    def __init__(
        self,
        *,
        base_url: str,
        bearer_token: str | None = None,
        timeout_seconds: float = 45.0,
        http_transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._bearer_token = bearer_token
        self._timeout = httpx.Timeout(connect=10.0, read=timeout_seconds, write=10.0, pool=10.0)
        self._http_transport = http_transport

    def _build_headers(self) -> dict[str, str]:
        headers = {
            "Accept": "text/event-stream",
            "Cache-Control": "no-cache",
        }
        if self._bearer_token:
            headers["Authorization"] = f"Bearer {self._bearer_token}"
        return headers

    async def fetch_snapshot(
        self,
        *,
        app_id: str,
        tenant_id: str,
    ) -> Result[ConfigSnapshot, ConfigSyncError]:
        """Performs a one-shot HTTPS snapshot fetch returning a first-class Result."""
        url = f"{self._base_url}/api/v1/internal/{app_id}/config/snapshot"
        headers: dict[str, str] = {"Accept": "application/json"}
        if self._bearer_token:
            headers["Authorization"] = f"Bearer {self._bearer_token}"

        try:
            async with httpx.AsyncClient(
                transport=self._http_transport,
                timeout=self._timeout,
            ) as client:
                response = await client.get(url, params={"tenant_id": tenant_id}, headers=headers)
        except httpx.HTTPError as exc:
            logger.error(
                "config_snapshot_transport_error",
                app_id=app_id,
                tenant_id=tenant_id,
                error=str(exc),
            )
            return Result.fail(
                ConfigSyncError(
                    code=ConfigSyncErrorCode.STREAM_DISCONNECTED,
                    message=f"Transport error fetching snapshot for {app_id}/{tenant_id}: {exc}",
                )
            )

        if response.is_error:
            logger.error(
                "config_snapshot_http_error",
                app_id=app_id,
                tenant_id=tenant_id,
                status_code=response.status_code,
            )
            return Result.fail(
                ConfigSyncError(
                    code=_http_status_to_error_code(response.status_code),
                    message=f"Config snapshot rejected with HTTP {response.status_code} for {app_id}/{tenant_id}.",
                )
            )

        try:
            parsed = response.json()
        except ValueError as exc:
            logger.error("config_snapshot_invalid_json", app_id=app_id, tenant_id=tenant_id)
            return Result.fail(
                ConfigSyncError(
                    code=ConfigSyncErrorCode.INVALID_FRAME,
                    message=f"Invalid JSON in snapshot response: {exc}",
                )
            )

        if not isinstance(parsed, dict):
            return Result.fail(
                ConfigSyncError(
                    code=ConfigSyncErrorCode.INVALID_FRAME,
                    message="Config snapshot response must be a JSON object.",
                )
            )

        raw_entities = parsed.get("entities", [])
        entities: list[ConfigEntityRecord] = []
        if isinstance(raw_entities, list):
            for raw_rec in raw_entities:
                rec = _parse_entity_record(raw_rec)
                if rec is not None:
                    entities.append(rec)
        raw_ver = parsed.get("version", 0)
        return Result.ok(
            ConfigSnapshot(
                app_id=str(parsed.get("app_id", app_id)),
                tenant_id=str(parsed.get("tenant_id", tenant_id)),
                version=int(raw_ver) if isinstance(raw_ver, int) else 0,
                entities=tuple(entities),
                checksum=str(parsed.get("checksum", "")),
            )
        )

    async def watch(
        self,
        *,
        app_id: str,
        tenant_id: str,
        since_version: int = 0,
    ) -> AsyncIterator[WatchStreamItem]:
        url = f"{self._base_url}/api/v1/internal/{app_id}/config/watch"
        params: dict[str, str | int] = {
            "tenant_id": tenant_id,
            "since_version": since_version,
        }

        try:
            async with (
                httpx.AsyncClient(
                    transport=self._http_transport,
                    timeout=self._timeout,
                ) as client,
                client.stream("GET", url, params=params, headers=self._build_headers()) as response,
            ):
                if response.is_error:
                    body = await response.aread()
                    detail = body.decode("utf-8", errors="replace")[:256]
                    logger.error(
                        "config_watch_http_error",
                        app_id=app_id,
                        tenant_id=tenant_id,
                        status_code=response.status_code,
                        detail=detail,
                    )
                    yield ConfigSyncError(
                        code=_http_status_to_error_code(response.status_code),
                        message=f"Config watch rejected with HTTP {response.status_code} for {app_id}/{tenant_id}.",
                    )
                    return

                event_name: str | None = None
                data_lines: list[str] = []
                accumulator: _SnapshotAccumulator | None = None

                async for line in response.aiter_lines():
                    if line == "":
                        if event_name and data_lines:
                            item, accumulator = self._handle_sse_frame(
                                event_name=event_name,
                                raw_data="\n".join(data_lines),
                                accumulator=accumulator,
                                app_id=app_id,
                                tenant_id=tenant_id,
                            )
                            if item is not None:
                                yield item
                        event_name = None
                        data_lines = []
                        continue

                    if line.startswith(":"):
                        continue
                    if line.startswith("event:"):
                        event_name = line[6:].strip()
                    elif line.startswith("data:"):
                        data_lines.append(line[5:].strip())
        except httpx.HTTPError as exc:
            logger.error(
                "config_watch_transport_error",
                app_id=app_id,
                tenant_id=tenant_id,
                url=url,
                error=str(exc),
            )
            yield ConfigSyncError(
                code=ConfigSyncErrorCode.STREAM_DISCONNECTED,
                message=f"Transport error connecting to {url}: {exc}",
            )

    @staticmethod
    def _append_snapshot_chunk(
        accumulator: _SnapshotAccumulator | None, parsed: dict[str, object]
    ) -> _SnapshotAccumulator | None:
        if accumulator is None:
            return None
        raw_entities = parsed.get("entities", [])
        if isinstance(raw_entities, list):
            for raw_rec in raw_entities:
                rec = _parse_entity_record(raw_rec)
                if rec is not None:
                    accumulator.entities.append(rec)
        return accumulator

    @classmethod
    def _handle_sse_frame(
        cls,
        *,
        event_name: str,
        raw_data: str,
        accumulator: _SnapshotAccumulator | None,
        app_id: str,
        tenant_id: str,
    ) -> tuple[WatchStreamItem | None, _SnapshotAccumulator | None]:
        try:
            parsed = json.loads(raw_data)
        except json.JSONDecodeError as exc:
            return (
                ConfigSyncError(
                    code=ConfigSyncErrorCode.INVALID_FRAME,
                    message=f"Malformed SSE JSON frame for {event_name}: {exc}",
                ),
                accumulator,
            )
        if not isinstance(parsed, dict):
            return (
                ConfigSyncError(
                    code=ConfigSyncErrorCode.INVALID_FRAME,
                    message=f"SSE frame payload must be a JSON object for {event_name}.",
                ),
                accumulator,
            )

        if event_name == ConfigWatchEventType.SNAPSHOT_START.value:
            base_ver = parsed.get("base_version", 0)
            return None, _SnapshotAccumulator(
                app_id=str(parsed.get("app_id", app_id)),
                tenant_id=str(parsed.get("tenant_id", tenant_id)),
                base_version=int(base_ver) if isinstance(base_ver, int) else 0,
                entities=[],
            )

        if event_name == ConfigWatchEventType.SNAPSHOT_CHUNK.value:
            return None, cls._append_snapshot_chunk(accumulator, parsed)

        if event_name == ConfigWatchEventType.SNAPSHOT_END.value:
            if accumulator is None:
                return None, None
            final_ver = parsed.get("final_version", accumulator.base_version)
            snapshot = ConfigSnapshot(
                app_id=accumulator.app_id,
                tenant_id=accumulator.tenant_id,
                version=int(final_ver) if isinstance(final_ver, int) else accumulator.base_version,
                entities=tuple(accumulator.entities),
                checksum=str(parsed.get("checksum", "")),
            )
            return snapshot, None

        if event_name == ConfigWatchEventType.DELTA.value:
            delta_res = _parse_delta(parsed)
            if delta_res.is_err:
                return delta_res.unwrap_err(), accumulator
            return delta_res.unwrap(), accumulator

        if event_name == ConfigWatchEventType.HEARTBEAT.value:
            latest = parsed.get("latest_version", 0)
            return (
                ConfigWatchHeartbeat(
                    app_id=str(parsed.get("app_id", app_id)),
                    tenant_id=str(parsed.get("tenant_id", tenant_id)),
                    latest_version=int(latest) if isinstance(latest, int) else 0,
                    timestamp=str(parsed.get("timestamp", "")),
                ),
                accumulator,
            )

        return None, accumulator


__all__ = ["HttpxSseConfigWatchClient"]
