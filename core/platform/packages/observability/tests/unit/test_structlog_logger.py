import logging  # noqa: TID251 - Unit test validating stdlib logging interception
import sys
import threading
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


def test_intercept_handler_routes_std_logging_to_structlog(monkeypatch: Any) -> None:
    events_captured: list[dict[str, Any]] = []

    def fake_logger_call(self: Any, event: str, **kwargs: Any) -> None:
        events_captured.append({"event": event, **kwargs})

    fake_structlog_logger = type(
        "FakeLogger", (), {"error": fake_logger_call, "info": fake_logger_call}
    )()

    monkeypatch.setattr(structlog, "get_logger", lambda _name: fake_structlog_logger)

    handler = structlog_logger.InterceptHandler()
    logger = logging.getLogger("test_uvicorn_error")
    logger.handlers = [handler]
    logger.propagate = False

    try:
        raise ValueError("synthetic database failure")
    except ValueError:
        logger.exception("an unhandled error occurred")

    assert len(events_captured) == 1
    assert events_captured[0]["event"] == "an unhandled error occurred"
    assert events_captured[0]["exc_info"] is True or events_captured[0]["exc_info"] is not None


def test_uncaught_exception_handler_routes_to_structlog(monkeypatch: Any) -> None:
    events_captured: list[dict[str, Any]] = []

    def fake_critical_call(self: Any, event: str, **kwargs: Any) -> None:
        events_captured.append({"event": event, **kwargs})

    fake_structlog_logger = type("FakeLogger", (), {"critical": fake_critical_call})()
    monkeypatch.setattr(structlog, "get_logger", lambda _name: fake_structlog_logger)

    try:
        raise RuntimeError("unhandled process crash")
    except RuntimeError as exc:
        structlog_logger._handle_uncaught_exception(RuntimeError, exc, exc.__traceback__)

    assert len(events_captured) == 1
    assert events_captured[0]["event"] == "uncaught_exception"
    assert events_captured[0]["exc_info"] is not None


def test_uncaught_thread_exception_handler_routes_to_structlog(monkeypatch: Any) -> None:
    events_captured: list[dict[str, Any]] = []

    def fake_critical_call(self: Any, event: str, **kwargs: Any) -> None:
        events_captured.append({"event": event, **kwargs})

    fake_structlog_logger = type("FakeLogger", (), {"critical": fake_critical_call})()
    monkeypatch.setattr(structlog, "get_logger", lambda _name: fake_structlog_logger)

    fake_thread = threading.Thread(name="worker_daemon_thread")
    try:
        raise ValueError("background thread crashed")
    except ValueError as exc:
        args = threading.ExceptHookArgs((ValueError, exc, exc.__traceback__, fake_thread))
        structlog_logger._handle_uncaught_thread_exception(args)

    assert len(events_captured) == 1
    assert events_captured[0]["event"] == "uncaught_thread_exception"
    assert events_captured[0]["thread_name"] == "worker_daemon_thread"
    assert events_captured[0]["exc_info"] is not None


def test_uncaught_keyboard_interrupt_delegates_to_sys_excepthook(monkeypatch: Any) -> None:
    delegated: list[bool] = []

    def fake_sys_excepthook(
        exc_type: type[BaseException],
        exc_value: BaseException,
        exc_tb: Any,
    ) -> None:
        delegated.append(True)

    monkeypatch.setattr(sys, "__excepthook__", fake_sys_excepthook)

    exc = KeyboardInterrupt()
    structlog_logger._handle_uncaught_exception(KeyboardInterrupt, exc, None)

    assert delegated == [True]
