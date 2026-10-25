"""Data mapper converting ConnectorPropertySchema domain models to AppSpecDTO port structures."""

from __future__ import annotations

from ip.engine.domain.models.connector_spec import (
    ConnectorProperty,
    ConnectorPropertySchema,
    DropdownOption,
    OAuthConfig,
)
from ip.engine.ports.types import (
    AppSpecDTO,
    ConnectorPropertyDTO,
    DropdownOptionDTO,
    OAuthConfigDTO,
)


def dropdown_option_to_dto(option: DropdownOption) -> DropdownOptionDTO:
    """Maps a DropdownOption domain entity to a DropdownOptionDTO."""
    return DropdownOptionDTO(
        label=option.label,
        value=option.value,
    )


def oauth_config_to_dto(oauth: OAuthConfig | None) -> OAuthConfigDTO | None:
    """Maps an OAuthConfig domain entity to an OAuthConfigDTO."""
    if oauth is None:
        return None
    return OAuthConfigDTO(
        auth_url=oauth.auth_url,
        token_url=oauth.token_url,
        scopes=tuple(oauth.scopes),
        client_id=oauth.client_id,
    )


def connector_property_to_dto(prop: ConnectorProperty) -> ConnectorPropertyDTO:
    """Maps a ConnectorProperty domain entity to a ConnectorPropertyDTO."""
    return ConnectorPropertyDTO(
        name=prop.name,
        label=prop.label,
        type=prop.type.value if hasattr(prop.type, "value") else str(prop.type),
        required=prop.required,
        default=prop.default,
        description=prop.description,
        options=tuple(dropdown_option_to_dto(opt) for opt in prop.options),
        oauth_config=oauth_config_to_dto(prop.oauth_config),
    )


def schema_to_app_spec_dto(schema: ConnectorPropertySchema) -> AppSpecDTO:
    """Maps a ConnectorPropertySchema domain entity to an AppSpecDTO."""
    return AppSpecDTO(
        app_id=schema.app_id,
        display_name=schema.display_name,
        auth_type=schema.auth_type,
        category=schema.category,
        properties=tuple(connector_property_to_dto(prop) for prop in schema.properties),
        description=schema.description,
    )
