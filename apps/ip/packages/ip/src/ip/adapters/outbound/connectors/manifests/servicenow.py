"""Declarative manifest specification for ServiceNow ITSM connector."""

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

SERVICENOW_PROPERTY_SCHEMA = ConnectorPropertySchema(
    app_id="servicenow",
    display_name="ServiceNow",
    auth_type="BASIC",
    category="ITSM",
    description="Sync Incidents and Assets with ServiceNow Enterprise ITSM",
    properties=(
        ConnectorProperty(
            name="instance",
            label="Instance Name",
            type=PropertyType.SHORT_TEXT,
            required=True,
            description="ServiceNow sub-domain (e.g. dev12345)",
        ),
        ConnectorProperty(
            name="username",
            label="Username",
            type=PropertyType.SHORT_TEXT,
            required=True,
        ),
        ConnectorProperty(
            name="password",
            label="Password",
            type=PropertyType.SECRET_TEXT,
            required=True,
        ),
    ),
)

SERVICENOW_MANIFEST = DeclarativeManifest(
    app_id="servicenow",
    display_name="ServiceNow",
    category="ITSM",
    auth_type="BASIC",
    base_url_template="https://{instance}.service-now.com/api/now",
    property_schema=SERVICENOW_PROPERTY_SCHEMA,
    check_action=HttpActionSpec(path="/table/incident?sysparm_limit=1", method="GET"),
    streams={
        "incidents": HttpActionSpec(
            path="/table/incident",
            pagination=PaginationConfig(
                pagination_type=PaginationType.OFFSET_LIMIT,
                limit_param="sysparm_limit",
                offset_param="sysparm_offset",
                page_size=100,
            ),
            response_records_path="result",
        ),
    },
    write_actions={
        "incidents": HttpActionSpec(path="/table/incident", method="POST"),
    },
)
