import typing
from functools import lru_cache

from edi.config.models import (
    CommonSettings,
    EdiAwsSettings,
    EdiDataPlaneSqsSettings,
)
from identity import PlatformIdentitySettings
from pydantic import Field, model_validator
from secret_store import PlatformSecretStoreSettings
from seedwork.infra.config import load_settings_safely
from storage import PlatformStorageSettings


class WorkerSettings(CommonSettings):
    storage: PlatformStorageSettings = Field(
        default_factory=lambda: typing.cast(PlatformStorageSettings, {})
    )
    aws: EdiAwsSettings = Field(default_factory=lambda: typing.cast(EdiAwsSettings, {}))
    identity: PlatformIdentitySettings = Field(
        default_factory=lambda: typing.cast(PlatformIdentitySettings, {})
    )
    secrets: PlatformSecretStoreSettings = Field(
        default_factory=lambda: typing.cast(PlatformSecretStoreSettings, {})
    )
    sqs: EdiDataPlaneSqsSettings = Field(
        default_factory=lambda: typing.cast(EdiDataPlaneSqsSettings, {})
    )

    @model_validator(mode="after")
    def validate_pubsub_transport_uris(self) -> "WorkerSettings":
        self.pubsub.validate_uris(
            {
                **self.sqs.pubsub_uris(),
                "SNS_PLATFORM_EVENTS_TOPIC_ARN": self.aws.sns_topic_arn,
            }
        )
        return self


@lru_cache
def get_settings() -> WorkerSettings:
    return load_settings_safely(WorkerSettings)
