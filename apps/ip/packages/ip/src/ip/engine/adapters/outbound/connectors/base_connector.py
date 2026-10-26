import hashlib
import json
import time
from abc import ABC
from collections.abc import Awaitable, Callable, Sequence
from contextvars import ContextVar
from datetime import UTC, datetime

import httpx
from ip.engine.application.responses import (
    DiscoveredCatalogDTO,
    StreamSchemaDTO,
)
from ip.engine.domain.enums import FailureDisposition
from ip.engine.domain.exceptions import (
    EndpointSecurityViolationError,
    InvalidConnectionConfigError,
    InvalidEndpointError,
    IpError,
    IpErrorCode,
    Result,
    UpstreamHttpError,
    UpstreamNetworkError,
)
from ip.engine.domain.services.outbound_error_classifier import (
    classify_outbound_http_outcome,
    redact_sensitive_headers,
)
from ip.engine.ports.outbound.connector_port import ConnectorPort
from ip.engine.ports.types import RecordEnvelopeDTO, WriteResultDTO
from seedwork.domain.types import JsonDict
from shttp import HttpError, validate_target_url
from shttp.exceptions import SsrfSecurityError

_LOCAL_TEST_HOSTS = ("localhost", "127.0.0.1", "::1", "testserver")

_last_stream_error: ContextVar[IpError | None] = ContextVar(
    "connector_last_stream_error", default=None
)


