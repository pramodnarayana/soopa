"""Declarative manifest specification for HubSpot CRM connector."""

from __future__ import annotations

from ip.domain.models.connector_spec import (
    ConnectorProperty,
    ConnectorPropertySchema,
    DeclarativeManifest,
    HttpActionSpec,
    PaginationConfig,
    PaginationType,
    PropertyType,
)

HUBSPOT_PROPERTY_SCHEMA = ConnectorPropertySchema(
    app_id="hubspot",
    display_name="HubSpot",
    auth_type="BEARER",
    category="CRM",
    description="Sync Contacts, Companies, and Deals with HubSpot CRM",
    properties=(
        ConnectorProperty(
            name="access_token",
            label="Private App Token",
            type=PropertyType.SECRET_TEXT,
            required=True,
            description="HubSpot Private App Access Token",
        ),
    ),
)

HUBSPOT_MANIFEST = DeclarativeManifest(
    app_id="hubspot",
    display_name="HubSpot",
    category="CRM",
    auth_type="BEARER",
    base_url_template="https://api.hubapi.com",
    property_schema=HUBSPOT_PROPERTY_SCHEMA,
    check_action=HttpActionSpec(path="/crm/v3/objects/contacts?limit=1", method="GET"),
    streams={
        "contacts": HttpActionSpec(
            path="/crm/v3/objects/contacts",
            pagination=PaginationConfig(
                pagination_type=PaginationType.CURSOR,
                cursor_param="after",
                cursor_path="paging.next.after",
                limit_param="limit",
                page_size=50,
            ),
            response_records_path="results",
        ),
        "companies": HttpActionSpec(
            path="/crm/v3/objects/companies",
            pagination=PaginationConfig(
                pagination_type=PaginationType.CURSOR,
                cursor_param="after",
                cursor_path="paging.next.after",
                limit_param="limit",
                page_size=50,
            ),
            response_records_path="results",
        ),
    },
    write_actions={
        "contacts": HttpActionSpec(path="/crm/v3/objects/contacts", method="POST"),
        "companies": HttpActionSpec(path="/crm/v3/objects/companies", method="POST"),
    },
)
