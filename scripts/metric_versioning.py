"""Metric Versioning — 基于内容寻址的 Metric 版本机制（仅标准库）。

- ``version_hash`` = SHA256(规范化语义内容)，相同内容永远产生相同哈希。
- 版本快照存放在 ``data/metrics/{category}/.versions/{metric_id}/{hash}.json``，
  文件名即内容校验，永不覆盖。
- 本模块不引入数据库、不改动任何现有文件，GUI/git_bridge/publish_metric 零影响。
"""

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_BASE_DIR = REPO_ROOT / "data" / "metrics"
CATEGORIES = ("llm", "non_llm")
PARAM_SEMANTIC_KEYS = ("key", "type", "default", "required", "min", "max", "step", "options")


def _metric_id(metric: dict) -> str:
    """返回 metric 的 id（优先 ``id``，其次 ``metric_id``），都缺则抛 ValueError。"""
    if not isinstance(metric, dict):
        raise ValueError("metric 必须是 JSON 对象（dict）")
    mid = metric.get("id") or metric.get("metric_id")
    if not mid:
        raise ValueError("metric 缺少 'id' 或 'metric_id'")
    return mid


def _canonical_param(p: dict) -> dict:
    """只保留 PARAM_SEMANTIC_KEYS 中「存在于 p 且值不为 None」的键（剔除 label）。"""
    if not isinstance(p, dict):
        raise ValueError(f"param 必须是 JSON 对象（dict），实际为 {type(p).__name__}")
    return {k: p[k] for k in PARAM_SEMANTIC_KEYS if k in p and p[k] is not None}


def _param_sort_key(p) -> str:
    """params 排序键：按 key 升序；缺 key/非 dict 排在最前。"""
    if not isinstance(p, dict):
        return ""
    k = p.get("key")
    if k is None:
        return ""
    return str(k)


def compute_version_hash(metric: dict) -> str:
    """计算 metric 的版本哈希（纯函数，不访问文件系统）。

    只对影响 evaluation semantics 的 6 个字段做规范化序列化后取 SHA256（完整 64 位）。
    """
    if not isinstance(metric, dict):
        raise ValueError("metric 必须是 JSON 对象（dict）")

    metric_id = metric.get("id") or metric.get("metric_id")
    if not metric_id:
        raise ValueError("metric 缺少 'id' 或 'metric_id'")

    category = metric.get("category")
    if not category:
        raise ValueError("metric 缺少 'category'")

    params = metric.get("params")
    if not isinstance(params, list):
        raise ValueError("metric 'params' 必须是 list")

    canonical_params = []
    seen_keys = set()
    for p in sorted(params, key=_param_sort_key):
        key = p.get("key") if isinstance(p, dict) else None
        if key in seen_keys:
            raise ValueError(f"metric 'params' 存在重复 key: {key!r}")
        seen_keys.add(key)
        canonical_params.append(_canonical_param(p))

    requires = metric.get("requires") or []
    if not isinstance(requires, list):
        raise ValueError("metric 'requires' 必须是 list")

    canonical = {
        "metric_id": metric_id,
        "category": category,
        "params": canonical_params,
        "criteria": metric.get("criteria"),
        "requires": sorted(requires),
        "code_template": metric.get("code_template") or "",
    }

    canonical_json = json.dumps(
        canonical, sort_keys=True, ensure_ascii=False, separators=(",", ":")
    )
    return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()


def create_version(metric_path: str, base_dir=None) -> dict:
    """从当前 metric 文件创建版本快照。

    ``base_dir`` 参数保留但不用：版本目录由 ``metric_path`` 推导，
    即 ``Path(metric_path).resolve().parent / ".versions" / metric_id / f"{hash}.json"``。
    已存在同名版本则返回旧记录的 ``created_at``，``is_new=False``，不覆盖。
    """
    p = Path(metric_path)
    metric = json.loads(p.read_text(encoding="utf-8"))

    metric_id = _metric_id(metric)
    category = metric.get("category")
    if not category:
        raise ValueError(f"metric 文件 {p} 缺少 'category'，无法创建版本快照")

    version_hash = compute_version_hash(metric)
    versions_dir = p.resolve().parent / ".versions" / metric_id
    target = versions_dir / f"{version_hash}.json"

    if target.exists():
        created_at = None
        try:
            old = json.loads(target.read_text(encoding="utf-8"))
            if isinstance(old, dict):
                created_at = old.get("created_at")
        except Exception:
            created_at = None
        return {
            "metric_id": metric_id,
            "version_hash": version_hash,
            "created_at": created_at,
            "is_new": False,
        }

    created_at = datetime.now(timezone.utc).isoformat()
    record = {
        "metric_id": metric_id,
        "version_hash": version_hash,
        "created_at": created_at,
        "name": metric.get("name"),
        "description": metric.get("description"),
        "category": category,
        "params": metric.get("params"),
        "criteria": metric.get("criteria"),
        "requires": metric.get("requires"),
        "code_template": metric.get("code_template"),
    }

    versions_dir.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return {
        "metric_id": metric_id,
        "version_hash": version_hash,
        "created_at": created_at,
        "is_new": True,
    }


