class ConsumerTransientError(Exception):
    """Raised when a consumer encounters a temporary infrastructure error that should be retried."""


class ConsumerTerminalError(Exception):
    """Raised when a consumer encounters a fatal infrastructure error (e.g. queue doesn't exist) that cannot be retried."""
