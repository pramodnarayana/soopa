"""Unit tests for Connection aggregate root and related domain invariants."""

import pytest
from ip.domain.constants import IpDomainIdPrefix
from ip.domain.events import (
    ConnectionActivatedEvent,
    ConnectionCreatedEvent,
    ConnectionDeactivatedEvent,
    ConnectionErrorRecordedEvent,
    ConnectionRelinkedEvent,
)
from ip.domain.exceptions import InvalidConnectionStateException
from ip.domain.models.connection import (
    AuthType,
    Connection,
    ConnectionStatus,
    compute_connection_fingerprint,
)


def test_connection_creation_emits_created_event_and_sets_prefix_id() -> None:
    tenant_id = "ten_12345"
    app_id = "itron_mdm"
    endpoint = "https://ami.utility.com/api"

    connection = Connection.create(
        tenant_id=tenant_id,
        app_id=app_id,
        name="Production Itron MDM",
        auth_type=AuthType.API_KEY,
        public_config={"endpoint_url": endpoint},
        encrypted_credentials=b"encrypted_secret",
        endpoint_for_fingerprint=endpoint,
    )

    assert connection.id.startswith(f"{IpDomainIdPrefix.CONNECTION}_")
    assert connection.tenant_id == tenant_id
    assert connection.app_id == app_id
    assert connection.name == "Production Itron MDM"
    assert connection.auth_type == AuthType.API_KEY
    assert connection.status == ConnectionStatus.PENDING_AUTH
    assert connection.connection_fingerprint == compute_connection_fingerprint(
        tenant_id, app_id, endpoint
    )

    # Check domain event
    events = connection.domain_events
    assert len(events) == 1
    assert isinstance(events[0], ConnectionCreatedEvent)
    assert events[0].connection_id == connection.id
    assert events[0].event_name == "ip.connection.created"
    assert events[0].get_routing_tenant_id() == tenant_id


def test_connection_creation_rejects_empty_parameters() -> None:
    with pytest.raises(ValueError, match="tenant_id cannot be empty"):
        Connection.create(
            tenant_id="",
            app_id="itron_mdm",
            name="Test",
            auth_type=AuthType.NO_AUTH,
            public_config={},
            encrypted_credentials=None,
            endpoint_for_fingerprint="https://endpoint.com",
        )

    with pytest.raises(ValueError, match="app_id cannot be empty"):
        Connection.create(
            tenant_id="ten_1",
            app_id=" ",
            name="Test",
            auth_type=AuthType.NO_AUTH,
            public_config={},
            encrypted_credentials=None,
            endpoint_for_fingerprint="https://endpoint.com",
        )

    with pytest.raises(ValueError, match="name cannot be empty"):
        Connection.create(
            tenant_id="ten_1",
            app_id="itron_mdm",
            name="",
            auth_type=AuthType.NO_AUTH,
            public_config={},
            encrypted_credentials=None,
            endpoint_for_fingerprint="https://endpoint.com",
        )


def test_connection_activation_flow() -> None:
    connection = Connection.create(
        tenant_id="ten_1",
        app_id="itron_mdm",
        name="Test",
        auth_type=AuthType.API_KEY,
        public_config={},
        encrypted_credentials=None,
        endpoint_for_fingerprint="https://endpoint.com",
    )
    connection.clear_domain_events()

    connection.activate()
    assert connection.status == ConnectionStatus.ACTIVE

    events = connection.domain_events
    assert len(events) == 1
    assert isinstance(events[0], ConnectionActivatedEvent)


def test_connection_error_and_deactivation_flow() -> None:
    connection = Connection.create(
        tenant_id="ten_1",
        app_id="itron_mdm",
        name="Test",
        auth_type=AuthType.API_KEY,
        public_config={},
        encrypted_credentials=None,
        endpoint_for_fingerprint="https://endpoint.com",
    )
    connection.clear_domain_events()

    connection.mark_error("AUTH_FAILED", "Invalid API token")
    assert connection.status == ConnectionStatus.ERROR
    assert connection.last_error_code == "AUTH_FAILED"
    assert connection.last_error_message == "Invalid API token"
    assert len(connection.domain_events) == 1
    assert isinstance(connection.domain_events[0], ConnectionErrorRecordedEvent)

    connection.clear_domain_events()
    connection.deactivate()
    assert connection.status == ConnectionStatus.DEACTIVATED
    assert connection.deactivated_at is not None
    assert len(connection.domain_events) == 1
    assert isinstance(connection.domain_events[0], ConnectionDeactivatedEvent)


def test_deactivated_connection_cannot_be_activated_directly() -> None:
    connection = Connection.create(
        tenant_id="ten_1",
        app_id="itron_mdm",
        name="Test",
        auth_type=AuthType.API_KEY,
        public_config={},
        encrypted_credentials=None,
        endpoint_for_fingerprint="https://endpoint.com",
    )
    connection.deactivate()

    with pytest.raises(
        InvalidConnectionStateException, match="Cannot activate deactivated connection"
    ):
        connection.activate()


def test_relink_restores_deactivated_connection() -> None:
    connection = Connection.create(
        tenant_id="ten_1",
        app_id="itron_mdm",
        name="Test",
        auth_type=AuthType.API_KEY,
        public_config={},
        encrypted_credentials=None,
        endpoint_for_fingerprint="https://endpoint.com",
    )
    connection.deactivate()
    connection.clear_domain_events()

    connection.relink(
        new_name="Restored Itron Connection", updated_encrypted_credentials=b"new_creds"
    )
    assert connection.status == ConnectionStatus.ACTIVE
    assert connection.name == "Restored Itron Connection"
    assert connection.encrypted_credentials == b"new_creds"
    assert connection.deactivated_at is None
    assert len(connection.domain_events) == 1
    assert isinstance(connection.domain_events[0], ConnectionRelinkedEvent)
