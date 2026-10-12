class OutboundPortError(Exception):
    """Base class for all outbound port exceptions."""


class PortConnectionError(OutboundPortError):
    """Raised when an outbound connection cannot be established (e.g., DNS failure, Connection Refused)."""


class PortTimeoutError(OutboundPortError):
    """Raised when an outbound connection times out."""


class PortAuthenticationError(OutboundPortError):
    """Raised when an outbound connection fails due to invalid credentials."""


class PortConfigurationError(OutboundPortError):
    """Raised when the provided configuration is invalid for the port."""
