"""Centralized enterprise SFTP and SSH infrastructure client package."""

from __future__ import annotations

from sftp.client import (
    SftpConnectionConfig,
    SftpFileMetadata,
    SftpSession,
    create_ssh_client,
    test_sftp_connection,
)
from sftp.exceptions import (
    SftpAuthenticationError,
    SftpConnectionError,
    SftpError,
    SftpHostValidationError,
    SftpOperationError,
)
from sftp.keys import parse_client_private_key, setup_host_key
from sftp.patches import apply_legacy_algorithm_support
from sftp.policies import (
    DiagnosticHostKeyPolicy,
    FingerprintHostKeyPolicy,
    verify_host_key_fingerprint,
)
from sftp.security import resolve_and_validate_host

__all__ = [
    "DiagnosticHostKeyPolicy",
    "FingerprintHostKeyPolicy",
    "SftpAuthenticationError",
    "SftpConnectionConfig",
    "SftpConnectionError",
    "SftpError",
    "SftpFileMetadata",
    "SftpHostValidationError",
    "SftpOperationError",
    "SftpSession",
    "apply_legacy_algorithm_support",
    "create_ssh_client",
    "parse_client_private_key",
    "resolve_and_validate_host",
    "setup_host_key",
    "test_sftp_connection",
    "verify_host_key_fingerprint",
]
