from unittest.mock import MagicMock, patch

import pytest

from soopa_identity.adapters.outbound.zitadel.jwks_token_verifier import (
    ZitadelTokenVerifier,
    ZitadelTokenVerifierOptions,
)


@pytest.fixture
def options() -> ZitadelTokenVerifierOptions:
    return ZitadelTokenVerifierOptions(
        issuer="https://auth.example.com",
        audience="my-api",
    )


@pytest.fixture
def verifier(options: ZitadelTokenVerifierOptions) -> ZitadelTokenVerifier:
    return ZitadelTokenVerifier(options)


@pytest.mark.asyncio
@patch("soopa_identity.adapters.outbound.zitadel.jwks_token_verifier.httpx.AsyncClient")
@patch("soopa_identity.adapters.outbound.zitadel.jwks_token_verifier.jwt.decode")
async def test_verify_valid_token(
    mock_jwt_decode: MagicMock,
    mock_async_client_cls: MagicMock,
    options: ZitadelTokenVerifierOptions,
) -> None:
    # We patch PyJWKClient on the module level before instantiating
    with patch("soopa_identity.adapters.outbound.zitadel.jwks_token_verifier.PyJWKClient") as mock_jwk_client_cls:

        mock_jwk_client = mock_jwk_client_cls.return_value
        mock_signing_key = MagicMock()
        mock_signing_key.key = "test-key"
        mock_jwk_client.get_signing_key_from_jwt.return_value = mock_signing_key

        verifier = ZitadelTokenVerifier(options)

        mock_async_client = mock_async_client_cls.return_value.__aenter__.return_value
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock(return_value=None)
        mock_async_client.get.return_value = mock_response

        mock_jwt_decode.return_value = {
            "sub": "user-123",
            "iss": "https://auth.example.com",
            "aud": "my-api",
            "exp": 1700000000,
            "tenant_id": "tenant-abc"
        }

        claims = await verifier.verify("fake.jwt.token")

        assert claims.sub == "user-123"
        assert claims.tenant_id == "tenant-abc"
        mock_jwt_decode.assert_called_once_with(
            "fake.jwt.token",
            "test-key",
            algorithms=["RS256"],
            audience="my-api",
            issuer="https://auth.example.com",
        )
        mock_async_client.get.assert_called_once_with("https://auth.example.com/oauth/v2/keys")

