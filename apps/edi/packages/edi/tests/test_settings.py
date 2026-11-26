import typing

from identity import PlatformIdentitySettings
from pydantic import Field
from secret_store import PlatformSecretStoreSettings
from seedwork.infra.config import load_settings_safely
from storage import PlatformStorageSettings

from edi.config.models import (
    CommonSettings,
    EdiAwsSettings,
)


class EdiTestSettings(CommonSettings):
    edi_environment: typing.Literal["P", "T", "I"] = Field(default="T")
    identity: PlatformIdentitySettings = Field(
        default_factory=lambda: typing.cast(PlatformIdentitySettings, {})
    )
    aws: EdiAwsSettings = Field(default_factory=lambda: typing.cast(EdiAwsSettings, {}))
    storage: PlatformStorageSettings = Field(
        default_factory=lambda: typing.cast(PlatformStorageSettings, {})
    )
    secrets: PlatformSecretStoreSettings = Field(
        default_factory=lambda: typing.cast(PlatformSecretStoreSettings, {})
    )


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
