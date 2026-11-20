"""HttpDispatchStepHandler dispatching HTTP requests via Solution SDK ConnectorSpec functions using centralized shttp."""

from __future__ import annotations

import inspect
from collections.abc import Callable

import httpx
import structlog
from ip.engine.domain.stitch.enums import StitchStepType
from ip.engine.domain.stitch.steps.http_steps import (
    HttpDispatchStepInput,
    HttpDispatchStepOutput,
)
from ip.engine.ports.outbound.connection_repository_port import ConnectionRepositoryPort
from ip.sdk.contracts import RequestSpec
from ip.sdk.registry import DomainFunctionRegistry, default_registry
from orchestration.domain.constants import EffectPolicy, StepFailureCode
from orchestration.domain.exceptions import Result
from orchestration.domain.failures import (
    RetryableFailure,
    StepFailure,
    TerminalFailure,
)
from orchestration.ports.inbound.step_handler_port import StepContext, StepHandlerPort
from seedwork.domain.types import JsonDict
from shttp import HttpClient
from shttp.exceptions import HttpError

logger = structlog.get_logger(__name__)


def _build_request_spec(fn: Callable[..., object], payload: JsonDict) -> Result[RequestSpec, str]:
    """Invokes pure solution connector function to construct a RequestSpec."""
    try:
        cmd_arg: object = payload
        try:
            hints = inspect.get_annotations(fn, eval_str=True)
        except (NameError, TypeError, ValueError):
            hints = {}

        sig = inspect.signature(fn)
        first_param_name = next(iter(sig.parameters.keys()), None)
        if first_param_name and first_param_name in hints:
            param_type = hints[first_param_name]
            from_payload_method = getattr(param_type, "from_payload", None)
            if callable(from_payload_method):
                cmd_arg = from_payload_method(payload)

        spec_obj = fn(cmd_arg)
        if not isinstance(spec_obj, RequestSpec):
            return Result.err("Connector did not return a valid RequestSpec.")
        return Result.ok(spec_obj)
    except (ValueError, TypeError, KeyError, AttributeError) as exc:
        return Result.err(f"Connector execution failed: {exc}")


async def _execute_raw_http(
    client: HttpClient,
    method_upper: str,
    full_url: str,
    spec: RequestSpec,
) -> httpx.Response:
    """Executes the raw HTTP client call matching the method."""
    body_bytes: bytes | None = None
    body_json: JsonDict | None = None
    if isinstance(spec.body, dict):
        body_json = spec.body
    elif isinstance(spec.body, str):
        body_bytes = spec.body.encode("utf-8")
    elif isinstance(spec.body, bytes):
        body_bytes = spec.body

    if method_upper == "GET":
        return await client.get(full_url, headers=spec.headers, params=spec.params)
    if method_upper == "POST":
        return await client.post(
            full_url,
            headers=spec.headers,
            params=spec.params,
            json=body_json,
            content=body_bytes,
        )
    if method_upper == "PUT":
        return await client.put(
            full_url,
            headers=spec.headers,
            params=spec.params,
            json=body_json,
            content=body_bytes,
        )
    if method_upper == "PATCH":
        return await client.patch(
            full_url,
            headers=spec.headers,
            params=spec.params,
            json=body_json,
            content=body_bytes,
        )
    if method_upper == "DELETE":
        return await client.delete(full_url, headers=spec.headers, params=spec.params)
    raise ValueError(f"Unsupported HTTP method: {method_upper}")


async def _dispatch_via_http_client(
    client: HttpClient,
    method_upper: str,
    full_url: str,
    spec: RequestSpec,
) -> Result[tuple[int, dict[str, str], str], StepFailure]:
    """Executes the HTTP call using the injected shttp client and translates status codes."""
    try:
        try:
            resp = await _execute_raw_http(client, method_upper, full_url, spec)
        except ValueError as val_err:
            return Result.err(
                TerminalFailure(
                    code=StepFailureCode.VALIDATION_REJECTED,
                    detail=str(val_err),
                )
            )

        if resp.is_error:
            detail = f"HTTP {resp.status_code} from '{full_url}': {resp.text}"
            if 400 <= resp.status_code < 500:
                return Result.err(TerminalFailure(code=StepFailureCode.UPSTREAM_4XX, detail=detail))
            return Result.err(RetryableFailure(code=StepFailureCode.UPSTREAM_5XX, detail=detail))

        return Result.ok((resp.status_code, dict(resp.headers), resp.text))

    except HttpError as exc:
        detail = f"HTTP request failed: {exc}"
        status_code = getattr(exc, "status_code", 0)
        if 400 <= status_code < 500:
            return Result.err(TerminalFailure(code=StepFailureCode.UPSTREAM_4XX, detail=detail))
        return Result.err(RetryableFailure(code=StepFailureCode.UPSTREAM_5XX, detail=detail))
    except (ConnectionError, TimeoutError, OSError) as exc:
        detail = f"Network failure during HTTP dispatch: {exc}"
        return Result.err(RetryableFailure(code=StepFailureCode.CONNECTION_ERROR, detail=detail))


