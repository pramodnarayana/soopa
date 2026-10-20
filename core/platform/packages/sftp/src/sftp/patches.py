"""Algorithm compatibility patches for paramiko."""

from __future__ import annotations

import paramiko
import structlog
from cryptography.hazmat.primitives import hashes

logger = structlog.get_logger(__name__)

_LEGACY_PATCH_APPLIED = False


def apply_legacy_algorithm_support() -> None:
    """Restores ssh-rsa (SHA-1) algorithm support to the running paramiko instance.

    Paramiko 3.4+ removed ssh-rsa by default. Many enterprise trading partner
    and logistics SFTP servers still rely on ssh-rsa during key negotiation.
    This function is idempotent and safe to invoke multiple times.
    """
    global _LEGACY_PATCH_APPLIED
    if _LEGACY_PATCH_APPLIED:
        return

    if hasattr(paramiko.Transport, "_key_info") and "ssh-rsa" not in paramiko.Transport._key_info:
        paramiko.Transport._key_info["ssh-rsa"] = paramiko.RSAKey

    if hasattr(paramiko.RSAKey, "HASHES") and "ssh-rsa" not in paramiko.RSAKey.HASHES:
        paramiko.RSAKey.HASHES["ssh-rsa"] = hashes.SHA1

    if (
        hasattr(paramiko.Transport, "_preferred_keys")
        and "ssh-rsa" not in paramiko.Transport._preferred_keys
    ):
        paramiko.Transport._preferred_keys = (
            *paramiko.Transport._preferred_keys,
            "ssh-rsa",
        )

    if (
        hasattr(paramiko.Transport, "_preferred_pubkeys")
        and "ssh-rsa" not in paramiko.Transport._preferred_pubkeys
    ):
        paramiko.Transport._preferred_pubkeys = (
            *paramiko.Transport._preferred_pubkeys,
            "ssh-rsa",
        )

    _LEGACY_PATCH_APPLIED = True
    logger.debug("paramiko_legacy_rsa_support_applied")
