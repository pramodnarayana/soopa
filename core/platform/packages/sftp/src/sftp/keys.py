"""SSH key parsing and host-key verification management."""

from __future__ import annotations

import base64
import io

import paramiko
import structlog

from sftp.exceptions import SftpAuthenticationError

logger = structlog.get_logger(__name__)


def parse_client_private_key(
    client_key_string: str,
    password: str | None = None,
) -> paramiko.PKey:
    """Parses a private key string across RSA, ECDSA, and Ed25519 key formats."""
    key_io = io.StringIO(client_key_string.strip())
    try:
        return paramiko.RSAKey.from_private_key(key_io, password=password)
    except (paramiko.SSHException, ValueError):
        key_io.seek(0)
        try:
            return paramiko.ECDSAKey.from_private_key(key_io, password=password)
        except (paramiko.SSHException, ValueError):
            key_io.seek(0)
            try:
                return paramiko.Ed25519Key.from_private_key(key_io, password=password)
            except (paramiko.SSHException, ValueError) as exc:
                logger.error("sftp_private_key_parse_failed", error=str(exc))
                raise SftpAuthenticationError(
                    f"Failed to parse private key (unsupported format or bad passphrase): {exc}"
                ) from exc


def setup_host_key(
    client: paramiko.SSHClient,
    host: str,
    port: int,
    host_key_string: str | None,
) -> None:
    """Configures strict host-key verification on an SSHClient instance."""
    if not host_key_string:
        logger.info(
            "sftp_missing_host_key_autoadd",
            host=host,
            port=port,
            message="No host key provided. Using AutoAddPolicy.",
        )
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        return

    valid_lines = [
        line.strip()
        for line in host_key_string.strip().splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    if not valid_lines:
        raise ValueError(f"No valid host key entry found in: '{host_key_string}'")

    key_line = valid_lines[0]
    parts = key_line.split()
    if len(parts) < 2:
        raise ValueError(f"Malformed host_key_string: '{host_key_string}'")

    key_type_idx = -1
    for idx, token in enumerate(parts):
        if token.startswith(("ssh-", "ecdsa-")):
            key_type_idx = idx
            break

    if key_type_idx != -1 and key_type_idx + 1 < len(parts):
        key_type = parts[key_type_idx]
        raw_b64 = parts[key_type_idx + 1]
    else:
        key_type = parts[0]
        raw_b64 = parts[1]

    key_data = base64.b64decode(raw_b64)
    if "ed25519" in key_type.lower():
        parsed_key: paramiko.PKey = paramiko.Ed25519Key(data=key_data)
    elif "ecdsa" in key_type.lower():
        parsed_key = paramiko.ECDSAKey(data=key_data)
    else:
        parsed_key = paramiko.RSAKey(data=key_data)

    host_identifier = f"[{host}]:{port}" if port != 22 else host
    client.get_host_keys().add(hostname=host_identifier, keytype=key_type, key=parsed_key)
    client.set_missing_host_key_policy(paramiko.RejectPolicy())
