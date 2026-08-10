from identity.domain.identity_context import IdentityContext, identity_context_from_claims
from identity.ports.token_verifier import TokenValidationError, TokenVerifier


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
    token_verifier: TokenVerifier,
) -> IdentityContext:
    if authorization_header is None:
        raise AuthenticationError("Missing bearer token.")

    parts = authorization_header.split(maxsplit=1)
    if not parts or parts[0].lower() != "bearer":
        raise AuthenticationError("Missing bearer token.")

    if len(parts) == 1 or not parts[1].strip():
        raise AuthenticationError("Empty bearer token.")

    token = parts[1].strip()

    try:
        claims = await token_verifier.verify(token)
    except TokenValidationError as e:
        raise AuthenticationError("Invalid token format or signature") from e
    return identity_context_from_claims(claims)
