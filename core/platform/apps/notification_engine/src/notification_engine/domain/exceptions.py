class DomainError(Exception):
    """Base class for all domain errors."""

    pass


class NotificationDispatchError(DomainError):
    """Raised when a notification fails to dispatch or render."""

    pass
