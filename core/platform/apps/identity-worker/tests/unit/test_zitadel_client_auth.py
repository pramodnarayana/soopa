import json

import httpx
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from identity_worker.adapters.outbound.identity_provider.zitadel_client import ZitadelClient
from identity_worker.bootstrap.config import get_settings


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
) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql://test:test@localhost/test")
    monkeypatch.setenv("ZITADEL_API_URL", "https://identity.example.com")
    monkeypatch.setenv("ZITADEL_MACHINE_KEY", _machine_key_json())
    monkeypatch.setenv("ZITADEL_UCP_PROJECT_ID", "project-1")
    monkeypatch.setenv("ZITADEL_DEFAULT_USER_PASSWORD", "not-for-production")
    get_settings.cache_clear()

    def zitadel(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/oauth/v2/token":
            return httpx.Response(
                200,
                json={"access_token": "short-lived-token", "expires_in": 300},
            )
        assert request.headers["Authorization"] == "Bearer short-lived-token"
        return httpx.Response(200, json={"result": []})

    client = ZitadelClient()
    client._client = httpx.AsyncClient(transport=httpx.MockTransport(zitadel))
    try:
        response = await client.fetch_with_auth("/management/v1/orgs/_search", method="POST")
    finally:
        await client.close()
        get_settings.cache_clear()

    assert response.status_code == 200
