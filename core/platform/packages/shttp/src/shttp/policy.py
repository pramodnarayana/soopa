"""Strategy policies for handling HTTP responses, mapping error statuses, and pseudo-success body errors."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Protocol, runtime_checkable

import httpx

from .exceptions import (
    _STATUS_CODE_REGISTRY,
    HttpAuthError,
    HttpNotFoundError,
    HttpRateLimitError,
    HttpServerError,
    HttpStatusError,
)


def create_status_error(response: httpx.Response) -> HttpStatusError:
    """Builds the corresponding typed HttpStatusError subclass from an HTTP response via the registry."""
    error_cls = _STATUS_CODE_REGISTRY.get(response.status_code)
    if error_cls is not None:
        return error_cls.from_response(response)
    if response.status_code >= 500:
        return HttpServerError.from_response(response)
    return HttpStatusError.from_response(response)


@runtime_checkable
class BodyErrorPredicate(Protocol):
    """Strategy protocol for detecting semantic error envelopes inside pseudo-success HTTP payloads."""

    def detect_error(self, response: httpx.Response) -> HttpStatusError | None:
        """Inspects response content; returns an HttpStatusError if an error envelope is detected, else None."""
        ...


class StandardJsonBodyErrorPredicate:
    """Detects standard JSON error envelopes (e.g. {"error": ...}, {"errors": [...]}, {"success": false})."""

    def detect_error(self, response: httpx.Response) -> HttpStatusError | None:
        content_type = response.headers.get("content-type", "").lower()
        if "application/json" not in content_type and "+json" not in content_type:
            return None

        try:
            data = response.json()
        except (ValueError, json.JSONDecodeError):
            return None

        if not isinstance(data, dict):
            return None

        # Pattern 1: {"error": str | dict}
        if "error" in data:
            error_val = data["error"]
            if isinstance(error_val, str) and error_val.strip():
                return self._classify_and_build(response, error_val)
            if isinstance(error_val, dict):
                msg = str(
                    error_val.get("message") or error_val.get("error_description") or error_val
                )
                return self._classify_and_build(response, msg, error_val)

        # Pattern 2: {"errors": [str | dict, ...]}
        if "errors" in data and isinstance(data["errors"], list) and len(data["errors"]) > 0:
            first_err = data["errors"][0]
            msg = str(first_err.get("message") if isinstance(first_err, dict) else first_err)
            return self._classify_and_build(
                response, msg, first_err if isinstance(first_err, dict) else None
            )

        # Pattern 3: {"success": false, "message" / "error": ...}
        if data.get("success") is False:
            msg = str(
                data.get("message")
                or data.get("error")
                or data.get("errorMessage")
                or "Operation failed"
            )
            return self._classify_and_build(response, msg, data)

        # Pattern 4: {"status": "error" | "failed", ...}
        status_val = str(data.get("status", "")).lower()
        if status_val in ("error", "failed", "failure"):
            msg = str(
                data.get("message")
                or data.get("reason")
                or "Remote operation returned error status"
            )
            return self._classify_and_build(response, msg, data)

        return None

    def _classify_and_build(
        self,
        response: httpx.Response,
        message: str,
        details: Mapping[str, object] | None = None,
    ) -> HttpStatusError:
        lower_msg = message.lower()
        url = str(response.url)
        full_msg = f"Pseudo-success HTTP {response.status_code} error from '{url}': {message}"

        if any(
            term in lower_msg
            for term in (
                "unauthorized",
                "invalid token",
                "forbidden",
                "access denied",
                "invalid api key",
                "expired_token",
            )
        ):
            return HttpAuthError(
                full_msg,
                status_code=401,
                url=url,
                response_text=message,
                headers=response.headers,
            )
        if any(term in lower_msg for term in ("rate limit", "too many requests", "quota exceeded")):
            return HttpRateLimitError(
                full_msg,
                status_code=429,
                url=url,
                response_text=message,
                headers=response.headers,
            )
        if any(term in lower_msg for term in ("not found", "does not exist")):
            return HttpNotFoundError(
                full_msg,
                status_code=404,
                url=url,
                response_text=message,
                headers=response.headers,
            )
        return HttpStatusError(
            full_msg,
            status_code=response.status_code if response.status_code >= 400 else 400,
            url=url,
            response_text=message,
            headers=response.headers,
        )


@runtime_checkable
class HttpResponsePolicy(Protocol):
    """Strategy interface governing how HTTP responses and operational errors are processed."""

    def handle_response(self, response: httpx.Response) -> httpx.Response:
        """Inspects or validates the response, raising a typed error if policy is violated."""
        ...


class PassThroughPolicy:
    """Pass-through strategy that returns responses unaltered without raising for status."""

    def handle_response(self, response: httpx.Response) -> httpx.Response:
        return response


class RaiseForStatusPolicy:
    """Strategy that transforms 4xx/5xx responses AND pseudo-success error payloads into typed errors."""

    def __init__(
        self,
        body_predicates: Sequence[BodyErrorPredicate] = (),
    ) -> None:
        self._body_predicates = body_predicates

    def handle_response(self, response: httpx.Response) -> httpx.Response:
        if response.is_error:
            raise create_status_error(response)

        for predicate in self._body_predicates:
            error = predicate.detect_error(response)
            if error is not None:
                raise error

        return response
