"""Unit tests for shttp response policies, exception hierarchy, and failure classification."""

from __future__ import annotations

import httpx
import pytest
from shttp.exceptions import (
    FailureDisposition,
    HttpAuthError,
    HttpFailureClassification,
    HttpNetworkError,
    HttpNotFoundError,
    HttpRateLimitError,
    HttpServerError,
    HttpStatusError,
    HttpTimeoutError,
    TimeoutKind,
    classify_http_failure,
    register_status_error,
)
from shttp.policy import (
    PassThroughPolicy,
    RaiseForStatusPolicy,
    StandardJsonBodyErrorPredicate,
    create_status_error,
)


def test_passthrough_policy_does_not_raise() -> None:
    policy = PassThroughPolicy()
    response_401 = httpx.Response(401, request=httpx.Request("GET", "https://api.example.com"))
    response_500 = httpx.Response(500, request=httpx.Request("GET", "https://api.example.com"))

    assert policy.handle_response(response_401).status_code == 401
    assert policy.handle_response(response_500).status_code == 500


def test_raise_for_status_policy_success() -> None:
    policy = RaiseForStatusPolicy()
    response_200 = httpx.Response(200, request=httpx.Request("GET", "https://api.example.com"))
    assert policy.handle_response(response_200).status_code == 200


def test_create_status_error_auth_401() -> None:
    resp = httpx.Response(
        401, text="Unauthorized", request=httpx.Request("GET", "https://api.example.com")
    )
    err = create_status_error(resp)
    assert isinstance(err, HttpAuthError)
    assert err.status_code == 401
    assert err.classify() == HttpFailureClassification.AUTH_FAILURE


def test_create_status_error_auth_403() -> None:
    resp = httpx.Response(
        403, text="Forbidden", request=httpx.Request("GET", "https://api.example.com")
    )
    err = create_status_error(resp)
    assert isinstance(err, HttpAuthError)
    assert err.status_code == 403
    assert err.classify() == HttpFailureClassification.AUTH_FAILURE


def test_create_status_error_not_found_404() -> None:
    resp = httpx.Response(
        404, text="Not Found", request=httpx.Request("GET", "https://api.example.com")
    )
    err = create_status_error(resp)
    assert isinstance(err, HttpNotFoundError)
    assert err.status_code == 404
    assert err.classify() == HttpFailureClassification.RESOURCE_NOT_FOUND


def test_create_status_error_rate_limit_429_with_header() -> None:
    resp = httpx.Response(
        429,
        text="Too Many Requests",
        headers={"Retry-After": "45"},
        request=httpx.Request("GET", "https://api.example.com"),
    )
    err = create_status_error(resp)
    assert isinstance(err, HttpRateLimitError)
    assert err.status_code == 429
    assert err.retry_after_seconds == 45.0
    assert err.classify() == HttpFailureClassification.RATE_LIMIT_EXCEEDED


def test_create_status_error_server_error_502() -> None:
    resp = httpx.Response(
        502, text="Bad Gateway", request=httpx.Request("GET", "https://api.example.com")
    )
    err = create_status_error(resp)
    assert isinstance(err, HttpServerError)
    assert err.status_code == 502
    assert err.classify() == HttpFailureClassification.SERVER_ERROR


def test_create_status_error_generic_client_error_400() -> None:
    resp = httpx.Response(
        400, text="Bad Request", request=httpx.Request("POST", "https://api.example.com")
    )
    err = create_status_error(resp)
    assert isinstance(err, HttpStatusError)
    assert err.is_client_error is True
    assert err.is_server_error is False


def test_classify_http_failure_various() -> None:
    timeout_err = HttpTimeoutError("Timed out", kind=TimeoutKind.CONNECT)
    assert classify_http_failure(timeout_err) == HttpFailureClassification.TIMEOUT

    net_err = HttpNetworkError("Connection reset")
    assert classify_http_failure(net_err) == HttpFailureClassification.NETWORK_UNAVAILABLE

    # Raw httpx responses
    assert classify_http_failure(httpx.Response(401)) == HttpFailureClassification.AUTH_FAILURE
    assert (
        classify_http_failure(httpx.Response(429)) == HttpFailureClassification.RATE_LIMIT_EXCEEDED
    )
    assert classify_http_failure(httpx.Response(503)) == HttpFailureClassification.SERVER_ERROR
    assert classify_http_failure(httpx.Response(200)) == HttpFailureClassification.UNCLASSIFIED


