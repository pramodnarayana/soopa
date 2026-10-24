"""Declarative manifest specification for Salesforce CRM connector."""

from __future__ import annotations

from ip.engine.domain.models.connector_spec import (
    ConnectorProperty,
    ConnectorPropertySchema,
    DeclarativeManifest,
    DropdownOption,
    HttpActionSpec,
    OAuthConfig,
    PaginationConfig,
    PaginationType,
    PropertyType,
)

SALESFORCE_PROPERTY_SCHEMA = ConnectorPropertySchema(
    app_id="salesforce",
    display_name="Salesforce CRM",
    auth_type="OAUTH2",
    category="CRM",
    description="Sync Contacts, Accounts, and Opportunities with Salesforce Cloud",
    properties=(
        ConnectorProperty(
            name="instance_host",
            label="Instance Host",
            type=PropertyType.SHORT_TEXT,
            required=True,
            default="login.salesforce.com",
            description="Use test.salesforce.com for sandbox environments",
        ),
        ConnectorProperty(
            name="environment",
            label="Environment",
            type=PropertyType.DROPDOWN,
            required=True,
            options=(
                DropdownOption(label="Production", value="production"),
                DropdownOption(label="Sandbox", value="sandbox"),
            ),
        ),
        ConnectorProperty(
            name="oauth",
            label="Salesforce Authorization",
            type=PropertyType.OAUTH2,
            required=True,
            oauth_config=OAuthConfig(
                auth_url="https://login.salesforce.com/services/oauth2/authorize",
                token_url="https://login.salesforce.com/services/oauth2/token",  # noqa: S106 - OAuth endpoint URL
                scopes=("api", "refresh_token", "offline_access"),
            ),
        ),
    ),
)

SALESFORCE_MANIFEST = DeclarativeManifest(
    app_id="salesforce",
    display_name="Salesforce CRM",
    category="CRM",
    auth_type="OAUTH2",
    base_url_template="https://{instance_host}/services/data/v58.0",
    property_schema=SALESFORCE_PROPERTY_SCHEMA,
    check_action=HttpActionSpec(path="/sobjects", method="GET"),
    streams={
        "contacts": HttpActionSpec(
            path="/query",
            method="GET",
            query_params={"q": "SELECT Id, FirstName, LastName, Email FROM Contact"},
            pagination=PaginationConfig(
                pagination_type=PaginationType.CURSOR,
                cursor_param="nextRecordsUrl",
                cursor_path="nextRecordsUrl",
            ),
            response_records_path="records",
        ),
        "accounts": HttpActionSpec(
            path="/query",
            method="GET",
            query_params={"q": "SELECT Id, Name, Industry, Phone FROM Account"},
            pagination=PaginationConfig(
                pagination_type=PaginationType.CURSOR,
                cursor_param="nextRecordsUrl",
                cursor_path="nextRecordsUrl",
            ),
            response_records_path="records",
        ),
    },
    write_actions={
        "contacts": HttpActionSpec(path="/sobjects/Contact", method="POST"),
        "accounts": HttpActionSpec(path="/sobjects/Account", method="POST"),
    },
)
