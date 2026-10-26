"""Polymorphic resolver mapping AuthType to concrete AuthenticatorPort strategies."""

from __future__ import annotations

import json

from ip.engine.adapters.outbound.auth.api_key_auth_strategy import (
    ApiKeyAuthStrategy,
    ApiKeyPlacement,
)
from ip.engine.adapters.outbound.auth.basic_auth_strategy import BasicAuthStrategy
from ip.engine.adapters.outbound.auth.bearer_auth_strategy import BearerAuthStrategy
from ip.engine.adapters.outbound.auth.no_auth_strategy import NoAuthStrategy
from ip.engine.adapters.outbound.auth.oauth2_strategy import OAuth2Strategy
from ip.engine.domain.enums import AuthType
from ip.engine.ports.outbound.auth_strategy_port import AuthenticatorPort
from seedwork.domain.types import JsonDict


def _parse_credentials_dict(credentials: JsonDict | bytes | str | None) -> JsonDict:
    if isinstance(credentials, bytes):
        try:
            parsed = json.loads(credentials.decode("utf-8"))
            return (
                parsed
                if isinstance(parsed, dict)
                else {"api_key": credentials.decode("utf-8", errors="ignore")}
            )
        except (json.JSONDecodeError, UnicodeDecodeError, ValueError):
            return {"api_key": credentials.decode("utf-8", errors="ignore")}
    if isinstance(credentials, str):
        try:
            parsed = json.loads(credentials)
            return parsed if isinstance(parsed, dict) else {"api_key": credentials}
        except (json.JSONDecodeError, ValueError):
            return {"api_key": credentials}
    if isinstance(credentials, dict):
        return credentials
    return {}


_AUTH_TYPE_ALIASES: dict[str, AuthType] = {
    "BEARER": AuthType.BEARER_TOKEN,
    "BEARER_TOKEN": AuthType.BEARER_TOKEN,
    "BASIC": AuthType.BASIC_AUTH,
    "BASIC_AUTH": AuthType.BASIC_AUTH,
    "API_KEY": AuthType.API_KEY,
    "OAUTH2": AuthType.OAUTH2,
    "OAUTH2_CLIENT_CREDENTIALS": AuthType.OAUTH2_CLIENT_CREDENTIALS,
    "NO_AUTH": AuthType.NO_AUTH,
    "NONE": AuthType.NO_AUTH,
}


class AuthStrategyResolver:
    """Resolves and instantiates the appropriate AuthenticatorPort strategy for a connection."""

    @classmethod
    def resolve(
        cls,
        auth_type: AuthType | str,
        credentials: JsonDict | bytes | str | None = None,
        *,
        allow_private_ips: bool = False,
    ) -> AuthenticatorPort:
        creds_dict = _parse_credentials_dict(credentials)
        resolved_type = (
            auth_type
            if isinstance(auth_type, AuthType)
            else _AUTH_TYPE_ALIASES.get(str(auth_type).strip().upper(), AuthType.NO_AUTH)
        )

        if resolved_type == AuthType.BASIC_AUTH:
            return BasicAuthStrategy(
                username=str(creds_dict.get("username", "")),
                password=str(creds_dict.get("password", "")),
            )

        if resolved_type == AuthType.BEARER_TOKEN:
            token = (
                creds_dict.get("access_token")
                or creds_dict.get("token")
                or creds_dict.get("api_key")
                or creds_dict.get("bearer_token")
                or ""
            )
            return BearerAuthStrategy(token=str(token))

        if resolved_type == AuthType.API_KEY:
            api_key = (
                creds_dict.get("api_key") or creds_dict.get("key") or creds_dict.get("token") or ""
            )
            param_name = (
                creds_dict.get("param_name") or creds_dict.get("api_key_header") or "X-API-Key"
            )
            placement_val = str(creds_dict.get("placement", "HEADER")).upper()
            placement = (
                ApiKeyPlacement.QUERY_PARAM
                if placement_val in ("QUERY_PARAM", "QUERY")
                else ApiKeyPlacement.HEADER
            )
            return ApiKeyAuthStrategy(
                api_key=str(api_key),
                param_name=str(param_name),
                placement=placement,
            )

        if resolved_type in (AuthType.OAUTH2, AuthType.OAUTH2_CLIENT_CREDENTIALS):
            raw_refresh = creds_dict.get("refresh_token")
            raw_expires = creds_dict.get("expires_at_epoch")
            expires_at: float | None = None
            if isinstance(raw_expires, (int, float, str)):
                try:
                    expires_at = float(raw_expires)
                except (ValueError, TypeError):
                    expires_at = None

            grant_mode = (
                "client_credentials"
                if resolved_type == AuthType.OAUTH2_CLIENT_CREDENTIALS
                else "refresh_token"
            )
            token_val = (
                creds_dict.get("access_token")
                or creds_dict.get("token")
                or creds_dict.get("api_key")
                or ""
            )
            return OAuth2Strategy(
                client_id=str(creds_dict.get("client_id", "")),
                client_secret=str(creds_dict.get("client_secret", "")),
                token_url=str(creds_dict.get("token_url", "")),
                access_token=str(token_val),
                refresh_token=str(raw_refresh) if raw_refresh is not None else None,
                expires_at_epoch=expires_at,
                allow_private_ips=allow_private_ips,
                grant_mode=grant_mode,
            )

        return NoAuthStrategy()
