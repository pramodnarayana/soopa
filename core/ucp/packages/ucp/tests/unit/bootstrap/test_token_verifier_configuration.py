"""
Unit tests for get_token_verifier() JWKS URL construction.

Regression test for the following bug:
  - IDENTITY_API_URL was set to the internal Cloud Map URL
    (http://zitadel.staging-cluster.local:8080).
  - The JWKS client was erroneously built from IDENTITY_API_URL.
  - Zitadel is host-header sensitive and returns HTTP 404 when the
    Host header doesn't match ZITADEL_EXTERNALDOMAIN, causing all
    token verification to silently fail with `authenticated: false`.

Fix:
  - The JWKS URL MUST be built from IDENTITY_ISSUER (the public domain),
    not from IDENTITY_API_URL (the internal domain).
"""

from types import SimpleNamespace

import pytest

from ucp.bootstrap.dependencies import get_token_verifier

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def clear_lru_cache():
    """Ensure the @lru_cache on get_token_verifier is cleared between tests."""
    get_token_verifier.cache_clear()
    yield
    get_token_verifier.cache_clear()


def _make_settings(issuer: str, api_url: str):
    """
    Build a minimal settings stub that satisfies all attributes accessed by
    get_token_verifier(). We must explicitly include the @property delegates
    (zitadel_ucp_project_id, zitadel_platform_org_id) that AppSettings exposes,
    because SimpleNamespace does not automatically derive them from `identity.*`.
    """
    identity = SimpleNamespace(
        issuer=issuer,
        ucp_project_id="test-project-id",
        oauth_client_id="test-client-id",
        platform_org_id="test-org-id",
        tenant_role_group="TenantAdmin",
    )
    return SimpleNamespace(
        # Raw fields
        zitadel_issuer=issuer,
        zitadel_api_url_value=api_url,
        identity=identity,
        # @property delegates that AppSettings exposes
        zitadel_ucp_project_id="test-project-id",
        zitadel_platform_org_id="test-org-id",
    )


def test_jwks_url_uses_internal_cloud_map_url_not_public_issuer(monkeypatch: pytest.MonkeyPatch):
    """
    JWKS URL must use the internal Cloud Map URL (no ALB hairpin), not the
    public issuer. Traffic stays within the VPC for performance and security.
    """
    public_issuer = "https://identity.staging.flowwolf.io"
    internal_api_url = "http://zitadel.staging-cluster.local:8080"

    settings = _make_settings(issuer=public_issuer, api_url=internal_api_url)

    monkeypatch.setattr("ucp.bootstrap.dependencies.get_settings", lambda: settings)
    verifier = get_token_verifier()

    expected_jwks_url = f"{internal_api_url}/oauth/v2/keys"
    actual_jwks_url = verifier.jwks_url

    assert actual_jwks_url == expected_jwks_url, (
        f"JWKS URL must use the internal Cloud Map address for VPC-internal routing.\n"
        f"Expected: {expected_jwks_url}\n"
        f"Actual:   {actual_jwks_url}"
    )


def test_jwks_host_header_override_is_set_to_public_issuer_hostname(
    monkeypatch: pytest.MonkeyPatch,
):
    """
    When using the internal Cloud Map URL for JWKS, the Host header must be
    overridden to the public issuer hostname so Zitadel's host-header domain
    matching succeeds. Without this, Zitadel returns HTTP 404.
    """
    public_issuer = "https://identity.staging.flowwolf.io"
    internal_api_url = "http://zitadel.staging-cluster.local:8080"

    settings = _make_settings(issuer=public_issuer, api_url=internal_api_url)

    monkeypatch.setattr("ucp.bootstrap.dependencies.get_settings", lambda: settings)
    verifier = get_token_verifier()

    expected_host = "identity.staging.flowwolf.io"
    actual_host = verifier.jwks_host_header

    assert actual_host == expected_host, (
        f"jwks_host_header must equal the public issuer hostname.\n"
        f"Expected: {expected_host}\n"
        f"Actual:   {actual_host}\n"
        f"Without this, Zitadel sees 'zitadel.staging-cluster.local' as Host "
        f"and returns HTTP 404."
    )
