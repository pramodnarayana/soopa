"""Declarative HTTP execution engine supporting 500+ SaaS applications via OpenAPI/JSON manifests."""

from __future__ import annotations

import base64
import re
from collections.abc import AsyncIterator, Sequence
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlparse

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
from shttp import (
    HttpClient,
    HttpError,
    PassThroughPolicy,
    create_http_client,
    validate_target_url,
)
from shttp.exceptions import SsrfSecurityError
from shttp.resilience import HttpBackoffHandler

logger = structlog.get_logger(__name__)


class DeclarativeHttpConnector(BaseConnector):
    """Data-driven HTTP connector executing REST actions defined by DeclarativeManifest."""

    def __init__(
        self,
        manifest: DeclarativeManifest,
        client: httpx.AsyncClient | None = None,
        http_client: HttpClient | None = None,
        timeout_seconds: float = 10.0,
        backoff_handler: HttpBackoffHandler | None = None,
        allow_private_ips: bool = False,
    ) -> None:
        self._manifest = manifest
        self._timeout_seconds = timeout_seconds
        # In test environments or when a custom client is injected, allow private/mock endpoints
        self._allow_private_ips = allow_private_ips or (client is not None)

        if http_client is not None:
            self._http_client = http_client
        elif client is not None:
            self._http_client = HttpClient(
                client=client,
                backoff_handler=backoff_handler,
                allow_private_ips=True,
                response_policy=PassThroughPolicy(),
            )
        else:
            raw_client = create_http_client(timeout=timeout_seconds)
            self._http_client = HttpClient(
                client=raw_client,
                backoff_handler=backoff_handler,
                allow_private_ips=allow_private_ips,
                response_policy=PassThroughPolicy(),
            )

    @property
    def app_id(self) -> str:
        return self._manifest.app_id

    def spec(self) -> JsonDict:
        return self._manifest.property_schema.to_dict()

    def _validate_url(self, url: str) -> None:
        """Validates that URL uses HTTPS and does not target restricted hosts via platform SSRF validator."""
        if not url.startswith("https://"):
            raise ValueError(f"Connector endpoint must use HTTPS: {url}")
        parsed = urlparse(url)
        hostname = (parsed.hostname or "").lower()
        if hostname in ("localhost", "127.0.0.1", "::1", "169.254.169.254"):
            raise ValueError(f"Restricted hostname or IP address in endpoint: {hostname}")
        try:
            validate_target_url(url, allow_private_ips=self._allow_private_ips)
        except SsrfSecurityError as exc:
            raise ValueError(f"Restricted destination forbidden: {exc}") from exc

    def _interpolate_string(
        self,
        template: str,
        public_config: JsonDict,
        credentials: JsonDict | None = None,
    ) -> str:
        """Safely interpolates {key} placeholders using public_config only.

        Validates host-segment placeholders to prevent path traversal and injection.
        """

        def replacer(match: re.Match[str]) -> str:
            key = match.group(1)
            val = public_config.get(key)
            if val is None:
                return match.group(0)
            cleaned = str(val).strip().rstrip("/")
            if not re.match(r"^[a-zA-Z0-9_\-\.]+$", cleaned):
                raise ValueError(f"Invalid character in URL parameter '{key}': {cleaned}")
            return cleaned

        interpolated = re.sub(r"\{([a-zA-Z0-9_]+)\}", replacer, template)
        self._validate_url(interpolated)
        return interpolated

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
        elif auth_type == "BASIC":
            username = str(credentials.get("username", ""))
            password = str(credentials.get("password", ""))
            if username and password:
                basic_token = base64.b64encode(f"{username}:{password}".encode()).decode("ascii")
                headers["Authorization"] = f"Basic {basic_token}"
        elif auth_type == "API_KEY":
            api_key = credentials.get("api_key") or credentials.get("key")
            header_name = str(credentials.get("api_key_header", "X-API-Key"))
            if api_key:
                headers[header_name] = str(api_key)

        return headers

    @staticmethod
    def _extract_nested(data: Any, path: str | None) -> Any:
        """Extracts data from a nested dictionary/list using dot-notation path, supporting negative indices."""
        if not path:
            return data
        current = data
        for part in path.split("."):
            if isinstance(current, dict):
                current = current.get(part)
            elif isinstance(current, (list, tuple)):
                try:
                    idx = int(part)
                    if -len(current) <= idx < len(current):
                        current = current[idx]
                    else:
                        return None
                except ValueError:
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
        if not action:
            return ConnectionCheckResultDTO(
                success=True,
                status="SUCCEEDED",
                message=f"No health check defined for {self.app_id}. Assuming valid.",
            )

        base_url = self._interpolate_string(
            self._manifest.base_url_template, public_config, credentials
        )
        url = f"{base_url.rstrip('/')}/{action.path.lstrip('/')}"
        headers = {
            **self._build_auth_headers(credentials),
            **action.headers,
        }

        try:
            resp = await self._http_client.request(
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
        except (HttpError, httpx.HTTPError, OSError, ValueError) as exc:
            return ConnectionCheckResultDTO(
                success=False,
                status="FAILED",
                message=f"Network error checking {self._manifest.display_name}: {exc}",
                error_code="NETWORK_ERROR",
            )

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

        if pagination.pagination_type == PaginationType.CURSOR:
            if current_cursor:
                if current_cursor.startswith(("http://", "https://")):
                    req_url = current_cursor
                elif current_cursor.startswith("/"):
                    root_match = re.match(r"(https?://[^/]+)", base_url)
                    host_prefix = root_match.group(1) if root_match else base_url
                    req_url = f"{host_prefix}{current_cursor}"
                else:
                    params[pagination.cursor_param] = current_cursor
            if pagination.limit_param:
                params[pagination.limit_param] = min(pagination.page_size, limit - records_emitted)
        elif pagination.pagination_type == PaginationType.OFFSET_LIMIT:
            params[pagination.limit_param] = min(pagination.page_size, limit - records_emitted)
            params[pagination.offset_param] = current_offset
        elif pagination.pagination_type == PaginationType.PAGE_NUMBER:
            params[pagination.limit_param] = min(pagination.page_size, limit - records_emitted)
            params[pagination.page_param] = current_page

        return req_url, params

    @staticmethod
    def _extract_records_from_response(
        data: Any,
        records_path: str | None,
    ) -> list[dict[str, Any]]:
        if not records_path:
            if isinstance(data, list):
                return [r for r in data if isinstance(r, dict)]
            if isinstance(data, dict):
                return [data]
            return []

        extracted = DeclarativeHttpConnector._extract_nested(data, records_path)
        if isinstance(extracted, list):
            return [r for r in extracted if isinstance(r, dict)]
        if isinstance(extracted, dict):
            return [extracted]
        return []

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
        if records_count == 0:
            return current_cursor, current_page, current_offset, False

        if pagination_type == PaginationType.NONE:
            return current_cursor, current_page, current_offset, False
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
        action: HttpActionSpec,
        credentials: JsonDict,
        req_url: str,
        params: dict[str, Any],
    ) -> tuple[list[dict[str, Any]], str | None, bool]:
        headers = {
            **self._build_auth_headers(credentials),
            **action.headers,
        }
        resp = await self._http_client.request(
            method=action.method,
            url=req_url,
            headers=headers,
            params=params or None,
            timeout=self._timeout_seconds,
        )
        if not resp.is_success:
            logger.error(
                "declarative_connector_fetch_page_failed",
                app_id=self.app_id,
                url=req_url,
                status_code=resp.status_code,
                response_text=resp.text,
            )
            return [], None, False

        data = resp.json()
        raw_records = self._extract_records_from_response(data, action.response_records_path)

        next_cursor = None
        if action.pagination.cursor_path:
            next_val = self._extract_nested(data, action.pagination.cursor_path)
            if next_val is not None:
                next_cursor = str(next_val)

        has_more = True
        if isinstance(data, dict) and data.get("has_more") is False:
            has_more = False

        return raw_records, next_cursor, has_more

    async def _iterate_pages(
        self,
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

            records, next_cursor, has_more = await self._fetch_records_page(
                action, credentials, req_url, params
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

            if not has_more:
                break

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

        async for r in self._iterate_pages(
            action, base_url, credentials, stream_name, cursor, limit
        ):
            yield r

    async def write_record(
        self,
        stream_name: str,
        command: WriteRecordCommand,
        public_config: JsonDict,
        credentials: JsonDict,
    ) -> WriteResultDTO:
        if command.operation != "CREATE":
            return WriteResultDTO(
                success=False,
                record_id="failed",
                destination_id=None,
                error_message=f"Unsupported write operation '{command.operation}' for declarative connector",
            )

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

        try:
            resp = await self._http_client.request(
                method=action.method,
                url=url,
                headers=headers,
                json=command.payload,
                timeout=self._timeout_seconds,
            )
            if not resp.is_success:
                logger.error(
                    "declarative_connector_write_failed",
                    app_id=self.app_id,
                    stream=stream_name,
                    status_code=resp.status_code,
                    response_text=resp.text,
                )
                return WriteResultDTO(
                    success=False,
                    record_id="failed",
                    destination_id=None,
                    error_message=f"HTTP request failed with status {resp.status_code}: {resp.text}",
                )

            data = resp.json() if resp.content else {}
            rec_id = str(data.get("id") or data.get("Id") or "written")
            return WriteResultDTO(
                success=True,
                record_id=rec_id,
                destination_id=rec_id,
            )
        except (HttpError, httpx.HTTPError, OSError, ValueError) as exc:
            logger.error(
                "declarative_connector_write_exception",
                app_id=self.app_id,
                stream=stream_name,
                error=str(exc),
            )
            return WriteResultDTO(
                success=False,
                record_id="failed",
                destination_id=None,
                error_message=f"HTTP request failed: {exc}",
            )
