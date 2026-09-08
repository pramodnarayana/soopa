from typing import Any

import structlog

from observability.adapters.outbound import structlog_logger
from observability.adapters.outbound.structlog_logger import StructlogLogger


def test_otlp_processor_preserves_each_lazy_logger_name(monkeypatch: Any) -> None:
    emitted_names: list[str] = []

    class FakeOtelLogger:
        def __init__(self, name: str) -> None:
            self.name = name

        def emit(self, _record: Any) -> None:
            emitted_names.append(self.name)

    monkeypatch.setattr(
        structlog_logger,
        "get_otel_logger",
        lambda name: FakeOtelLogger(name),
    )

    try:
        first_logger = StructlogLogger(name="first")
        second_logger = StructlogLogger(name="second")

        first_logger.info("first_event")
        second_logger.info("second_event")

        assert emitted_names == ["first", "second"]
    finally:
        structlog.reset_defaults()
