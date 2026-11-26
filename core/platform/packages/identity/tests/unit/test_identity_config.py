"""Unit tests for PlatformIdentitySettings configuration model."""

import pytest

from identity.config import PlatformIdentitySettings

pytestmark = pytest.mark.unit


def test_platform_identity_settings_pure_instantiation() -> None:
    settings = PlatformIdentitySettings(
        oauth_client_id="client_web_3",
        platform_admin_client_id="",
        raw_audiences="api-gateway, extra_aud_1 , extra_aud_2",
        issuer="https://idp.example.com",
    )

    assert settings.oauth_client_id == "client_web_3"
    assert settings.accepted_audiences == (
        "api-gateway",
        "client_web_3",
        "extra_aud_1",
        "extra_aud_2",
    )


def test_platform_identity_settings_alias_choices_resolution() -> None:
    # Resolves via IDENTITY_UCP_WEB_CLIENT_ID alias
    settings_web = PlatformIdentitySettings.model_validate(
        {"IDENTITY_UCP_WEB_CLIENT_ID": "web_client_999"}
    )
    assert settings_web.oauth_client_id == "web_client_999"

    # Resolves via IDENTITY_OAUTH_CLIENT_ID alias
    settings_oauth = PlatformIdentitySettings.model_validate(
        {"IDENTITY_OAUTH_CLIENT_ID": "oauth_client_888"}
    )
    assert settings_oauth.oauth_client_id == "oauth_client_888"


def test_accepted_audiences_deduplicates_and_ignores_empty() -> None:
    settings = PlatformIdentitySettings(
        oauth_client_id="proj_common",
        platform_admin_client_id="",
        raw_audiences="proj_common, ,  ",
    )

    assert settings.accepted_audiences == ("proj_common",)
