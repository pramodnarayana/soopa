"""Unit tests for ucp.domain.services.slug_service.

These tests cover the pure generate_slug(), try_generate_slug(), and generate_unique_slug() functions.
No fakes are needed — pure function, zero external dependencies.
"""

import pytest

from ucp.domain.exceptions import InvalidTenantNameError, UcpErrorCode
from ucp.domain.services.slug_service import (
    generate_slug,
    generate_unique_slug,
    try_generate_slug,
)


class TestGenerateSlug:
    """Tests for generate_slug() — pure ASCII slug generation."""

    def test_basic_two_word_name(self) -> None:
        assert generate_slug("Acme Corp") == "acme-corp"

    def test_leading_and_trailing_spaces(self) -> None:
        assert generate_slug("  Hello World  ") == "hello-world"

    def test_accented_latin_characters(self) -> None:
        assert generate_slug("Café & Co.") == "cafe-co"

    def test_multiple_spaces_collapsed(self) -> None:
        assert generate_slug("Acme   Corp") == "acme-corp"

    def test_multiple_hyphens_collapsed(self) -> None:
        assert generate_slug("hello--world") == "hello-world"

    def test_special_characters_stripped(self) -> None:
        assert generate_slug("A@B#C!") == "abc"

    def test_numbers_preserved(self) -> None:
        assert generate_slug("Tenant 42") == "tenant-42"

    def test_all_lowercase(self) -> None:
        assert generate_slug("UPPERCASE NAME") == "uppercase-name"

    def test_mixed_case_and_symbols(self) -> None:
        assert generate_slug("Hello, World!") == "hello-world"

    def test_single_word(self) -> None:
        assert generate_slug("Platform") == "platform"

    def test_unicode_ae_ligature(self) -> None:
        assert generate_slug("Ærø") == "aer"

    def test_empty_string_raises(self) -> None:
        with pytest.raises(InvalidTenantNameError):
            generate_slug("")

    def test_only_special_chars_raises(self) -> None:
        with pytest.raises(InvalidTenantNameError):
            generate_slug("!!!")

    def test_only_spaces_raises(self) -> None:
        with pytest.raises(InvalidTenantNameError):
            generate_slug("   ")


class TestTryGenerateSlug:
    """Tests for try_generate_slug() — Result-based slug generation."""

    def test_valid_name_returns_ok(self) -> None:
        res = try_generate_slug("Acme Corp")
        assert res.is_ok
        assert res.unwrap() == "acme-corp"

    def test_invalid_name_returns_typed_error(self) -> None:
        res = try_generate_slug("!!!")
        assert res.is_err
        assert res.unwrap_err().code == UcpErrorCode.INVALID_TENANT_NAME


class TestGenerateUniqueSlug:
    """Tests for generate_unique_slug() — collision-free slug allocation."""

    def test_no_collision_returns_base(self) -> None:
        assert generate_unique_slug("Acme Corp", set()) == "acme-corp"

    def test_first_collision_appends_2(self) -> None:
        assert generate_unique_slug("Acme Corp", {"acme-corp"}) == "acme-corp-2"

    def test_multiple_collisions_increments(self) -> None:
        existing = {"acme-corp", "acme-corp-2", "acme-corp-3"}
        assert generate_unique_slug("Acme Corp", existing) == "acme-corp-4"

    def test_non_contiguous_gap_skipped(self) -> None:
        existing = {"acme-corp", "acme-corp-3"}
        assert generate_unique_slug("Acme Corp", existing) == "acme-corp-2"

    def test_empty_existing_slugs(self) -> None:
        assert generate_unique_slug("New Co", set()) == "new-co"

    def test_invalid_name_propagates_error(self) -> None:
        with pytest.raises(InvalidTenantNameError):
            generate_unique_slug("!!!", set())
