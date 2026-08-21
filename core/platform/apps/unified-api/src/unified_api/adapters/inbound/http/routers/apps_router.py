from typing import Any

from dependency_injector.wiring import Provide, inject
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from ucp.bootstrap.container import Container
from ucp.bootstrap.dependencies import get_db_session
from ucp.ports.outbound.uow import UcpUnitOfWorkPort

router = APIRouter(prefix="/apps", tags=["Apps"])


class AppResponse(BaseModel):
    id: str
    name: str
    slug: str
    description: str


@router.get("", response_model=list[AppResponse])
@inject
async def get_apps(
    session: AsyncSession = Depends(get_db_session),
    uow_factory: Any = Depends(Provide[Container.uow.provider]),
) -> list[AppResponse]:
    uow: UcpUnitOfWorkPort = uow_factory(session=session)
    async with uow:
        apps = await uow.app_repo.find_all()
    return [
        AppResponse(
            id=app.id,
            name=app.name,
            slug=app.slug,
            description=app.description,
        )
        for app in apps
    ]
