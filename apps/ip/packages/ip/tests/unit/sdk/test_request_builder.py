"""Unit tests for the fluent RequestBuilder."""

from ip.sdk.builder import RequestBuilder
from seedwork.domain.types import JsonDict


def test_request_builder_assembles_get_request() -> None:
    spec = (
        RequestBuilder.get("/api/v2/items")
        .with_headers({"Accept": "application/json"})
        .with_params({"page": "1", "limit": "25"})
        .build()
    )

    assert spec.method == "GET"
    assert spec.path == "/api/v2/items"
    assert spec.headers == {"Accept": "application/json"}
    assert spec.params == {"page": "1", "limit": "25"}
    assert spec.body is None


def test_request_builder_assembles_post_request() -> None:
    payload: JsonDict = {"name": "test_device", "enabled": True}
    spec = (
        RequestBuilder.post("/api/v2/items")
        .with_headers({"Content-Type": "application/json"})
        .with_body(payload)
        .build()
    )

    assert spec.method == "POST"
    assert spec.path == "/api/v2/items"
    assert spec.headers == {"Content-Type": "application/json"}
    assert spec.body == {"name": "test_device", "enabled": True}


def test_request_builder_assembles_patch_request() -> None:
    spec = RequestBuilder.patch("/api/v2/items/42").with_body({"status": "ACTIVE"}).build()

    assert spec.method == "PATCH"
    assert spec.path == "/api/v2/items/42"
    assert spec.body == {"status": "ACTIVE"}


def test_request_builder_merges_multiple_headers() -> None:
    spec = RequestBuilder.get("/api").with_headers({"Header-A": "1"}, {"Header-B": "2"}).build()

    assert spec.headers == {"Header-A": "1", "Header-B": "2"}


def test_request_builder_merges_multiple_params() -> None:
    spec = RequestBuilder.get("/api").with_params({"param_a": "alpha"}, {"param_b": "beta"}).build()

    assert spec.params == {"param_a": "alpha", "param_b": "beta"}


def test_request_builder_normalizes_method_casing() -> None:
    spec = RequestBuilder("get", "  /api/v1/spaces  ").build()

    assert spec.method == "GET"
    assert spec.path == "/api/v1/spaces"
