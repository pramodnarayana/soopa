"""Async HTTP client with connection pooling, SSRF protection, and resilience."""

from __future__ import annotations

from collections.abc import Mapping
from types import TracebackType

import httpx

from .policy import HttpResponsePolicy, PassThroughPolicy
from .resilience import HttpBackoffHandler
from .security import ssrf_safe_context
from .types import FormData, HttpRequest, JsonValue, QueryParams

DEFAULT_LIMITS = httpx.Limits(
    max_keepalive_connections=20,
    max_connections=100,
    keepalive_expiry=30.0,
)
DEFAULT_TIMEOUT = httpx.Timeout(30.0, connect=10.0)


def create_http_client(
    limits: httpx.Limits = DEFAULT_LIMITS,
    timeout: httpx.Timeout | float = DEFAULT_TIMEOUT,
    follow_redirects: bool = False,
    headers: Mapping[str, str] | None = None,
) -> httpx.AsyncClient:
    """Factory creating an AsyncClient with connection pooling defaults."""
    return httpx.AsyncClient(
        limits=limits,
        timeout=timeout,
        follow_redirects=follow_redirects,
        headers=headers,
    )


class HttpClient:
    """High-level async HTTP client providing SSRF protection, connection pooling, and backoff resilience."""

    def __init__(
        self,
        client: httpx.AsyncClient | None = None,
        backoff_handler: HttpBackoffHandler | None = None,
        allow_private_ips: bool = False,
        response_policy: HttpResponsePolicy | None = None,
    ) -> None:
        if client is not None and getattr(client, "follow_redirects", False):
            raise ValueError(
                "Injected httpx.AsyncClient must have follow_redirects=False to prevent SSRF bypass via redirects."
            )
        self._client = client or create_http_client()
        self._backoff_handler = backoff_handler or HttpBackoffHandler()
        self._allow_private_ips = allow_private_ips
        self._response_policy = response_policy or PassThroughPolicy()
        self._owns_client = client is None

    @property
    def raw_client(self) -> httpx.AsyncClient:
        return self._client

    @property
    def response_policy(self) -> HttpResponsePolicy:
        return self._response_policy

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def aclose(self) -> None:
        await self.close()

    async def __aenter__(self) -> HttpClient:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        await self.close()

    async def send(
        self,
        request: HttpRequest,
        *,
        allow_private_ips: bool | None = None,
        policy: HttpResponsePolicy | None = None,
    ) -> httpx.Response:
        """Executes a strongly-typed HttpRequest command object."""
        return await self.request(
            method=request.method,
            url=request.url,
            headers=request.headers,
            params=request.params,
            data=request.data,
            content=request.content,
            json=request.json,
            timeout=request.timeout,
            allow_private_ips=allow_private_ips,
            policy=policy,
        )

    async def request(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str] | None = None,
        params: QueryParams | None = None,
        data: FormData | None = None,
        content: bytes | None = None,
        json: JsonValue | None = None,
        timeout: float | httpx.Timeout | None = None,
        allow_private_ips: bool | None = None,
        policy: HttpResponsePolicy | None = None,
    ) -> httpx.Response:
        """Executes an HTTP request wrapped in SSRF IP pinning, transient backoff retries, and response policy."""
        check_private = self._allow_private_ips if allow_private_ips is None else allow_private_ips
        effective_policy = policy or self._response_policy
        effective_timeout = timeout if timeout is not None else httpx.USE_CLIENT_DEFAULT

        with ssrf_safe_context(url, allow_private_ips=check_private):
            response = await self._backoff_handler.execute(
                lambda: self._client.request(
                    method=method,
                    url=url,
                    headers=headers,
                    params=params,
                    data=data,
                    content=content,
                    json=json,
                    timeout=effective_timeout,
                ),
                url=url,
                method=method,
            )

        return effective_policy.handle_response(response)

    async def get(
        self,
        url: str,
        *,
        headers: Mapping[str, str] | None = None,
        params: QueryParams | None = None,
        timeout: float | httpx.Timeout | None = None,
        allow_private_ips: bool | None = None,
        policy: HttpResponsePolicy | None = None,
    ) -> httpx.Response:
        return await self.request(
            "GET",
            url,
            headers=headers,
            params=params,
            timeout=timeout,
            allow_private_ips=allow_private_ips,
            policy=policy,
        )

    async def post(
        self,
        url: str,
        *,
        headers: Mapping[str, str] | None = None,
        params: QueryParams | None = None,
        data: FormData | None = None,
        content: bytes | None = None,
        json: JsonValue | None = None,
        timeout: float | httpx.Timeout | None = None,
        allow_private_ips: bool | None = None,
        policy: HttpResponsePolicy | None = None,
    ) -> httpx.Response:
        return await self.request(
            "POST",
            url,
            headers=headers,
            params=params,
            data=data,
            content=content,
            json=json,
            timeout=timeout,
            allow_private_ips=allow_private_ips,
            policy=policy,
        )

    async def put(
        self,
        url: str,
        *,
        headers: Mapping[str, str] | None = None,
        params: QueryParams | None = None,
        data: FormData | None = None,
        content: bytes | None = None,
        json: JsonValue | None = None,
        timeout: float | httpx.Timeout | None = None,
        allow_private_ips: bool | None = None,
        policy: HttpResponsePolicy | None = None,
    ) -> httpx.Response:
        return await self.request(
            "PUT",
            url,
            headers=headers,
            params=params,
            data=data,
            content=content,
            json=json,
            timeout=timeout,
            allow_private_ips=allow_private_ips,
            policy=policy,
        )

    async def delete(
        self,
        url: str,
        *,
        headers: Mapping[str, str] | None = None,
        params: QueryParams | None = None,
        timeout: float | httpx.Timeout | None = None,
        allow_private_ips: bool | None = None,
        policy: HttpResponsePolicy | None = None,
    ) -> httpx.Response:
        return await self.request(
            "DELETE",
            url,
            headers=headers,
            params=params,
            timeout=timeout,
            allow_private_ips=allow_private_ips,
            policy=policy,
        )

    async def patch(
        self,
        url: str,
        *,
        headers: Mapping[str, str] | None = None,
        params: QueryParams | None = None,
        data: FormData | None = None,
        content: bytes | None = None,
        json: JsonValue | None = None,
        timeout: float | httpx.Timeout | None = None,
        allow_private_ips: bool | None = None,
        policy: HttpResponsePolicy | None = None,
    ) -> httpx.Response:
        return await self.request(
            "PATCH",
            url,
            headers=headers,
            params=params,
            data=data,
            content=content,
            json=json,
            timeout=timeout,
            allow_private_ips=allow_private_ips,
            policy=policy,
        )
