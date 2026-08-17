from unittest.mock import MagicMock

from observability.provider import ObservabilityProvider


def test_observability_provider_initialization():
    # Capture existing state
    old_tracer = ObservabilityProvider._tracer
    old_metrics = ObservabilityProvider._metrics
    old_logger = ObservabilityProvider._logger

    try:
        mock_tracer = MagicMock()
        mock_metrics = MagicMock()
        mock_logger = MagicMock()

        ObservabilityProvider.configure(
            tracer=mock_tracer,
            metrics=mock_metrics,
            logger=mock_logger,
        )

        assert ObservabilityProvider.tracer() is mock_tracer
        assert ObservabilityProvider.metrics() is mock_metrics
        assert ObservabilityProvider.logger() is mock_logger
    finally:
        # Restore previous state
        ObservabilityProvider._tracer = old_tracer
        ObservabilityProvider._metrics = old_metrics
        ObservabilityProvider._logger = old_logger
