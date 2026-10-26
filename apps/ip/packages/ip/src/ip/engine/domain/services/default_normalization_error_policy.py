"""Default NormalizationErrorPolicy strategy implementation."""

from __future__ import annotations


class DefaultNormalizationErrorPolicy:
    """Default error classification strategy adhering to the Strategy pattern without boolean flags."""

    def is_terminal_failure(self, error: Exception) -> bool:
        """Domain validation errors, schema failures, and ValueError/KeyErrors in mapping are terminal."""
        return isinstance(error, (ValueError, KeyError, TypeError))
