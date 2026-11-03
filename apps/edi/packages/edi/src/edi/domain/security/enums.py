"""Security and Certificate Domain Enumerations."""

from enum import StrEnum


class CertificateStatus(StrEnum):
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"


class CertificateUsage(StrEnum):
    SIGNING = "SIGNING"
    ENCRYPTION = "ENCRYPTION"
    BOTH = "BOTH"


class CertificateFormat(StrEnum):
    PEM = "PEM"
    DER = "DER"
    PKCS12 = "PKCS12"
