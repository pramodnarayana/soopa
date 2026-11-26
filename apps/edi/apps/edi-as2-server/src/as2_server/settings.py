import typing
from functools import lru_cache

from edi.config.models import (
    CommonSettings,
    EdiAwsSettings,
    EdiDataPlaneSqsSettings,
)
from identity import PlatformIdentitySettings
from pydantic import Field
from secret_store import PlatformSecretStoreSettings
from seedwork.infra.config import load_settings_safely
from storage import PlatformStorageSettings


class As2ServerSettings(CommonSettings):
    identity: PlatformIdentitySettings = Field(
        default_factory=lambda: typing.cast(PlatformIdentitySettings, {})
    )
    secrets: PlatformSecretStoreSettings = Field(
        default_factory=lambda: typing.cast(PlatformSecretStoreSettings, {})
    )
    storage: PlatformStorageSettings = Field(
        default_factory=lambda: typing.cast(PlatformStorageSettings, {})
    )
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
