"""Normalization, GEM, and canonical transformation enumerations."""

from enum import StrEnum


class TransformationMode(StrEnum):
    """Execution mode of a stream transformation."""

    ACTIVE = "ACTIVE"
    SHADOW = "SHADOW"
    DISABLED = "DISABLED"


class NormalizationOutcome(StrEnum):
    """Result of normalizing an L2 replica snapshot into canonical domain records."""

    NORMALIZED = "NORMALIZED"
    REJECTED = "REJECTED"
    SKIPPED_STALE = "SKIPPED_STALE"
    TOMBSTONED = "TOMBSTONED"
    SKIPPED_NO_TRANSFORMATION = "SKIPPED_NO_TRANSFORMATION"


class RuleSeverity(StrEnum):
    """Action severity for a canonical entity quality validation rule."""

    REJECT = "REJECT"
    FLAG = "FLAG"


class NormalizationRejectionReason(StrEnum):
    """Typed failure code for a canonical transformation or validation rejection."""

    MISSING_REQUIRED_FIELD = "MISSING_REQUIRED_FIELD"
    SCHEMA_VALIDATION_FAILED = "SCHEMA_VALIDATION_FAILED"
    QUALITY_RULE_REJECTED = "QUALITY_RULE_REJECTED"
    TRANSFORMER_ERROR = "TRANSFORMER_ERROR"
    UNRESOLVED_REFERENCE = "UNRESOLVED_REFERENCE"
    MISSING_TRANSFORMATION = "MISSING_TRANSFORMATION"


class PendingReferenceStatus(StrEnum):
    """Resolution status of a late-arriving canonical source reference."""

    PENDING = "PENDING"
    RESOLVED = "RESOLVED"


class CanonicalAction(StrEnum):
    """Mutation action applied to a canonical domain record."""

    UPSERT = "UPSERT"
    TOMBSTONE = "TOMBSTONE"
