"""
ILogger Port — Abstract interface for structured logging.
Business logic depends ONLY on this interface.
The concrete implementation (structlog, loguru, stdlib, etc.) is injected at startup.
"""

from abc import ABC, abstractmethod
from typing import Any


class ILogger(ABC):
    """
    Port for structured logging.
    All log methods accept arbitrary keyword arguments as structured fields.
    """

    @abstractmethod
    def debug(self, event: str, **kwargs: Any) -> None: ...

    @abstractmethod
    def info(self, event: str, **kwargs: Any) -> None: ...

    @abstractmethod
    def warning(self, event: str, **kwargs: Any) -> None: ...

    @abstractmethod
    def error(self, event: str, **kwargs: Any) -> None: ...

    @abstractmethod
    def bind(self, **kwargs: Any) -> "ILogger":
        """
        Returns a new logger with the given fields permanently bound.
        Useful for injecting request-scoped context (e.g., tenant_id, message_id).

        Usage:
            request_logger = logger.bind(message_id=msg.message_id, tenant_id=1)
            request_logger.info("as2_decrypt_started")
            request_logger.info("as2_decrypt_finished")
        """
        ...
