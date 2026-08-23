from collections.abc import Awaitable, Callable
from typing import Any, Protocol, runtime_checkable

from fastapi import Depends, Header, HTTPException, status

from identity.application.authenticate_use_case import (
    AuthenticationError,
    authenticate_bearer_token,
)
from identity.domain.identity_context import IdentityContext
from identity.ports.outbound.token_verifier_port import TokenVerifierPort


@runtime_checkable
class _HeadersProtocol(Protocol):
    def get(self, key: str) -> str | None: ...


@runtime_checkable
class _RequestLike(Protocol):
    """Structural protocol for the minimal request interface used by attach_identity_to_request.

    Using a Protocol instead of the concrete FastAPI Request type allows this
    function to be tested with lightweight fakes without coupling the domain
    adapter layer to the FastAPI framework.
    """

    headers: _HeadersProtocol
    state: Any


def identity_dependency(
    token_verifier: TokenVerifierPort,
) -> Callable[[str | None], Awaitable[IdentityContext]]:
    async def dependency(authorization: str | None = Header(default=None)) -> IdentityContext:
        try:
            return await authenticate_bearer_token(authorization, token_verifier)
        except AuthenticationError as exc:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=str(exc),
            ) from exc

    return dependency


def require_identity(token_verifier: TokenVerifierPort) -> object:
    return Depends(identity_dependency(token_verifier))


async def attach_identity_to_request(
    request: _RequestLike, token_verifier: TokenVerifierPort
) -> None:
    """Attach an authenticated IdentityContext to request.state.identity.

    Accepts any object satisfying _RequestLike, including the real FastAPI
    Request and lightweight test fakes.
    """
    authorization = request.headers.get("authorization")
    request.state.identity = await authenticate_bearer_token(authorization, token_verifier)
