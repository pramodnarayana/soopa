"""Declarative HTTP execution engine supporting 500+ SaaS applications via OpenAPI/JSON manifests."""

from __future__ import annotations

import re
from collections.abc import AsyncIterator, Sequence
from datetime import UTC, datetime
from urllib.parse import quote, urlparse

import httpx
import structlog
from ip.engine.adapters.outbound.auth.resolver import AuthStrategyResolver
from ip.engine.adapters.outbound.connectors.base_connector import BaseConnector
from ip.engine.adapters.outbound.connectors.spec_mapper import schema_to_app_spec_dto
from ip.engine.domain.exceptions import (
    EndpointSecurityViolationError,
    FailureDisposition,
    InvalidConnectionConfigError,
    InvalidEndpointError,
    IpError,
    IpErrorCode,
    Result,
    StreamNotFoundError,
    UnsupportedWriteOperationError,
    UpstreamHttpError,
    UpstreamNetworkError,
    WriteActionNotConfiguredError,
)
from ip.engine.domain.models.connector_spec import (
    DeclarativeManifest,
    HttpActionSpec,
    PaginationType,
)
from ip.engine.ports.types import (
    AppSpecDTO,
    ConnectionCheckResultDTO,
    DiscoveredCatalogDTO,
    RecordEnvelopeDTO,
    StreamFieldDTO,
    StreamSchemaDTO,
    WriteRecordCommand,
    WriteResultDTO,
)
from seedwork.domain.types import JsonDict
from shttp import (
    HttpClient,
    HttpError,
    PassThroughPolicy,
    create_http_client,
)
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

    def spec(self) -> AppSpecDTO:
        return schema_to_app_spec_dto(self._manifest.property_schema)

    def _validate_url(
        self, url: str
    ) -> Result[
        str,
        InvalidConnectionConfigError | InvalidEndpointError | EndpointSecurityViolationError,
    ]:
        """Validates that URL uses HTTPS and does not target restricted hosts via BaseConnector SSRF validator."""
        return self.validate_http_endpoint_url(
            url,
            allow_private_ips=self._allow_private_ips,
            enforce_ssrf_precheck=True,
            error_code=IpErrorCode.INVALID_CONFIGURATION,
        )

    def _interpolate_string(
        self,
        template: str,
        public_config: JsonDict,
        credentials: JsonDict | None = None,
    ) -> Result[
        str,
        InvalidConnectionConfigError | InvalidEndpointError | EndpointSecurityViolationError,
    ]:
        """Safely interpolates {key} placeholders using public_config only.

        Validates host-segment placeholders to prevent path traversal and injection.
        """
        invalid_param_error: InvalidConnectionConfigError | None = None

        def replacer(match: re.Match[str]) -> str:
            nonlocal invalid_param_error
            key = match.group(1)
            val = public_config.get(key)
            if val is None:
                return match.group(0)
            cleaned = str(val).strip().rstrip("/")
            if key in ("endpoint_url", "base_url") or cleaned.startswith(("http://", "https://")):
                return cleaned
            if not re.match(r"^[a-zA-Z0-9_\-\.]+$", cleaned):
                invalid_param_error = InvalidConnectionConfigError(
                    field_name=key,
                    code=IpErrorCode.INVALID_CONFIGURATION,
                    message=f"Invalid character in URL parameter '{key}': {cleaned}",
                    details={"field": key, "value": cleaned},
                )
                return match.group(0)
            return cleaned

        interpolated = re.sub(r"\{([a-zA-Z0-9_]+)\}", replacer, template)
        if invalid_param_error is not None:
            return Result.fail(invalid_param_error)
        return self._validate_url(interpolated)

    def _build_auth_headers(self, credentials: JsonDict) -> dict[str, str]:
        """Injects authentication headers via unified AuthStrategyResolver."""
        authenticator = AuthStrategyResolver.resolve(
            self._manifest.auth_type,
            credentials,
            allow_private_ips=self._allow_private_ips,
        )
        dummy_req = httpx.Request("GET", "https://auth.internal")
        authed_req = authenticator.authenticate_request(dummy_req)
        canonical_names = {
            "authorization": "Authorization",
            "x-api-key": "X-API-Key",
        }
        return {
            canonical_names.get(k.lower(), k): v
            for k, v in authed_req.headers.items()
            if k.lower() not in ("host", "user-agent", "accept", "accept-encoding", "connection")
        }

    @staticmethod
    def _extract_nested(data: object | None, path: str | None) -> object | None:
        """Extracts data from a nested dictionary/list using dot-notation path, supporting negative indices."""
        if not path:
            return data
        current: object | None = data
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
            return ConnectionCheckResultDTO.ok(
                f"No health check defined for {self.app_id}. Assuming valid."
            )

        interp_res = self._interpolate_string(
            self._manifest.base_url_template, public_config, credentials
        )
        if interp_res.error is not None or interp_res.value is None:
            cfg_err = interp_res.error or InvalidConnectionConfigError(
                code=IpErrorCode.INVALID_CONFIGURATION,
                message=f"Configuration error checking {self._manifest.display_name}",
            )
            return ConnectionCheckResultDTO(
                success=False,
                status="FAILED",
                message=f"Configuration error checking {self._manifest.display_name}: {cfg_err.message}",
                error_code=IpErrorCode.INVALID_CONFIGURATION.value,
                error=cfg_err,
            )

        base_url = interp_res.value
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
                return ConnectionCheckResultDTO.ok(
                    f"Connected successfully to {self._manifest.display_name}"
                )
            http_err = UpstreamHttpError(
                status_code=resp.status_code,
                message=f"Endpoint returned HTTP {resp.status_code}: {resp.text[:200]}",
                disposition=(
                    FailureDisposition.RETRY
                    if resp.status_code == 429 or resp.status_code >= 500
                    else FailureDisposition.FAIL
                ),
            )
            return ConnectionCheckResultDTO.from_error(
                http_err,
                error_code_override=f"HTTP_{resp.status_code}",
            )
        except (HttpError, httpx.HTTPError, OSError) as exc:
            net_err = UpstreamNetworkError(
                endpoint=url,
                message=f"Network error checking {self._manifest.display_name}: {exc}",
            )
            return ConnectionCheckResultDTO.from_error(net_err)

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
    ) -> Result[tuple[str, dict[str, str | int]], EndpointSecurityViolationError]:
        pagination = action.pagination
        params: dict[str, str | int] = dict(action.query_params)
        req_url = f"{base_url.rstrip('/')}/{action.path.lstrip('/')}"

        if pagination.pagination_type == PaginationType.CURSOR:
            if current_cursor:
                if current_cursor.startswith(("http://", "https://")):
                    parsed_cursor = urlparse(current_cursor)
                    parsed_base = urlparse(base_url)
                    if (
                        parsed_cursor.scheme != parsed_base.scheme
                        or parsed_cursor.netloc != parsed_base.netloc
                    ):
                        return Result.fail(
                            EndpointSecurityViolationError(
                                endpoint=current_cursor,
                                message=(
                                    f"Pagination cursor URL origin '{parsed_cursor.scheme}://{parsed_cursor.netloc}' "
                                    f"does not match connector base URL origin '{parsed_base.scheme}://{parsed_base.netloc}'"
                                ),
                            )
                        )
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

        return Result.ok((req_url, params))

    @staticmethod
    def _extract_records_from_response(
        data: object | None,
        records_path: str | None,
    ) -> list[JsonDict]:
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
        params: dict[str, str | int],
    ) -> Result[tuple[list[JsonDict], str | None, bool], IpError]:
        headers = {
            **self._build_auth_headers(credentials),
            **action.headers,
        }
        try:
            resp = await self._http_client.request(
                method=action.method,
                url=req_url,
                headers=headers,
                params=params or None,
                timeout=self._timeout_seconds,
            )
        except (HttpError, httpx.HTTPError, OSError) as exc:
            logger.error(
                "declarative_connector_fetch_page_network_error",
                app_id=self.app_id,
                url=req_url,
                error=str(exc),
            )
            return Result.fail(
                UpstreamNetworkError(
                    endpoint=req_url,
                    message=f"Network error fetching page from '{req_url}': {exc}",
                )
            )

        if not resp.is_success:
            logger.error(
                "declarative_connector_fetch_page_failed",
                app_id=self.app_id,
                url=req_url,
                status_code=resp.status_code,
                response_text=resp.text[:200],
            )
            return Result.fail(
                UpstreamHttpError(
                    status_code=resp.status_code,
                    message=f"HTTP {resp.status_code} error from '{req_url}': {resp.text[:200]}",
                    disposition=(
                        FailureDisposition.RETRY
                        if resp.status_code == 429 or resp.status_code >= 500
                        else FailureDisposition.FAIL
                    ),
                )
            )

        try:
            data = resp.json()
        except ValueError as exc:
            logger.error(
                "declarative_connector_fetch_page_invalid_json",
                app_id=self.app_id,
                url=req_url,
                error=str(exc),
            )
            return Result.fail(
                UpstreamHttpError(
                    status_code=resp.status_code,
                    message=f"Invalid JSON response from '{req_url}': {exc}",
                    disposition=FailureDisposition.FAIL,
                )
            )
        raw_records = self._extract_records_from_response(data, action.response_records_path)

        next_cursor = None
        if action.pagination.cursor_path:
            next_val = self._extract_nested(data, action.pagination.cursor_path)
            if next_val is not None:
                next_cursor = str(next_val)

        has_more = True
        if isinstance(data, dict) and data.get("has_more") is False:
            has_more = False

        return Result.ok((raw_records, next_cursor, has_more))

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
            page_prep = self._prepare_page_url_and_params(
                action,
                base_url,
                current_cursor,
                current_page,
                current_offset,
                limit,
                records_emitted,
            )
            if page_prep.error is not None or page_prep.value is None:
                self._last_error = page_prep.error
                logger.error(
                    "declarative_connector_invalid_page_url",
                    app_id=self.app_id,
                    stream_name=stream_name,
                    error=page_prep.error.message if page_prep.error else "Invalid page URL",
                )
                break

            req_url, params = page_prep.value
            page_res = await self._fetch_records_page(action, credentials, req_url, params)
            if page_res.error is not None or page_res.value is None:
                self._last_error = page_res.error
                break

            records, next_cursor, has_more = page_res.value
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
        self._last_error = None
        action = self._manifest.streams.get(stream_name)
        if not action:
            stream_err = StreamNotFoundError(
                app_id=self.app_id,
                stream_name=stream_name,
                message=f"Stream '{stream_name}' not defined in manifest for {self.app_id}",
            )
            self._last_error = stream_err
            logger.error(
                "declarative_connector_stream_not_found",
                app_id=self.app_id,
                stream_name=stream_name,
                error_code=stream_err.code.value,
            )
            return

        interp_res = self._interpolate_string(
            self._manifest.base_url_template, public_config, credentials
        )
        if interp_res.error is not None or interp_res.value is None:
            self._last_error = interp_res.error
            logger.error(
                "declarative_connector_read_stream_invalid_url",
                app_id=self.app_id,
                stream_name=stream_name,
                error=interp_res.error.message if interp_res.error else "Invalid URL",
            )
            return

        base_url = interp_res.value
        async for r in self._iterate_pages(
            action, base_url, credentials, stream_name, cursor, limit
        ):
            yield r

    def _resolve_declarative_write_action(
        self,
        stream_name: str,
        operation: str,
    ) -> Result[HttpActionSpec, IpError]:
        action = self._manifest.write_actions.get(f"{stream_name}:{operation}")
        if action is None and operation == "CREATE":
            action = self._manifest.write_actions.get(stream_name)
        if action is not None:
            return Result.ok(action)
        if operation != "CREATE":
            return Result.fail(
                UnsupportedWriteOperationError(
                    operation=operation,
                    stream_name=stream_name,
                    message=(
                        f"Unsupported write operation '{operation}' for declarative connector"
                    ),
                )
            )
        return Result.fail(
            WriteActionNotConfiguredError(
                app_id=self.app_id,
                stream_name=stream_name,
                message=f"No write action configured for stream '{stream_name}' in {self.app_id}",
            )
        )

    async def write_record(
        self,
        stream_name: str,
        command: WriteRecordCommand,
        public_config: JsonDict,
        credentials: JsonDict,
    ) -> WriteResultDTO:
        action_res = self._resolve_declarative_write_action(stream_name, command.operation)
        if action_res.error is not None or action_res.value is None:
            return WriteResultDTO.from_error(
                action_res.error
                or WriteActionNotConfiguredError(
                    app_id=self.app_id,
                    stream_name=stream_name,
                    message=f"No write action configured for stream '{stream_name}'",
                )
            )
        action = action_res.value

        interp_res = self._interpolate_string(
            self._manifest.base_url_template, public_config, credentials
        )
        if interp_res.error is not None or interp_res.value is None:
            return WriteResultDTO.from_error(
                interp_res.error
                or InvalidConnectionConfigError(message="Invalid base URL configuration")
            )

        base_url = interp_res.value
        encoded_record_id = quote(str(command.record_id or ""), safe="")
        action_path = action.path.replace("{record_id}", encoded_record_id)
        url = f"{base_url.rstrip('/')}/{action_path.lstrip('/')}"
        headers: dict[str, str] = {
            **self._build_auth_headers(credentials),
            **action.headers,
            **command.headers,
            "Content-Type": "application/json",
        }
        if command.idempotency_key:
            headers[command.idempotency_header_name] = command.idempotency_key

        return await self._execute_tracked_write_request(
            send_fn=lambda: self._http_client.request(
                method=action.method,
                url=url,
                headers=headers,
                json=command.payload if action.method.upper() != "DELETE" else None,
                timeout=self._timeout_seconds,
            ),
            target_url=url,
            http_method=action.method,
            request_headers=headers,
            default_record_id=command.record_id or "written",
            error_record_id=command.record_id or "failed",
        )
