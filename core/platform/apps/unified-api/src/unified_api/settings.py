import typing
from functools import lru_cache
from typing import Literal

from edi.config.models import CommonSettings, EdiAwsSettings, S3Settings, SecretsSettings
from pydantic import Field
from seedwork.infra.config import load_settings_safely
from seedwork.infra.config_models import PlatformIdentitySettings


class ApiSettings(CommonSettings):
    storage_backend: Literal["postgres", "s3"] = Field(
        validation_alias="STORAGE_BACKEND", default="postgres"
    )
    s3: S3Settings = Field(default_factory=lambda: typing.cast(S3Settings, {}))
    aws: EdiAwsSettings = Field(default_factory=lambda: typing.cast(EdiAwsSettings, {}))
    identity: PlatformIdentitySettings = Field(
        default_factory=lambda: typing.cast(PlatformIdentitySettings, {})
    )
    secrets: SecretsSettings = Field(default_factory=lambda: typing.cast(SecretsSettings, {}))


@lru_cache
def get_settings() -> ApiSettings:
    return load_settings_safely(ApiSettings)
