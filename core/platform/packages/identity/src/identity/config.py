"""Configuration models for the Identity bounded context."""

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class PlatformIdentitySettings(BaseSettings):
    """
    Centralized model for Identity Provider Configuration (Auth verification).
    """

    model_config = SettingsConfigDict(extra="ignore")

    ucp_project_id: str = Field(
        validation_alias="IDENTITY_UCP_PROJECT_ID",
        default="",
        description="The Project ID representing the UCP.",
    )
    tenant_role_group: str = Field(validation_alias="IDENTITY_TENANT_ROLE_GROUP", default="Tenant")
    platform_org_id: str = Field(validation_alias="IDENTITY_PLATFORM_ORG_ID", default="")
    issuer: str = Field(validation_alias="IDENTITY_ISSUER", default="")
    oauth_client_id: str = Field(validation_alias="IDENTITY_OAUTH_CLIENT_ID", default="")
    allow_private_ips: bool = Field(
        validation_alias="IDENTITY_ALLOW_PRIVATE_IPS",
        default=False,
        description="Explicit opt-in for private/loopback IdP endpoints in local/test environments.",
    )


__all__ = ["PlatformIdentitySettings"]
