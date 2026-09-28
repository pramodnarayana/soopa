import typing

from pydantic import Field
from seedwork.infra.config import load_settings_safely
from seedwork.infra.config_models import PlatformIdentitySettings

from edi.config.models import (
    CommonSettings,
    EdiAwsSettings,
    S3Settings,
    SecretsSettings,
)


class EdiTestSettings(CommonSettings):
    identity: PlatformIdentitySettings = Field(
        default_factory=lambda: typing.cast(PlatformIdentitySettings, {})
    )
    aws: EdiAwsSettings = Field(default_factory=lambda: typing.cast(EdiAwsSettings, {}))
    s3: S3Settings = Field(default_factory=lambda: typing.cast(S3Settings, {}))
    secrets: SecretsSettings = Field(default_factory=lambda: typing.cast(SecretsSettings, {}))


def get_test_settings():
    return load_settings_safely(EdiTestSettings)


def test_settings_load_without_provisioning_password(monkeypatch):
    """
    Test that ensures Interface Segregation is respected:
    The EDI apps (AS2, workers) should never crash if the Identity Provisioning
    Password is missing, because they only require the base Auth configuration.
    """
    monkeypatch.delenv("IDENTITY_DEFAULT_USER_PASSWORD", raising=False)

    # This should not raise any Pydantic validation errors
    settings = get_test_settings()

    assert settings is not None
    assert isinstance(settings, CommonSettings)
