import json

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from identity_worker.adapters.outbound.identity_provider.zitadel_client import ZitadelClient
from identity_worker.config.settings import get_settings
from pytest_httpserver import HTTPServer
from werkzeug.wrappers import Response


def _machine_key_json() -> str:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()
    return json.dumps(
        {
            "type": "serviceaccount",
            "keyId": "key-1",
            "key": private_pem,
            "userId": "user-1",
        }
    )


@pytest.mark.asyncio
async def test_client_authenticates_when_only_machine_key_is_configured(
    monkeypatch: pytest.MonkeyPatch,
    httpserver: HTTPServer,
) -> None:
    monkeypatch.setenv("ZITADEL_MACHINE_KEY", _machine_key_json())
    monkeypatch.setenv("ZITADEL_API_URL", httpserver.url_for("/"))
    get_settings.cache_clear()

    def zitadel_token(request) -> Response:
        return Response(
            json.dumps({"access_token": "short-lived-token", "expires_in": 300}),
            status=200,
            content_type="application/json",
        )

    def zitadel_search(request) -> Response:
        assert request.headers["Authorization"] == "Bearer short-lived-token"
        return Response(json.dumps({"result": []}), status=200, content_type="application/json")

    httpserver.expect_request("/oauth/v2/token", method="POST").respond_with_handler(zitadel_token)
    httpserver.expect_request("/management/v1/orgs/_search", method="POST").respond_with_handler(
        zitadel_search
    )

    client = ZitadelClient()
    try:
        response = await client.fetch_with_auth("/management/v1/orgs/_search", method="POST")
    finally:
        await client.close()
        get_settings.cache_clear()

    assert response.status_code == 200
