"""
structlog Adapter — implements ILogger using structlog.
Automatically injects the active OTel trace_id into every log line.
Swap this out by registering a different ILogger implementation in provider.py.
"""

import sys
import time
from collections.abc import MutableMapping
from typing import Any

import structlog
from opentelemetry import trace
from opentelemetry._logs import LogRecord
from opentelemetry._logs import get_logger as get_otel_logger
from opentelemetry._logs.severity import SeverityNumber

from ..ports.logger import ILogger


def _inject_trace_context(
    _logger: Any, _method: Any, event_dict: MutableMapping[str, Any]
) -> MutableMapping[str, Any]:
    """structlog processor: injects OTel trace_id/span_id for log-trace correlation."""
    span = trace.get_current_span()
    if span and span.is_recording():
        ctx = span.get_span_context()
        event_dict["trace_id"] = format(ctx.trace_id, "032x")
        event_dict["span_id"] = format(ctx.span_id, "016x")
    return event_dict


def _otlp_log_processor(
    _logger: Any, method_name: str, event_dict: MutableMapping[str, Any]
) -> MutableMapping[str, Any]:
    """structlog processor: emits the log to the global OTLP logger provider."""
    otel_logger = get_otel_logger("edi-structlog")

    level_map = {
        "debug": SeverityNumber.DEBUG,
        "info": SeverityNumber.INFO,
        "warning": SeverityNumber.WARN,
        "error": SeverityNumber.ERROR,
        "exception": SeverityNumber.ERROR,
        "critical": SeverityNumber.FATAL,
    }
    level = level_map.get(method_name, SeverityNumber.INFO)

    span_ctx = trace.get_current_span().get_span_context()

    # Exclude basic fields from attributes
    attributes = {
        k: v
        for k, v in event_dict.items()
        if k not in ["event", "trace_id", "span_id", "level", "timestamp"]
    }

    otel_logger.emit(
        LogRecord(
            timestamp=time.time_ns(),
            observed_timestamp=time.time_ns(),
            trace_id=span_ctx.trace_id if span_ctx.is_valid else None,
            span_id=span_ctx.span_id if span_ctx.is_valid else None,
            trace_flags=span_ctx.trace_flags if span_ctx.is_valid else None,
            severity_text=method_name.upper(),
            severity_number=level,
            body=str(event_dict.get("event", "")),
            attributes=attributes,
        )
    )
    return event_dict


def _configure_structlog(log_level: str) -> None:
    # Map string log levels to structlog filtering int values (same as standard logging ints)
    level_filter_map = {
        "DEBUG": 10,
        "INFO": 20,
        "WARNING": 30,
        "ERROR": 40,
        "CRITICAL": 50,
    }
    log_level_int = level_filter_map.get(log_level.upper(), 20)
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            _inject_trace_context,
            _otlp_log_processor,  # push to OTel BEFORE stringification
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.UnicodeDecoder(),
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(log_level_int),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(sys.stdout),
    )


from opentelemetry._logs import set_logger_provider
from opentelemetry.exporter.otlp.proto.grpc._log_exporter import OTLPLogExporter
from opentelemetry.sdk._logs import LoggerProvider
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
from opentelemetry.sdk.resources import SERVICE_NAME, Resource


class StructlogLogger(ILogger):
    """
    structlog implementation of ILogger.
    """

    def __init__(
        self,
        name: str,
        log_level: str = "INFO",
        service_name: str | None = None,
        otlp_endpoint: str | None = None,
        _bound_logger: Any = None,
    ) -> None:
        if _bound_logger is None:
            if service_name:
                resource = Resource(attributes={SERVICE_NAME: service_name})
                logger_provider = LoggerProvider(resource=resource)
                if otlp_endpoint:
                    log_exporter = OTLPLogExporter(endpoint=otlp_endpoint, insecure=True)
                    logger_provider.add_log_record_processor(BatchLogRecordProcessor(log_exporter))
                set_logger_provider(logger_provider)
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

    def exception(self, event: str, **kwargs: Any) -> None:
        self._logger.exception(event, **kwargs)

    def bind(self, **kwargs: Any) -> "StructlogLogger":
        bound = self._logger.bind(**kwargs)
        return StructlogLogger(name="", _bound_logger=bound)
