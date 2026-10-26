"""Stateless Generic HTTP Connector executing REST operations for any HTTP application."""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from datetime import UTC, datetime
from urllib.parse import quote, urljoin, urlsplit

import httpx
import structlog
from ip.engine.adapters.outbound.auth.resolver import AuthStrategyResolver
from ip.engine.adapters.outbound.connectors.base_connector import BaseConnector
from ip.engine.adapters.outbound.connectors.egress_policy import PublicInternetEgressPolicy
from ip.engine.adapters.outbound.connectors.pagination_strategies import PaginationStrategyResolver
from ip.engine.application.responses import (
    AppSpecDTO,
    ConnectionCheckResultDTO,
    ConnectorPropertyDTO,
    DiscoveredCatalogDTO,
    DropdownOptionDTO,
    StreamFieldDTO,
    StreamSchemaDTO,
)
from ip.engine.domain.enums import (
    AuthType,
    CursorKind,
    HttpWriteOperation,
    PaginationType,
    SyncMode,
)
from ip.engine.domain.exceptions import (
    EndpointSecurityViolationError,
    InvalidConnectionConfigError,
    IpErrorCode,
    Result,
    UpstreamHttpError,
    UpstreamNetworkError,
)
from ip.engine.domain.models.http_source_spec import (
    HttpRequestSpec,
    HttpSourceSpec,
    HttpStreamDefinition,
)
from ip.engine.domain.models.stream_definition import DeletionMarker, StreamDefinition
from ip.engine.ports.outbound.auth_strategy_port import AuthenticatorPort
from ip.engine.ports.outbound.egress_policy_port import EgressPolicyPort
from ip.engine.ports.types import RecordEnvelopeDTO, WriteRecordCommand, WriteResultDTO
from seedwork.domain.types import JsonDict, JsonValue
from shttp import HttpClient, PassThroughPolicy, create_http_client
from shttp.exceptions import HttpError
from shttp.resilience import HttpBackoffHandler

logger = structlog.get_logger(__name__)


def _extract_nested(data: JsonValue, path: list[str] | tuple[str, ...]) -> JsonValue:
    curr = data
    for key in path:
        if not isinstance(curr, dict) or key not in curr:
            return None
        curr = curr[key]
    return curr


def _infer_type(val: JsonValue) -> str:
    if isinstance(val, bool):
        return "boolean"
    if isinstance(val, (int, float)):
        return "number"
    if isinstance(val, (dict, list)):
        return "json"
    return "string"


