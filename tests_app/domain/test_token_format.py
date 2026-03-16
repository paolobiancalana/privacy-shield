"""
Token format domain service tests.

Adversarial Analysis:
  1. Tokens with invalid pii_type codes could bypass validation if VALID_TYPES check is missing.
  2. parse_token on partial matches (e.g., "[#pe:a3f2] extra") must return None (fullmatch).
  3. build_collision_hash with attempt=0 could produce unexpected suffix if guard is wrong.
"""
from __future__ import annotations

import pytest

from app.domain.services.token_format import (
    VALID_TYPES,
    TOKEN_PATTERN,
    build_collision_hash,
    find_all_tokens,
    format_token,
    is_token,
    parse_token,
)


class TestFormatToken:
    """format_token: create canonical token strings."""

    def test_basic_format(self) -> None:
        assert format_token("pe", "a3f2") == "[#pe:a3f2]"

    def test_format_with_collision_suffix(self) -> None:
        assert format_token("pe", "a3f2_2") == "[#pe:a3f2_2]"

    def test_format_three_letter_type(self) -> None:
        assert format_token("org", "1234") == "[#org:1234]"

    def test_format_invalid_type_raises(self) -> None:
        with pytest.raises(ValueError, match="Unknown pii_type"):
            format_token("xx", "a3f2")

    def test_format_invalid_hash_too_short_raises(self) -> None:
        with pytest.raises(ValueError, match="hash_hex must be"):
            format_token("pe", "a3f")

    def test_format_invalid_hash_uppercase_raises(self) -> None:
        with pytest.raises(ValueError, match="hash_hex must be"):
            format_token("pe", "A3F2")

    def test_format_invalid_hash_non_hex_raises(self) -> None:
        with pytest.raises(ValueError, match="hash_hex must be"):
            format_token("pe", "zzzz")


class TestParseToken:
    """parse_token: extract components from token strings."""

    def test_parse_basic_token(self) -> None:
        result = parse_token("[#pe:a3f2]")
        assert result == ("pe", "a3f2")

    def test_parse_collision_suffix(self) -> None:
        result = parse_token("[#pe:a3f2_2]")
        assert result == ("pe", "a3f2_2")

    def test_parse_three_letter_type(self) -> None:
        result = parse_token("[#org:c4f7]")
        assert result == ("org", "c4f7")

    def test_parse_invalid_string(self) -> None:
        assert parse_token("invalid") is None

    def test_parse_empty_string(self) -> None:
        assert parse_token("") is None

    def test_parse_invalid_type_code(self) -> None:
        """'xx' is not in VALID_TYPES even though regex matches 2 lowercase chars."""
        assert parse_token("[#xx:1234]") is None

    def test_parse_partial_match_extra_text(self) -> None:
        """fullmatch must reject trailing text."""
        assert parse_token("[#pe:a3f2] extra") is None

    def test_parse_partial_match_leading_text(self) -> None:
        assert parse_token("prefix [#pe:a3f2]") is None

    def test_parse_missing_hash_bracket(self) -> None:
        assert parse_token("[#pe:a3f2") is None

    def test_parse_double_bracket(self) -> None:
        assert parse_token("[[#pe:a3f2]]") is None


class TestIsToken:
    """is_token: boolean check."""

    def test_is_token_true(self) -> None:
        assert is_token("[#pe:a3f2]") is True

    def test_is_token_false_plain_text(self) -> None:
        assert is_token("hello") is False

    def test_is_token_false_partial_match(self) -> None:
        assert is_token("[#pe:a3f2] trailing") is False


class TestFindAllTokens:
    """find_all_tokens: locate tokens within larger text."""

    def test_find_two_tokens(self) -> None:
        text = "Call [#pe:a3f2] at [#tel:7b2c]"
        results = find_all_tokens(text)
        assert len(results) == 2
        # First token
        assert results[0][0] == "pe"
        assert results[0][1] == "a3f2"
        assert text[results[0][2]:results[0][3]] == "[#pe:a3f2]"
        # Second token
        assert results[1][0] == "tel"
        assert results[1][1] == "7b2c"
        assert text[results[1][2]:results[1][3]] == "[#tel:7b2c]"

    def test_find_no_tokens(self) -> None:
        assert find_all_tokens("plain text with no tokens") == []

    def test_find_empty_string(self) -> None:
        assert find_all_tokens("") == []

    def test_find_token_with_collision_suffix(self) -> None:
        text = "User [#pe:a3f2_2] found"
        results = find_all_tokens(text)
        assert len(results) == 1
        assert results[0][1] == "a3f2_2"

    def test_find_ignores_invalid_type_tokens(self) -> None:
        """Tokens with type codes not in VALID_TYPES are skipped."""
        text = "Skip [#xx:1234] but find [#pe:a3f2]"
        results = find_all_tokens(text)
        assert len(results) == 1
        assert results[0][0] == "pe"

    def test_find_adjacent_tokens(self) -> None:
        text = "[#pe:a3f2][#cf:9b1d]"
        results = find_all_tokens(text)
        assert len(results) == 2

    def test_positions_correct_with_unicode(self) -> None:
        """Ensure character offsets work with multi-byte unicode."""
        text = "Nome: [#pe:a3f2]"  # e-grave is 1 char
        results = find_all_tokens(text)
        assert len(results) == 1
        assert text[results[0][2]:results[0][3]] == "[#pe:a3f2]"


class TestBuildCollisionHash:
    """build_collision_hash: suffix generation."""

    def test_first_attempt_no_suffix(self) -> None:
        assert build_collision_hash("a3f2", 1) == "a3f2"

    def test_second_attempt_suffix_2(self) -> None:
        assert build_collision_hash("a3f2", 2) == "a3f2_2"

    def test_third_attempt_suffix_3(self) -> None:
        assert build_collision_hash("a3f2", 3) == "a3f2_3"

    def test_zero_attempt_returns_base(self) -> None:
        """attempt <= 1 returns base hash."""
        assert build_collision_hash("a3f2", 0) == "a3f2"

    def test_negative_attempt_returns_base(self) -> None:
        assert build_collision_hash("a3f2", -5) == "a3f2"


class TestValidTypes:
    """Verify the VALID_TYPES set contains all 14 expected codes."""

    def test_all_14_types_present(self) -> None:
        expected = {"pe", "org", "loc", "ind", "tel", "em", "cf", "ib", "med", "leg", "rel", "fin", "pro", "dt"}
        assert VALID_TYPES == expected

    def test_valid_types_is_frozenset(self) -> None:
        assert isinstance(VALID_TYPES, frozenset)

    def test_each_type_recognized_by_format_and_parse(self) -> None:
        """Every VALID_TYPE can be formatted into a token and parsed back."""
        for t in VALID_TYPES:
            token_str = format_token(t, "abcd")
            parsed = parse_token(token_str)
            assert parsed is not None, f"parse_token failed for type {t!r}"
            assert parsed[0] == t
