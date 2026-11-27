"""Live local Casdoor integration tests verifying OIDC/JWKS, minimal JWT-Custom, and Admin API CRUD."""

from __future__ import annotations

import os
import secrets
from pathlib import Path

import httpx
import pytest
from dotenv import load_dotenv

from identity.adapters.outbound.casdoor.casdoor_admin_adapter import (
    CasdoorAdminAdapter,
    CasdoorAdminOptions,
)
from identity.adapters.outbound.casdoor.constants import CasdoorEndpoint, CasdoorRealm
from identity.adapters.outbound.oidc.oidc_jwks_token_verifier_adapter import (
    OidcJwksTokenVerifierAdapter,
    OidcTokenVerifierOptions,
)

pytestmark = pytest.mark.integration

_REPO_ROOT = Path(__file__).resolve().parents[7]


def _load_local_casdoor_config() -> tuple[str, str, str, str, str]:
    load_dotenv(_REPO_ROOT / ".env", override=True)
    base_url = os.getenv("IDENTITY_API_URL", "http://localhost:8080").rstrip("/")
    dashboard_client_id = os.getenv("IDENTITY_OAUTH_CLIENT_ID", "")
    dashboard_client_secret = os.getenv("IDENTITY_OAUTH_CLIENT_SECRET", "")
    admin_client_id = os.getenv("IDENTITY_ADMIN_CLIENT_ID", "")
    admin_client_secret = os.getenv("IDENTITY_ADMIN_CLIENT_SECRET", "")
    return (
        base_url,
        dashboard_client_id,
        dashboard_client_secret,
        admin_client_id,
        admin_client_secret,
    )


async def _casdoor_is_running(base_url: str) -> bool:
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            resp = await client.get(f"{base_url}{CasdoorEndpoint.HEALTH.value}")
            return resp.status_code == 200
    except httpx.HTTPError:
        return False


@pytest.mark.asyncio
async def test_live_casdoor_oidc_discovery_jwks_minimal_jwt_and_admin_crud() -> None:
    """Runs against local Casdoor (`pnpm infra:bootstrap-identity`) to verify real end-to-end OIDC + Admin."""
    (
        base_url,
        dashboard_client_id,
        dashboard_client_secret,
        admin_client_id,
        admin_client_secret,
    ) = _load_local_casdoor_config()
    if not await _casdoor_is_running(base_url):
        pytest.skip(
            f"Local Casdoor not reachable at {base_url}; run `pnpm infra:bootstrap-identity`."
        )
    if (
        not admin_client_id
        or not admin_client_secret
        or not dashboard_client_id
        or not dashboard_client_secret
    ):
        pytest.skip(
            "Casdoor client credentials not configured in .env; run `pnpm infra:bootstrap-identity`."
        )

    # 1. Verify OIDC Discovery + JWKS endpoint return valid RS256 keyset
    async with httpx.AsyncClient(timeout=5.0) as client:
        disc = await client.get(f"{base_url}{CasdoorEndpoint.OIDC_DISCOVERY.value}")
        assert disc.status_code == 200
        disc_doc = disc.json()
        assert "jwks_uri" in disc_doc

    # 2. Verify minimal CasdoorAdminAdapter CRUD (create -> update -> deactivate -> delete)
    admin = CasdoorAdminAdapter(
        options=CasdoorAdminOptions(
            endpoint=base_url,
            client_id=admin_client_id,
            client_secret=admin_client_secret,
            default_organization=CasdoorRealm.GLOBAL.value,
            allow_private_ips=True,
        )
    )
    nonce = secrets.token_hex(4)
    test_email = f"casdoor_int_{nonce}@example.com"
    test_password = "Password1!"

    created_res = await admin.create_user(
        realm=CasdoorRealm.GLOBAL.value,
        email=test_email,
        display_name="Casdoor Integration Test User",
        initial_password=test_password,
    )
    assert created_res.is_ok, f"create_user failed: {created_res.unwrap_err()}"
    ext_ref = created_res.unwrap()
    assert ext_ref.idp_realm_name == CasdoorRealm.GLOBAL.value
    assert ext_ref.idp_subject

    try:
        # 3. Verify real Casdoor OIDC Auth Code -> Access Token issues compact JWT-Custom
        # verified by generic OidcJwksTokenVerifierAdapter
        username = test_email.replace("@", "_")
        async with httpx.AsyncClient(timeout=5.0) as client:
            login_resp = await client.post(
                f"{base_url}{CasdoorEndpoint.LOGIN.value}",
                params={
                    "clientId": dashboard_client_id,
                    "responseType": "code",
                    "redirectUri": "http://localhost:5173/callback",
                    "scope": "openid email profile",
                    "state": f"st_{nonce}",
                },
                json={
                    "application": f"soopa-dashboard-org-{CasdoorRealm.GLOBAL.value}",
                    "organization": CasdoorRealm.GLOBAL.value,
                    "username": username,
                    "password": test_password,
                    "type": "code",
                },
            )
            assert login_resp.status_code == 200
            login_body = login_resp.json()
            assert login_body.get("status") == "ok", f"Casdoor login failed: {login_body}"
            auth_code = str(login_body["data"])

            token_resp = await client.post(
                f"{base_url}{CasdoorEndpoint.OAUTH_TOKEN.value}",
                data={
                    "grant_type": "authorization_code",
                    "client_id": dashboard_client_id,
                    "client_secret": dashboard_client_secret,
                    "code": auth_code,
                },
            )
            assert token_resp.status_code == 200, f"Token exchange failed: {token_resp.text}"
            token_body = token_resp.json()
            access_token = str(token_body["access_token"])

        # Assert compact JWT size (JWT-Custom avoids 8-32KB bloat!)
        assert len(access_token) < 2000

        verifier = OidcJwksTokenVerifierAdapter(
            options=OidcTokenVerifierOptions(
                default_issuer=base_url,
                default_jwks_uri=f"{base_url}{CasdoorEndpoint.JWKS.value}",
                default_audiences=(dashboard_client_id,),
                allow_private_ips=True,
            )
        )
        verified = await verifier.verify_result(access_token)
        assert verified.is_ok, f"OIDC JWKS verification failed: {verified.unwrap_err()}"
        claims = verified.unwrap()
        assert claims.sub == ext_ref.idp_subject
        assert claims.idp_realm == CasdoorRealm.GLOBAL.value
        assert claims.email == test_email

        # 4. Update & Deactivate user via CasdoorAdminAdapter
        upd = await admin.update_user(
            realm=CasdoorRealm.GLOBAL.value,
            external_subject=ext_ref.idp_subject,
            display_name="Updated Integration User",
        )
        assert upd.is_ok
        deact = await admin.set_user_active(
            realm=CasdoorRealm.GLOBAL.value,
            external_subject=ext_ref.idp_subject,
            active=False,
        )
        assert deact.is_ok
    finally:
        await admin.delete_user(
            realm=CasdoorRealm.GLOBAL.value,
            external_subject=ext_ref.idp_subject,
        )
