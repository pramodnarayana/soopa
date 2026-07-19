import pytest

from soopa_identity.domain.identity_context import IdentityContext
from soopa_identity.domain.permissions import AuthorizationError, has_permission, require_permission


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


def test_requires_permission_decorator_success() -> None:
    from soopa_identity.decorators.requires_permission import requires_permission

    identity = IdentityContext(
        subject="user-1",
        tenant_id="tenant-1",
        permissions=("edi:transactions:read",),
        claims={},
    )

    @requires_permission("edi:transactions:read")
    def my_handler(identity: IdentityContext) -> str:
        return "success"

    result = my_handler(identity=identity)
    assert result == "success"


def test_requires_permission_decorator_failure() -> None:
    from soopa_identity.decorators.requires_permission import requires_permission

    identity = IdentityContext(
        subject="user-1",
        tenant_id="tenant-1",
        permissions=("edi:transactions:read",),
        claims={},
    )

    @requires_permission("edi:transactions:write")
    def my_handler(identity: IdentityContext) -> str:
        return "success"

    with pytest.raises(AuthorizationError):
        my_handler(identity=identity)


def test_requires_permission_decorator_missing_identity() -> None:
    from soopa_identity.decorators.requires_permission import requires_permission

    @requires_permission("edi:transactions:read")
    def my_handler() -> str:
        return "success"

    with pytest.raises(TypeError, match="requires_permission expects an IdentityContext keyword argument"):
        my_handler()
