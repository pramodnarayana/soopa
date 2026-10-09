import typing
from functools import lru_cache

from edi.config.models import (
    CommonSettings,
    EdiAwsSettings,
    EdiDataPlaneSqsSettings,
    SecretsSettings,
)
from pydantic import Field
from seedwork.infra.config import load_settings_safely
from seedwork.infra.config_models import PlatformIdentitySettings


class As2ServerSettings(CommonSettings):
    identity: PlatformIdentitySettings = Field(
        default_factory=lambda: typing.cast(PlatformIdentitySettings, {})
    )
    secrets: SecretsSettings = Field(default_factory=lambda: typing.cast(SecretsSettings, {}))
    aws: EdiAwsSettings = Field(default_factory=lambda: typing.cast(EdiAwsSettings, {}))
    sqs: EdiDataPlaneSqsSettings = Field(
        default_factory=lambda: typing.cast(EdiDataPlaneSqsSettings, {})
    )
    as2_receive_url: str = Field(
        validation_alias="AS2_RECEIVE_URL",
        description="The fully-qualified absolute URL for AS2 payload ingress",
    )


@lru_cache
def get_settings() -> As2ServerSettings:
    return load_settings_safely(As2ServerSettings)
