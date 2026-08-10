from identity.domain.identity_context import IdentityContext, identity_context_from_claims
from identity.ports.token_verifier import TokenVerifier


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
    if authorization_header is None or not authorization_header.startswith("Bearer "):
        raise AuthenticationError("Missing bearer token.")

    token = authorization_header.removeprefix("Bearer ").strip()
    if not token:
        raise AuthenticationError("Empty bearer token.")

    try:
        claims = await token_verifier.verify(token)
    except Exception as e:
        raise AuthenticationError("Invalid token format or signature") from e
    return identity_context_from_claims(claims)
