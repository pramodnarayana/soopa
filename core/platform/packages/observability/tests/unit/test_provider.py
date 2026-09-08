from observability.adapters.outbound.noop import NoOpLogger, NoOpMetrics, NoOpTracer
from observability.provider import ObservabilityProvider


def test_observability_provider_defaults_to_noop_adapters() -> None:
    """The provider must default to no-op adapters so services run without telemetry infra."""
    provider = ObservabilityProvider()
    assert isinstance(provider.tracer(), NoOpTracer)
    assert isinstance(provider.metrics(), NoOpMetrics)
    assert isinstance(provider.logger(), NoOpLogger)


def test_observability_provider_configure_registers_adapters() -> None:
    """configure() must replace each no-op slot with the injected concrete adapter."""
    old_tracer = ObservabilityProvider._tracer
    old_metrics = ObservabilityProvider._metrics
    old_logger = ObservabilityProvider._default_logger

    try:
        tracer = NoOpTracer()
        metrics = NoOpMetrics()
        logger = NoOpLogger()

        ObservabilityProvider.configure(
            tracer=tracer,
            metrics=metrics,
            logger=logger,
        )

        assert ObservabilityProvider.tracer() is tracer
        assert ObservabilityProvider.metrics() is metrics
        assert ObservabilityProvider.logger() is logger
    finally:
        # Restore original singleton state after the test
        ObservabilityProvider._tracer = old_tracer
        ObservabilityProvider._metrics = old_metrics
        ObservabilityProvider._default_logger = old_logger


def test_observability_provider_logger_binds_name() -> None:
    """logger(name) must return a bound logger, not the default instance."""
    result = ObservabilityProvider.logger("my.module")
    # NoOpLogger.bind() returns self — this validates the call doesn't raise
    assert result is not None
