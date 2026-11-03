"""Security and Certificate Domain Models."""

from dataclasses import dataclass
from datetime import datetime

from edi.domain.security.enums import CertificateFormat, CertificateStatus, CertificateUsage


@dataclass(frozen=True)
class CertificateMetadata:
    """Pure domain metadata for a trading partner certificate."""

    subject: str
    issuer: str
    valid_from: datetime
    valid_to: datetime
    status: CertificateStatus = CertificateStatus.ACTIVE
    usage: CertificateUsage = CertificateUsage.BOTH
    format: CertificateFormat = CertificateFormat.PEM
    thumbprint: str | None = None