def test_raise_for_status_policy_raises_on_401() -> None:
    policy = RaiseForStatusPolicy()
    response = httpx.Response(
        401,
        json={"error": "invalid_api_key"},
        request=httpx.Request("GET", "https://api.example.com/protected"),
    )
    with pytest.raises(HttpAuthError) as exc_info:
        policy.handle_response(response)

    assert exc_info.value.status_code == 401
    assert exc_info.value.classify() == HttpFailureClassification.AUTH_FAILURE


def test_register_custom_status_error_is_open_for_extension() -> None:
    @register_status_error(409)
    class HttpConflictError(HttpStatusError):
        def classify(self) -> HttpFailureClassification:
            return HttpFailureClassification.RESOURCE_NOT_FOUND

    resp = httpx.Response(
        409, text="Resource conflict", request=httpx.Request("POST", "https://api.example.com")
    )
    err = create_status_error(resp)
    assert isinstance(err, HttpConflictError)
    assert err.status_code == 409
    assert err.classify() == HttpFailureClassification.RESOURCE_NOT_FOUND


def test_error_remediation_and_disposition() -> None:
    auth_err = HttpAuthError("Invalid key", status_code=401, url="https://api.example.com")
    assert auth_err.disposition == FailureDisposition.FAIL
    assert auth_err.remediation is not None
    assert "credentials" in auth_err.remediation.lower() or "keys" in auth_err.remediation.lower()

    rate_limit_err = HttpRateLimitError("429 Too Many", url="https://api.example.com")
    assert rate_limit_err.disposition == FailureDisposition.RETRY
    assert rate_limit_err.remediation is not None
    assert "rate limit" in rate_limit_err.remediation.lower()

    timeout_err = HttpTimeoutError("Timed out", url="https://api.example.com")
    assert timeout_err.disposition == FailureDisposition.RETRY
    assert timeout_err.remediation is not None
    assert (
        "timed out" in timeout_err.remediation.lower()
        or "timeout" in timeout_err.remediation.lower()
    )

    server_err = HttpServerError("Internal fault", status_code=500, url="https://api.example.com")
    assert server_err.disposition == FailureDisposition.RETRY


def test_standard_json_body_error_predicate_detects_pseudo_success_auth_error() -> None:
    policy = RaiseForStatusPolicy(body_predicates=[StandardJsonBodyErrorPredicate()])
    response_200_auth_fail = httpx.Response(
        200,
        headers={"Content-Type": "application/json"},
        json={"error": "Unauthorized: invalid api key provided"},
        request=httpx.Request("GET", "https://api.example.com/data"),
    )

    with pytest.raises(HttpAuthError) as exc_info:
        policy.handle_response(response_200_auth_fail)

    assert exc_info.value.status_code == 401
    assert exc_info.value.disposition == FailureDisposition.FAIL
    assert exc_info.value.classify() == HttpFailureClassification.AUTH_FAILURE


def test_standard_json_body_error_predicate_detects_pseudo_success_rate_limit() -> None:
    policy = RaiseForStatusPolicy(body_predicates=[StandardJsonBodyErrorPredicate()])
    response_200_rate_limit = httpx.Response(
        200,
        headers={"Content-Type": "application/json"},
        json={"errors": [{"message": "Rate limit exceeded. Try again later."}]},
        request=httpx.Request("GET", "https://api.example.com/data"),
    )

    with pytest.raises(HttpRateLimitError) as exc_info:
        policy.handle_response(response_200_rate_limit)

    assert exc_info.value.status_code == 429
    assert exc_info.value.disposition == FailureDisposition.RETRY


def test_standard_json_body_error_predicate_passes_through_clean_success() -> None:
    policy = RaiseForStatusPolicy(body_predicates=[StandardJsonBodyErrorPredicate()])
    response_200_clean = httpx.Response(
        200,
        headers={"Content-Type": "application/json"},
        json={"data": [{"id": "item_123", "name": "Catalog Item"}]},
        request=httpx.Request("GET", "https://api.example.com/data"),
    )

    handled = policy.handle_response(response_200_clean)
    assert handled.status_code == 200
    assert handled.json() == {"data": [{"id": "item_123", "name": "Catalog Item"}]}
