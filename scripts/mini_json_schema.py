"""mini_json_schema — 标准库 Draft-7 最小子集校验器。

只实现 dataset/run_manifest 所需的校验关键字。遇到不支持的关键字显式抛
``UnsupportedKeywordError``（绝不静默忽略）。供 ``dataset_versioning`` 与后续
``run_manifest`` 共用。
"""

import re

__all__ = ["validate", "UnsupportedKeywordError"]


class UnsupportedKeywordError(ValueError):
    """遇到不支持的关键字时抛出（显式失败，绝不静默忽略）。"""


# 注解类关键字：不影响校验结果，仅声明 dialect，显式允许（MANIFEST_SCHEMA 含 $schema）。
_ANNOTATION_KEYWORDS = frozenset({"$schema"})


def validate(instance, schema):
    """校验 instance 是否满足 schema，返回错误信息列表（空列表 = 通过）。

    支持的关键字子集：type（含数组 union 与 "null"）、properties、required、
    items、enum、const、pattern、minLength、maxLength、minimum、maximum、
    minItems、maxItems、additionalProperties（bool）、oneOf / anyOf（递归）、
    null（空 schema）。
    """
    errors = []
    _validate(instance, schema, "", errors)
    return errors


def _validate(instance, schema, path, errors):
    # null schema / true schema：始终通过。
    if schema is None or schema is True:
        return
    # false schema：始终失败。
    if schema is False:
        errors.append(_err(path, "值不符合 schema（false schema）"))
        return
    if not isinstance(schema, dict):
        raise ValueError(
            f"schema 必须是 dict / null / 布尔，实际为 {type(schema).__name__}"
        )

    for keyword, value in schema.items():
        if keyword in _ANNOTATION_KEYWORDS:
            continue
        if keyword == "type":
            _check_type(instance, value, path, errors)
        elif keyword == "properties":
            _check_properties(instance, value, path, errors)
        elif keyword == "required":
            _check_required(instance, value, path, errors)
        elif keyword == "items":
            _check_items(instance, value, path, errors)
        elif keyword == "enum":
            _check_enum(instance, value, path, errors)
        elif keyword == "const":
            _check_const(instance, value, path, errors)
        elif keyword == "pattern":
            _check_pattern(instance, value, path, errors)
        elif keyword == "minLength":
            _check_min_length(instance, value, path, errors)
        elif keyword == "maxLength":
            _check_max_length(instance, value, path, errors)
        elif keyword == "minimum":
            _check_minimum(instance, value, path, errors)
        elif keyword == "maximum":
            _check_maximum(instance, value, path, errors)
        elif keyword == "minItems":
            _check_min_items(instance, value, path, errors)
        elif keyword == "maxItems":
            _check_max_items(instance, value, path, errors)
        elif keyword == "additionalProperties":
            _check_additional_properties(instance, schema, path, errors)
        elif keyword == "oneOf":
            _check_one_of(instance, value, path, errors)
        elif keyword == "anyOf":
            _check_any_of(instance, value, path, errors)
        else:
            raise UnsupportedKeywordError(f"不支持的关键字: {keyword!r}")


def _err(path, message):
    return message if not path else f"{path}: {message}"


def _join(path, key):
    return f"{path}/{key}"


def _type_of(instance):
    if instance is None:
        return "null"
    if isinstance(instance, bool):
        return "boolean"
    if isinstance(instance, int):
        return "integer"
    if isinstance(instance, float):
        return "number"
    if isinstance(instance, str):
        return "string"
    if isinstance(instance, list):
        return "array"
    if isinstance(instance, dict):
        return "object"
    return "unknown"


def _matches_type(instance, expected):
    if expected == "null":
        return instance is None
    if expected == "boolean":
        return isinstance(instance, bool)
    if expected == "integer":
        return isinstance(instance, int) and not isinstance(instance, bool)
    if expected == "number":
        return isinstance(instance, (int, float)) and not isinstance(instance, bool)
    if expected == "string":
        return isinstance(instance, str)
    if expected == "array":
        return isinstance(instance, list)
    if expected == "object":
        return isinstance(instance, dict)
    return False


