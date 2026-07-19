from soopa_identity.domain.identity_context import IdentityContext, identity_context_from_claims
from soopa_identity.ports.token_verifier import TokenVerifier


class AuthenticationError(Exception):
    pass


async def authenticate_bearer_token(
    authorization_header: str | None,
    token_verifier: TokenVerifier,
) -> IdentityContext:
    if authorization_header is None or not authorization_header.startswith("Bearer "):
        raise AuthenticationError("Missing bearer token.")

    token = authorization_header.removeprefix("Bearer ").strip()
    if not token:
        raise AuthenticationError("Empty bearer token.")

    claims = await token_verifier.verify(token)
    return identity_context_from_claims(claims)
