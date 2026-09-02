import pytest

from identity.adapters.inbound.http.requires_permission import requires_permission
from identity.domain.identity_context import IdentityContext
from identity.domain.permissions import AuthorizationError


def test_requires_permission_decorator_success() -> None:

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

    @requires_permission("edi:transactions:read")
    def my_handler() -> str:
        return "success"

    with pytest.raises(
        TypeError, match="requires_permission expects an IdentityContext keyword argument"
    ):
        my_handler()
