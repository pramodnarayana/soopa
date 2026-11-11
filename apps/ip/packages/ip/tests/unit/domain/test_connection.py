"""Unit tests for Connection aggregate root and related domain invariants."""

from ip.engine.domain.connection.connection import Connection, compute_connection_fingerprint
from ip.engine.domain.connection.enums import (
    AuthType,
    ConnectionStatus,
)
from ip.engine.domain.connection.events import (
    ConnectionActivatedEvent,
    ConnectionCreatedEvent,
    ConnectionDeactivatedEvent,
    ConnectionDeletedEvent,
    ConnectionErrorRecordedEvent,
    ConnectionRelinkedEvent,
    ConnectionUpdatedEvent,
)
from ip.engine.domain.constants import IpIdPrefix
from ip.engine.domain.exceptions import (
    FailureDisposition,
    InvalidConnectionConfigError,
    InvalidConnectionStateError,
    IpErrorCode,
)


def test_connection_creation_initializes_pending_aggregate_with_created_event() -> None:
    tenant_id = "ten_12345"
    app_id = "acme_source"
    endpoint = "https://api.partner.example.com/api"

    connection = Connection.create(
        tenant_id=tenant_id,
        app_id=app_id,
        name="Production Source API",
        auth_type=AuthType.API_KEY,
        public_config={"endpoint_url": endpoint},
        encrypted_credentials=b"encrypted_secret",
        endpoint_for_fingerprint=endpoint,
    )

    assert connection.id.startswith(f"{IpIdPrefix.CONNECTION.value}_")
    assert connection.tenant_id == tenant_id
    assert connection.app_id == app_id
    assert connection.name == "Production Source API"
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


def test_no_auth_connection_creation_initializes_active_status() -> None:
    connection = Connection.create(
        tenant_id="ten_12345",
        app_id="universal_simulator",
        name="Universal Sandbox Simulator Primary",
        auth_type=AuthType.NO_AUTH,
        public_config={"seed": 42},
        encrypted_credentials=None,
        endpoint_for_fingerprint="Universal Sandbox Simulator Primary",
    )

    assert connection.auth_type == AuthType.NO_AUTH
    assert connection.status == ConnectionStatus.ACTIVE


def test_connection_try_create_returns_typed_error_for_empty_parameters() -> None:
    res_tenant = Connection.try_create(
        tenant_id="",
        app_id="acme_source",
        name="Test",
        auth_type=AuthType.NO_AUTH,
        public_config={},
        encrypted_credentials=None,
        endpoint_for_fingerprint="https://endpoint.com",
    )
    assert res_tenant.is_err is True
    assert isinstance(res_tenant.error, InvalidConnectionConfigError)
    assert res_tenant.error.code == IpErrorCode.INVALID_CONFIG
    assert res_tenant.error.field_name == "tenant_id"
    assert "tenant_id cannot be empty" in res_tenant.error.message

    res_app = Connection.try_create(
        tenant_id="ten_1",
        app_id=" ",
        name="Test",
        auth_type=AuthType.NO_AUTH,
        public_config={},
        encrypted_credentials=None,
        endpoint_for_fingerprint="https://endpoint.com",
    )
    assert res_app.is_err is True
    assert isinstance(res_app.error, InvalidConnectionConfigError)
    assert res_app.error.field_name == "app_id"
    assert "app_id cannot be empty" in res_app.error.message

    res_name = Connection.try_create(
        tenant_id="ten_1",
        app_id="acme_source",
        name="",
        auth_type=AuthType.NO_AUTH,
        public_config={},
        encrypted_credentials=None,
        endpoint_for_fingerprint="https://endpoint.com",
    )
    assert res_name.is_err is True
    assert isinstance(res_name.error, InvalidConnectionConfigError)
    assert res_name.error.field_name == "name"
    assert "name cannot be empty" in res_name.error.message


def test_connection_activation_flow() -> None:
    connection = Connection.create(
        tenant_id="ten_1",
        app_id="acme_source",
        name="Test",
        auth_type=AuthType.API_KEY,
        public_config={},
        encrypted_credentials=None,
        endpoint_for_fingerprint="https://endpoint.com",
    )
    connection.clear_domain_events()

    res = connection.activate()
    assert res.is_ok is True
    assert connection.status == ConnectionStatus.ACTIVE

    events = connection.domain_events
    assert len(events) == 1
    assert isinstance(events[0], ConnectionActivatedEvent)


def test_connection_mark_error_records_failure_state() -> None:
    connection = Connection.create(
        tenant_id="ten_1",
        app_id="acme_source",
        name="Test",
        auth_type=AuthType.API_KEY,
        public_config={},
        encrypted_credentials=None,
        endpoint_for_fingerprint="https://endpoint.com",
    )
    connection.clear_domain_events()

    err_res = connection.mark_error("AUTH_FAILED", "Invalid API token")
    assert err_res.is_ok is True
    assert connection.status == ConnectionStatus.ERROR
    assert connection.last_error_code == "AUTH_FAILED"
    assert connection.last_error_message == "Invalid API token"
    assert len(connection.domain_events) == 1
    assert isinstance(connection.domain_events[0], ConnectionErrorRecordedEvent)