def _resolve_base(base_dir) -> Path:
    return Path(base_dir) if base_dir else DEFAULT_BASE_DIR


def _categories(category) -> list:
    return [category] if category else list(CATEGORIES)


def read_version(metric_id: str, version_hash: str, base_dir=None, category=None):
    """读取指定版本，返回完整版本记录；不存在或 JSON 损坏返回 None（损坏时 stderr 告警）。"""
    base = _resolve_base(base_dir)
    for cat in _categories(category):
        f = base / cat / ".versions" / metric_id / f"{version_hash}.json"
        if f.exists():
            try:
                return json.loads(f.read_text(encoding="utf-8"))
            except Exception as exc:  # JSON 损坏：告警但不抛
                print(
                    f"[metric_versioning] 读取版本文件失败 {f}: {exc}",
                    file=sys.stderr,
                )
                return None
    return None


def _created_at_sort_key(created_at):
    """解析 created_at 用于排序：可解析的按时间戳（优先），否则回退字符串排序。"""
    if created_at is None:
        return (0, "")
    try:
        dt = datetime.fromisoformat(created_at)
        return (1, dt.timestamp())
    except (ValueError, TypeError):
        return (0, str(created_at))


def list_versions(metric_id: str, base_dir=None, category=None) -> list:
    """列出某 metric 的所有版本摘要（metric_id/version_hash/created_at/name），按 created_at 降序。"""
    base = _resolve_base(base_dir)
    results = {}
    for cat in _categories(category):
        versions_dir = base / cat / ".versions" / metric_id
        if not versions_dir.is_dir():
            continue
        for f in versions_dir.glob("*.json"):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
            except Exception:
                continue
            if not isinstance(data, dict):
                continue
            vh = data.get("version_hash") or f.stem
            if vh in results:
                continue
            results[vh] = {
                "metric_id": data.get("metric_id") or metric_id,
                "version_hash": vh,
                "created_at": data.get("created_at"),
                "name": data.get("name"),
            }
    items = list(results.values())
    items.sort(key=lambda x: _created_at_sort_key(x.get("created_at")), reverse=True)
    return items


def diff_versions(metric_id: str, hash_a: str, hash_b: str, base_dir=None, category=None) -> dict:
    """对比两个版本的语义字段，返回结构化 diff。

    比较范围：category/criteria/code_template、params（按 key 匹配，modified 细化到子键）、
    requires（按值判 added/removed）。不比较 name/description/version_hash/created_at。
    """
    va = read_version(metric_id, hash_a, base_dir=base_dir, category=category)
    vb = read_version(metric_id, hash_b, base_dir=base_dir, category=category)
    if va is None:
        raise ValueError(f"版本不存在: {hash_a}")
    if vb is None:
        raise ValueError(f"版本不存在: {hash_b}")

    result = {
        "metric_id": metric_id,
        "version_a": hash_a,
        "version_b": hash_b,
        "changes": [],
        "added_fields": [],
        "removed_fields": [],
        "modified_fields": [],
    }

    # 顶层语义字段
    for field in ("category", "criteria", "code_template"):
        before = va.get(field)
        after = vb.get(field)
        if before != after:
            result["changes"].append(
                {"field": field, "type": "modified", "before": before, "after": after}
            )
            result["modified_fields"].append(field)

    # params：按 key 匹配
    params_a = va.get("params") or []
    params_b = vb.get("params") or []
    by_key_a = {}
    for i, p in enumerate(params_a):
        k = p.get("key") if isinstance(p, dict) else None
        by_key_a[k] = (i, p)
    by_key_b = {}
    for i, p in enumerate(params_b):
        k = p.get("key") if isinstance(p, dict) else None
        by_key_b[k] = (i, p)

    # removed：在 a 不在 b
    for k in sorted(by_key_a, key=lambda x: by_key_a[x][0]):
        if k not in by_key_b:
            i, p = by_key_a[k]
            result["changes"].append({"field": f"params[{i}]", "type": "removed", "before": p})
            result["removed_fields"].append(f"params[{i}]")

    # added：在 b 不在 a
    for k in sorted(by_key_b, key=lambda x: by_key_b[x][0]):
        if k not in by_key_a:
            i, p = by_key_b[k]
            result["changes"].append({"field": f"params[{i}]", "type": "added", "after": p})
            result["added_fields"].append(f"params[{i}]")

    # modified：两侧都存在，细化到语义子键（剔除 label）
    for k in sorted(by_key_a, key=lambda x: by_key_a[x][0]):
        if k in by_key_b:
            ia, pa = by_key_a[k]
            ib, pb = by_key_b[k]
            ca = _canonical_param(pa) if isinstance(pa, dict) else {}
            cb = _canonical_param(pb) if isinstance(pb, dict) else {}
            for sub in PARAM_SEMANTIC_KEYS:
                if sub == "key":
                    continue
                if ca.get(sub) != cb.get(sub):
                    field = f"params[{ib}].{sub}"
                    result["changes"].append(
                        {"field": field, "type": "modified", "before": ca.get(sub), "after": cb.get(sub)}
                    )
                    result["modified_fields"].append(field)

    # requires：按值判 added/removed
    req_a = va.get("requires") or []
    req_b = vb.get("requires") or []
    for i, val in enumerate(req_a):
        if val not in req_b:
            result["changes"].append({"field": f"requires[{i}]", "type": "removed", "before": val})
            result["removed_fields"].append(f"requires[{i}]")
    for i, val in enumerate(req_b):
        if val not in req_a:
            result["changes"].append({"field": f"requires[{i}]", "type": "added", "after": val})
            result["added_fields"].append(f"requires[{i}]")

    return result


