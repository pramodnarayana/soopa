"""Casdoor realm defaults, token format constants, and endpoint paths."""

from __future__ import annotations

from enum import StrEnum


class CasdoorTokenFormat(StrEnum):
    """Casdoor Application tokenFormat values (ALWAYS use JWT-Custom to avoid 8-32KB JWT bloat)."""

    JWT_CUSTOM = "JWT-Custom"
    JWT_EMPTY = "JWT-Empty"
    JWT_STANDARD = "JWT-Standard"


class CasdoorRealm(StrEnum):
    """Canonical Casdoor Organizations (Realms) for the 3-Realm Hybrid Architecture."""

    BUILT_IN = "built-in"
    PLATFORM = "soopa-platform"
    GLOBAL = "soopa-global"


CASDOOR_DEFAULT_APPLICATION = "soopa-dashboard"

# Strictly minimal standard OIDC token fields (Casdoor Go struct PascalCase names)
# keeping Access Tokens ~1KB instead of Casdoor's bloated 8-32KB default JWT.
CASDOOR_MINIMAL_TOKEN_FIELDS: tuple[str, ...] = (
    "Owner",
    "Name",
    "Email",
    "EmailVerified",
    "DisplayName",
)


class CasdoorEndpoint(StrEnum):
    HEALTH = "/api/health"
    OIDC_DISCOVERY = "/.well-known/openid-configuration"
    JWKS = "/.well-known/jwks"
    LOGIN = "/api/login"
    ADD_USER = "/api/add-user"
    UPDATE_USER = "/api/update-user"
    DELETE_USER = "/api/delete-user"
    GET_USER = "/api/get-user"
    GET_USERS = "/api/get-users"
    ADD_ORGANIZATION = "/api/add-organization"
    UPDATE_ORGANIZATION = "/api/update-organization"
    GET_ORGANIZATION = "/api/get-organization"
    ADD_APPLICATION = "/api/add-application"
    UPDATE_APPLICATION = "/api/update-application"
    GET_APPLICATION = "/api/get-application"
    ADD_PROVIDER = "/api/add-provider"
    OAUTH_TOKEN = "/api/login/oauth/access_token"  # noqa: S105 - OAuth2 token endpoint URL path, not a credential


__all__ = [
    "CASDOOR_DEFAULT_APPLICATION",
    "CASDOOR_MINIMAL_TOKEN_FIELDS",
    "CasdoorEndpoint",
    "CasdoorRealm",
    "CasdoorTokenFormat",
]
