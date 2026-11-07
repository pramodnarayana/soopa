"""Pure unit tests for SftpConnector spec, schema discovery, SSRF defense, and host key policy."""

from __future__ import annotations

import base64
import hashlib

import paramiko
import pytest
from ip.engine.adapters.outbound.connectors.sftp_connector import SftpConnector
from ip.engine.domain.exceptions import SftpConnectionError
from sftp.exceptions import SftpHostValidationError
from sftp.policies import FingerprintHostKeyPolicy


def test_sftp_connector_spec() -> None:
    connector = SftpConnector()
    spec = connector.spec()
    assert spec.app_id == "sftp"
    assert spec.display_name == "SFTP File Gateway"
    assert spec.category == "STORAGE"
    prop_names = [p.name for p in spec.properties]
    assert "host" in prop_names
    assert "port" in prop_names
    assert "username" in prop_names


@pytest.mark.asyncio
async def test_sftp_connector_blocks_loopback_when_allow_local_is_false() -> None:
    connector = SftpConnector(timeout_seconds=2.0, allow_local=False)
    result = await connector.check(
        public_config={"host": "127.0.0.1", "port": 2222},
        credentials={"username": "testuser", "password": "pass"},
    )
    assert result.success is False
    assert result.status == "FAILED"
    assert result.error_code == "SFTP_CONNECTION_FAILED"
    assert isinstance(result.error, SftpConnectionError)


@pytest.mark.asyncio
async def test_sftp_connector_discover() -> None:
    connector = SftpConnector()
    catalog = await connector.discover(
        connection_id="ip_conn_sftp_123",
        public_config={"host": "127.0.0.1", "port": 2222},
        credentials={"username": "testuser"},
    )
    assert catalog.connection_id == "ip_conn_sftp_123"
    assert len(catalog.streams) >= 1
    stream_names = [s.name for s in catalog.streams]
    assert "files" in stream_names


def test_sftp_host_key_fingerprint_verification_policy_with_real_rsa_key() -> None:
    rsa_key = paramiko.RSAKey.generate(2048)
    raw_key_bytes = rsa_key.asbytes()
    sha256_b64 = (
        base64.b64encode(hashlib.sha256(raw_key_bytes).digest()).decode("ascii").rstrip("=")
    )
    md5_colon_hex = ":".join(f"{b:02x}" for b in rsa_key.get_fingerprint())

    policy_sha256 = FingerprintHostKeyPolicy(expected_fingerprint=f"SHA256:{sha256_b64}")
    client = paramiko.SSHClient()

    # SHA256 match succeeds without raising
    policy_sha256.missing_host_key(client, "127.0.0.1", rsa_key)

    # SHA256 mismatch raises SftpHostValidationError
    mismatch_policy = FingerprintHostKeyPolicy(expected_fingerprint="SHA256:differentdigest")
    with pytest.raises(SftpHostValidationError, match="Host key mismatch"):
        mismatch_policy.missing_host_key(client, "127.0.0.1", rsa_key)

    # Legacy MD5 match succeeds
    md5_policy = FingerprintHostKeyPolicy(expected_fingerprint=md5_colon_hex)
    md5_policy.missing_host_key(client, "127.0.0.1", rsa_key)
