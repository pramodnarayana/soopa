"""
structlog Adapter — implements ILogger using structlog.
Automatically injects the active OTel trace_id into every log line.
Swap this out by registering a different ILogger implementation in provider.py.
"""

import logging
import sys
from typing import Any

import structlog
from opentelemetry import trace

from ..ports.logger import ILogger


def _inject_trace_context(_logger: Any, _method: Any, event_dict: dict[str, Any]) -> dict[str, Any]:
    """structlog processor: injects OTel trace_id/span_id for log-trace correlation."""
    span = trace.get_current_span()
    if span and span.is_recording():
        ctx = span.get_span_context()
        event_dict["trace_id"] = format(ctx.trace_id, "032x")
        event_dict["span_id"] = format(ctx.span_id, "016x")
    return event_dict


def _configure_structlog(log_level: str) -> None:
    log_level_int = getattr(logging, log_level.upper(), logging.INFO)
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            _inject_trace_context,  # type: ignore
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.UnicodeDecoder(),
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(log_level_int),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(sys.stdout),
    )


class StructlogLogger(ILogger):
    """
    structlog implementation of ILogger.
    """

    def __init__(self, name: str, log_level: str = "INFO", _bound_logger: Any = None) -> None:
        if _bound_logger is None:
            _configure_structlog(log_level)
        self._logger = _bound_logger or structlog.get_logger(name)

    def debug(self, event: str, **kwargs: Any) -> None:
        self._logger.debug(event, **kwargs)

    def info(self, event: str, **kwargs: Any) -> None:
        self._logger.info(event, **kwargs)

    def warning(self, event: str, **kwargs: Any) -> None:
        self._logger.warning(event, **kwargs)

    def error(self, event: str, **kwargs: Any) -> None:
        self._logger.error(event, **kwargs)

    def bind(self, **kwargs: Any) -> "StructlogLogger":
        bound = self._logger.bind(**kwargs)
        return StructlogLogger(name="", _bound_logger=bound)