class HttpDispatchStepHandler(StepHandlerPort[JsonDict, JsonDict]):
    """Dispatches HTTP requests specified by Solution SDK ConnectorSpec functions using centralized shttp."""

    def __init__(
        self,
        *,
        registry: DomainFunctionRegistry | None = None,
        connection_repository: ConnectionRepositoryPort | None = None,
        http_client: HttpClient | None = None,
    ) -> None:
        self._registry = registry or default_registry
        self._connection_repo = connection_repository
        self._http_client = http_client

    @property
    def step_type(self) -> str:
        return StitchStepType.HTTP_DISPATCH.value

    @property
    def effect_policy(self) -> EffectPolicy:
        return EffectPolicy.IDEMPOTENT_EFFECT

    async def execute(
        self, context: StepContext, step_input: JsonDict
    ) -> Result[JsonDict, StepFailure]:
        bound = logger.bind(
            tenant_id=context.tenant_id,
            run_id=context.run_id,
            step_run_id=context.step_run_id,
            node_key=context.node_key,
        )
        bound.info("http_dispatch.received")

        parsed_res = HttpDispatchStepInput.from_payload(step_input)
        if parsed_res.is_err:
            detail = parsed_res.unwrap_err().message
            bound.error("http_dispatch.validation_failed", detail=detail)
            return Result.err(
                TerminalFailure(code=StepFailureCode.VALIDATION_REJECTED, detail=detail)
            )
        req = parsed_res.unwrap()

        # 1. Look up Solution Connector function in registry
        descriptor = self._registry.get_connector(req.app, req.entity)
        if descriptor is None:
            detail = f"No Solution Connector registered for '{req.app}.{req.entity}'."
            bound.error("http_dispatch.connector_missing", detail=detail)
            return Result.err(
                TerminalFailure(code=StepFailureCode.VALIDATION_REJECTED, detail=detail)
            )

        # 2. Invoke pure solution function to construct RequestSpec
        spec_res = _build_request_spec(descriptor.fn, req.command_payload)
        if spec_res.is_err:
            detail = spec_res.unwrap_err()
            bound.error("http_dispatch.spec_error", detail=detail)
            return Result.err(
                TerminalFailure(code=StepFailureCode.VALIDATION_REJECTED, detail=detail)
            )
        spec = spec_res.unwrap()

        # 3. Resolve base URL and connection credentials
        base_url = "http://localhost"
        if self._connection_repo is not None:
            conn = await self._connection_repo.get_by_id(req.connection_id)
            if conn is not None and conn.public_config:
                ep = conn.public_config.get("base_url") or conn.public_config.get("endpoint_url")
                if isinstance(ep, str) and ep.strip():
                    base_url = ep.rstrip("/")

        full_url = f"{base_url}/{spec.path.lstrip('/')}"
        client = self._http_client or HttpClient()

        dispatch_res = await _dispatch_via_http_client(
            client=client,
            method_upper=spec.method.upper(),
            full_url=full_url,
            spec=spec,
        )
        if dispatch_res.is_err:
            err = dispatch_res.unwrap_err()
            bound.error("http_dispatch.failed", code=err.code, detail=err.detail)
            return Result.err(err)

        status_code, headers, raw_payload = dispatch_res.unwrap()
        output = HttpDispatchStepOutput(
            connection_id=req.connection_id,
            app=req.app,
            entity=req.entity,
            status_code=status_code,
            headers=headers,
            raw_payload=raw_payload,
        )
        bound.info(
            "http_dispatch.completed",
            status_code=status_code,
            url=full_url,
        )
        return Result.ok(output.to_payload())


__all__ = ["HttpDispatchStepHandler"]
