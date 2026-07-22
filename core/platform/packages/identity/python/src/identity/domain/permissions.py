from identity.domain.identity_context import IdentityContext


class AuthorizationError(Exception):
    pass


def has_permission(identity: IdentityContext, permission: str) -> bool:
    return permission in identity.permissions


def has_role(identity: IdentityContext, role: str) -> bool:
    return role in identity.roles


def require_permission(identity: IdentityContext, permission: str) -> None:
    if not has_permission(identity, permission):
        msg = f"Missing permission: {permission}"
        raise AuthorizationError(msg)


def require_any_permission(identity: IdentityContext, permissions: tuple[str, ...]) -> None:
    if not any(has_permission(identity, permission) for permission in permissions):
        msg = f"Missing one of permissions: {', '.join(permissions)}"
        raise AuthorizationError(msg)
