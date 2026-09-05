"""
Canonical type aliases for the EDI bounded context.

These aliases give mypy a structurally sound type to check against for
domain-specific objects.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# AstNode — for the EDI transformer pipeline's Abstract Syntax Tree nodes.
# ---------------------------------------------------------------------------
from typing import TypeAlias

from seedwork.domain.types import JsonValue

JsonDict: TypeAlias = dict[str, JsonValue]

# EDI AST nodes are deeply recursive dicts. We alias it to JsonDict
# which provides a strict structural type representing valid JSON nodes.
AstNode: TypeAlias = JsonDict
