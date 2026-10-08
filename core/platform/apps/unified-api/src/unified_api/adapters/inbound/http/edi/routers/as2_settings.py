from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel

from unified_api.settings import get_settings

router = APIRouter(tags=["Platform Settings"])


class SupportedAlgorithm(BaseModel):
    value: str
    label: str


class PlatformSettingsResponse(BaseModel):
    available_as2_receive_urls: list[str]
    supported_as2_encryption_algorithms: list[SupportedAlgorithm]
    supported_as2_signature_algorithms: list[SupportedAlgorithm]


@router.get("/as2/settings", response_model=PlatformSettingsResponse)
async def get_platform_settings() -> Any:
    settings = get_settings()

    return PlatformSettingsResponse(
        available_as2_receive_urls=[settings.as2_receive_url],
        supported_as2_encryption_algorithms=[
            SupportedAlgorithm(value="AES256", label="AES-256-CBC"),
            SupportedAlgorithm(value="AES128", label="AES-128-CBC"),
            SupportedAlgorithm(value="3DES", label="3DES (Legacy)"),
        ],
        supported_as2_signature_algorithms=[
            SupportedAlgorithm(value="SHA256", label="SHA-256"),
            SupportedAlgorithm(value="SHA1", label="SHA-1 (Legacy)"),
        ],
    )