def test_connection_deactivate_transitions_to_deactivated_state() -> None:
    connection = Connection.create(
        tenant_id="ten_1",
        app_id="acme_source",
        name="Test",
        auth_type=AuthType.API_KEY,
        public_config={},
        encrypted_credentials=None,
        endpoint_for_fingerprint="https://endpoint.com",
    )
    connection.clear_domain_events()
    deact_res = connection.deactivate()
    assert deact_res.is_ok is True
    assert connection.status.value == ConnectionStatus.DEACTIVATED.value
    assert connection.deactivated_at is not None
    assert len(connection.domain_events) == 1
    assert isinstance(connection.domain_events[0], ConnectionDeactivatedEvent)


def test_deactivated_connection_cannot_be_activated_directly() -> None:
    connection = Connection.create(
        tenant_id="ten_1",
        app_id="acme_source",
        name="Test",
        auth_type=AuthType.API_KEY,
        public_config={},
        encrypted_credentials=None,
        endpoint_for_fingerprint="https://endpoint.com",
    )
    connection.deactivate()

    result = connection.activate()
    assert result.is_err is True
    assert isinstance(result.error, InvalidConnectionStateError)
    assert result.error.code == IpErrorCode.INVALID_CONNECTION_STATE
    assert result.error.disposition == FailureDisposition.FAIL
    assert result.error.attempted_action == "activate"
    assert "Cannot activate deactivated connection" in result.error.message


def test_relink_restores_deactivated_connection() -> None:
    connection = Connection.create(
        tenant_id="ten_1",
        app_id="acme_source",
        name="Test",
        auth_type=AuthType.API_KEY,
        public_config={},
        encrypted_credentials=None,
        endpoint_for_fingerprint="https://endpoint.com",
    )
    connection.deactivate()
    connection.clear_domain_events()

    relink_res = connection.relink(
        new_name="Restored Source Connection", updated_encrypted_credentials=b"new_creds"
    )
    assert relink_res.is_ok is True
    assert connection.status == ConnectionStatus.ACTIVE
    assert connection.name == "Restored Source Connection"
    assert connection.encrypted_credentials == b"new_creds"
    assert connection.deactivated_at is None
    assert len(connection.domain_events) == 1
    assert isinstance(connection.domain_events[0], ConnectionRelinkedEvent)


def test_compute_connection_fingerprint_preserves_path_case() -> None:
    fp1 = compute_connection_fingerprint(
        "ten_1", "app_1", "HTTPS://API.Example.com/Path/CaseSensitive"
    )
    fp2 = compute_connection_fingerprint(
        "ten_1", "app_1", "https://api.example.com/Path/CaseSensitive"
    )
    fp3 = compute_connection_fingerprint(
        "ten_1", "app_1", "https://api.example.com/path/casesensitive"
    )

    # Host/scheme normalized (fp1 == fp2)
    assert fp1 == fp2
    # Path is case-sensitive (fp1 != fp3)
    assert fp1 != fp3


def test_relink_recomputes_fingerprint_when_public_config_changes() -> None:
    connection = Connection.create(
        tenant_id="ten_1",
        app_id="acme_source",
        name="Test",
        auth_type=AuthType.API_KEY,
        public_config={"endpoint_url": "https://api.example.com/v1"},
        encrypted_credentials=None,
        endpoint_for_fingerprint="https://api.example.com/v1",
    )
    old_fingerprint = connection.connection_fingerprint
    connection.deactivate()

    connection.relink(
        new_name="Relinked Test",
        updated_public_config={"endpoint_url": "https://api.example.com/v2"},
    )
    new_fingerprint = connection.connection_fingerprint

    assert new_fingerprint != old_fingerprint
    assert new_fingerprint == compute_connection_fingerprint(
        "ten_1", "acme_source", "https://api.example.com/v2"
    )


def test_compute_connection_fingerprint_preserves_userinfo_case() -> None:
    fp1 = compute_connection_fingerprint(
        "ten_1", "app_1", "https://UserAdmin:SecretPass@API.Example.COM:8080/path;param?query"
    )
    fp2 = compute_connection_fingerprint(
        "ten_1", "app_1", "https://UserAdmin:SecretPass@api.example.com:8080/path;param?query"
    )
    fp3 = compute_connection_fingerprint(
        "ten_1", "app_1", "https://useradmin:secretpass@api.example.com:8080/path;param?query"
    )
    assert fp1 == fp2
    assert fp1 != fp3


def test_compute_connection_fingerprint_handles_malformed_url() -> None:
    malformed_url = "http://[::ffff:invalid:ipv6:address/path"
    fp = compute_connection_fingerprint("ten_1", "app_1", malformed_url)
    assert isinstance(fp, str)
    assert len(fp) == 64


