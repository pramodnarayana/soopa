"""Pure domain value objects for declarative connector UI property schemas."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from seedwork.domain.types import JsonDict, JsonValue

from ip.engine.domain.connection.enums import PropertyType

__all__ = [
    "ConnectorProperty",
    "ConnectorPropertySchema",
    "DropdownOption",
    "OAuthConfig",
]


@dataclass(frozen=True)
class DropdownOption:
    """Option choice for dropdown property fields."""

    label: str
    value: str

    def to_dict(self) -> JsonDict:
        return {
            "label": self.label,
            "value": self.value,
        }


@dataclass(frozen=True)
class OAuthConfig:
    """OAuth2 authorization configuration for dynamic UI authorization modals."""

    auth_url: str
    token_url: str
    scopes: Sequence[str] = ()
    client_id: str | None = None

    def to_dict(self) -> JsonDict:
        scopes_val: list[JsonValue] = list(self.scopes)
        data: JsonDict = {
            "authUrl": self.auth_url,
            "tokenUrl": self.token_url,
            "scopes": scopes_val,
        }
        if self.client_id is not None:
            data["clientId"] = self.client_id
        return data


@dataclass(frozen=True)
class ConnectorProperty:
    """Specification of an individual configuration parameter for connection modals."""

    name: str
    label: str
    type: PropertyType
    required: bool = True
    default: str | int | float | bool | None = None
    description: str | None = None
    options: Sequence[DropdownOption] = ()
    oauth_config: OAuthConfig | None = None

    def to_dict(self) -> JsonDict:
        data: JsonDict = {
            "name": self.name,
            "label": self.label,
            "type": self.type.value,
            "required": self.required,
        }
        if self.default is not None:
            data["default"] = self.default
        if self.description is not None:
            data["description"] = self.description
        if self.options:
            options_val: list[JsonValue] = [
                {"label": opt.label, "value": opt.value} for opt in self.options
            ]
            data["options"] = options_val
        if self.oauth_config is not None:
            data["oauthConfig"] = self.oauth_config.to_dict()
        return data


@dataclass(frozen=True)
class ConnectorPropertySchema:
    """Complete declarative UI property schema for an application connector."""

    app_id: str
    display_name: str
    auth_type: str
    category: str
    properties: Sequence[ConnectorProperty]
    description: str | None = None

    def to_dict(self) -> JsonDict:
        props_val: list[JsonValue] = [p.to_dict() for p in self.properties]
        data: JsonDict = {
            "appId": self.app_id,
            "displayName": self.display_name,
            "authType": self.auth_type,
            "category": self.category,
            "properties": props_val,
        }
        if self.description is not None:
            data["description"] = self.description
        return data
