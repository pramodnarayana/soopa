import pytest
from infra_seedwork import (
    LogRetentionPolicy,
    validate_log_retention,
)


def test_log_retention_policies_defined() -> None:
    expected_policies = {
        "EPHEMERAL": 1,
        "NON_PROD": 3,
        "WEEKLY": 7,
        "BIWEEKLY": 14,
        "STANDARD": 30,
        "COMPLIANCE": 90,
        "ANNUAL": 365,
    }
    for name, value in expected_policies.items():
        assert getattr(LogRetentionPolicy, name).value == value
        assert validate_log_retention(value) == value


def test_validate_log_retention_valid_tiers() -> None:
    for tier in LogRetentionPolicy:
        assert validate_log_retention(tier.value) == tier.value


def test_validate_log_retention_invalid_rejected() -> None:
    with pytest.raises(ValueError, match="is not an approved enterprise policy tier") as exc_info:
        validate_log_retention(2)
    assert "Approved policies" in str(exc_info.value)

    with pytest.raises(ValueError, match="is not an approved enterprise policy tier"):
        validate_log_retention(10)

    with pytest.raises(ValueError, match="is not an approved enterprise policy tier"):
        validate_log_retention(545)

    with pytest.raises(ValueError, match="is not an approved enterprise policy tier"):
        validate_log_retention(-1)
