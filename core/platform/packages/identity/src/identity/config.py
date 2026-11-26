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
    platform_realm: str = Field(
        validation_alias=AliasChoices("IDENTITY_PLATFORM_REALM", "platform_realm"),
        default="soopa-platform",
        description="Canonical IdP realm/organization for internal platform operators.",
    )
    global_realm: str = Field(
        validation_alias=AliasChoices("IDENTITY_GLOBAL_REALM", "global_realm"),
        default="soopa-global",
        description="Pooled IdP realm/organization for individuals and standard companies.",
    )
    issuer: str = Field(
        validation_alias=AliasChoices("IDENTITY_ISSUER", "issuer"),
        default="",
    )
    jwks_url: str = Field(
        validation_alias=AliasChoices("IDENTITY_JWKS_URL", "jwks_url"),
        default="",
        description="Explicit JWKS endpoint URL (optional; defaults to OIDC discovery).",
    )
    jwks_host_header: str = Field(
        validation_alias=AliasChoices("IDENTITY_JWKS_HOST_HEADER", "jwks_host_header"),
        default="",
        description="Optional Host header override for private/internal JWKS fetches.",
    )
    admin_client_id: str = Field(
        validation_alias=AliasChoices("IDENTITY_ADMIN_CLIENT_ID", "admin_client_id"),
        default="",
        description="Client ID for provider-agnostic IdP management API calls.",
    )
    admin_client_secret: str = Field(
        validation_alias=AliasChoices("IDENTITY_ADMIN_CLIENT_SECRET", "admin_client_secret"),
        default="",
        description="Client secret for provider-agnostic IdP management API calls.",
    )
    l1_cache_max_entries: int = Field(
        validation_alias=AliasChoices("IDENTITY_L1_CACHE_MAX_ENTRIES", "l1_cache_max_entries"),
        default=50_000,
    )
    l1_cache_ttl_seconds: float = Field(
        validation_alias=AliasChoices("IDENTITY_L1_CACHE_TTL_SECONDS", "l1_cache_ttl_seconds"),
        default=60.0,
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
    platform_admin_client_id: str = Field(
        validation_alias=AliasChoices(
            "IDENTITY_PLATFORM_ADMIN_CLIENT_ID",
            "platform_admin_client_id",
        ),
        default="",
        description="Dedicated OAuth SPA Client ID for internal platform operators (self-signup disabled).",
    )
    platform_admin_domains_raw: str = Field(
        validation_alias=AliasChoices(
            "IDENTITY_PLATFORM_ADMIN_DOMAINS",
            "COMPANY_DOMAIN",
            "platform_admin_domains_raw",
        ),
        default="",
        description="Comma-separated verified email domains routed to the internal platform realm.",
    )
    shared_app_realm_delimiter: str = Field(
        validation_alias=AliasChoices(
            "IDENTITY_SHARED_APP_REALM_DELIMITER",
            "shared_app_realm_delimiter",
        ),
        default="",
        description="Optional client_id realm suffix delimiter injected by IdPs with shared-app syntax.",
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
    def platform_admin_domains(self) -> frozenset[str]:
        """Normalized lowercase set of verified email domains routed to the platform operator realm."""
        return frozenset(
            item.strip().lower()
            for item in self.platform_admin_domains_raw.split(",")
            if item.strip()
        )

    def resolve_realm_client_id(self, realm: str) -> str:
        """Resolves the OIDC client_id for a target realm (100% IdP-agnostic)."""
        cleaned_realm = realm.strip()
        if cleaned_realm == self.platform_realm and self.platform_admin_client_id:
            return self.platform_admin_client_id
        if self.oauth_client_id and self.shared_app_realm_delimiter and cleaned_realm:
            return f"{self.oauth_client_id}{self.shared_app_realm_delimiter}{cleaned_realm}"
        return self.oauth_client_id

    @property
    def accepted_audiences(self) -> Sequence[str]:
        """Calculates all distinct valid audiences configured for this Identity instance."""
        entries = (
            self.oauth_client_id,
            self.platform_admin_client_id,
            *self.raw_audiences.split(","),
        )
        return tuple(sorted({item.strip() for item in entries if item.strip()}))


__all__ = ["PlatformIdentitySettings"]
