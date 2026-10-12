import typing
from functools import lru_cache

from edi.config.models import CommonSettings, SecretsSettings
from pydantic import Field
from seedwork.infra.config import load_settings_safely
from seedwork.infra.config_models import PlatformIdentitySettings


class ApiSettings(CommonSettings):
    identity: PlatformIdentitySettings = Field(
        default_factory=lambda: typing.cast(PlatformIdentitySettings, {})
    )
    secrets: SecretsSettings = Field(default_factory=lambda: typing.cast(SecretsSettings, {}))
    cors_allowed_origins: list[str] = Field(validation_alias="CORS_ALLOWED_ORIGINS")
    as2_receive_url: str = Field(
        validation_alias="AS2_RECEIVE_URL",
        description="The fully-qualified absolute URL for AS2 payload ingress",
    )


@lru_cache
def get_settings() -> ApiSettings:
    return load_settings_safely(ApiSettings)
