import json
import threading
import time
from collections.abc import Generator
from http.server import BaseHTTPRequestHandler, HTTPServer

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from shttp import HttpError, SsrfSecurityError

from identity.adapters.outbound.zitadel.jwks_token_verifier_adapter import (
    ZitadelTokenVerifierAdapter,
    ZitadelTokenVerifierOptions,
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

    def log_message(self, format: str, *args: object) -> None:
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
def options(jwks_server: str) -> ZitadelTokenVerifierOptions:
    return ZitadelTokenVerifierOptions(
        issuer=jwks_server,
        audience="my-api",
        allow_private_ips=True,
    )


@pytest.fixture
def verifier(options: ZitadelTokenVerifierOptions) -> ZitadelTokenVerifierAdapter:
    return ZitadelTokenVerifierAdapter(options)


@pytest.mark.asyncio
async def test_verify_valid_token(
    verifier: ZitadelTokenVerifierAdapter, options: ZitadelTokenVerifierOptions
) -> None:
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
    verifier: ZitadelTokenVerifierAdapter, options: ZitadelTokenVerifierOptions
) -> None:
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
async def test_default_options_enforce_ssrf_protection_against_private_ips(httpserver) -> None:
    default_options = ZitadelTokenVerifierOptions(
        issuer=httpserver.url_for("/").rstrip("/"),
        audience="my-api",
    )
    assert default_options.allow_private_ips is False
    verifier = ZitadelTokenVerifierAdapter(default_options)
    try:
        with pytest.raises(SsrfSecurityError):
            await verifier._get_cached_userinfo("token", "jti")
    finally:
        await verifier.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("userinfo", [None, 42, [], "invalid"])
async def test_get_cached_userinfo_rejects_non_object_json(httpserver, userinfo: object) -> None:
    httpserver.expect_request("/oidc/v1/userinfo").respond_with_data(
        json.dumps(userinfo), status=200, content_type="application/json"
    )

    options = ZitadelTokenVerifierOptions(
        issuer=httpserver.url_for("/").rstrip("/"),
        audience="my-api",
        allow_private_ips=True,
    )
    verifier = ZitadelTokenVerifierAdapter(options)

    with pytest.raises(TypeError, match="userinfo response must be a JSON object"):
        await verifier._get_cached_userinfo("token", "jti")

    assert "jti" not in verifier._userinfo_cache
    await verifier.close()


@pytest.mark.asyncio
async def test_get_cached_userinfo_raises_http_error_on_status_error(httpserver) -> None:
    httpserver.expect_request("/oidc/v1/userinfo").respond_with_data(
        "Bad Request", status=400, content_type="text/plain"
    )

    options = ZitadelTokenVerifierOptions(
        issuer=httpserver.url_for("/").rstrip("/"),
        audience="my-api",
        allow_private_ips=True,
    )
    verifier = ZitadelTokenVerifierAdapter(options)

    with pytest.raises(HttpError) as exc_info:
        await verifier._get_cached_userinfo("token", "jti")

    assert exc_info.value.status_code == 400
    assert "jti" not in verifier._userinfo_cache
    await verifier.close()


@pytest.mark.asyncio
async def test_get_cached_userinfo_caches_and_returns_valid_object(httpserver) -> None:
    httpserver.expect_request("/oidc/v1/userinfo").respond_with_json(
        {"email": "user@example.com", "name": "Test User"}
    )

    options = ZitadelTokenVerifierOptions(
        issuer=httpserver.url_for("/").rstrip("/"),
        audience="my-api",
        allow_private_ips=True,
    )
    verifier = ZitadelTokenVerifierAdapter(options)

    userinfo = await verifier._get_cached_userinfo("token", "jti")
    assert userinfo == {"email": "user@example.com", "name": "Test User"}
    assert "jti" in verifier._userinfo_cache

    # Subsequent call hits in-memory cache without hitting httpserver again
    cached = await verifier._get_cached_userinfo("token", "jti")
    assert cached == userinfo
    await verifier.close()
