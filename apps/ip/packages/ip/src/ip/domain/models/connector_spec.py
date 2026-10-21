"""Domain models defining Declarative Connector manifests and Dynamic UI schemas."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Literal


class PropertyType(StrEnum):
    """Dynamic UI input types for self-service connector configuration."""

    SHORT_TEXT = "shortText"
    SECRET_TEXT = "secretText"  # noqa: S105 - UI schema property type identifier, not a password credential
    DROPDOWN = "dropdown"
    OAUTH2 = "oauth2"
    NUMBER = "number"
    BOOLEAN = "boolean"


@dataclass(frozen=True)
class DropdownOption:
    """Option choice for dropdown property fields."""

    label: str
    value: str

    def to_dict(self) -> dict[str, str]:
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

    def to_dict(self) -> dict[str, object]:
        data: dict[str, object] = {
            "authUrl": self.auth_url,
            "tokenUrl": self.token_url,
            "scopes": list(self.scopes),
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

    def to_dict(self) -> dict[str, object]:
        data: dict[str, object] = {
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
            data["options"] = [opt.to_dict() for opt in self.options]
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

    def to_dict(self) -> dict[str, object]:
        data: dict[str, object] = {
            "appId": self.app_id,
            "displayName": self.display_name,
            "authType": self.auth_type,
            "category": self.category,
            "properties": [p.to_dict() for p in self.properties],
        }
        if self.description is not None:
            data["description"] = self.description
        return data


class PaginationType(StrEnum):
    """Pagination strategies for Declarative HTTP APIs."""

    NONE = "none"
    OFFSET_LIMIT = "offset_limit"
    PAGE_NUMBER = "page_number"
    CURSOR = "cursor"
    LINK_HEADER = "link_header"


@dataclass(frozen=True)
class PaginationConfig:
    """Configuration for paginated endpoint reading."""

    pagination_type: PaginationType = PaginationType.NONE
    page_size: int = 100
    cursor_param: str = "cursor"
    cursor_path: str | None = None
    limit_param: str = "limit"
    offset_param: str = "offset"
    page_param: str = "page"


@dataclass(frozen=True)
class HttpActionSpec:
    """Declarative specification for an HTTP endpoint call."""

    path: str
    method: Literal["GET", "POST", "PUT", "PATCH", "DELETE"] = "GET"
    headers: Mapping[str, str] = field(default_factory=dict)
    query_params: Mapping[str, str] = field(default_factory=dict)
    body_template: str | None = None
    pagination: PaginationConfig = field(default_factory=PaginationConfig)
    response_records_path: str | None = None
    response_cursor_path: str | None = None


@dataclass(frozen=True)
class DeclarativeManifest:
    """Self-contained metadata and action specification for declarative HTTP connectors."""

    app_id: str
    display_name: str
    category: str
    auth_type: str
    base_url_template: str
    property_schema: ConnectorPropertySchema
    check_action: HttpActionSpec
    streams: Mapping[str, HttpActionSpec]
    write_actions: Mapping[str, HttpActionSpec] = field(default_factory=dict)
