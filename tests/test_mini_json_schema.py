"""mini_json_schema 模块测试（pytest）。

覆盖所有已支持的关键字，包括新增的 maximum、maxLength、maxItems。
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from mini_json_schema import validate, UnsupportedKeywordError


# ── Existing keywords ─────────────────────────────────────────────────────────


def test_type():
    assert validate(5, {"type": "integer"}) == []
    assert len(validate("x", {"type": "integer"})) == 1


def test_properties():
    assert validate({"a": 1}, {"type": "object", "properties": {"a": {"type": "integer"}}}) == []


def test_required():
    assert validate({"a": 1}, {"type": "object", "required": ["a"]}) == []
    assert len(validate({}, {"type": "object", "required": ["a"]})) == 1


def test_items():
    assert validate([1, 2], {"type": "array", "items": {"type": "integer"}}) == []
    assert len(validate(["x"], {"type": "array", "items": {"type": "integer"}})) == 1


def test_enum():
    assert validate(1, {"enum": [1, 2, 3]}) == []
    assert len(validate(4, {"enum": [1, 2, 3]})) == 1


def test_const():
    assert validate(1, {"const": 1}) == []
    assert len(validate(2, {"const": 1})) == 1


def test_pattern():
    assert validate("abc", {"type": "string", "pattern": "^a"}) == []
    assert len(validate("xyz", {"type": "string", "pattern": "^a"})) == 1


def test_min_length():
    assert validate("abc", {"type": "string", "minLength": 2}) == []
    assert len(validate("a", {"type": "string", "minLength": 2})) == 1


def test_minimum():
    assert validate(5, {"type": "integer", "minimum": 3}) == []
    assert len(validate(2, {"type": "integer", "minimum": 3})) == 1


def test_min_items():
    assert validate([1, 2], {"type": "array", "minItems": 2}) == []
    assert len(validate([1], {"type": "array", "minItems": 2})) == 1


def test_additional_properties_false():
    assert validate({"a": 1}, {"type": "object", "properties": {"a": {"type": "integer"}}, "additionalProperties": False}) == []
    assert len(validate({"a": 1, "b": 2}, {"type": "object", "properties": {"a": {"type": "integer"}}, "additionalProperties": False})) == 1


def test_one_of():
    schema = {"oneOf": [{"type": "integer"}, {"type": "string"}]}
    assert validate(5, schema) == []
    assert validate("x", schema) == []
    assert len(validate(5.5, schema)) == 1  # float matches neither


def test_any_of():
    schema = {"anyOf": [{"type": "integer"}, {"type": "string"}]}
    assert validate(5, schema) == []
    assert validate("x", schema) == []
    assert len(validate(5.5, schema)) == 1


# ── New keywords: maximum, maxLength, maxItems ────────────────────────────────


def test_maximum():
    """maximum should pass when value <= max and fail when value > max."""
    assert validate(5, {"type": "integer", "maximum": 10}) == []
    assert len(validate(15, {"type": "integer", "maximum": 10})) == 1


def test_maximum_edge():
    """maximum with exact boundary value should pass."""
    assert validate(10, {"type": "integer", "maximum": 10}) == []
    assert validate(10.0, {"type": "number", "maximum": 10}) == []


def test_maximum_not_applicable():
    """maximum should not apply to non-numeric types."""
    assert validate("abc", {"type": "string", "maximum": 10}) == []
    assert validate([1, 2], {"type": "array", "maximum": 10}) == []


def test_max_length():
    """maxLength should pass when len <= max and fail when len > max."""
    assert validate("abc", {"type": "string", "maxLength": 5}) == []
    assert len(validate("abcdef", {"type": "string", "maxLength": 5})) == 1


def test_max_length_edge():
    """maxLength with exact boundary should pass."""
    assert validate("abcde", {"type": "string", "maxLength": 5}) == []


def test_max_length_not_applicable():
    """maxLength should not apply to non-string types."""
    assert validate(123, {"type": "integer", "maxLength": 5}) == []
    assert validate([1, 2], {"type": "array", "maxLength": 5}) == []


def test_max_items():
    """maxItems should pass when len <= max and fail when len > max."""
    assert validate([1, 2], {"type": "array", "maxItems": 3}) == []
    assert len(validate([1, 2, 3, 4], {"type": "array", "maxItems": 3})) == 1


def test_max_items_edge():
    """maxItems with exact boundary should pass."""
    assert validate([1, 2, 3], {"type": "array", "maxItems": 3}) == []


def test_max_items_not_applicable():
    """maxItems should not apply to non-array types."""
    assert validate("abc", {"type": "string", "maxItems": 3}) == []
    assert validate(123, {"type": "integer", "maxItems": 3}) == []


# ── Combined keywords ─────────────────────────────────────────────────────────


def test_combined_min_max():
    """minimum and maximum combined should work together."""
    schema = {"type": "integer", "minimum": 0, "maximum": 10}
    assert validate(5, schema) == []
    assert len(validate(-1, schema)) == 1
    assert len(validate(11, schema)) == 1


def test_combined_min_max_length():
    """minLength and maxLength combined should work together."""
    schema = {"type": "string", "minLength": 2, "maxLength": 5}
    assert validate("abc", schema) == []
    assert len(validate("a", schema)) == 1
    assert len(validate("abcdef", schema)) == 1


def test_combined_min_max_items():
    """minItems and maxItems combined should work together."""
    schema = {"type": "array", "minItems": 2, "maxItems": 4}
    assert validate([1, 2, 3], schema) == []
    assert len(validate([1], schema)) == 1
    assert len(validate([1, 2, 3, 4, 5], schema)) == 1


# ── Unsupported keyword ───────────────────────────────────────────────────────


def test_unsupported_keyword():
    """Unsupported keywords should raise UnsupportedKeywordError."""
    with pytest.raises(UnsupportedKeywordError):
        validate(1, {"exclusiveMinimum": 1})


# ── Null/boolean schemas ──────────────────────────────────────────────────────


def test_null_schema():
    assert validate(1, None) == []
    assert validate("x", None) == []


def test_true_schema():
    assert validate(1, True) == []


def test_false_schema():
    assert len(validate(1, False)) == 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])