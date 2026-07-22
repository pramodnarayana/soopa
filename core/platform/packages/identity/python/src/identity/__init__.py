from identity.application.authenticate import AuthenticationError, authenticate_bearer_token
from identity.domain.identity_context import IdentityContext, TokenClaims
from identity.domain.permissions import (
    AuthorizationError,
    has_permission,
    has_role,
    require_any_permission,
    require_permission,
)
from identity.middleware.fastapi import (
    attach_identity_to_request,
    identity_dependency,
    require_identity,
)

__all__ = [
    "AuthenticationError",
    "AuthorizationError",
    "IdentityContext",
    "TokenClaims",
    "authenticate_bearer_token",
    "has_permission",
    "has_role",
    "require_any_permission",
    "require_permission",
    "require_identity",
    "identity_dependency",
    "attach_identity_to_request",
]
