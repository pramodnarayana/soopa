import pytest

from scheduler_worker.bootstrap.container import _validate_positive_int


def test_validate_positive_int_success():
    assert _validate_positive_int(5, "test_val") == 5


def test_validate_positive_int_failure():
    with pytest.raises(ValueError, match="test_val must be positive, got 0"):
        _validate_positive_int(0, "test_val")

    with pytest.raises(ValueError, match="test_val must be positive, got -5"):
        _validate_positive_int(-5, "test_val")
