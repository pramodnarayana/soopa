"""Trading Partner Domain Enumerations."""

from enum import StrEnum


class PartnerStatus(StrEnum):
    """Provisioning lifecycle of a trading partner (AS2 or SFTP)."""

    PROVISIONING = "PROVISIONING"
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"
