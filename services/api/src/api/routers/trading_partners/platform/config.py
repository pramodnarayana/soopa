from typing import Any

from config.settings import get_settings
from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(tags=["Platform Config"])


class PlatformConfigResponse(BaseModel):
    available_as2_receive_urls: list[str]


@router.get("/config", response_model=PlatformConfigResponse)
async def get_platform_config() -> Any:
    settings = get_settings()

    # We strip trailing slashes to ensure consistent path appending
    base_url = settings.server.external_url.rstrip("/")

    return PlatformConfigResponse(available_as2_receive_urls=[f"{base_url}/api/v1/as2/receive"])
