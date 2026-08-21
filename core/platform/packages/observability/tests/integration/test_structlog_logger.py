import pytest
from opentelemetry import trace
from opentelemetry._logs import set_logger_provider
from opentelemetry.sdk._logs import LoggerProvider
from opentelemetry.sdk._logs.export import InMemoryLogExporter, SimpleLogRecordProcessor
from opentelemetry.sdk.resources import SERVICE_NAME, Resource
from opentelemetry.sdk.trace import TracerProvider

from observability.adapters.outbound.structlog_logger import StructlogLogger

# Global setup for log and trace providers to avoid overriding warnings
_memory_log_exporter = InMemoryLogExporter()
_resource = Resource(attributes={SERVICE_NAME: "test-logger"})
_logger_provider = LoggerProvider(resource=_resource)
_logger_provider.add_log_record_processor(SimpleLogRecordProcessor(_memory_log_exporter))
set_logger_provider(_logger_provider)

# Set tracer provider once at module level
if trace.get_tracer_provider().__class__.__name__ == "ProxyTracerProvider":
    trace.set_tracer_provider(TracerProvider())


@pytest.fixture
def memory_log_exporter():
    _memory_log_exporter.clear()
    return _memory_log_exporter


@pytest.fixture
def structlog_logger(memory_log_exporter):
    # Initialize the adapter
    logger = StructlogLogger(name="test-logger", log_level="INFO")
    return logger


def test_structlog_emits_to_otlp(structlog_logger, memory_log_exporter):
    # Emit a simple log without active trace
    structlog_logger.info("User created", user_id="123")

    exported_logs = memory_log_exporter.get_finished_logs()
    assert len(exported_logs) == 1

    log_record = exported_logs[0]

    # Check body and severity
    assert log_record.log_record.body == "User created"
    assert log_record.log_record.severity_text == "INFO"

    # Check attributes mapping
    assert log_record.log_record.attributes["user_id"] == "123"
    # Ensure redundant fields are stripped
    assert "event" not in log_record.log_record.attributes


def test_structlog_injects_trace_context(structlog_logger, memory_log_exporter):
    tracer = trace.get_tracer("test")

    with tracer.start_as_current_span("active-span") as span:
        structlog_logger.warning("Something looks off", retry=True)

    exported_logs = memory_log_exporter.get_finished_logs()
    assert len(exported_logs) == 1

    log_record = exported_logs[0]

    assert log_record.log_record.body == "Something looks off"
    assert log_record.log_record.severity_text == "WARNING"
    assert log_record.log_record.attributes["retry"] is True

    # Verify Trace ID and Span ID are properly injected into the log record
    span_ctx = span.get_span_context()
    assert log_record.log_record.trace_id == span_ctx.trace_id
    assert log_record.log_record.span_id == span_ctx.span_id
    assert log_record.log_record.trace_flags == span_ctx.trace_flags
