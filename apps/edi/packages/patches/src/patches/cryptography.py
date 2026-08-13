"""
Monkey-patch for cryptography

Context
-------
The `cryptography` library explicitly restricts PKCS#7 / S/MIME EnvelopedData
encryption to AES128 and AES256 due to security deprecations of 3DES.
However, in B2B AS2 integrations, 3DES remains a mandatory legacy requirement
for interoperability with older Remote Trading Partners.

This patch bypasses the Python-level type check inside `set_content_encryption_algorithm`.
The underlying Rust/C bindings actually still support TripleDES, so removing the
Python type restriction is all that's required to restore functionality.

Upstream logic: https://github.com/pyca/cryptography/blob/main/src/cryptography/hazmat/primitives/serialization/pkcs7.py
"""

import structlog
from cryptography.hazmat.primitives.serialization import pkcs7

logger = structlog.get_logger(__name__)

_PATCH_APPLIED = False


def apply_legacy_3des_support() -> None:
    """
    Restore 3DES support to PKCS7EnvelopeBuilder.
    This function is idempotent — calling it multiple times is safe.
    """
    global _PATCH_APPLIED
    if _PATCH_APPLIED:
        return

    def _patched_set_content_encryption_algorithm(self, algorithm):  # type: ignore
        # We completely bypass the strict type check to allow TripleDES (and others)
        # to pass down to the native Rust backend, which still supports it.
        self._algorithm = algorithm
        return self

    pkcs7.PKCS7EnvelopeBuilder.set_content_encryption_algorithm = (  # type: ignore
        _patched_set_content_encryption_algorithm
    )

    _PATCH_APPLIED = True
    logger.debug("cryptography: legacy 3DES PKCS7 envelope support enabled")


# Apply automatically on import so callers can simply do:
#   import patches.cryptography
apply_legacy_3des_support()