class GenericHttpConnector(BaseConnector):
    """Stateless, generic HTTP connector driven by per-connection HttpSourceSpec contracts."""

    def __init__(
        self,
        *,
        app_id: str = "http",
        client: httpx.AsyncClient | None = None,
        http_client: HttpClient | None = None,
        egress_policy: EgressPolicyPort | None = None,
        timeout_seconds: float = 10.0,
        allow_private_ips: bool = False,
    ) -> None:
        self._app_id = app_id
        self._timeout_seconds = timeout_seconds
        self._allow_private_ips = allow_private_ips or (client is not None)
        self._egress_policy = egress_policy or PublicInternetEgressPolicy(
            allow_private_ips=self._allow_private_ips
        )

        if http_client is not None:
            self._http_client = http_client
        elif client is not None:
            self._http_client = HttpClient(
                client=client,
                backoff_handler=HttpBackoffHandler(max_retries=0),
                allow_private_ips=True,
                response_policy=PassThroughPolicy(),
            )
        else:
            raw_client = create_http_client(timeout=timeout_seconds)
            self._http_client = HttpClient(
                client=raw_client,
                backoff_handler=HttpBackoffHandler(max_retries=2),
                allow_private_ips=self._allow_private_ips,
                response_policy=PassThroughPolicy(),
            )

    @property
    def app_id(self) -> str:
        return self._app_id

    @staticmethod
    def _build_safe_target_url(
        base_url: str, path: str
    ) -> Result[str, EndpointSecurityViolationError]:
        """Combines base_url with relative path ensuring scheme and netloc do not deviate."""
        base_parts = urlsplit(base_url)
        joined = urljoin(base_url.rstrip("/") + "/", path.lstrip("/"))
        joined_parts = urlsplit(joined)
        if joined_parts.scheme != base_parts.scheme or joined_parts.netloc != base_parts.netloc:
            return Result.fail(
                EndpointSecurityViolationError(
                    endpoint=joined,
                    message=f"Target URL '{joined}' deviates from configured origin '{base_url}'",
                )
            )
        return Result.ok(joined)

    async def _send_request(self, req: httpx.Request) -> httpx.Response:
        url_without_query = str(req.url).split("?")[0]
        params = dict(req.url.params) if req.url.params else None
        return await self._http_client.request(
            method=req.method,
            url=url_without_query,
            headers=dict(req.headers),
            params=params,
            content=req.content,
            timeout=self._timeout_seconds,
        )

    def spec(self) -> AppSpecDTO:
        """Returns the dynamic property schema for configuring generic HTTP connections."""
        return AppSpecDTO(
            app_id=self._app_id,
            display_name="HTTP / REST API",
            category="API",
            description="Universal HTTP / REST API connector for SaaS and custom web endpoints.",
            properties=[
                ConnectorPropertyDTO(
                    name="base_url",
                    label="Base URL",
                    type="SHORT_TEXT",
                    required=True,
                    description="Base HTTPS URL for the target API.",
                    default="https://api.example.com",
                ),
                ConnectorPropertyDTO(
                    name="auth_type",
                    label="Authentication Type",
                    type="DROPDOWN",
                    required=True,
                    description="Authentication method required by the API.",
                    options=[
                        DropdownOptionDTO(label="None", value="NO_AUTH"),
                        DropdownOptionDTO(label="Bearer Token", value="BEARER_TOKEN"),
                        DropdownOptionDTO(label="API Key", value="API_KEY"),
                        DropdownOptionDTO(label="Basic Auth", value="BASIC_AUTH"),
                        DropdownOptionDTO(
                            label="OAuth2 Client Credentials", value="OAUTH2_CLIENT_CREDENTIALS"
                        ),
                    ],
                    default="BEARER_TOKEN",
                ),
                ConnectorPropertyDTO(
                    name="check_path",
                    label="Health Check Path",
                    type="SHORT_TEXT",
                    required=False,
                    description="Relative path used to verify connection status (e.g. /health).",
                    default="/",
                ),
            ],
            auth_type=AuthType.BEARER_TOKEN.value,
        )

    def _build_source_spec(
        self, public_config: JsonDict
    ) -> Result[HttpSourceSpec, InvalidConnectionConfigError]:
        """Constructs an immutable HttpSourceSpec from per-connection public config."""
        base_url_raw = (
            public_config.get("base_url")
            or public_config.get("endpoint_url")
            or public_config.get("host")
        )
        if not base_url_raw or not str(base_url_raw).strip():
            return Result.fail(
                InvalidConnectionConfigError(
                    field_name="public_config",
                    message="Public config must contain 'base_url' or 'endpoint_url'.",
                )
            )
        base_url = str(base_url_raw).strip()

        raw_auth = str(public_config.get("auth_type") or "NO_AUTH")
        try:
            auth_type = AuthType(raw_auth)
        except ValueError:
            auth_type = AuthType.NO_AUTH

        raw_headers = public_config.get("default_headers")
        default_headers: dict[str, str] = (
            {str(k): str(v) for k, v in raw_headers.items()}
            if isinstance(raw_headers, dict)
            else {}
        )

        check_path = str(public_config.get("check_path") or "/")
        check_request = HttpRequestSpec(path=check_path, method="GET")

        raw_streams = public_config.get("streams")
        streams_list = [
            self._build_stream_definition(s)
            for s in (raw_streams if isinstance(raw_streams, list) else [])
            if isinstance(s, dict)
        ]

        return Result.ok(
            HttpSourceSpec(
                base_url=base_url,
                auth_type=auth_type,
                default_headers=default_headers,
                check_request=check_request,
                streams=tuple(streams_list),
            )
        )

    @staticmethod
    def _build_stream_definition(s: JsonDict) -> HttpStreamDefinition:
        stream_name = str(s.get("name") or s.get("stream") or "records")
        path = str(s.get("path") or f"/{stream_name}")
        raw_rec_path = s.get("record_path")
        record_path: tuple[str, ...] = (
            tuple(str(part) for part in raw_rec_path)
            if isinstance(raw_rec_path, (list, tuple))
            else ()
        )
        raw_pk = s.get("primary_key")
        pk_items = raw_pk if isinstance(raw_pk, (list, tuple)) else [["id"]]
        pk: tuple[tuple[str, ...], ...] = tuple(
            tuple(str(part) for part in p) if isinstance(p, (list, tuple)) else (str(p),)
            for p in pk_items
        )
        raw_cf = s.get("cursor_field")
        cursor_field: tuple[str, ...] | None = (
            tuple(str(part) for part in raw_cf)
            if isinstance(raw_cf, (list, tuple))
            else ((str(raw_cf),) if raw_cf else None)
        )
        del_marker: DeletionMarker | None = None
        raw_dm = s.get("deletion_marker")
        if isinstance(raw_dm, dict):
            raw_fp = raw_dm.get("field_path")
            fp_tuple = (
                tuple(str(part) for part in raw_fp) if isinstance(raw_fp, (list, tuple)) else ()
            )
            raw_ev = raw_dm.get("expected_value")
            ev_prim = raw_ev if isinstance(raw_ev, (str, int, float, bool)) else None
            del_marker = DeletionMarker(
                field_path=fp_tuple,
                expected_value=ev_prim,
            )
        raw_pag = str(s.get("pagination", "none")).lower()
        try:
            pag_type = PaginationType(raw_pag)
        except ValueError:
            pag_type = PaginationType.NONE

        raw_qp = s.get("query_params")
        query_params = (
            {str(k): str(v) for k, v in raw_qp.items()} if isinstance(raw_qp, dict) else {}
        )
        raw_hdrs = s.get("headers")
        headers = (
            {str(k): str(v) for k, v in raw_hdrs.items()} if isinstance(raw_hdrs, dict) else {}
        )
        raw_pp = s.get("pagination_params")
        pag_params: dict[str, JsonValue] = (
            {str(k): v for k, v in raw_pp.items()} if isinstance(raw_pp, dict) else {}
        )
        raw_inc = s.get("incremental_param")
        inc_param = str(raw_inc) if raw_inc is not None else None

        req_spec = HttpRequestSpec(
            path=path,
            method=str(s.get("method", "GET")),
            query_params=query_params,
            headers=headers,
            pagination=pag_type,
            pagination_params=pag_params,
            incremental_param=inc_param,
        )
        rep_spec = StreamDefinition(
            stream=stream_name,
            record_path=record_path,
            primary_key=pk,
            cursor_field=cursor_field,
            cursor_kind=CursorKind(str(s.get("cursor_kind", "STRING"))),
            sync_mode=SyncMode(str(s.get("sync_mode", "INCREMENTAL"))),
            deletion_marker=del_marker,
            extractor_id=str(s.get("extractor_id", "declarative")),
        )
        fetch_one_raw = s.get("fetch_one")
        fetch_one_spec = None
        if isinstance(fetch_one_raw, dict) and "path" in fetch_one_raw:
            fo_hdrs = fetch_one_raw.get("headers")
            fo_qp = fetch_one_raw.get("query_params")
            fetch_one_spec = HttpRequestSpec(
                path=str(fetch_one_raw["path"]),
                method=str(fetch_one_raw.get("method", "GET")),
                headers=(
                    {str(k): str(v) for k, v in fo_hdrs.items()}
                    if isinstance(fo_hdrs, dict)
                    else {}
                ),
                query_params=(
                    {str(k): str(v) for k, v in fo_qp.items()} if isinstance(fo_qp, dict) else {}
                ),
            )
        raw_norm = s.get("normalizer_id")
        return HttpStreamDefinition(
            request=req_spec,
            replication=rep_spec,
            normalizer_id=str(raw_norm) if raw_norm is not None else None,
            fetch_one=fetch_one_spec,
        )

    async def check(
        self,
        public_config: JsonDict,
        credentials: JsonDict,
    ) -> ConnectionCheckResultDTO:
        """Validates connection health and authentication with the external system."""
        spec_res = self._build_source_spec(public_config)
        if spec_res.is_err or spec_res.value is None:
            assert spec_res.error is not None
            return ConnectionCheckResultDTO(
                success=False,
                status="FAILED",
                error_code="INVALID_CONFIG",
                message=spec_res.error.message,
            )
        spec = spec_res.value

        # 1. Egress validation
        egress_res = self._egress_policy.validate_url(spec.base_url)
        if egress_res.is_err and egress_res.error:
            return ConnectionCheckResultDTO.from_error(
                egress_res.error, error_code_override="NETWORK_ERROR"
            )

        # 2. Build authenticator
        authenticator = AuthStrategyResolver.resolve(
            spec.auth_type,
            credentials,
            allow_private_ips=self._allow_private_ips,
        )

        # 3. Assemble target request
        check_path = spec.check_request.path if spec.check_request else "/"
        url_res = self._build_safe_target_url(spec.base_url, check_path)
        if url_res.is_err or url_res.value is None:
            assert url_res.error is not None
            return ConnectionCheckResultDTO.from_error(
                url_res.error, error_code_override="NETWORK_ERROR"
            )
        target_url = url_res.value

        req = httpx.Request(
            method="GET",
            url=target_url,
            headers=dict(spec.default_headers),
        )
        req = authenticator.authenticate_request(req)

        try:
            resp = await self._send_request(req)
            if resp.status_code in (401, 403):
                return ConnectionCheckResultDTO(
                    success=False,
                    status="FAILED",
                    error_code="UNAUTHORIZED",
                    message=f"HTTP {resp.status_code}: Unauthorized - {resp.text[:200]}",
                )
            if resp.status_code >= 400:
                return ConnectionCheckResultDTO(
                    success=False,
                    status="FAILED",
                    error_code=IpErrorCode.HTTP_ERROR.value,
                    message=f"HTTP {resp.status_code}: {resp.text[:200]}",
                )
            return ConnectionCheckResultDTO.ok("Connection verified successfully.")
        except (httpx.HTTPError, HttpError, OSError) as exc:
            return ConnectionCheckResultDTO(
                success=False,
                status="FAILED",
                error_code="NETWORK_ERROR",
                message=str(exc),
            )

    def _fallback_streams_for_app(self) -> list[StreamSchemaDTO]:
        return [
            StreamSchemaDTO(
                name="records",
                fields=[
                    StreamFieldDTO(name="id", data_type="string", nullable=False),
                    StreamFieldDTO(name="data", data_type="json", nullable=True),
                ],
                primary_key=["id"],
                supported_sync_modes=["FULL_REFRESH", "INCREMENTAL"],
            )
        ]

    async def _discover_from_schema_endpoint(
        self,
        connection_id: str,
        spec: HttpSourceSpec,
        authenticator: AuthenticatorPort,
    ) -> tuple[list[StreamSchemaDTO], DiscoveredCatalogDTO | None]:
        url_res = self._build_safe_target_url(spec.base_url, "api/v1/schema/streams")
        if url_res.is_err or url_res.value is None:
            assert url_res.error is not None
            return [], DiscoveredCatalogDTO.from_error(
                connection_id=connection_id, error=url_res.error
            )
        schema_url = url_res.value
        req = httpx.Request(
            method="GET",
            url=schema_url,
            headers=dict(spec.default_headers),
        )
        req = authenticator.authenticate_request(req)
        try:
            resp = await self._send_request(req)
            if resp.status_code in (401, 403):
                return [], DiscoveredCatalogDTO(
                    connection_id=connection_id,
                    catalog_version=1,
                    catalog_hash="",
                    streams=[],
                    success=False,
                    error_code="UNAUTHORIZED",
                    error_message=f"Authentication failed: HTTP {resp.status_code}",
                )
            if resp.status_code == 200:
                payload = resp.json()
                streams: list[StreamSchemaDTO] = []
                for s in payload.get("streams", []):
                    fields = [
                        StreamFieldDTO(
                            name=f["name"],
                            data_type=f["data_type"],
                            nullable=f.get("nullable", True),
                            description=f.get("description"),
                        )
                        for f in s.get("fields", [])
                    ]
                    supported = [
                        m
                        for m in s.get("supported_sync_modes", ["FULL_REFRESH", "INCREMENTAL"])
                        if m in ("FULL_REFRESH", "INCREMENTAL")
                    ]
                    if supported:
                        streams.append(
                            StreamSchemaDTO(
                                name=s["name"],
                                fields=fields,
                                primary_key=list(s.get("primary_key", ["id"])),
                                cursor_field=s.get("cursor_field"),
                                supported_sync_modes=supported,
                            )
                        )
                return streams, None
            if resp.status_code == 404:
                return self._fallback_streams_for_app(), None
        except (httpx.HTTPError, HttpError, OSError) as e:
            logger.exception("schema_discovery_request_failed", error=str(e))
        return [], None

    async def _sample_stream_schema(
        self,
        stream_def: HttpStreamDefinition,
        spec: HttpSourceSpec,
        authenticator: AuthenticatorPort,
    ) -> StreamSchemaDTO:
        stream_name = stream_def.replication.stream
        req_spec = stream_def.request
        url_res = self._build_safe_target_url(spec.base_url, req_spec.path)
        if url_res.is_err or url_res.value is None:
            pk_strings = [".".join(p) for p in stream_def.replication.primary_key] or ["id"]
            cursor_str = (
                ".".join(stream_def.replication.cursor_field)
                if stream_def.replication.cursor_field
                else None
            )
            return StreamSchemaDTO(
                name=stream_name,
                fields=[
                    StreamFieldDTO(name="id", data_type="string", nullable=False),
                    StreamFieldDTO(name="data", data_type="json", nullable=True),
                ],
                primary_key=pk_strings,
                cursor_field=cursor_str,
                supported_sync_modes=[stream_def.replication.sync_mode.value],
            )

        target_url = url_res.value

        sample_params = dict(req_spec.query_params)
        sample_params["limit"] = "5"

        req = httpx.Request(
            method=req_spec.method,
            url=target_url,
            params=sample_params,
            headers={**spec.default_headers, **req_spec.headers},
        )
        req = authenticator.authenticate_request(req)

        fields: list[StreamFieldDTO] = []
        try:
            resp = await self._send_request(req)
            if resp.status_code < 400:
                payload = resp.json()
                records = _extract_nested(payload, stream_def.replication.record_path)
                if isinstance(records, dict):
                    records = [records]
                if isinstance(records, list) and records and isinstance(records[0], dict):
                    first = records[0]
                    for k, v in first.items():
                        fields.append(
                            StreamFieldDTO(
                                name=str(k),
                                data_type=_infer_type(v),
                                nullable=True,
                            )
                        )
        except (httpx.HTTPError, HttpError, OSError, ValueError) as e:
            logger.exception(
                "stream_discovery_sample_read_failed",
                stream=stream_name,
                error=str(e),
            )

        if not fields:
            fields = [
                StreamFieldDTO(name="id", data_type="string", nullable=False),
                StreamFieldDTO(name="data", data_type="json", nullable=True),
            ]

        pk_strings = [".".join(p) for p in stream_def.replication.primary_key] or ["id"]
        cursor_str = (
            ".".join(stream_def.replication.cursor_field)
            if stream_def.replication.cursor_field
            else None
        )

        return StreamSchemaDTO(
            name=stream_name,
            fields=fields,
            primary_key=pk_strings,
            cursor_field=cursor_str,
            supported_sync_modes=[stream_def.replication.sync_mode.value],
        )

    async def discover(
        self,
        connection_id: str,
        public_config: JsonDict,
        credentials: JsonDict,
    ) -> DiscoveredCatalogDTO:
        """Introspects configured streams and samples data to infer schemas."""
        spec_res = self._build_source_spec(public_config)
        if spec_res.is_err or spec_res.value is None:
            assert spec_res.error is not None
            return DiscoveredCatalogDTO.from_error(
                connection_id=connection_id, error=spec_res.error
            )
        spec = spec_res.value

        egress_res = self._egress_policy.validate_url(spec.base_url)
        if egress_res.is_err and egress_res.error:
            return DiscoveredCatalogDTO.from_error(
                connection_id=connection_id, error=egress_res.error
            )

        authenticator = AuthStrategyResolver.resolve(
            spec.auth_type,
            credentials,
            allow_private_ips=self._allow_private_ips,
        )

        if not spec.streams:
            discovered, auth_err = await self._discover_from_schema_endpoint(
                connection_id, spec, authenticator
            )
            if auth_err is not None:
                return auth_err
        else:
            discovered = [
                await self._sample_stream_schema(s_def, spec, authenticator)
                for s_def in spec.streams
            ]

        return self.build_catalog_dto(
            connection_id=connection_id,
            streams=discovered,
            catalog_version=1,
        )

    async def list_objects(
        self,
        stream_name: str,
        public_config: JsonDict,
        credentials: JsonDict,
        limit: int = 100,
        cursor: str | None = None,
    ) -> Sequence[str]:
        """Lists discrete object identifiers from a stream."""
        identifiers: list[str] = []
        async for envelope in self.read_stream(
            stream_name=stream_name,
            public_config=public_config,
            credentials=credentials,
            cursor=cursor,
            limit=limit,
        ):
            record_id = envelope.record_id or envelope.data.get("id") or str(len(identifiers))
            identifiers.append(str(record_id))
            if len(identifiers) >= limit:
                break
        return identifiers

    def _resolve_read_stream_def(
        self, spec: HttpSourceSpec, stream_name: str
    ) -> HttpStreamDefinition:
        stream_def = spec.get_stream(stream_name)
        if stream_def:
            return stream_def

        fallback_path = f"/{stream_name}"
        req_spec = HttpRequestSpec(path=fallback_path, method="GET")
        rep_spec = StreamDefinition(stream=stream_name, primary_key=(("id",),))
        return HttpStreamDefinition(request=req_spec, replication=rep_spec)

    @staticmethod
    def _extract_records_from_response(
        resp: httpx.Response, stream_def: HttpStreamDefinition
    ) -> tuple[list[JsonDict], JsonValue]:
        try:
            payload = resp.json()
        except (ValueError, TypeError):
            payload = {"raw": resp.text}

        records_raw = _extract_nested(payload, stream_def.replication.record_path)
        if (records_raw is None or records_raw == payload) and isinstance(payload, dict):
            records_raw = (
                payload.get("records") or payload.get("items") or payload.get("data") or payload
            )
        if isinstance(records_raw, dict):
            records_raw = [records_raw]
        elif not isinstance(records_raw, list):
            records_raw = []

        dict_records: list[JsonDict] = [r for r in records_raw if isinstance(r, dict)]
        return dict_records, payload

    @staticmethod
    def _create_record_envelope(
        item: JsonDict, stream_def: HttpStreamDefinition, stream_name: str
    ) -> RecordEnvelopeDTO:
        cursor_val: str | None = None
        if stream_def.replication.cursor_field:
            c_val = _extract_nested(item, stream_def.replication.cursor_field)
            if c_val is not None:
                cursor_val = str(c_val)

        pk_parts = [
            str(_extract_nested(item, path))
            for path in stream_def.replication.primary_key
            if _extract_nested(item, path) is not None
        ]
        if pk_parts:
            rec_id = ":".join(pk_parts)
        else:
            rec_id = str(item.get("id") or item.get("_id") or cursor_val or "")
        return RecordEnvelopeDTO(
            stream_name=stream_name,
            record_id=rec_id,
            data=item,
            emitted_at=datetime.now(UTC).isoformat(),
            cursor_value=cursor_val,
        )

    def _init_read_params(
        self,
        stream_def: HttpStreamDefinition,
        cursor: str | None,
        limit: int,
    ) -> dict[str, str]:
        params = dict(stream_def.request.query_params)
        if limit:
            params["limit"] = str(limit)
        if cursor and stream_def.request.incremental_param:
            params[stream_def.request.incremental_param] = str(cursor)
        return params

    async def _fetch_read_page(
        self,
        req: httpx.Request,
        target_url: str,
        stream_name: str,
    ) -> httpx.Response | None:
        try:
            resp = await self._send_request(req)
        except (httpx.HTTPError, HttpError, OSError) as e:
            self._last_error = UpstreamNetworkError(
                endpoint=target_url,
                message=f"Network error reading stream '{stream_name}': {e}",
            )
            return None

        if resp.status_code >= 400:
            self._last_error = UpstreamHttpError(
                status_code=resp.status_code,
                message=f"Upstream HTTP error {resp.status_code} on stream '{stream_name}'",
                details={"endpoint": target_url, "response_body": resp.text[:500]},
            )
            return None
        return resp

    async def read_stream(
        self,
        stream_name: str,
        public_config: JsonDict,
        credentials: JsonDict,
        cursor: str | None = None,
        limit: int = 100,
    ) -> AsyncIterator[RecordEnvelopeDTO]:
        """Streams records asynchronously from the target HTTP stream."""
        self._last_error = None
        spec_res = self._build_source_spec(public_config)
        if spec_res.is_err or spec_res.value is None:
            self._last_error = spec_res.error
            return
        spec = spec_res.value

        stream_def = self._resolve_read_stream_def(spec, stream_name)

        egress_res = self._egress_policy.validate_url(spec.base_url)
        if egress_res.is_err:
            self._last_error = egress_res.error
            return

        authenticator = AuthStrategyResolver.resolve(
            spec.auth_type,
            credentials,
            allow_private_ips=self._allow_private_ips,
        )

        pagination_strat = PaginationStrategyResolver.resolve(stream_def.request.pagination)
        query_params = self._init_read_params(stream_def, cursor, limit)
        page_index = 0
        url_res = self._build_safe_target_url(spec.base_url, stream_def.request.path)
        if url_res.is_err or url_res.value is None:
            self._last_error = url_res.error
            return
        target_url = url_res.value

        while page_index <= 500:
            req = httpx.Request(
                method=stream_def.request.method,
                url=target_url,
                params=query_params,
                headers={**spec.default_headers, **stream_def.request.headers},
            )
            req = authenticator.authenticate_request(req)

            resp = await self._fetch_read_page(req, target_url, stream_name)
            if resp is None:
                return

            dict_records, payload = self._extract_records_from_response(resp, stream_def)
            for item in dict_records:
                yield self._create_record_envelope(item, stream_def, stream_name)

            next_params = pagination_strat.get_next_page(
                current_query_params=query_params,
                last_response_data=payload,
                last_response_headers=dict(resp.headers),
                page_index=page_index,
                records_in_page=len(dict_records),
                pagination_params=stream_def.request.pagination_params,
            )

            if not next_params or next_params == query_params:
                break

            query_params = next_params
            page_index += 1

    async def fetch_record(
        self,
        stream_name: str,
        record_id: str,
        public_config: JsonDict,
        credentials: JsonDict,
    ) -> RecordEnvelopeDTO | None:
        """Fetches a single record by primary key via fetch_one specification."""
        self._last_error = None
        spec_res = self._build_source_spec(public_config)
        if spec_res.is_err or spec_res.value is None:
            self._last_error = spec_res.error
            return None
        spec = spec_res.value

        stream_def = self._resolve_read_stream_def(spec, stream_name)
        if stream_def.fetch_one is None:
            return None

        egress_res = self._egress_policy.validate_url(spec.base_url)
        if egress_res.is_err:
            self._last_error = egress_res.error
            return None

        authenticator = AuthStrategyResolver.resolve(
            spec.auth_type,
            credentials,
            allow_private_ips=self._allow_private_ips,
        )

        encoded_record_id = quote(str(record_id), safe="")
        path = stream_def.fetch_one.path.replace("{record_id}", encoded_record_id)
        url_res = self._build_safe_target_url(spec.base_url, path)
        if url_res.is_err or url_res.value is None:
            self._last_error = url_res.error
            return None
        target_url = url_res.value

        req = httpx.Request(
            method=stream_def.fetch_one.method,
            url=target_url,
            params=stream_def.fetch_one.query_params,
            headers={**spec.default_headers, **stream_def.fetch_one.headers},
        )
        req = authenticator.authenticate_request(req)

        resp = await self._fetch_read_page(req, target_url, stream_name)
        if resp is None:
            return None

        dict_records, _ = self._extract_records_from_response(resp, stream_def)
        if dict_records:
            return self._create_record_envelope(dict_records[0], stream_def, stream_name)
        return None

    def _resolve_write_action(
        self,
        stream_def: HttpStreamDefinition | None,
        operation: str,
        target_record_id: str,
        stream_name: str,
    ) -> tuple[str, str]:
        encoded_record_id = quote(str(target_record_id), safe="") if target_record_id else ""
        fallback_prefix = (
            stream_def.request.path
            if stream_def and stream_def.request and stream_def.request.path
            else f"/{stream_name}"
        )
        method = "POST"
        path = fallback_prefix
        if operation == "UPDATE":
            method = "PUT"
            path = f"{fallback_prefix}/{encoded_record_id}"
        elif operation == "UPSERT":
            method = "PUT" if encoded_record_id else "POST"
            path = (
                f"{fallback_prefix}/{encoded_record_id}" if encoded_record_id else fallback_prefix
            )
        elif operation == "DELETE":
            method = "DELETE"
            path = f"{fallback_prefix}/{encoded_record_id}"

        if stream_def and stream_def.write:
            try:
                op_enum = HttpWriteOperation(operation)
                if op_enum in stream_def.write.actions:
                    action = stream_def.write.actions[op_enum]
                    method = action.method
                    path = action.path_template.replace("{record_id}", encoded_record_id)
            except ValueError:
                pass
        return method, path

    async def write_record(
        self,
        stream_name: str,
        command: WriteRecordCommand,
        public_config: JsonDict,
        credentials: JsonDict,
    ) -> WriteResultDTO:
        """Writes/mutates an individual record in the destination HTTP system."""
        target_record_id = command.record_id or ""
        spec_res = self._build_source_spec(public_config)
        if spec_res.is_err or spec_res.value is None:
            err = spec_res.error or InvalidConnectionConfigError(
                field_name="public_config",
                message="Invalid connection public configuration.",
            )
            self._last_error = err
            return WriteResultDTO.from_error(err, record_id=target_record_id or "failed")
        spec = spec_res.value

        egress_res = self._egress_policy.validate_url(spec.base_url)
        if egress_res.is_err and egress_res.error:
            self._last_error = egress_res.error
            return WriteResultDTO.from_error(
                egress_res.error, record_id=target_record_id or "failed"
            )

        stream_def = spec.get_stream(stream_name)

        method, path = self._resolve_write_action(
            stream_def, command.operation, target_record_id, stream_name
        )
        url_res = self._build_safe_target_url(spec.base_url, path)
        if url_res.is_err or url_res.value is None:
            url_err = url_res.error or EndpointSecurityViolationError(
                endpoint=path,
                message="Invalid target URL.",
            )
            self._last_error = url_err
            return WriteResultDTO.from_error(url_err, record_id=target_record_id or "failed")
        target_url = url_res.value

        authenticator = AuthStrategyResolver.resolve(
            spec.auth_type,
            credentials,
            allow_private_ips=self._allow_private_ips,
        )

        merged_headers: dict[str, str] = {
            **spec.default_headers,
            **command.headers,
        }
        if command.idempotency_key:
            merged_headers[command.idempotency_header_name] = command.idempotency_key

        req = httpx.Request(
            method=method,
            url=target_url,
            headers=merged_headers,
            json=command.payload if method != "DELETE" else None,
        )
        req = authenticator.authenticate_request(req)

        return await self._execute_tracked_write_request(
            send_fn=lambda: self._send_request(req),
            target_url=target_url,
            http_method=method,
            request_headers=dict(req.headers),
            default_record_id=target_record_id,
            error_record_id=target_record_id,
        )
