"""Connection catalog aggregate root and connector UI property schemas."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import ClassVar

from seedwork.domain.aggregate import AggregateRoot
from seedwork.domain.types import JsonDict, JsonValue

from ip.engine.domain.connection.enums import PropertyType
from ip.engine.domain.connection.stream_schema import StreamSchema
from ip.engine.domain.constants import IpIdPrefix
from ip.engine.domain.exceptions import InvalidConnectionConfigError, Result

__all__ = [
    "ConnectionCatalog",
    "ConnectorProperty",
    "ConnectorPropertySchema",
    "DropdownOption",
    "OAuthConfig",
]


@dataclass(kw_only=True, eq=False)
class ConnectionCatalog(AggregateRoot):
    """Aggregate Root representing the discovered schema definition for a connection."""

    ID_PREFIX: ClassVar[str] = IpIdPrefix.CATALOG.value

    id: str
    tenant_id: str
    connection_id: str
    catalog_version: int
    catalog_hash: str
    streams: Sequence[StreamSchema]
    is_active: bool = True
    discovered_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    @classmethod
    def try_create(
        cls,
        *,
        tenant_id: str,
        connection_id: str,
        catalog_version: int,
        streams: Sequence[StreamSchema],
    ) -> Result[ConnectionCatalog, InvalidConnectionConfigError]:
        if not tenant_id.strip():
            return Result.fail(
                InvalidConnectionConfigError(
                    field_name="tenant_id",
                    message="tenant_id cannot be empty",
                    details={"field": "tenant_id"},
                )
            )
        if not connection_id.strip():
            return Result.fail(
                InvalidConnectionConfigError(
                    field_name="connection_id",
                    message="connection_id cannot be empty",
                    details={"field": "connection_id"},
                )
            )
        return Result.ok(
            cls.create(
                tenant_id=tenant_id,
                connection_id=connection_id,
                catalog_version=catalog_version,
                streams=streams,
            )
        )

    @classmethod
    def create(
        cls,
        *,
        tenant_id: str,
        connection_id: str,
        catalog_version: int,
        streams: Sequence[StreamSchema],
    ) -> ConnectionCatalog:
        sorted_streams = sorted(streams, key=lambda s: s.name)
        stream_dicts = [
            {
                "name": s.name,
                "fields": sorted(
                    [
                        {
                            "name": f.name,
                            "type": f.data_type,
                            "nullable": f.nullable,
                        }
                        for f in s.fields
                    ],
                    key=lambda f: str(f["name"]),
                ),
                "primary_key": sorted(s.primary_key),
                "cursor_field": s.cursor_field,
                "supported_sync_modes": sorted([m.value for m in s.supported_sync_modes]),
            }
            for s in sorted_streams
        ]
        raw_json = json.dumps(stream_dicts, sort_keys=True)
        catalog_hash = hashlib.sha256(raw_json.encode("utf-8")).hexdigest()

        return cls(
            id=cls.new_id(),
            tenant_id=tenant_id,
            connection_id=connection_id,
            catalog_version=catalog_version,
            catalog_hash=catalog_hash,
            streams=streams,
            is_active=True,
        )

    def get_stream(self, stream_name: str) -> StreamSchema | None:
        """Retrieves a stream schema by name."""
        for s in self.streams:
            if s.name == stream_name:
                return s
        return None


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