def migrate_existing(base_dir=None) -> list:
    """为 base_dir/{llm,non_llm}/*.json（非递归）逐文件创建初始版本快照。

    跳过缺 id/category 的文件；返回本次「新产生」的 version_hash 列表（幂等：二次运行返回 []）。
    """
    base = _resolve_base(base_dir)
    new_hashes = []
    for cat in CATEGORIES:
        cat_dir = base / cat
        if not cat_dir.is_dir():
            continue
        for f in sorted(cat_dir.glob("*.json")):
            try:
                metric = json.loads(f.read_text(encoding="utf-8"))
            except Exception as exc:
                print(f"[metric_versioning] 跳过无法解析的 {f}: {exc}", file=sys.stderr)
                continue
            if not isinstance(metric, dict):
                continue
            if not (metric.get("id") or metric.get("metric_id")):
                continue
            if not metric.get("category"):
                continue
            result = create_version(str(f))
            if result.get("is_new"):
                new_hashes.append(result["version_hash"])
    return new_hashes


def main() -> None:
    parser = argparse.ArgumentParser(prog="metric_versioning", description="Metric 版本管理")
    sub = parser.add_subparsers(dest="command", required=True)

    p_create = sub.add_parser("create", help="为 metric 文件创建版本快照")
    p_create.add_argument("--metric", required=True, help="metric JSON 文件路径")
    p_create.add_argument("--base-dir", default=None, help="指标根目录（保留，未使用）")

    p_read = sub.add_parser("read", help="读取某个版本")
    p_read.add_argument("--metric-id", required=True)
    p_read.add_argument("--version-hash", required=True)
    p_read.add_argument("--category", default=None)
    p_read.add_argument("--base-dir", default=None)

    p_list = sub.add_parser("list", help="列出某 metric 的所有版本")
    p_list.add_argument("--metric-id", required=True)
    p_list.add_argument("--category", default=None)
    p_list.add_argument("--base-dir", default=None)

    p_diff = sub.add_parser("diff", help="对比两个版本")
    p_diff.add_argument("--metric-id", required=True)
    p_diff.add_argument("--version-a", required=True)
    p_diff.add_argument("--version-b", required=True)
    p_diff.add_argument("--category", default=None)
    p_diff.add_argument("--base-dir", default=None)

    p_migrate = sub.add_parser("migrate", help="为所有现有 metric 创建初始版本快照")
    p_migrate.add_argument("--base-dir", default=None)

    args = parser.parse_args()

    if args.command == "create":
        print(json.dumps(create_version(args.metric, base_dir=args.base_dir), ensure_ascii=False, indent=2))
    elif args.command == "read":
        data = read_version(
            args.metric_id, args.version_hash, base_dir=args.base_dir, category=args.category
        )
        print(json.dumps(data, ensure_ascii=False, indent=2) if data is not None else "null")
    elif args.command == "list":
        items = list_versions(args.metric_id, base_dir=args.base_dir, category=args.category)
        print(json.dumps(items, ensure_ascii=False, indent=2))
    elif args.command == "diff":
        result = diff_versions(
            args.metric_id, args.version_a, args.version_b, base_dir=args.base_dir, category=args.category
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif args.command == "migrate":
        hashes = migrate_existing(base_dir=args.base_dir)
        print(json.dumps(hashes, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
