from typing import Any

from config.settings import get_settings
from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(tags=["Platform Config"])


class SupportedAlgorithm(BaseModel):
    value: str
    label: str


class PlatformConfigResponse(BaseModel):
    available_as2_receive_urls: list[str]
    supported_as2_encryption_algorithms: list[SupportedAlgorithm]
    supported_as2_signature_algorithms: list[SupportedAlgorithm]


@router.get("/config", response_model=PlatformConfigResponse)
async def get_platform_config() -> Any:
    settings = get_settings()

    # We strip trailing slashes to ensure consistent path appending
    base_url = settings.server.external_url.rstrip("/")

    return PlatformConfigResponse(
        available_as2_receive_urls=[f"{base_url}/api/v1/as2/receive"],
        supported_as2_encryption_algorithms=[
            SupportedAlgorithm(value="AES256", label="AES-256-CBC"),
            SupportedAlgorithm(value="AES128", label="AES-128-CBC"),
            SupportedAlgorithm(value="3DES", label="3DES (Legacy)"),
        ],
        supported_as2_signature_algorithms=[
            SupportedAlgorithm(value="SHA256", label="SHA-256"),
            SupportedAlgorithm(value="SHA1", label="SHA-1 (Legacy)"),
            SupportedAlgorithm(value="MD5", label="MD5 (Legacy)"),
        ],
    )
