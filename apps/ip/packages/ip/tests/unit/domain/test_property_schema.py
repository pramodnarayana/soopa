"""Pure zero-mock unit tests for declarative ConnectorPropertySchema value objects."""

from __future__ import annotations

from ip.engine.domain.connection.enums import PropertyType
from ip.engine.domain.connection.property_schema import (
    ConnectorProperty,
    ConnectorPropertySchema,
    DropdownOption,
    OAuthConfig,
)


def test_connector_property_schema_serializes_nested_options_oauth_config() -> None:
    option = DropdownOption(label="Production", value="prod")
    assert option.to_dict() == {"label": "Production", "value": "prod"}

    oauth = OAuthConfig(
        auth_url="https://login.example.com/authorize",
        token_url="https://login.example.com/token",
        scopes=("read", "write"),
        client_id="client_123",
    )
    assert oauth.to_dict()["clientId"] == "client_123"

    prop = ConnectorProperty(
        name="environment",
        label="Environment",
        type=PropertyType.DROPDOWN,
        required=True,
        default="prod",
        description="Target deployment environment",
        options=(option,),
        oauth_config=oauth,
    )
    schema = ConnectorPropertySchema(
        app_id="acme_crm",
        display_name="Acme CRM",
        auth_type="OAUTH2",
        category="CRM",
        properties=(prop,),
        description="Connect to Acme CRM",
    )
    serialized = schema.to_dict()
    assert serialized["appId"] == "acme_crm"
    assert serialized["description"] == "Connect to Acme CRM"
    props = serialized["properties"]
    assert isinstance(props, list)
    assert len(props) == 1
