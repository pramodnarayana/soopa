"""
Monkey-patch for paramiko >= 3.4

Context
-------
Paramiko 3.4 removed the legacy ssh-rsa (SHA-1) algorithm from its internal
registries as part of a security hardening effort. However, many enterprise
SFTP servers deployed on older hardware or software still advertise only
ssh-rsa during key exchange negotiation.

This patch restores the algorithm mappings so paramiko can continue to
connect to those legacy trading partners.

When to remove this patch
-------------------------
When paramiko ships a first-class option to re-enable legacy algorithms
(e.g. a config flag), or when all trading partners have been migrated to
modern algorithms, this file can be deleted.

Upstream issue: https://github.com/paramiko/paramiko/issues/2277
"""

import paramiko
import structlog
from cryptography.hazmat.primitives import hashes

logger = structlog.get_logger(__name__)

_PATCH_APPLIED = False


def apply_legacy_algorithm_support() -> None:
    """
    Restore ssh-rsa (SHA-1) support to the running paramiko instance.
    This function is idempotent — calling it multiple times is safe.
    """
    global _PATCH_APPLIED
    if _PATCH_APPLIED:
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
            "ssh-dss",
        )

    if (
        hasattr(paramiko.Transport, "_preferred_pubkeys")
        and "ssh-rsa" not in paramiko.Transport._preferred_pubkeys
    ):
        paramiko.Transport._preferred_pubkeys = (
            *paramiko.Transport._preferred_pubkeys,
            "ssh-rsa",
            "ssh-dss",
        )

    _PATCH_APPLIED = True
    logger.debug("paramiko: legacy ssh-rsa algorithm support enabled")


# Apply automatically on import so callers can simply do:
#   import patches.paramiko
apply_legacy_algorithm_support()
