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


class AuthStrategyResolver:
    """Resolves and instantiates the appropriate AuthenticatorPort strategy for a connection."""

    @classmethod
    def resolve(
        cls,
        auth_type: AuthType,
        credentials: JsonDict | bytes | str | None = None,
        *,
        allow_private_ips: bool = False,
    ) -> AuthenticatorPort:
        creds_dict: JsonDict = {}
        if isinstance(credentials, bytes):
            try:
                creds_dict = json.loads(credentials.decode("utf-8"))
            except (json.JSONDecodeError, UnicodeDecodeError, ValueError):
                creds_dict = {"api_key": credentials.decode("utf-8", errors="ignore")}
        elif isinstance(credentials, str):
            try:
                creds_dict = json.loads(credentials)
            except (json.JSONDecodeError, ValueError):
                creds_dict = {"api_key": credentials}
        elif isinstance(credentials, dict):
            creds_dict = credentials

        if auth_type == AuthType.BASIC_AUTH:
            return BasicAuthStrategy(
                username=str(creds_dict.get("username", "")),
                password=str(creds_dict.get("password", "")),
            )

        if auth_type == AuthType.BEARER_TOKEN:
            token = (
                creds_dict.get("token")
                or creds_dict.get("api_key")
                or creds_dict.get("bearer_token")
                or ""
            )
            return BearerAuthStrategy(token=str(token))

        if auth_type == AuthType.API_KEY:
            api_key = creds_dict.get("api_key") or creds_dict.get("token") or ""
            param_name = creds_dict.get("param_name") or "X-API-Key"
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

        if auth_type in (AuthType.OAUTH2, AuthType.OAUTH2_CLIENT_CREDENTIALS):
            raw_refresh = creds_dict.get("refresh_token")
            raw_expires = creds_dict.get("expires_at_epoch")
            return OAuth2Strategy(
                client_id=str(creds_dict.get("client_id", "")),
                client_secret=str(creds_dict.get("client_secret", "")),
                token_url=str(creds_dict.get("token_url", "")),
                access_token=str(creds_dict.get("access_token", "")),
                refresh_token=str(raw_refresh) if raw_refresh is not None else None,
                expires_at_epoch=(
                    float(raw_expires) if isinstance(raw_expires, (int, float, str)) else None
                ),
                allow_private_ips=allow_private_ips,
            )

        return NoAuthStrategy()