def _strict_equal(a, b):
    """JSON 语义相等：区分 bool 与 int（True != 1）。"""
    if isinstance(a, bool) != isinstance(b, bool):
        return False
    return a == b


def _check_type(instance, value, path, errors):
    expected_types = value if isinstance(value, list) else [value]
    if not any(_matches_type(instance, t) for t in expected_types):
        expected = "/".join(str(t) for t in expected_types)
        errors.append(_err(path, f"类型应为 {expected}，实际为 {_type_of(instance)}"))


def _check_properties(instance, value, path, errors):
    if not isinstance(instance, dict):
        return
    for key, subschema in value.items():
        if key in instance:
            _validate(instance[key], subschema, _join(path, key), errors)


def _check_required(instance, value, path, errors):
    if not isinstance(instance, dict):
        return
    for key in value:
        if key not in instance:
            errors.append(_err(path, f"缺少必填属性 {key!r}"))


def _check_items(instance, value, path, errors):
    if not isinstance(instance, list):
        return
    for i, item in enumerate(instance):
        _validate(item, value, _join(path, str(i)), errors)


def _check_enum(instance, value, path, errors):
    if not any(_strict_equal(instance, v) for v in value):
        errors.append(_err(path, f"值 {instance!r} 不在枚举 {value!r} 中"))


def _check_const(instance, value, path, errors):
    if not _strict_equal(instance, value):
        errors.append(_err(path, f"值 {instance!r} 不等于常量 {value!r}"))


def _check_pattern(instance, value, path, errors):
    if not isinstance(instance, str):
        return
    try:
        matched = re.search(value, instance) is not None
    except re.error as exc:
        raise ValueError(f"无效的正则表达式 {value!r}: {exc}") from exc
    if not matched:
        errors.append(_err(path, f"字符串 {instance!r} 不匹配 pattern {value!r}"))


def _check_min_length(instance, value, path, errors):
    if not isinstance(instance, str):
        return
    if len(instance) < value:
        errors.append(_err(path, f"字符串长度 {len(instance)} 小于 minLength {value}"))


def _check_minimum(instance, value, path, errors):
    if not isinstance(instance, (int, float)) or isinstance(instance, bool):
        return
    if instance < value:
        errors.append(_err(path, f"数值 {instance} 小于 minimum {value}"))


def _check_min_items(instance, value, path, errors):
    if not isinstance(instance, list):
        return
    if len(instance) < value:
        errors.append(_err(path, f"数组长度 {len(instance)} 小于 minItems {value}"))


def _check_maximum(instance, value, path, errors):
    if not isinstance(instance, (int, float)) or isinstance(instance, bool):
        return
    if instance > value:
        errors.append(_err(path, f"数值 {instance} 大于 maximum {value}"))


def _check_max_length(instance, value, path, errors):
    if not isinstance(instance, str):
        return
    if len(instance) > value:
        errors.append(_err(path, f"字符串长度 {len(instance)} 大于 maxLength {value}"))


def _check_max_items(instance, value, path, errors):
    if not isinstance(instance, list):
        return
    if len(instance) > value:
        errors.append(_err(path, f"数组长度 {len(instance)} 大于 maxItems {value}"))


def _check_additional_properties(instance, schema, path, errors):
    if not isinstance(instance, dict):
        return
    if schema.get("additionalProperties") is not False:
        return
    allowed = schema.get("properties") or {}
    for key in instance:
        if key not in allowed:
            errors.append(_err(_join(path, key), "不允许的额外属性"))


def _check_one_of(instance, value, path, errors):
    matched = 0
    for subschema in value:
        sub_errors = []
        _validate(instance, subschema, path, sub_errors)
        if not sub_errors:
            matched += 1
    if matched != 1:
        errors.append(
            _err(path, f"oneOf 需要恰好匹配 1 个子 schema，实际匹配 {matched} 个")
        )


def _check_any_of(instance, value, path, errors):
    for subschema in value:
        sub_errors = []
        _validate(instance, subschema, path, sub_errors)
        if not sub_errors:
            return
    errors.append(_err(path, "anyOf 没有任何子 schema 匹配"))
