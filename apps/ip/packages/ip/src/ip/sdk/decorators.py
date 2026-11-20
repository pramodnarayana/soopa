"""DEPRECATED: Decorator-based registration has been retired in favor of pure functional Specs.

All solution functions must be registered via explicit immutable specification objects:
- `ConnectorSpec` (for ingress connectors)
- `TransformerSpec` (for canonical normalizers)
- `MutationSpec` (for downstream mutations)
- `StitchSpec` (for functional Stitch workflows with StitchContext)

Decorators have been removed to prevent import-time side-effects, global singleton state,
and framework coupling.
"""

from __future__ import annotations

from typing import NoReturn


def _raise_deprecated(decorator_name: str) -> NoReturn:
    raise RuntimeError(
        f"The @{decorator_name} decorator has been permanently removed as part of the "
        "enterprise pure functional architecture. Use explicit immutable Spec objects "
        "(e.g., StitchSpec, ConnectorSpec, TransformerSpec, MutationSpec) and pure functions "
        "with typed StitchContext instead."
    )


def connector(*args: object, **kwargs: object) -> NoReturn:
    _raise_deprecated("connector")


def transformer(*args: object, **kwargs: object) -> NoReturn:
    _raise_deprecated("transformer")


def mutation(*args: object, **kwargs: object) -> NoReturn:
    _raise_deprecated("mutation")


def stitch(*args: object, **kwargs: object) -> NoReturn:
    _raise_deprecated("stitch")


__all__ = [
    "connector",
    "mutation",
    "stitch",
    "transformer",
]
