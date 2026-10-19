"""Domain exceptions for the Integration Platform bounded context."""


class IpDomainException(Exception):
    """Base exception for all Integration Platform domain errors."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class InvalidConnectionStateException(IpDomainException):
    """Raised when an operation is invalid for the current connection state."""


class DuplicateConnectionFingerprintException(IpDomainException):
    """Raised when an active connection already exists with the same external fingerprint."""


class AuthenticationFailedException(IpDomainException):
    """Raised when credential verification or connection check fails."""


class ConnectorNotFoundException(IpDomainException):
    """Raised when an unknown app/provider ID is requested."""


class CatalogDiscoveryFailedException(IpDomainException):
    """Raised when schema/stream discovery fails against the source system."""


class ConnectionNotFoundException(IpDomainException):
    """Raised when an operation references a connection that does not exist."""

    def __init__(self, connection_id: str) -> None:
        super().__init__(f"Connection '{connection_id}' was not found.")
        self.connection_id = connection_id


class StreamNotFoundException(IpDomainException):
    """Raised when a stream is requested that does not exist in the connection's catalog."""
