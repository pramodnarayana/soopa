from fastapi import FastAPI

from ucp.adapters.inbound.http.routers import apps_router, tenants_router, users_router
from ucp.bootstrap.container import Container
from ucp.bootstrap.exceptions import setup_exception_handlers
from ucp.bootstrap.lifespan import lifespan
from ucp.bootstrap.middleware import setup_middleware


def create_ucp_app() -> FastAPI:
    """
    Creates the isolated UCP bounded context sub-application.
    It has its own middleware, DI container, and exception handlers.
    """
    app = FastAPI(title="UCP Module", version="1.0.0", lifespan=lifespan)

    # 1. Register Cross-Cutting Middleware (CORS, Authentication)
    setup_middleware(app)

    # 2. Register Domain Exception Handlers
    setup_exception_handlers(app)

    # 3. Mount UCP Domain Routers
    app.include_router(tenants_router.router, prefix="/api/v1")
    app.include_router(users_router.router, prefix="/api/v1")
    app.include_router(apps_router.router, prefix="/api/v1")

    # 4. Wire Up Dependency Injection (IoC Container)
    container = Container()
    app.container = container  # type: ignore[attr-defined]

    return app
