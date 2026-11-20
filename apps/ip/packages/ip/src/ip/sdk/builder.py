"""Fluent RequestBuilder for assembling immutable RequestSpec objects."""

from __future__ import annotations

from ip.sdk.contracts import HttpRequestBody, RequestSpec


class RequestBuilder:
    """Fluent, typed builder for constructing validated RequestSpec instances."""

    def __init__(self, method: str, path: str) -> None:
        self._method: str = method.strip().upper()
        self._path: str = path.strip()
        self._headers: dict[str, str] = {}
        self._params: dict[str, str] = {}
        self._body: HttpRequestBody = None

    @classmethod
    def get(cls, path: str) -> RequestBuilder:
        return cls("GET", path)

    @classmethod
    def post(cls, path: str) -> RequestBuilder:
        return cls("POST", path)

    @classmethod
    def patch(cls, path: str) -> RequestBuilder:
        return cls("PATCH", path)

    @classmethod
    def put(cls, path: str) -> RequestBuilder:
        return cls("PUT", path)

    @classmethod
    def delete(cls, path: str) -> RequestBuilder:
        return cls("DELETE", path)

    def with_headers(self, *header_dicts: dict[str, str]) -> RequestBuilder:
        for hd in header_dicts:
            self._headers.update(hd)
        return self

    def with_params(self, *param_dicts: dict[str, str]) -> RequestBuilder:
        for pd in param_dicts:
            self._params.update(pd)
        return self

    def with_body(self, body: HttpRequestBody) -> RequestBuilder:
        self._body = body
        return self

    def build(self) -> RequestSpec:
        return RequestSpec(
            method=self._method,
            path=self._path,
            headers=dict(self._headers),
            params=dict(self._params),
            body=self._body,
        )
