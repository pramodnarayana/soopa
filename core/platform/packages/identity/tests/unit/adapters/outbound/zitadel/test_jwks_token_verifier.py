import json
import threading
import time
from collections.abc import Generator
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from identity.adapters.outbound.zitadel.jwks_token_verifier_adapter import (
    ZitadelTokenVerifierPort,
    ZitadelTokenVerifierPortOptions,
)
from identity.ports.outbound.token_verifier_port import TokenValidationError

# Generate global test keys once for the module
private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
public_key = private_key.public_key()
jwk_str = jwt.algorithms.RSAAlgorithm.to_jwk(public_key)
jwk = json.loads(jwk_str)
jwk["kid"] = "test-kid"

private_pem = private_key.private_bytes(
    encoding=serialization.Encoding.PEM,
    format=serialization.PrivateFormat.TraditionalOpenSSL,
    encryption_algorithm=serialization.NoEncryption(),
)

jwks_payload = json.dumps({"keys": [jwk]}).encode()


class JWKSRequestHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path.endswith("/oauth/v2/keys"):
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(jwks_payload)
        elif self.path.endswith("/oidc/v1/userinfo"):
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(
                json.dumps(
                    {"urn:zitadel:iam:org:project:roles": {"admin": {"tenant-abc": "domain.com"}}}
                ).encode()
            )
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format: str, *args: Any) -> None:
        pass


@pytest.fixture(scope="module")
def jwks_server() -> Generator[str, None, None]:
    server = HTTPServer(("127.0.0.1", 0), JWKSRequestHandler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever)
    thread.daemon = True
    thread.start()
    yield f"http://127.0.0.1:{port}"
    server.shutdown()
    server.server_close()
    thread.join()


@pytest.fixture
def options(jwks_server: str) -> ZitadelTokenVerifierPortOptions:
    return ZitadelTokenVerifierPortOptions(
        issuer=jwks_server,
        audience="my-api",
    )


@pytest.fixture
def verifier(options: ZitadelTokenVerifierPortOptions) -> ZitadelTokenVerifierPort:
    return ZitadelTokenVerifierPort(options)


@pytest.mark.asyncio
async def test_verify_valid_token(
    verifier: ZitadelTokenVerifierPort, options: ZitadelTokenVerifierPortOptions
) -> None:
    # Sign a real JWT with our private key
    payload = {
        "sub": "user-123",
        "iss": options.issuer,
        "aud": "my-api",
        "exp": int(time.time()) + 3600,
        "tenant_id": "tenant-abc",
    }

    token = jwt.encode(payload, private_pem, algorithm="RS256", headers={"kid": "test-kid"})

    claims = await verifier.verify(token)

    assert claims.sub == "user-123"
    assert claims.tenant_id == "tenant-abc"
    assert "admin" in claims.roles


@pytest.mark.asyncio
async def test_verify_expired_token(
    verifier: ZitadelTokenVerifierPort, options: ZitadelTokenVerifierPortOptions
) -> None:
    # Sign an expired token
    payload = {
        "sub": "user-123",
        "iss": options.issuer,
        "aud": "my-api",
        "exp": int(time.time()) - 3600,
        "tenant_id": "tenant-abc",
    }
    token = jwt.encode(payload, private_pem, algorithm="RS256", headers={"kid": "test-kid"})

    with pytest.raises(TokenValidationError, match="Signature has expired"):
        await verifier.verify(token)


@pytest.mark.asyncio
@pytest.mark.parametrize("userinfo", [None, 42, [], "invalid"])
async def test_get_cached_userinfo_rejects_non_object_json(
    monkeypatch, verifier: ZitadelTokenVerifierPort, userinfo: object
) -> None:
    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> object:
            return userinfo

    class FakeAsyncClient:
        def __init__(self, timeout: float) -> None:
            self.timeout = timeout

        async def __aenter__(self) -> "FakeAsyncClient":
            return self

        async def __aexit__(self, *args: object) -> None:
            return None

        async def get(self, url: str, headers: dict[str, str]) -> FakeResponse:
            return FakeResponse()

    monkeypatch.setattr(httpx, "AsyncClient", FakeAsyncClient)

    with pytest.raises(TypeError, match="userinfo response must be a JSON object"):
        await verifier._get_cached_userinfo("token", "jti")

    assert "jti" not in verifier._userinfo_cache
