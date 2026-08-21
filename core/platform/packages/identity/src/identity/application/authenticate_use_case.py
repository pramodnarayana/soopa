import structlog

from identity.domain.identity_context import IdentityContext, identity_context_from_claims
from identity.ports.outbound.token_verifier_port import TokenValidationError, TokenVerifierPort

logger = structlog.get_logger(__name__)


class AuthenticationError(Exception):
    """Raised when token validation fails (e.g., expired, invalid signature)."""


class TenantNotProvisionedError(Exception):
    """Raised when a valid IdP token contains a tenant ID that is not provisioned in the system."""

    def __init__(self, tenant_id: str):
        super().__init__(
            f"Authentication failed: The organization '{tenant_id}' is not provisioned in this system."
        )
        self.tenant_id = tenant_id


async def authenticate_bearer_token(
    authorization_header: str | None,
    token_verifier: TokenVerifierPort,
) -> IdentityContext:
    if authorization_header is None:
        logger.warning("authentication_failed", reason="missing_header")
        raise AuthenticationError("Missing bearer token.")

    parts = authorization_header.split(maxsplit=1)
    if not parts or parts[0].lower() != "bearer":
        logger.warning("authentication_failed", reason="missing_bearer_prefix")
        raise AuthenticationError("Missing bearer token.")

    if len(parts) == 1 or not parts[1].strip():
        logger.warning("authentication_failed", reason="empty_token")
        raise AuthenticationError("Empty bearer token.")

    token = parts[1].strip()

    try:
        claims = await token_verifier.verify(token)
    except TokenValidationError as e:
        logger.warning("authentication_failed", reason="invalid_token", error=str(e))
        raise AuthenticationError(f"Authentication failed: {str(e)}") from e

    return identity_context_from_claims(claims)