class BaseConnector(ConnectorPort, ABC):
    """Abstract base connector encapsulating catalog hashing and shared URL/SSRF validation helpers."""

    @property
    def last_error(self) -> IpError | None:
        """Returns the task-isolated domain/operational error encountered during stream reading, if any."""
        return _last_stream_error.get()

    @last_error.setter
    def last_error(self, err: IpError | None) -> None:
        _last_stream_error.set(err)

    @property
    def _last_error(self) -> IpError | None:
        return _last_stream_error.get()

    @_last_error.setter
    def _last_error(self, err: IpError | None) -> None:
        _last_stream_error.set(err)

    @staticmethod
    def _parse_and_validate_url_structure(
        stripped: str,
        raw_endpoint: str,
        *,
        disallow_query_or_fragment: bool,
        error_code: IpErrorCode,
        field_name: str,
    ) -> Result[
        httpx.URL,
        InvalidConnectionConfigError | InvalidEndpointError | EndpointSecurityViolationError,
    ]:
        if not stripped:
            return Result.fail(
                InvalidConnectionConfigError(
                    field_name=field_name,
                    code=error_code,
                    message=f"Missing required field: {field_name}",
                )
            )
        try:
            url = httpx.URL(stripped)
        except httpx.InvalidURL as exc:
            return Result.fail(
                InvalidEndpointError(
                    endpoint=raw_endpoint,
                    code=error_code,
                    message=f"Malformed endpoint URL: {exc}",
                )
            )
        if not url.host:
            return Result.fail(
                InvalidEndpointError(
                    endpoint=raw_endpoint,
                    code=error_code,
                    message="Endpoint URL must include a host.",
                )
            )
        if url.username or url.password:
            return Result.fail(
                EndpointSecurityViolationError(
                    endpoint=raw_endpoint,
                    code=error_code,
                    message="Endpoint URL cannot contain embedded user credentials.",
                )
            )
        if disallow_query_or_fragment and (url.query or url.fragment):
            return Result.fail(
                InvalidEndpointError(
                    endpoint=raw_endpoint,
                    code=error_code,
                    message="Endpoint URL cannot contain query or fragment parameters.",
                )
            )
        return Result.ok(url)

    @staticmethod
    def validate_http_endpoint_url(
        endpoint: str,
        *,
        allow_private_ips: bool = False,
        enforce_ssrf_precheck: bool = True,
        disallow_query_or_fragment: bool = False,
        error_code: IpErrorCode = IpErrorCode.INVALID_CONFIGURATION,
        field_name: str = "endpoint_url",
    ) -> Result[
        str,
        InvalidConnectionConfigError | InvalidEndpointError | EndpointSecurityViolationError,
    ]:
        """Centralized HTTP endpoint URL & SSRF validation shared across connectors."""
        stripped = endpoint.strip()
        parsed_res = BaseConnector._parse_and_validate_url_structure(
            stripped,
            endpoint,
            disallow_query_or_fragment=disallow_query_or_fragment,
            error_code=error_code,
            field_name=field_name,
        )
        if parsed_res.error is not None or parsed_res.value is None:
            return Result.fail(
                parsed_res.error
                or InvalidEndpointError(
                    endpoint=endpoint,
                    code=error_code,
                    message="Malformed endpoint URL.",
                )
            )

        url = parsed_res.value
        hostname = url.host.lower()
        allowed_http_hosts = (
            _LOCAL_TEST_HOSTS if (allow_private_ips or not enforce_ssrf_precheck) else ()
        )
        if url.scheme != "https" and hostname not in allowed_http_hosts:
            return Result.fail(
                EndpointSecurityViolationError(
                    endpoint=endpoint,
                    code=error_code,
                    message=f"Endpoint URL must use HTTPS: {endpoint}",
                )
            )

        if hostname.startswith("169.254."):
            return Result.fail(
                EndpointSecurityViolationError(
                    endpoint=endpoint,
                    code=error_code,
                    message="Access to link-local and cloud metadata endpoints is prohibited.",
                )
            )

        if enforce_ssrf_precheck:
            if not allow_private_ips and hostname in _LOCAL_TEST_HOSTS:
                return Result.fail(
                    EndpointSecurityViolationError(
                        endpoint=endpoint,
                        code=error_code,
                        message=f"Restricted hostname or IP address in endpoint: {hostname}",
                    )
                )
            try:
                validate_target_url(stripped, allow_private_ips=allow_private_ips)
            except SsrfSecurityError as exc:
                return Result.fail(
                    EndpointSecurityViolationError(
                        endpoint=endpoint,
                        code=error_code,
                        message=f"Restricted destination forbidden: {exc}",
                    )
                )

        return Result.ok(stripped.rstrip("/"))

    @staticmethod
    def build_catalog_dto(
        connection_id: str,
        streams: Sequence[StreamSchemaDTO],
        catalog_version: int = 1,
        discovered_at: str | None = None,
    ) -> DiscoveredCatalogDTO:
        """Helper to construct DiscoveredCatalogDTO with deterministic SHA-256 hash."""
        stream_dicts = [
            {
                "name": s.name,
                "fields": [{"name": f.name, "type": f.data_type} for f in s.fields],
                "primary_key": list(s.primary_key),
                "cursor_field": s.cursor_field,
            }
            for s in streams
        ]
        raw = json.dumps(stream_dicts, sort_keys=True)
        catalog_hash = hashlib.sha256(raw.encode("utf-8")).hexdigest()

        return DiscoveredCatalogDTO(
            connection_id=connection_id,
            catalog_version=catalog_version,
            catalog_hash=catalog_hash,
            streams=streams,
            discovered_at=discovered_at or datetime.now(UTC).isoformat(),
        )

    async def fetch_record(
        self,
        stream_name: str,
        record_id: str,
        public_config: JsonDict,
        credentials: JsonDict,
    ) -> RecordEnvelopeDTO | None:
        """Default fetch_record implementation returning None when unsupported."""
        return None

    @staticmethod
    def _parse_json_write_response(
        resp: httpx.Response,
        default_record_id: str,
    ) -> tuple[str, str | None, JsonDict | None]:
        result_record_id = default_record_id
        destination_id: str | None = None
        parsed_body: JsonDict | None = None
        if resp.content:
            try:
                body = resp.json()
                if isinstance(body, dict):
                    parsed_body = body
                    raw_id = body.get("id") or body.get("Id")
                    if raw_id is not None:
                        result_record_id = str(raw_id)
                        destination_id = str(raw_id)
                    if "destination_id" in body and body["destination_id"] is not None:
                        destination_id = str(body["destination_id"])
            except (ValueError, TypeError):
                pass
        return result_record_id, destination_id, parsed_body

    async def _execute_tracked_write_request(
        self,
        *,
        send_fn: Callable[[], Awaitable[httpx.Response]],
        target_url: str,
        http_method: str,
        request_headers: dict[str, str],
        default_record_id: str,
        error_record_id: str,
        extra_sensitive_headers: Sequence[str] | None = None,
    ) -> WriteResultDTO:
        """Shared Layer-5 outbound HTTP execution with timing, header redaction, and error classification."""
        redacted_req_headers = redact_sensitive_headers(
            request_headers, extra_sensitive_names=extra_sensitive_headers
        )
        started_at = time.perf_counter()
        try:
            resp = await send_fn()
            duration_ms = max(1, int((time.perf_counter() - started_at) * 1000))
            resp_headers_raw = dict(resp.headers)
            redacted_resp_headers = redact_sensitive_headers(
                resp_headers_raw, extra_sensitive_names=extra_sensitive_headers
            )
            result_record_id, destination_id, parsed_body = self._parse_json_write_response(
                resp, default_record_id
            )
            classification = classify_outbound_http_outcome(
                resp.status_code,
                headers=resp_headers_raw,
            )
            if resp.status_code >= 400:
                http_err = UpstreamHttpError(
                    status_code=resp.status_code,
                    message=f"HTTP {resp.status_code}: {resp.text[:200]}",
                    disposition=(
                        FailureDisposition.RETRY
                        if resp.status_code == 429 or resp.status_code >= 500
                        else FailureDisposition.FAIL
                    ),
                )
                return WriteResultDTO.from_error(
                    http_err,
                    record_id=error_record_id,
                    target_url=target_url,
                    http_method=http_method,
                    request_headers=redacted_req_headers,
                    response_status_code=resp.status_code,
                    response_headers=redacted_resp_headers,
                    response_body=parsed_body,
                    raw_response_bytes=bytes(resp.content) if resp.content else None,
                    duration_ms=duration_ms,
                    retry_after_seconds=classification.retry_after_seconds,
                    failure_category=(
                        classification.failure_category.value
                        if classification.failure_category is not None
                        else None
                    ),
                )
            return WriteResultDTO(
                success=True,
                record_id=result_record_id,
                destination_id=destination_id,
                target_url=target_url,
                http_method=http_method,
                request_headers=redacted_req_headers,
                response_status_code=resp.status_code,
                response_headers=redacted_resp_headers,
                response_body=parsed_body,
                raw_response_bytes=bytes(resp.content) if resp.content else None,
                duration_ms=duration_ms,
            )
        except (httpx.HTTPError, HttpError, OSError, ValueError) as exc:
            duration_ms = max(1, int((time.perf_counter() - started_at) * 1000))
            classification = classify_outbound_http_outcome(None)
            net_err = UpstreamNetworkError(
                endpoint=target_url,
                message=str(exc),
            )
            return WriteResultDTO.from_error(
                net_err,
                record_id=error_record_id,
                target_url=target_url,
                http_method=http_method,
                request_headers=redacted_req_headers,
                duration_ms=duration_ms,
                failure_category=(
                    classification.failure_category.value
                    if classification.failure_category is not None
                    else None
                ),
            )
