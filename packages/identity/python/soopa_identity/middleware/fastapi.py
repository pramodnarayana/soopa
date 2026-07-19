from collections.abc import Awaitable, Callable

from fastapi import Depends, Header, HTTPException, Request, status

from soopa_identity.application.authenticate import AuthenticationError, authenticate_bearer_token
from soopa_identity.domain.identity_context import IdentityContext
from soopa_identity.ports.token_verifier import TokenVerifier


def identity_dependency(token_verifier: TokenVerifier) -> Callable[[str | None], Awaitable[IdentityContext]]:
    async def dependency(authorization: str | None = Header(default=None)) -> IdentityContext:
        try:
            return await authenticate_bearer_token(authorization, token_verifier)
        except AuthenticationError as exc:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=str(exc),
            ) from exc

    return dependency


def require_identity(token_verifier: TokenVerifier) -> object:
    return Depends(identity_dependency(token_verifier))


async def attach_identity_to_request(request: Request, token_verifier: TokenVerifier) -> None:
    authorization = request.headers.get("authorization")
    request.state.identity = await authenticate_bearer_token(authorization, token_verifier)
