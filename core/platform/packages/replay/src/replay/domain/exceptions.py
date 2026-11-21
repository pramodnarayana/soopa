"""Universal replay domain exceptions."""

from __future__ import annotations


class ReplayError(Exception):
    """Base exception for replay errors."""


class UnsupportedReplayStageError(ReplayError):
    """Raised when an app has no processor registered for the requested stage."""

    def __init__(self, stage: str) -> None:
        super().__init__(f"No replay processor registered for stage: {stage}")
        self.stage = stage


class ReplayIdempotencyConflictError(ReplayError):
    """Raised when an identical idempotency token is re-submitted with differing payload."""
