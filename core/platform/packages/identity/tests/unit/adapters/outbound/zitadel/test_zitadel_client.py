from __future__ import annotations

import json

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from pytest_httpserver import HTTPServer
from shttp import HttpClient, create_http_client
from shttp.resilience import HeaderWaitTimeStrategy, HttpBackoffHandler
from werkzeug.wrappers import Request, Response

from identity.adapters.outbound.zitadel.client import ZitadelClient


def _generate_machine_key() -> str:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()
    return json.dumps(
        {
            "type": "serviceaccount",
            "keyId": "key-test-1",
            "key": private_pem,
            "userId": "usr_service_1",
        }
    )


@pytest.mark.asyncio
async def test_zitadel_client_uses_http_client_and_authenticates(httpserver: HTTPServer) -> None:
    httpserver.expect_request("/oauth/v2/token", method="POST").respond_with_json(
        {"access_token": "valid_token_xyz", "expires_in": 300}
    )
    httpserver.expect_request("/management/v1/projects/_search", method="POST").respond_with_json(
        {"result": [{"id": "prj_1", "name": "soopa"}]}
    )

    client = ZitadelClient(
        api_url=httpserver.url_for(""),
        machine_key=_generate_machine_key(),
    )

    assert isinstance(client._get_client(), HttpClient)
    assert client.raw_client is not None

    resp = await client.fetch_with_auth("/management/v1/projects/_search", method="POST")
    assert resp.status_code == 200
    assert resp.json() == {"result": [{"id": "prj_1", "name": "soopa"}]}

    await client.close()


@pytest.mark.asyncio
async def test_zitadel_client_handles_429_rate_limit_backoff(httpserver: HTTPServer) -> None:
    httpserver.expect_request("/oauth/v2/token", method="POST").respond_with_json(
        {"access_token": "valid_token_xyz", "expires_in": 300}
    )

    call_count = 0

    def flakey_handler(request: Request) -> Response:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return Response("Too Many Requests", status=429, headers={"Retry-After": "1"})
        return Response(
            json.dumps({"result": [{"id": "org_1"}]}), status=200, content_type="application/json"
        )

    httpserver.expect_request("/management/v1/orgs/_search", method="POST").respond_with_handler(
        flakey_handler
    )

    # Use max_wait_seconds=0.0 to verify retry logic without real sleep
    fast_backoff = HttpBackoffHandler(strategies=[HeaderWaitTimeStrategy(max_wait_seconds=0.0)])
    fast_http_client = HttpClient(
        client=create_http_client(follow_redirects=False),
        backoff_handler=fast_backoff,
        allow_private_ips=True,
    )

    client = ZitadelClient(
        api_url=httpserver.url_for(""),
        machine_key=_generate_machine_key(),
        client=fast_http_client,
    )

    resp = await client.fetch_with_auth("/management/v1/orgs/_search", method="POST")
    assert resp.status_code == 200
    assert resp.json() == {"result": [{"id": "org_1"}]}
    assert call_count == 2

    await client.close()


@pytest.mark.asyncio
async def test_zitadel_client_returns_http_status_responses(httpserver: HTTPServer) -> None:
    httpserver.expect_request("/oauth/v2/token", method="POST").respond_with_json(
        {"access_token": "valid_token_xyz", "expires_in": 300}
    )
    httpserver.expect_request("/err/400", method="GET").respond_with_json(
        {"error": "bad_request"}, status=400
    )
    httpserver.expect_request("/err/404", method="GET").respond_with_json(
        {"error": "not_found"}, status=404
    )
    httpserver.expect_request("/err/409", method="GET").respond_with_json(
        {"error": "conflict"}, status=409
    )

    client = ZitadelClient(
        api_url=httpserver.url_for(""),
        machine_key=_generate_machine_key(),
    )

    res_400 = await client.fetch_with_auth("/err/400")
    assert res_400.status_code == 400
    assert res_400.json() == {"error": "bad_request"}

    res_404 = await client.fetch_with_auth("/err/404")
    assert res_404.status_code == 404
    assert res_404.json() == {"error": "not_found"}

    res_409 = await client.fetch_with_auth("/err/409")
    assert res_409.status_code == 409
    assert res_409.json() == {"error": "conflict"}

    await client.close()
