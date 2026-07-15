class ProvisioningError(Exception):
    """Base exception for provisioning errors."""

    pass


class PermanentProvisioningError(ProvisioningError):
    """An error that cannot be resolved by retrying (e.g., bad payload)."""

    pass


class TransientProvisioningError(ProvisioningError):
    """An error that might be resolved by retrying (e.g., network failure)."""

    pass
