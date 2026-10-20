"""Declarative HTTP execution engine supporting 500+ SaaS applications via OpenAPI/JSON manifests."""

from __future__ import annotations

import re
from collections.abc import AsyncIterator, Sequence
from datetime import UTC, datetime
from typing import Any

import httpx
import structlog
from ip.adapters.outbound.connectors.base_connector import BaseConnector
from ip.domain.exceptions import CatalogDiscoveryFailedException
from ip.domain.models.connector_spec import (
    DeclarativeManifest,
    HttpActionSpec,
    PaginationType,
)
from ip.domain.types import JsonDict
from ip.ports.types import (
    ConnectionCheckResultDTO,
    DiscoveredCatalogDTO,
    RecordEnvelopeDTO,
    StreamFieldDTO,
    StreamSchemaDTO,
    WriteRecordCommand,
    WriteResultDTO,
)

logger = structlog.get_logger(__name__)


class DeclarativeHttpConnector(BaseConnector):
    """Data-driven HTTP connector executing REST actions defined by DeclarativeManifest."""

    def __init__(
        self,
        manifest: DeclarativeManifest,
        client: httpx.AsyncClient | None = None,
        timeout_seconds: float = 10.0,
    ) -> None:
        self._manifest = manifest
        self._client = client
        self._timeout_seconds = timeout_seconds

    @property
    def app_id(self) -> str:
        return self._manifest.app_id

    def spec(self) -> JsonDict:
        return self._manifest.property_schema.to_dict()

    def _interpolate_string(
        self,
        template: str,
        public_config: JsonDict,
        credentials: JsonDict,
    ) -> str:
        """Safely interpolates {key} placeholders using combined configs."""
        combined: dict[str, Any] = {**public_config, **credentials}

        def replacer(match: re.Match[str]) -> str:
            key = match.group(1)
            val = combined.get(key)
            if val is None:
                return match.group(0)
            return str(val).rstrip("/")

        return re.sub(r"\{([a-zA-Z0-9_]+)\}", replacer, template)

    def _build_auth_headers(self, credentials: JsonDict) -> dict[str, str]:
        """Injects authentication headers based on manifest auth_type."""
        headers: dict[str, str] = {}
        auth_type = self._manifest.auth_type.upper()

        if auth_type in ("BEARER", "OAUTH2"):
            token = (
                credentials.get("access_token")
                or credentials.get("token")
                or credentials.get("api_key")
            )
            if token:
                headers["Authorization"] = f"Bearer {token}"
        elif auth_type == "API_KEY":
            api_key = credentials.get("api_key") or credentials.get("key")
            header_name = str(credentials.get("api_key_header", "X-API-Key"))
            if api_key:
                headers[header_name] = str(api_key)

        return headers

    @staticmethod
    def _extract_nested(data: Any, path: str | None) -> Any:
        """Extracts data from a nested dictionary/list using dot-notation path."""
        if not path:
            return data
        current = data
        for part in path.split("."):
            if isinstance(current, dict):
                current = current.get(part)
            elif isinstance(current, (list, tuple)) and part.isdigit():
                idx = int(part)
                if 0 <= idx < len(current):
                    current = current[idx]
                else:
                    return None
            else:
                return None
        return current

    async def check(
        self,
        public_config: JsonDict,
        credentials: JsonDict,
    ) -> ConnectionCheckResultDTO:
        action = self._manifest.check_action
        base_url = self._interpolate_string(
            self._manifest.base_url_template, public_config, credentials
        )
        url = f"{base_url.rstrip('/')}/{action.path.lstrip('/')}"
        headers = {
            **self._build_auth_headers(credentials),
            **action.headers,
        }

        async def _execute(c: httpx.AsyncClient) -> ConnectionCheckResultDTO:
            try:
                resp = await c.request(
                    method=action.method,
                    url=url,
                    headers=headers,
                    params=action.query_params or None,
                    timeout=self._timeout_seconds,
                )
                if resp.is_success:
                    return ConnectionCheckResultDTO(
                        success=True,
                        status="SUCCEEDED",
                        message=f"Connected successfully to {self._manifest.display_name}",
                    )
                return ConnectionCheckResultDTO(
                    success=False,
                    status="FAILED",
                    message=f"Endpoint returned HTTP {resp.status_code}: {resp.text[:200]}",
                    error_code=f"HTTP_{resp.status_code}",
                )
            except httpx.HTTPError as exc:
                return ConnectionCheckResultDTO(
                    success=False,
                    status="FAILED",
                    message=f"Network error checking {self._manifest.display_name}: {exc}",
                    error_code="NETWORK_ERROR",
                )

        if self._client is not None:
            return await _execute(self._client)
        async with httpx.AsyncClient() as client:
            return await _execute(client)

    async def discover(
        self,
        connection_id: str,
        public_config: JsonDict,
        credentials: JsonDict,
    ) -> DiscoveredCatalogDTO:
        streams: list[StreamSchemaDTO] = []
        for stream_name, _action in self._manifest.streams.items():
            streams.append(
                StreamSchemaDTO(
                    name=stream_name,
                    fields=[
                        StreamFieldDTO(name="id", data_type="string", nullable=False),
                        StreamFieldDTO(name="raw_data", data_type="json", nullable=True),
                    ],
                    primary_key=["id"],
                    cursor_field="id",
                )
            )

        return self.build_catalog_dto(
            connection_id=connection_id,
            streams=streams,
        )

    async def list_objects(
        self,
        stream_name: str,
        public_config: JsonDict,
        credentials: JsonDict,
        limit: int = 100,
        cursor: str | None = None,
    ) -> Sequence[str]:
        ids: list[str] = []
        async for record in self.read_stream(
            stream_name=stream_name,
            public_config=public_config,
            credentials=credentials,
            cursor=cursor,
            limit=limit,
        ):
            ids.append(record.record_id)
        return ids

    @staticmethod
    def _prepare_page_url_and_params(
        action: HttpActionSpec,
        base_url: str,
        current_cursor: str | None,
        current_page: int,
        current_offset: int,
        limit: int,
        records_emitted: int,
    ) -> tuple[str, dict[str, Any]]:
        pagination = action.pagination
        params = dict(action.query_params)
        req_url = f"{base_url.rstrip('/')}/{action.path.lstrip('/')}"

        if pagination.pagination_type == PaginationType.CURSOR and current_cursor:
            if current_cursor.startswith(("http://", "https://")):
                req_url = current_cursor
            elif current_cursor.startswith("/"):
                root_match = re.match(r"(https?://[^/]+)", base_url)
                host_prefix = root_match.group(1) if root_match else base_url
                req_url = f"{host_prefix}{current_cursor}"
            else:
                params[pagination.cursor_param] = current_cursor
        elif pagination.pagination_type == PaginationType.OFFSET_LIMIT:
            params[pagination.limit_param] = min(pagination.page_size, limit - records_emitted)
            params[pagination.offset_param] = current_offset
        elif pagination.pagination_type == PaginationType.PAGE_NUMBER:
            params[pagination.limit_param] = min(pagination.page_size, limit - records_emitted)
            params[pagination.page_param] = current_page

        return req_url, params

    @staticmethod
    def _advance_pagination(
        pagination_type: PaginationType,
        page_size: int,
        records_count: int,
        next_cursor: str | None,
        current_cursor: str | None,
        current_page: int,
        current_offset: int,
    ) -> tuple[str | None, int, int, bool]:
        if pagination_type == PaginationType.CURSOR:
            if not next_cursor or next_cursor == current_cursor:
                return current_cursor, current_page, current_offset, False
            return next_cursor, current_page, current_offset, True
        if pagination_type == PaginationType.OFFSET_LIMIT:
            if records_count < page_size:
                return current_cursor, current_page, current_offset, False
            return current_cursor, current_page, current_offset + records_count, True
        if pagination_type == PaginationType.PAGE_NUMBER:
            if records_count < page_size:
                return current_cursor, current_page, current_offset, False
            return current_cursor, current_page + 1, current_offset, True
        return current_cursor, current_page, current_offset, False

    async def _fetch_records_page(
        self,
        c: httpx.AsyncClient,
        action: HttpActionSpec,
        credentials: JsonDict,
        req_url: str,
        params: dict[str, Any],
    ) -> tuple[list[dict[str, Any]], str | None]:
        headers = {
            **self._build_auth_headers(credentials),
            **action.headers,
        }
        resp = await c.request(
            method=action.method,
            url=req_url,
            headers=headers,
            params=params or None,
            timeout=self._timeout_seconds,
        )
        resp.raise_for_status()
        data = resp.json()

        extracted = self._extract_nested(data, action.response_records_path)
        raw_records = extracted if isinstance(extracted, list) else []

        next_cursor = None
        if action.pagination.cursor_path:
            next_val = self._extract_nested(data, action.pagination.cursor_path)
            if next_val is not None:
                next_cursor = str(next_val)

        return raw_records, next_cursor

    async def _iterate_pages(
        self,
        c: httpx.AsyncClient,
        action: HttpActionSpec,
        base_url: str,
        credentials: JsonDict,
        stream_name: str,
        cursor: str | None,
        limit: int,
    ) -> AsyncIterator[RecordEnvelopeDTO]:
        current_cursor = cursor
        current_page = 1
        current_offset = 0
        records_emitted = 0

        while records_emitted < limit:
            req_url, params = self._prepare_page_url_and_params(
                action,
                base_url,
                current_cursor,
                current_page,
                current_offset,
                limit,
                records_emitted,
            )

            records, next_cursor = await self._fetch_records_page(
                c, action, credentials, req_url, params
            )
            if not records:
                break

            for rec in records:
                if records_emitted >= limit:
                    break
                records_emitted += 1
                rec_id = str(rec.get("id") or rec.get("Id") or f"{stream_name}_{records_emitted}")
                yield RecordEnvelopeDTO(
                    stream_name=stream_name,
                    record_id=rec_id,
                    data=rec,
                    emitted_at=datetime.now(UTC).isoformat(),
                )

            new_cursor, new_page, new_offset, should_cont = self._advance_pagination(
                action.pagination.pagination_type,
                action.pagination.page_size,
                len(records),
                next_cursor,
                current_cursor,
                current_page,
                current_offset,
            )
            current_cursor, current_page, current_offset = new_cursor, new_page, new_offset
            if not should_cont:
                break

    async def read_stream(
        self,
        stream_name: str,
        public_config: JsonDict,
        credentials: JsonDict,
        cursor: str | None = None,
        limit: int = 100,
    ) -> AsyncIterator[RecordEnvelopeDTO]:
        action = self._manifest.streams.get(stream_name)
        if not action:
            raise CatalogDiscoveryFailedException(
                f"Stream '{stream_name}' not defined in manifest for {self.app_id}"
            )

        base_url = self._interpolate_string(
            self._manifest.base_url_template, public_config, credentials
        )

        if self._client is not None:
            async for r in self._iterate_pages(
                self._client, action, base_url, credentials, stream_name, cursor, limit
            ):
                yield r
        else:
            async with httpx.AsyncClient() as client:
                async for r in self._iterate_pages(
                    client, action, base_url, credentials, stream_name, cursor, limit
                ):
                    yield r

    async def write_record(
        self,
        stream_name: str,
        command: WriteRecordCommand,
        public_config: JsonDict,
        credentials: JsonDict,
    ) -> WriteResultDTO:
        action = self._manifest.write_actions.get(stream_name)
        if not action:
            raise ValueError(
                f"No write action configured for stream '{stream_name}' in {self.app_id}"
            )

        base_url = self._interpolate_string(
            self._manifest.base_url_template, public_config, credentials
        )
        url = f"{base_url.rstrip('/')}/{action.path.lstrip('/')}"
        headers = {
            **self._build_auth_headers(credentials),
            **action.headers,
            "Content-Type": "application/json",
        }

        async def _execute(c: httpx.AsyncClient) -> WriteResultDTO:
            resp = await c.request(
                method=action.method,
                url=url,
                headers=headers,
                json=command.payload,
                timeout=self._timeout_seconds,
            )
            resp.raise_for_status()
            data = resp.json() if resp.content else {}
            rec_id = str(data.get("id") or data.get("Id") or "written")
            return WriteResultDTO(
                success=True,
                record_id=rec_id,
                destination_id=rec_id,
            )

        if self._client is not None:
            return await _execute(self._client)
        async with httpx.AsyncClient() as client:
            return await _execute(client)
