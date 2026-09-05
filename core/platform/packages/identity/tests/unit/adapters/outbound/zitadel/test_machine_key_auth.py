import json
from urllib.parse import parse_qs

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from identity.adapters.outbound.zitadel.machine_key_auth import (
    ZitadelMachineAuthenticationError,
    ZitadelMachineKey,
    ZitadelMachineTokenProvider,
)


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


def test_machine_key_requires_all_signing_fields() -> None:
    with pytest.raises(ZitadelMachineAuthenticationError, match="keyId"):
        ZitadelMachineKey.from_json('{"key":"private","userId":"user-1"}')


@pytest.mark.asyncio
async def test_machine_key_is_exchanged_and_access_token_is_cached() -> None:
    token_requests = 0

    def token_endpoint(request: httpx.Request) -> httpx.Response:
        nonlocal token_requests
        token_requests += 1
        form = parse_qs(request.content.decode())
        assertion = form["assertion"][0]
        unverified_header = jwt.get_unverified_header(assertion)
        unverified_claims = jwt.decode(assertion, options={"verify_signature": False})

        assert request.url == "https://identity.example.com/oauth/v2/token"
        assert form["grant_type"] == ["urn:ietf:params:oauth:grant-type:jwt-bearer"]
        assert form["scope"] == ["openid urn:zitadel:iam:org:project:id:zitadel:aud"]
        assert unverified_header["kid"] == "key-1"
        assert unverified_claims["iss"] == "user-1"
        assert unverified_claims["sub"] == "user-1"
        assert unverified_claims["aud"] == "https://identity.example.com"
        return httpx.Response(200, json={"access_token": "access-token", "expires_in": 300})

    provider = ZitadelMachineTokenProvider(
        "https://identity.example.com/",
        _machine_key_json(),
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(token_endpoint)) as client:
        first_token = await provider.get_access_token(client)
        second_token = await provider.get_access_token(client)

    assert first_token == "access-token"
    assert second_token == "access-token"
    assert token_requests == 1
