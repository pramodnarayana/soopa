"""AS2 Protocol Domain Enumerations."""

from enum import StrEnum


class Disposition(StrEnum):
    """AS2 MDN disposition strings as defined in RFC 4130."""

    PROCESSED = "automatic-action/MDN-sent-automatically; processed"
    DECRYPTION_FAILED = "automatic-action/MDN-sent-automatically; failed/decryption-failed"
    AUTHENTICATION_FAILED = "automatic-action/MDN-sent-automatically; failed/authentication-failed"
    INSUFFICIENT_SECURITY = (
        "automatic-action/MDN-sent-automatically; failed/insufficient-message-security"
    )


class As2SignatureAlgorithm(StrEnum):
    """Cryptographic hashing algorithms used for S/MIME signatures."""

    SHA1 = "sha1"
    SHA256 = "sha256"
    SHA384 = "sha384"
    SHA512 = "sha512"


class As2EncryptionAlgorithm(StrEnum):
    """Cryptographic ciphers used for S/MIME payload encryption."""

    AES128 = "aes128"
    AES256 = "aes256"
    DES3 = "3des"


class EncryptionAlgorithm(StrEnum):
    """Symmetric encryption algorithm used for AS2 message encryption."""

    AES128 = "AES128"
    AES256 = "AES256"
    RC2 = "RC2"
    DES3 = "3DES"


class SignatureAlgorithm(StrEnum):
    """Digest/hash algorithm used for AS2 message signing."""

    SHA1 = "SHA1"
    SHA256 = "SHA256"
    SHA384 = "SHA384"
    SHA512 = "SHA512"
    MD5 = "MD5"


class MDNType(StrEnum):
    """AS2 MDN (Message Disposition Notification) delivery mode."""

    SYNC = "SYNC"
    ASYNC = "ASYNC"


class CertificateRotationAction(StrEnum):
    """Supported certificate rotation modes for AS2 Trading Partners."""

    GENERATE = "generate"
    UPLOAD = "upload"
