"""Declarative manifest specification for Stripe Payments connector."""

from __future__ import annotations

from ip.engine.domain.models.connector_spec import (
    ConnectorProperty,
    ConnectorPropertySchema,
    DeclarativeManifest,
    HttpActionSpec,
    PaginationConfig,
    PaginationType,
    PropertyType,
)

STRIPE_PROPERTY_SCHEMA = ConnectorPropertySchema(
    app_id="stripe",
    display_name="Stripe Payments",
    auth_type="BEARER",
    category="BILLING",
    description="Sync Customers, Invoices, and Charges from Stripe",
    properties=(
        ConnectorProperty(
            name="api_key",
            label="Secret API Key",
            type=PropertyType.SECRET_TEXT,
            required=True,
            description="Stripe secret key (sk_live_... / sk_test_...)",
        ),
    ),
)

STRIPE_MANIFEST = DeclarativeManifest(
    app_id="stripe",
    display_name="Stripe Payments",
    category="BILLING",
    auth_type="BEARER",
    base_url_template="https://api.stripe.com/v1",
    property_schema=STRIPE_PROPERTY_SCHEMA,
    check_action=HttpActionSpec(path="/balance", method="GET"),
    streams={
        "customers": HttpActionSpec(
            path="/customers",
            pagination=PaginationConfig(
                pagination_type=PaginationType.CURSOR,
                cursor_param="starting_after",
                cursor_path="data.-1.id",
                limit_param="limit",
                page_size=100,
            ),
            response_records_path="data",
        ),
        "invoices": HttpActionSpec(
            path="/invoices",
            pagination=PaginationConfig(
                pagination_type=PaginationType.CURSOR,
                cursor_param="starting_after",
                cursor_path="data.-1.id",
                limit_param="limit",
                page_size=100,
            ),
            response_records_path="data",
        ),
    },
    write_actions={
        "customers": HttpActionSpec(path="/customers", method="POST"),
    },
)
