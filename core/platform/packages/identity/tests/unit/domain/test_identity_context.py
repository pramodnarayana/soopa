from identity.domain.identity_context import TokenClaims, identity_context_from_claims


def test_identity_context_from_claims_creates_valid_context() -> None:
    claims = TokenClaims(
        sub="user-123",
        iss="https://auth.soopa.io",
        aud="api-1",
        exp=1700000000,
        tenant_id="tenant-abc",
        organization_id="org-xyz",
        roles=["admin", "user"],
        permissions=["read:data", "write:data"],
        raw_claims={"extra_claim": "some-value", "iss": "https://auth.soopa.io"},
    )

    context = identity_context_from_claims(claims)

    assert context.subject == "user-123"
    assert context.tenant_id == "tenant-abc"
    assert context.organization_id == "org-xyz"
    assert context.roles == ("admin", "user")
    assert context.permissions == ("read:data", "write:data")
    assert context.claims["extra_claim"] == "some-value"
    assert context.claims["iss"] == "https://auth.soopa.io"


def test_token_claims_defaults() -> None:
    claims = TokenClaims(
        sub="user-123",
        iss="test-iss",
        aud="test-aud",
        exp=1000,
        tenant_id="tenant-1",
    )
    assert claims.roles == []
    assert claims.permissions == []
    assert claims.organization_id is None
    assert claims.iat is None


def test_is_platform_admin_with_valid_role() -> None:
    from identity.domain.identity_context import PLATFORM_TENANT_ID

    claims = TokenClaims(
        sub="admin-1",
        iss="test",
        aud="test",
        exp=1000,
        tenant_id="tenant-1",
        authorized_tenants={PLATFORM_TENANT_ID},
        roles=["platform-admin"],
        tenant_roles={PLATFORM_TENANT_ID: ["platform-admin"]},
    )
    context = identity_context_from_claims(claims)
    assert context.is_platform_admin is True


def test_is_platform_admin_with_non_admin_role() -> None:
    from identity.domain.identity_context import PLATFORM_TENANT_ID

    claims = TokenClaims(
        sub="user-1",
        iss="test",
        aud="test",
        exp=1000,
        tenant_id="tenant-1",
        authorized_tenants={PLATFORM_TENANT_ID},
        roles=["viewer"],
        tenant_roles={PLATFORM_TENANT_ID: ["viewer"]},
    )
    context = identity_context_from_claims(claims)
    assert context.is_platform_admin is False


def test_is_platform_admin_with_admin_role_wrong_tenant() -> None:
    from identity.domain.identity_context import PLATFORM_TENANT_ID

    claims = TokenClaims(
        sub="user-1",
        iss="test",
        aud="test",
        exp=1000,
        tenant_id="tenant-1",
        authorized_tenants={PLATFORM_TENANT_ID, "other_tenant"},
        roles=["platform-admin"],
        tenant_roles={"other_tenant": ["platform-admin"]},
    )
    context = identity_context_from_claims(claims)
    assert context.is_platform_admin is False
