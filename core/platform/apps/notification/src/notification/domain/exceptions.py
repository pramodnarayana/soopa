class DomainError(Exception):
    """Base class for all domain errors."""


class NotificationDispatchError(DomainError):
    """Raised when a notification fails to dispatch or render."""
