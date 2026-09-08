from collections.abc import Sequence

import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from httpx import ASGITransport, AsyncClient
from identity.application.authenticate_use_case import AuthenticationError
from identity.domain.authentication_strategy import AuthenticationStrategyPort
from identity.domain.identity_context import IdentityContext

from unified_api.adapters.inbound.http.middleware.authentication import AuthenticationMiddleware


class FailingStrategy(AuthenticationStrategyPort):
    def can_handle(self, token: str) -> bool:
        return True

    async def authenticate(self, token: str) -> IdentityContext:
        raise AuthenticationError(token)


class SuccessfulStrategy(AuthenticationStrategyPort):
    def can_handle(self, token: str) -> bool:
        return True

    async def authenticate(self, token: str) -> IdentityContext:
        return IdentityContext(subject="machine-client", claims={})


def create_app(strategies: Sequence[AuthenticationStrategyPort]) -> FastAPI:
    app = FastAPI()

    @app.get("/protected")
    async def protected(request: Request) -> JSONResponse:
        status_code = 200 if request.state.identity is not None else 401
        return JSONResponse(status_code=status_code, content={"ok": status_code == 200})

    app.add_middleware(
        AuthenticationMiddleware,
        strategies=strategies,
        public_paths=frozenset(),
    )
    return app


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "token",
    [
        pytest.param("invalid-prefix", id="invalid-prefix"),
        pytest.param("sp_api_invalid-format", id="invalid-format"),
        pytest.param("sp_api_revoked-key.secret", id="revoked-key"),
    ],
)
async def test_failed_authentication_preserves_bearer_challenge(token: str) -> None:
    transport = ASGITransport(app=create_app([FailingStrategy()]))
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/protected", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == "Bearer"


@pytest.mark.asyncio
async def test_successful_authentication_is_unchanged() -> None:
    transport = ASGITransport(app=create_app([SuccessfulStrategy()]))
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/protected", headers={"Authorization": "Bearer token"})

    assert response.status_code == 200
    assert "WWW-Authenticate" not in response.headers
