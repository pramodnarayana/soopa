from identity.adapters.inbound.http.fastapi_middleware import (
    attach_identity_to_request,
    identity_dependency,
    require_identity,
)
from identity.application.authenticate_use_case import (
    AuthenticationError,
    authenticate_bearer_token,
)
from identity.domain.identity_context import IdentityContext, TokenClaims
from identity.domain.permissions import (
    AuthorizationError,
    has_permission,
    has_role,
    require_any_permission,
    require_permission,
)

__all__ = [
    "AuthenticationError",
    "AuthorizationError",
    "IdentityContext",
    "TokenClaims",
    "attach_identity_to_request",
    "authenticate_bearer_token",
    "has_permission",
    "has_role",
    "identity_dependency",
    "require_any_permission",
    "require_identity",
    "require_permission",
]
