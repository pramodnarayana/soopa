"""Configuration models for the Identity bounded context."""

from collections.abc import Sequence

from pydantic import AliasChoices, Field
from pydantic_settings import SettingsConfigDict
from seedwork.infra.config import CleanBaseSettings


class PlatformIdentitySettings(CleanBaseSettings):
    """
    Centralized model for Identity Provider Configuration (Auth verification).

    Pure platform identity configuration decoupled from any specific business
    domain or client application.
    """

    model_config = SettingsConfigDict(
        extra="ignore",
        populate_by_name=True,
    )

    tenant_role_group: str = Field(
        validation_alias=AliasChoices("IDENTITY_TENANT_ROLE_GROUP", "tenant_role_group"),
        default="Tenant",
    )
    platform_org_id: str = Field(
        validation_alias=AliasChoices("IDENTITY_PLATFORM_ORG_ID", "platform_org_id"),
        default="",
    )
    issuer: str = Field(
        validation_alias=AliasChoices("IDENTITY_ISSUER", "issuer"),
        default="",
    )
    oauth_client_id: str = Field(
        validation_alias=AliasChoices(
            "IDENTITY_OAUTH_CLIENT_ID",
            "IDENTITY_UCP_WEB_CLIENT_ID",
            "oauth_client_id",
        ),
        default="",
        description="The OAuth Web / SPA Client ID used by frontend applications.",
    )
    raw_audiences: str = Field(
        validation_alias=AliasChoices("IDENTITY_AUDIENCE", "raw_audiences"),
        default="",
        description="Optional comma-separated list of additional accepted audiences.",
    )
    allow_private_ips: bool = Field(
        validation_alias=AliasChoices("IDENTITY_ALLOW_PRIVATE_IPS", "allow_private_ips"),
        default=False,
        description="Explicit opt-in for private/loopback IdP endpoints in local/test environments.",
    )

    @property
    def accepted_audiences(self) -> Sequence[str]:
        """Calculates all distinct valid audiences configured for this Identity instance."""
        entries = (
            self.oauth_client_id,
            *self.raw_audiences.split(","),
        )
        return tuple(sorted({item.strip() for item in entries if item.strip()}))


__all__ = ["PlatformIdentitySettings"]
