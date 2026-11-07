"""Unit tests for CanonicalEntityRegistry and DefaultNormalizationErrorPolicy."""

from ip.engine.domain.normalization.policies import DefaultNormalizationErrorPolicy
from ip.engine.domain.normalization.registries import CanonicalEntityRegistry
from ip.engine.domain.normalization.transformation import CanonicalEntityDefinition


def test_canonical_entity_registry_resolves_registered_definitions() -> None:
    reg = CanonicalEntityRegistry()
    d1 = CanonicalEntityDefinition(canonical_type="canonical.record_alpha", schema_version=1)
    reg.register(d1)

    assert reg.get("canonical.record_alpha") == d1
    assert reg.get("unknown") is None


def test_default_normalization_error_policy_marks_mapper_exceptions_terminal() -> None:
    policy = DefaultNormalizationErrorPolicy()

    assert policy.is_terminal_failure(ValueError("Invalid int")) is True
    assert policy.is_terminal_failure(KeyError("missing_col")) is True
    assert policy.is_terminal_failure(TypeError("NoneType not subscriptable")) is True


def test_default_normalization_error_policy_marks_infrastructure_exceptions_transient() -> None:
    policy = DefaultNormalizationErrorPolicy()

    assert policy.is_terminal_failure(ConnectionError("DB connection refused")) is False
    assert policy.is_terminal_failure(TimeoutError("DB query timed out")) is False
    assert policy.is_terminal_failure(RuntimeError("Unexpected thread termination")) is False
