from fastapi import APIRouter, Depends
from pydantic import BaseModel

from ucp.ports.outbound.app_repository import IAppRepository

router = APIRouter(prefix="/apps", tags=["Apps"])


def get_app_repo() -> IAppRepository:
    raise NotImplementedError()


class AppResponse(BaseModel):
    id: str
    name: str
    slug: str
    description: str


@router.get("", response_model=list[AppResponse])
async def get_apps(app_repo: IAppRepository = Depends(get_app_repo)) -> list[AppResponse]:
    apps = await app_repo.find_all()
    return [
        AppResponse(
            id=app.id,
            name=app.name,
            slug=app.slug,
            description=app.description,
        )
        for app in apps
    ]
