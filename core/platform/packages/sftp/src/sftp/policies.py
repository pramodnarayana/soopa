"""Paramiko host-key policies for SFTP connections."""

from __future__ import annotations

import base64
import hashlib

import paramiko

from sftp.exceptions import SftpHostValidationError


def verify_host_key_fingerprint(
    hostname: str,
    key: paramiko.PKey,
    expected_fingerprint: str,
) -> tuple[bool, str | None]:
    """Verifies a server's public key against an expected SHA256 (base64) or MD5 (hex) fingerprint.

    Returns:
        tuple[bool, str | None]: (is_valid, error_message_if_invalid)
    """
    clean_expected = expected_fingerprint.strip()
    if clean_expected.lower().startswith("sha256:"):
        clean_expected = clean_expected[7:]

    sha256_digest = hashlib.sha256(key.asbytes()).digest()
    sha256_b64 = base64.b64encode(sha256_digest).decode("ascii").rstrip("=")
    clean_expected_b64 = clean_expected.rstrip("=")

    if sha256_b64 == clean_expected_b64:
        return True, None

    actual_md5 = key.get_fingerprint().hex().lower()
    clean_expected_md5 = clean_expected.replace(":", "").lower()
    if actual_md5 == clean_expected_md5:
        return True, None

    return (
        False,
        f"Host key mismatch for {hostname}: expected {expected_fingerprint.strip()}, got SHA256:{sha256_b64}",
    )


class FingerprintHostKeyPolicy(paramiko.MissingHostKeyPolicy):
    """Enforces that the remote SFTP server's host key matches the configured SHA256 or MD5 fingerprint."""

    def __init__(self, expected_fingerprint: str) -> None:
        self._expected_fingerprint = expected_fingerprint.strip()

    def missing_host_key(
        self, client: paramiko.SSHClient, hostname: str, key: paramiko.PKey
    ) -> None:
        is_valid, err_msg = verify_host_key_fingerprint(
            hostname=hostname,
            key=key,
            expected_fingerprint=self._expected_fingerprint,
        )
        if not is_valid and err_msg is not None:
            raise SftpHostValidationError(err_msg)


class DiagnosticHostKeyPolicy(paramiko.MissingHostKeyPolicy):
    """Silently accepts any host key during diagnostic connectivity test pings.

    This policy is strictly intended for diagnostic credential checks and ping tests.
    Production data transfers must use setup_host_key with RejectPolicy or FingerprintHostKeyPolicy.
    """

    def missing_host_key(
        self, client: paramiko.SSHClient, hostname: str, key: paramiko.PKey
    ) -> None:
        pass
