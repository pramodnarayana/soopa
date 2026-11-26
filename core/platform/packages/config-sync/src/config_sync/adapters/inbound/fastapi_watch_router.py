"""FastAPI inbound SSE router for Universal Control-to-Data-Plane Dynamic Watch."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Callable

import structlog
from fastapi import APIRouter, Header, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from seedwork.domain.types import JsonDict, JsonValue

from config_sync.adapters.inbound.watch_auth_strategies import (
    BearerTokenWatchAuthStrategy,
    FailClosedUnconfiguredAuthStrategy,
)
from config_sync.application.stream_config_watch_use_case import (
    StreamConfigWatchQuery,
    StreamConfigWatchUseCase,
)
from config_sync.domain.dtos import ConfigCursor, ConfigSnapshot, ConfigWatchFrame
from config_sync.domain.enums import ConfigSyncErrorCode
from config_sync.ports.config_watch_auth_port import ConfigWatchAuthStrategyPort

logger = structlog.get_logger(__name__)


def _format_sse_frame(frame: ConfigWatchFrame) -> str:
    serialized = json.dumps(frame.data, sort_keys=True, separators=(",", ":"), default=str)
    if frame.frame_id:
        return f"id: {frame.frame_id}\nevent: {frame.event}\ndata: {serialized}\n\n"
    return f"event: {frame.event}\ndata: {serialized}\n\n"


def _serialize_snapshot(snapshot: ConfigSnapshot) -> JsonDict:
    entities: list[JsonValue] = [
        {
            "entity_type": rec.entity_type,
            "entity_id": rec.entity_id,
            "tenant_id": rec.tenant_id,
            "checksum": rec.checksum,
            "payload": rec.payload,
        }
        for rec in snapshot.entities
    ]
    return {
        "app_id": snapshot.app_id,
        "tenant_id": snapshot.tenant_id,
        "txid": snapshot.txid,
        "version": snapshot.version,
        "cursor": snapshot.cursor.encode(),
        "checksum": snapshot.checksum,
        "entities": entities,
    }


def _resolve_since_cursor(
    *,
    since_cursor: str | None,
    last_event_id: str | None,
    since_version: int,
) -> ConfigCursor:
    raw = since_cursor or last_event_id
    if raw:
        parsed = ConfigCursor.parse(raw)
        if parsed is not None:
            return parsed
    if since_version > 0:
        return ConfigCursor(txid=0, version=since_version)
    return ConfigCursor.zero()


def _enforce_auth(
    auth_strategy: ConfigWatchAuthStrategyPort,
    authorization: str | None,
) -> None:
    auth_res = auth_strategy.verify(authorization)
    if auth_res.is_ok:
        return
    err = auth_res.unwrap_err()
    if err.code == ConfigSyncErrorCode.UNCONFIGURED_AUTH:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=err.message,
        )
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=err.message,
    )


def create_config_sync_router(
    *,
    use_case_provider: Callable[[], StreamConfigWatchUseCase],
    internal_bearer_token: str | None = None,
    auth_strategy: ConfigWatchAuthStrategyPort | None = None,
    heartbeat_interval_seconds: float = 15.0,
) -> APIRouter:
    """Creates the domain-agnostic FastAPI router exposing `/api/v1/internal/{app_id}/config/*`.

    Fails closed by default (`FailClosedUnconfiguredAuthStrategy` -> HTTP 503) unless a non-empty
    `internal_bearer_token` or an explicit `auth_strategy` is injected by the Composition Root.
    """
    resolved_auth: ConfigWatchAuthStrategyPort
    if auth_strategy is not None:
        resolved_auth = auth_strategy
    elif internal_bearer_token and internal_bearer_token.strip():
        resolved_auth = BearerTokenWatchAuthStrategy(internal_bearer_token)
    else:
        resolved_auth = FailClosedUnconfiguredAuthStrategy()

    router = APIRouter(prefix="/api/v1/internal", tags=["internal-config-watch"])

    @router.get("/{app_id}/config/watch", status_code=status.HTTP_200_OK)
    async def watch_app_config(
        app_id: str,
        tenant_id: str = Query(..., min_length=1),
        since_cursor: str | None = Query(default=None),
        since_version: int = Query(default=0, ge=0),
        chunk_size: int = Query(default=100, ge=1, le=1000),
        max_events: int | None = Query(default=None, ge=1),
        authorization: str | None = Header(default=None),
        last_event_id: str | None = Header(default=None, alias="Last-Event-ID"),
    ) -> StreamingResponse:
        _enforce_auth(resolved_auth, authorization)
        use_case = use_case_provider()
        provider_res = use_case.resolve_provider(app_id)
        if provider_res.is_err:
            err = provider_res.unwrap_err()
            logger.error("config_watch_unknown_app", app_id=app_id, error=err.message)
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=err.message)

        provider = provider_res.unwrap()
        resolved_cursor = _resolve_since_cursor(
            since_cursor=since_cursor,
            last_event_id=last_event_id,
            since_version=since_version,
        )
        query = StreamConfigWatchQuery(
            app_id=provider.app_id,
            tenant_id=tenant_id,
            since_cursor=resolved_cursor,
            chunk_size=chunk_size,
            heartbeat_interval_seconds=heartbeat_interval_seconds,
            max_events=max_events,
        )

        async def _sse_generator() -> AsyncIterator[str]:
            async for frame in use_case.stream(provider, query):
                yield _format_sse_frame(frame)

        return StreamingResponse(
            _sse_generator(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    @router.get("/{app_id}/config/snapshot", status_code=status.HTTP_200_OK)
    async def get_app_config_snapshot(
        app_id: str,
        tenant_id: str = Query(..., min_length=1),
        authorization: str | None = Header(default=None),
    ) -> JsonDict:
        _enforce_auth(resolved_auth, authorization)
        use_case = use_case_provider()
        snapshot_res = await use_case.get_snapshot(app_id=app_id, tenant_id=tenant_id)
        if snapshot_res.is_err:
            err = snapshot_res.unwrap_err()
            logger.error("config_snapshot_unknown_app", app_id=app_id, error=err.message)
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=err.message)
        return _serialize_snapshot(snapshot_res.unwrap())

    return router


__all__ = ["create_config_sync_router"]
