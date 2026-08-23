"""
Enterprise Cryptography Library.
Provides native PKCS7 and S/MIME operations.
"""

from .smime import decrypt_payload, encrypt_payload, sign_payload, verify_signature

__all__ = [
    "decrypt_payload",
    "encrypt_payload",
    "sign_payload",
    "verify_signature",
]
