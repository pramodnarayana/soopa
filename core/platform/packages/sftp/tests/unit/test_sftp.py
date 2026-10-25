"""Unit tests for centralized platform SFTP package."""

from __future__ import annotations

from datetime import UTC, datetime

import paramiko
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from sftp.client import (
    SftpConnectionConfig,
    SftpFileMetadata,
)
from sftp.client import (
    test_sftp_connection as run_test_sftp_connection,
)
from sftp.exceptions import (
    SftpAuthenticationError,
    SftpHostValidationError,
)
from sftp.keys import parse_client_private_key, setup_host_key
from sftp.patches import apply_legacy_algorithm_support
from sftp.policies import DiagnosticHostKeyPolicy
from sftp.security import resolve_and_validate_host


def _generate_rsa_private_key_pem() -> str:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption(),
    )
    return pem.decode("utf-8")


def test_resolve_and_validate_host_empty_raises() -> None:
    with pytest.raises(SftpHostValidationError, match="Host cannot be empty"):
        resolve_and_validate_host("")


def test_resolve_and_validate_host_ssrf_blocked() -> None:
    # 127.0.0.1 is loopback and not globally routable
    with pytest.raises(SftpHostValidationError, match="SSRF blocked"):
        resolve_and_validate_host("127.0.0.1", allow_local=False)


def test_resolve_and_validate_host_allow_local() -> None:
    ips = resolve_and_validate_host("127.0.0.1", allow_local=True)
    assert "127.0.0.1" in ips


def test_parse_client_private_key_rsa() -> None:
    pem = _generate_rsa_private_key_pem()
    pkey = parse_client_private_key(pem)
    assert isinstance(pkey, paramiko.RSAKey)


def test_parse_client_private_key_invalid_raises() -> None:
    with pytest.raises(SftpAuthenticationError, match="Failed to parse private key"):
        parse_client_private_key("invalid-private-key-data")


def test_setup_host_key_autoadd_policy_when_none() -> None:
    client = paramiko.SSHClient()
    setup_host_key(client, "sftp.example.com", 22, host_key_string=None)
    assert len(client.get_host_keys()) == 0
    assert isinstance(client._policy, paramiko.AutoAddPolicy)


def test_setup_host_key_reject_policy_when_provided() -> None:
    client = paramiko.SSHClient()
    rsa_key = paramiko.RSAKey.generate(2048)
    host_key_str = f"ssh-rsa {rsa_key.get_base64()} test@example.com"
    setup_host_key(client, "sftp.example.com", 22, host_key_string=host_key_str)
    assert client.get_host_keys().lookup("sftp.example.com") is not None
    assert isinstance(client._policy, paramiko.RejectPolicy)


def test_diagnostic_host_key_policy() -> None:
    policy = DiagnosticHostKeyPolicy()
    client = paramiko.SSHClient()
    # Should silently pass without raising
    policy.missing_host_key(client, "sftp.example.com", paramiko.RSAKey.generate(2048))


def test_apply_legacy_algorithm_support_idempotency() -> None:
    apply_legacy_algorithm_support()
    apply_legacy_algorithm_support()
    if hasattr(paramiko.Transport, "_preferred_keys"):
        assert "ssh-rsa" in paramiko.Transport._preferred_keys


def test_sftp_file_metadata() -> None:
    now = datetime.now(UTC)
    meta = SftpFileMetadata(filename="orders.edi", size_bytes=2048, modified_at=now)
    assert meta.filename == "orders.edi"
    assert meta.size_bytes == 2048
    assert meta.modified_at == now


@pytest.mark.asyncio
async def test_test_sftp_connection_failure() -> None:
    config = SftpConnectionConfig(
        host="127.0.0.1",
        port=2222,
        username="nonexistent",
        password="bad",
        allow_local=True,
        timeout_seconds=0.1,
    )
    success, error = await run_test_sftp_connection(config)
    assert success is False
    assert error is not None
