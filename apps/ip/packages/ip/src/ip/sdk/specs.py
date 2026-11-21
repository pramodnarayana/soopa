"""Strongly-typed declarative specifications for pure solution functions (Zero Decorators)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta

from orchestration.domain.definition import RetryPolicy


def retry_policy(
    max_attempts: int = 3,
    initial_backoff: timedelta = timedelta(seconds=1),
    backoff_multiplier: float = 2.0,
    max_backoff: timedelta = timedelta(minutes=5),
) -> RetryPolicy:
    """Helper factory constructing a strongly-typed RetryPolicy with exponential backoff."""
    return RetryPolicy(
        max_attempts=max_attempts,
        initial_backoff=initial_backoff,
        backoff_multiplier=backoff_multiplier,
        max_backoff=max_backoff,
    )


@dataclass(frozen=True, kw_only=True)
class ConnectorSpec:
    """Explicit specification binding a pure ingress connector function."""

    app: str
    entity: str
    fn: Callable[..., object]
    description: str = ""

    def __post_init__(self) -> None:
        if not self.app.strip():
            raise ValueError("ConnectorSpec requires non-empty app identifier")
        if not self.entity.strip():
            raise ValueError("ConnectorSpec requires non-empty entity identifier")


@dataclass(frozen=True, kw_only=True)
class TransformerSpec:
    """Explicit specification binding a pure canonical normalizer function."""

    app: str
    entity: str
    fn: Callable[..., object]
    description: str = ""

    def __post_init__(self) -> None:
        if not self.app.strip():
            raise ValueError("TransformerSpec requires non-empty app identifier")
        if not self.entity.strip():
            raise ValueError("TransformerSpec requires non-empty entity identifier")


@dataclass(frozen=True, kw_only=True)
class MutationSpec:
    """Explicit specification binding a pure downstream mutation builder function."""

    app: str
    entity: str
    operation: str
    fn: Callable[..., object]
    description: str = ""

    def __post_init__(self) -> None:
        if not self.app.strip():
            raise ValueError("MutationSpec requires non-empty app identifier")
        if not self.entity.strip():
            raise ValueError("MutationSpec requires non-empty entity identifier")
        if not self.operation.strip():
            raise ValueError("MutationSpec requires non-empty operation identifier")


@dataclass(frozen=True, kw_only=True)
class StitchSpec:
    """Explicit specification for a functional Stitch pipeline (Zero Decorators)."""

    id: str = ""
    trigger: str
    handler: Callable[..., object] | None = None
    name: str = ""
    description: str = ""
    connector: Callable[..., object] | None = None
    transformer: Callable[..., object] | None = None
    destination: Callable[..., object] | str | None = None
    concurrency_key: str | None = None
    retry: RetryPolicy | None = None
    step_timeout: timedelta | None = None
    workflow_sla: timedelta | None = None

    def __post_init__(self) -> None:
        effective_id = (self.id or self.name).strip()
        effective_name = (self.name or self.id).strip()
        object.__setattr__(self, "id", effective_id)
        object.__setattr__(self, "name", effective_name)

        if not self.id.strip():
            raise ValueError("StitchSpec requires non-empty id or name")
        if not self.trigger.strip():
            raise ValueError("StitchSpec requires non-empty trigger event key")
        if self.handler is None and self.transformer is None and self.connector is None:
            raise ValueError("StitchSpec requires either handler, transformer, or connector")


# Ubiquitous alias: Pipelines ARE Stitches
Stitch = StitchSpec

__all__ = [
    "ConnectorSpec",
    "MutationSpec",
    "Stitch",
    "StitchSpec",
    "TransformerSpec",
    "retry_policy",
]