def test_relink_preserves_fingerprint_when_no_endpoint_in_public_config() -> None:
    connection = Connection.create(
        tenant_id="ten_1",
        app_id="acme_source",
        name="Test",
        auth_type=AuthType.API_KEY,
        public_config={"endpoint_url": "https://api.example.com/v1"},
        encrypted_credentials=None,
        endpoint_for_fingerprint="https://api.example.com/v1",
    )
    old_fingerprint = connection.connection_fingerprint
    connection.deactivate()

    connection.relink(
        new_name="Relinked Without Endpoint",
        updated_public_config={"other_setting": "val"},
    )
    assert connection.connection_fingerprint == old_fingerprint


def test_relink_uses_base_url_then_host_when_endpoint_url_missing() -> None:
    connection = Connection.create(
        tenant_id="ten_1",
        app_id="acme_source",
        name="Test",
        auth_type=AuthType.API_KEY,
        public_config={"endpoint_url": "https://api.example.com/v1"},
        encrypted_credentials=None,
        endpoint_for_fingerprint="https://api.example.com/v1",
    )
    connection.deactivate()

    connection.relink(
        updated_public_config={"base_url": "https://base.example.com"},
    )
    assert connection.connection_fingerprint == compute_connection_fingerprint(
        "ten_1", "acme_source", "https://base.example.com"
    )


def test_connection_mark_deleted_emits_deleted_event() -> None:
    connection = Connection.create(
        tenant_id="ten_delete_1",
        app_id="acme_source",
        name="Partner Source API",
        auth_type=AuthType.API_KEY,
        public_config={"endpoint_url": "https://api.test.example.com"},
        encrypted_credentials=b"secret",
        endpoint_for_fingerprint="https://api.test.example.com",
    )
    connection.clear_domain_events()

    connection.mark_deleted()

    events = connection.domain_events
    assert len(events) == 1
    assert isinstance(events[0], ConnectionDeletedEvent)
    assert events[0].connection_id == connection.id
    assert events[0].tenant_id == "ten_delete_1"
    assert events[0].app_id == "acme_source"
    assert events[0].event_name == "ip.connection.deleted"


def test_connection_update_configuration_success() -> None:
    connection = Connection.create(
        tenant_id="ten_update_1",
        app_id="acme_source",
        name="Original Name",
        auth_type=AuthType.API_KEY,
        public_config={"endpoint_url": "https://api.original.example.com"},
        encrypted_credentials=b"original_secret",
        endpoint_for_fingerprint="https://api.original.example.com",
    )
    connection.clear_domain_events()

    res = connection.update_configuration(
        new_name="Updated Name",
        updated_encrypted_credentials=b"new_secret",
        updated_public_config={"endpoint_url": "https://api.updated.example.com"},
    )
    assert res.is_ok is True
    assert connection.name == "Updated Name"
    assert connection.encrypted_credentials == b"new_secret"
    assert connection.public_config == {"endpoint_url": "https://api.updated.example.com"}

    events = connection.domain_events
    assert len(events) == 1
    assert isinstance(events[0], ConnectionUpdatedEvent)
    assert events[0].connection_id == connection.id
    assert events[0].tenant_id == "ten_update_1"
    assert events[0].event_name == "ip.connection.updated"


def test_connection_update_configuration_fails_when_deactivated() -> None:
    connection = Connection.create(
        tenant_id="ten_update_2",
        app_id="acme_source",
        name="Deactivated Connection",
        auth_type=AuthType.API_KEY,
        public_config={"endpoint_url": "https://api.example.com"},
        encrypted_credentials=b"secret",
        endpoint_for_fingerprint="https://api.example.com",
    )
    connection.deactivate()

    res = connection.update_configuration(new_name="New Name")
    assert res.is_err is True
    assert isinstance(res.error, InvalidConnectionStateError)
    assert res.error.attempted_action == "update_configuration"


def test_connection_update_configuration_fails_when_name_blank() -> None:
    connection = Connection.create(
        tenant_id="ten_update_3",
        app_id="acme_source",
        name="Active Connection",
        auth_type=AuthType.API_KEY,
        public_config={"endpoint_url": "https://api.example.com"},
        encrypted_credentials=b"secret",
        endpoint_for_fingerprint="https://api.example.com",
    )

    res = connection.update_configuration(new_name="   ")
    assert res.is_err is True
    assert isinstance(res.error, InvalidConnectionConfigError)
    assert res.error.field_name == "name"


def test_connection_update_configuration_updates_fingerprint_when_endpoint_changes() -> None:
    connection = Connection.create(
        tenant_id="ten_update_4",
        app_id="acme_source",
        name="Active Connection",
        auth_type=AuthType.API_KEY,
        public_config={"endpoint_url": "https://api.example.com/v1"},
        encrypted_credentials=None,
        endpoint_for_fingerprint="https://api.example.com/v1",
    )
    res = connection.update_configuration(
        updated_public_config={"base_url": "https://base.example.com"},
    )
    assert res.is_ok is True
    assert connection.connection_fingerprint == compute_connection_fingerprint(
        "ten_update_4", "acme_source", "https://base.example.com"
    )
