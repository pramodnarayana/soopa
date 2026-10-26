"""NormalizationErrorPolicyPort for classifying domain vs infrastructure failures."""

from __future__ import annotations

from typing import Protocol


class NormalizationErrorPolicyPort(Protocol):
    """Strategy interface defining how the Normalizer classifies errors without boolean control flags."""

    def is_terminal_failure(self, error: Exception) -> bool:
        """Return True if failure is terminal (e.g. data or mapping error) and should be ACKed after rejection."""
        ...
