"""Enumerations for the declarative field mapping domain."""

from __future__ import annotations

from enum import StrEnum


class MappingRuleType(StrEnum):
    """Supported rule types for translating fields from canonical models to wire contracts."""

    DIRECT = "DIRECT"
    CONSTANT = "CONSTANT"
    EXPRESSION = "EXPRESSION"
    IGNORE = "IGNORE"
