class ProvisioningError(Exception):
    """Base exception for provisioning errors."""


class PermanentProvisioningError(ProvisioningError):
    """An error that cannot be resolved by retrying (e.g., bad payload)."""


class TransientProvisioningError(ProvisioningError):
    """An error that might be resolved by retrying (e.g., network failure)."""
