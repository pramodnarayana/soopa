"""Unit tests verifying Solution SDK contracts and strict typing contracts."""

from dataclasses import FrozenInstanceError

import pytest
from ip.sdk.contracts import HttpRequestBody, RequestSpec
from seedwork.domain.types import JsonDict


def test_request_spec_instantiation_preserves_attributes() -> None:
    headers: dict[str, str] = {"Content-Type": "application/json"}
    params: dict[str, str] = {"limit": "50"}
    body: JsonDict = {"filter": "active"}

    spec = RequestSpec(
        method="POST",
        path="/api/v1/extract",
        headers=headers,
        params=params,
        body=body,
    )

    assert spec.method == "POST"
    assert spec.path == "/api/v1/extract"
    assert spec.headers == {"Content-Type": "application/json"}
    assert spec.params == {"limit": "50"}
    assert spec.body == {"filter": "active"}


def test_request_spec_is_immutable_against_mutation() -> None:
    spec = RequestSpec(
        method="GET",
        path="/api/v1/status",
    )

    with pytest.raises(FrozenInstanceError):
        spec.method = "POST"


def test_http_request_body_accepts_valid_payload_variants() -> None:
    json_body: HttpRequestBody = {"key": "value", "count": 10}
    xml_body: HttpRequestBody = "<Envelope><Body/></Envelope>"
    bytes_body: HttpRequestBody = b"\x00\x01\x02"
    none_body: HttpRequestBody = None

    spec_json = RequestSpec(method="POST", path="/", body=json_body)
    spec_xml = RequestSpec(method="POST", path="/", body=xml_body)
    spec_bytes = RequestSpec(method="POST", path="/", body=bytes_body)
    spec_none = RequestSpec(method="GET", path="/", body=none_body)

    assert spec_json.body == {"key": "value", "count": 10}
    assert spec_xml.body == "<Envelope><Body/></Envelope>"
    assert spec_bytes.body == b"\x00\x01\x02"
    assert spec_none.body is None
