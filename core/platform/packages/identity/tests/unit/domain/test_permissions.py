import pytest

from identity.domain.identity_context import IdentityContext
from identity.domain.permissions import AuthorizationError, has_permission, require_permission


def test_checks_granted_permissions_without_adapters() -> None:
    identity = IdentityContext(
        subject="user-1",
        tenant_id="tenant-1",
        roles=("soopa.operator",),
        permissions=("edi:transactions:read",),
        claims={},
    )

    assert has_permission(identity, "edi:transactions:read") is True
    assert has_permission(identity, "edi:transactions:write") is False


def test_raises_for_missing_permissions() -> None:
    identity = IdentityContext(
        subject="user-1",
        tenant_id="tenant-1",
        permissions=("edi:transactions:read",),
        claims={},
    )

    with pytest.raises(AuthorizationError, match="Missing permission"):
        require_permission(identity, "edi:transactions:write")
