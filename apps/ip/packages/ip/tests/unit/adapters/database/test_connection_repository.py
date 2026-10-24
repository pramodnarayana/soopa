"""Pure zero-mock Data Mapper unit tests for SqlAlchemyConnectionRepository."""

from __future__ import annotations

from datetime import UTC, datetime

from ip.engine.adapters.outbound.database.control_plane.connection_repository import (
    SqlAlchemyConnectionRepository,
)
from ip.engine.adapters.outbound.database.models.control_plane import ConnectionRecord
from ip.engine.domain.models.connection import AuthType, Connection, ConnectionStatus


def test_connection_record_to_domain_model_mapping() -> None:
    now = datetime.now(UTC)
    record = ConnectionRecord(
        id="ip_conn_12345",
        tenant_id="ten_01",
        app_id="itron_mdm",
        name="Production Itron",
        auth_type="API_KEY",
        public_config={"endpoint_url": "https://api.example.com"},
        encrypted_credentials=b"kid:k1:ciphertext",
        key_encryption_version=2,
        connection_fingerprint="a" * 64,
        status="ACTIVE",
        token_expires_at=now,
        last_refreshed_at=now,
        last_error_code=None,
        last_error_message=None,
        created_at=now,
        updated_at=now,
        deactivated_at=None,
    )

    domain = SqlAlchemyConnectionRepository._to_domain_model(record)

    assert domain.id == "ip_conn_12345"
    assert domain.tenant_id == "ten_01"
    assert domain.app_id == "itron_mdm"
    assert domain.name == "Production Itron"
    assert domain.auth_type == AuthType.API_KEY
    assert domain.public_config == {"endpoint_url": "https://api.example.com"}
    assert domain.encrypted_credentials == b"kid:k1:ciphertext"
    assert domain.key_encryption_version == 2
    assert domain.status == ConnectionStatus.ACTIVE
    assert domain.token_expires_at == now.isoformat()


def test_connection_update_record_from_domain_mapping() -> None:
    now = datetime.now(UTC)
    record = ConnectionRecord(
        id="ip_conn_12345",
        tenant_id="ten_01",
        app_id="itron_mdm",
        name="Initial Name",
        auth_type="API_KEY",
        public_config={"endpoint_url": "https://old.example.com"},
        encrypted_credentials=b"old",
        key_encryption_version=1,
        connection_fingerprint="a" * 64,
        status="PENDING_AUTH",
        token_expires_at=None,
        last_refreshed_at=None,
        last_error_code=None,
        last_error_message=None,
        created_at=now,
        updated_at=now,
        deactivated_at=None,
    )

    domain = Connection.create(
        tenant_id="ten_01",
        app_id="itron_mdm",
        name="Updated Name",
        auth_type=AuthType.OAUTH2,
        public_config={"endpoint_url": "https://new.example.com"},
        encrypted_credentials=b"new_encrypted",
        endpoint_for_fingerprint="https://new.example.com",
    )
    domain.key_encryption_version = 3
    domain.token_expires_at = now.isoformat()
    domain.activate()

    SqlAlchemyConnectionRepository._update_record_from_domain(record, domain)

    assert record.name == "Updated Name"
    assert record.auth_type == "OAUTH2"
    assert record.public_config == {"endpoint_url": "https://new.example.com"}
    assert record.encrypted_credentials == b"new_encrypted"
    assert record.key_encryption_version == 3
    assert record.status == "ACTIVE"
    assert record.token_expires_at == now
