"""Dataset Versioning — 基于内容寻址的 Dataset 版本机制（仅标准库 + mini_json_schema）。

- ``content_hash`` = SHA256(规范化 test cases 数组)，任何 case 字段变化即变化。
- ``version_hash`` = SHA256(metadata + content_hash)，metadata 或内容变化即变化。
- 内容文件与版本记录分开存储：版本记录小（list 快），内容文件大（按需加载）。
- 文件名即内容校验，永不覆盖；本模块不引入数据库、不改动任何现有文件。
"""

import argparse
import hashlib
import json
import os
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from mini_json_schema import validate as _js_validate

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_BASE_DIR = REPO_ROOT / "data" / "datasets"

_MISSING = object()


# ── Hash 计算 ────────────────────────────────────────────────────────────────

def compute_content_hash(cases):
    """SHA256(按 case_id 升序排序后的 test cases 数组的规范化 JSON)。

    空数组合法：``sha256("[]")``。
    """
    cases_sorted = sorted(cases, key=lambda c: c["case_id"])
    canonical = json.dumps(
        cases_sorted, sort_keys=True, ensure_ascii=False, separators=(",", ":")
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def compute_version_hash(dataset_def, content_hash):
    """SHA256(规范化 version record)，其中包含 content_hash。

    缺 ``dataset_id`` 或 ``name`` → 抛 ValueError。schema 归一 None→{}。
    """
    dataset_id = dataset_def.get("dataset_id")
    name = dataset_def.get("name")
    if not dataset_id or not name:
        raise ValueError("dataset_def 缺少 'dataset_id' 或 'name'")

    record = {
        "dataset_id": dataset_id,
        "name": name,
        "description": dataset_def.get("description", ""),
        "schema": dataset_def.get("schema") or {},
        "n_cases": dataset_def.get("n_cases", 0),
        "content_hash": content_hash,
    }
    canonical = json.dumps(
        record, sort_keys=True, ensure_ascii=False, separators=(",", ":")
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


# ── Schema 推断 / 校验 ───────────────────────────────────────────────────────

def _infer_type(val):
    """推断单个 JSON 值的类型。bool 必须先判（bool 是 int 子类）。"""
    if val is None:
        return "null"
    if isinstance(val, bool):
        return "boolean"
    if isinstance(val, int):
        return "integer"
    if isinstance(val, float):
        return "number"
    if isinstance(val, str):
        return "string"
    if isinstance(val, list):
        return "array"
    if isinstance(val, dict):
        return "object"
    raise ValueError(f"无法推断 JSON 类型: {type(val).__name__}")


def infer_schema(cases):
    """聚合全部 case，自动推断 JSON Schema（Draft-7 子集）。"""
    if not cases:
        return {"type": "object"}

    type_sets = {}
    for case in cases:
        if not isinstance(case, dict):
            raise ValueError("每个 case 必须是 JSON 对象（dict）")
        for key, val in case.items():
            type_sets.setdefault(key, set()).add(_infer_type(val))

    properties = {}
    for key in sorted(type_sets):
        types = sorted(type_sets[key])
        properties[key] = (
            {"type": types[0]} if len(types) == 1 else {"type": types}
        )

    # required = 在所有 case 都存在且非 null 的字段。
    required = [
        key
        for key in sorted(type_sets)
        if all(key in case and case[key] is not None for case in cases)
    ]

    schema = {"type": "object"}
    if properties:
        schema["properties"] = properties
    if required:
        schema["required"] = required
    return schema


def validate_dataset(cases, schema):
    """逐 case 校验，错误累积为 ``case_id={id}: {msg}``，空列表 = 通过。"""
    errors = []
    for case in cases:
        case_id = case.get("case_id", "?") if isinstance(case, dict) else "?"
        for msg in _js_validate(case, schema):
            errors.append(f"case_id={case_id}: {msg}")
    return errors


# ── 内部工具 ─────────────────────────────────────────────────────────────────

def _resolve_base(base_dir) -> Path:
    return Path(base_dir) if base_dir else DEFAULT_BASE_DIR


def _dataset_dir(base, dataset_id) -> Path:
    return base / dataset_id


def _write_atomic(target: Path, text: str) -> None:
    """临时文件 + os.replace 原子落盘（覆盖语义，用于 dataset.json/test_cases.json）。"""
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(target.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, target)


def _write_atomic_if_absent(target: Path, text: str) -> bool:
    """临时文件 + os.replace 原子落盘；已存在同名文件永不覆盖，返回是否实际写入。"""
    if target.exists():
        return False
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(target.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, target)
    return True


def _assign_case_ids(cases):
    """分配 case_id：已有要求 int（非 int 尝试 int() 转换，失败 ValueError）；
    无则从 1 起分配未被占用的最小递增 int；重复 → ValueError。
    返回新的 case 列表，不修改入参。
    """
    if not isinstance(cases, list):
        raise ValueError("cases 必须是 list")

    copied = []
    used = set()
    pending = []
    for case in cases:
        if not isinstance(case, dict):
            raise ValueError("每个 case 必须是 JSON 对象（dict）")
        c = dict(case)
        raw = c.get("case_id")
        if raw is None:
            pending.append(c)
            copied.append(c)
            continue
        if isinstance(raw, bool):
            raise ValueError(f"case_id 必须是 int，实际为 bool: {raw!r}")
        if not isinstance(raw, int):
            try:
                raw = int(raw)
            except (TypeError, ValueError):
                raise ValueError(f"case_id 无法转换为 int: {raw!r}")
        if raw in used:
            raise ValueError(f"重复 case_id: {raw}")
        used.add(raw)
        c["case_id"] = raw
        copied.append(c)

    next_id = 1
    for c in pending:
        while next_id in used:
            next_id += 1
        used.add(next_id)
        c["case_id"] = next_id
        next_id += 1
    return copied


def _created_at_sort_key(created_at):
    """解析 created_at 用于排序：可解析的按时间戳，否则回退字符串排序。"""
    if created_at is None:
        return (0, "")
    try:
        dt = datetime.fromisoformat(created_at)
        return (1, dt.timestamp())
    except (ValueError, TypeError):
        return (0, str(created_at))


def _read_content(dataset_id, content_hash, base: Path):
    f = base / dataset_id / ".versions" / ".content" / f"{content_hash}.json"
    if not f.exists():
        raise ValueError(f"content 文件不存在: {content_hash}")
    return json.loads(f.read_text(encoding="utf-8"))


# ── CRUD ─────────────────────────────────────────────────────────────────────

def create_dataset(dataset_id, name, cases, description="", schema=None, base_dir=None):
    """创建新 dataset：分配 case_id → 推断/用给定 schema → 校验 → 写
    dataset.json + test_cases.json → 创建初始版本 → 返回记录。
    """
    cases = _assign_case_ids(cases)

    if schema is None:
        schema = infer_schema(cases)
    else:
        errors = validate_dataset(cases, schema)
        if errors:
            raise ValueError("schema 校验失败: " + "; ".join(errors))

    content_hash = compute_content_hash(cases)
    n_cases = len(cases)
    created_at = datetime.now(timezone.utc).isoformat()

    dataset_def = {
        "dataset_id": dataset_id,
        "name": name,
        "description": description,
        "schema": schema,
        "n_cases": n_cases,
        "content_hash": content_hash,
        "created_at": created_at,
    }

    base = _resolve_base(base_dir)
    ds_dir = _dataset_dir(base, dataset_id)
    ds_dir.mkdir(parents=True, exist_ok=True)

    _write_atomic(
        ds_dir / "dataset.json",
        json.dumps(dataset_def, ensure_ascii=False, indent=2),
    )
    cases_sorted = sorted(cases, key=lambda c: c["case_id"])
    _write_atomic(
        ds_dir / "test_cases.json",
        json.dumps(cases_sorted, ensure_ascii=False, indent=2),
    )

    version = create_version(dataset_id, base_dir=base_dir)

    return {
        "dataset_id": dataset_id,
        "name": name,
        "description": description,
        "schema": schema,
        "n_cases": n_cases,
        "content_hash": content_hash,
        "created_at": created_at,
        "version_hash": version["version_hash"],
        "is_new": True,
    }


def create_version(dataset_id, base_dir=None):
    """从当前 dataset.json + test_cases.json 创建版本快照。

    强制 ``n_cases = len(cases)`` → ``content_hash`` → ``version_hash`` →
    先写 content（已存在则不写）再写 version record。幂等：已存在返回
    ``is_new=False`` + 旧 created_at。
    """
    base = _resolve_base(base_dir)
    ds_dir = _dataset_dir(base, dataset_id)
    def_path = ds_dir / "dataset.json"
    cases_path = ds_dir / "test_cases.json"

    if not def_path.exists() or not cases_path.exists():
        raise ValueError(f"dataset 不存在或缺少文件: {dataset_id}")

    dataset_def = json.loads(def_path.read_text(encoding="utf-8"))
    cases = json.loads(cases_path.read_text(encoding="utf-8"))

    n_cases = len(cases)
    content_hash = compute_content_hash(cases)

    def_for_hash = dict(dataset_def)
    def_for_hash["n_cases"] = n_cases
    version_hash = compute_version_hash(def_for_hash, content_hash)

    # 1) 先写 content 文件（已存在则不写）。
    content_file = ds_dir / ".versions" / ".content" / f"{content_hash}.json"
    _write_atomic_if_absent(
        content_file,
        json.dumps(
            sorted(cases, key=lambda c: c["case_id"]), ensure_ascii=False, indent=2
        ),
    )

    # 2) 再写 version record（已存在则不写，返回旧 created_at）。
    version_file = ds_dir / ".versions" / f"{version_hash}.json"
    if version_file.exists():
        created_at = None
        try:
            old = json.loads(version_file.read_text(encoding="utf-8"))
            if isinstance(old, dict):
                created_at = old.get("created_at")
        except Exception:
            created_at = None
        return {
            "dataset_id": dataset_id,
            "version_hash": version_hash,
            "created_at": created_at,
            "is_new": False,
        }

    created_at = datetime.now(timezone.utc).isoformat()
    record = {
        "dataset_id": dataset_id,
        "version_hash": version_hash,
        "created_at": created_at,
        "name": dataset_def.get("name"),
        "description": dataset_def.get("description", ""),
        "schema": dataset_def.get("schema") or {},
        "n_cases": n_cases,
        "content_hash": content_hash,
    }
    _write_atomic_if_absent(
        version_file,
        json.dumps(record, ensure_ascii=False, indent=2),
    )
    return {
        "dataset_id": dataset_id,
        "version_hash": version_hash,
        "created_at": created_at,
        "is_new": True,
    }


def read_version(dataset_id, version_hash, base_dir=None):
    """读取指定版本，返回完整 version record（含 content_hash）；
    不存在 / JSON 损坏返回 None（损坏时 stderr 告警）。
    """
    base = _resolve_base(base_dir)
    f = base / dataset_id / ".versions" / f"{version_hash}.json"
    if not f.exists():
        return None
    try:
        return json.loads(f.read_text(encoding="utf-8"))
    except Exception as exc:
        print(
            f"[dataset_versioning] 读取版本文件失败 {f}: {exc}",
            file=sys.stderr,
        )
        return None


def list_versions(dataset_id, base_dir=None):
    """列出某 dataset 的所有版本摘要（dataset_id/version_hash/created_at/name），
    按 created_at 降序（非递归 glob("*.json")）。
    """
    base = _resolve_base(base_dir)
    versions_dir = base / dataset_id / ".versions"
    if not versions_dir.is_dir():
        return []

    results = {}
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
            "dataset_id": data.get("dataset_id") or dataset_id,
            "version_hash": vh,
            "created_at": data.get("created_at"),
            "name": data.get("name"),
        }
    items = list(results.values())
    items.sort(key=lambda x: _created_at_sort_key(x.get("created_at")), reverse=True)
    return items


def get_current(dataset_id, base_dir=None):
    """读 dataset.json + test_cases.json，返回 ``{**def, "cases": cases}``
    （供 run_manifest 取全量 def），不存在 / 损坏返回 None。
    """
    base = _resolve_base(base_dir)
    ds_dir = _dataset_dir(base, dataset_id)
    def_path = ds_dir / "dataset.json"
    cases_path = ds_dir / "test_cases.json"
    if not def_path.exists() or not cases_path.exists():
        return None
    try:
        dataset_def = json.loads(def_path.read_text(encoding="utf-8"))
        cases = json.loads(cases_path.read_text(encoding="utf-8"))
    except Exception as exc:
        print(
            f"[dataset_versioning] 读取 dataset 失败 {dataset_id}: {exc}",
            file=sys.stderr,
        )
        return None
    result = dict(dataset_def)
    result["cases"] = cases
    return result


# ── Diff ─────────────────────────────────────────────────────────────────────

def diff_case(case_a, case_b, fields=None):
    """逐字段比较两个 case。fields=None 比较所有字段；case_id 永不比较。"""
    if fields is not None:
        all_fields = set(fields) - {"case_id"}
    else:
        all_fields = (set(case_a) | set(case_b)) - {"case_id"}

    changes = []
    for field in sorted(all_fields):
        val_a = case_a.get(field, _MISSING)
        val_b = case_b.get(field, _MISSING)
        if val_a is _MISSING and val_b is not _MISSING:
            changes.append({"field": field, "type": "added", "after": val_b})
        elif val_a is not _MISSING and val_b is _MISSING:
            changes.append({"field": field, "type": "removed", "before": val_a})
        elif val_a != val_b:
            changes.append(
                {"field": field, "type": "modified", "before": val_a, "after": val_b}
            )
    return changes


def detect_schema_changes(matched_changes, n_matched, threshold=0.95):
    """从 matched cases 的逐字段变化中检测 schema 级变化。

    分母用 ``n_matched``（而非仅该字段出现变化的 case 数）；新增"字段全局类型
    变化"（type_changed）。``n_matched == 0`` 返回空（防除零）。
    """
    if n_matched == 0:
        return []

    field_counts = defaultdict(lambda: {"added": 0, "removed": 0, "type_changed": 0})
    for entry in matched_changes:
        for ch in entry.get("changes", []):
            field = ch.get("field")
            typ = ch.get("type")
            if typ == "added":
                field_counts[field]["added"] += 1
            elif typ == "removed":
                field_counts[field]["removed"] += 1
            elif typ == "modified":
                if _infer_type(ch.get("before")) != _infer_type(ch.get("after")):
                    field_counts[field]["type_changed"] += 1

    schema_changes = []
    for field in sorted(field_counts):
        counts = field_counts[field]
        if counts["added"] / n_matched >= threshold:
            schema_changes.append(
                {"field": field, "type": "added", "affected_cases": counts["added"]}
            )
        elif counts["removed"] / n_matched >= threshold:
            schema_changes.append(
                {"field": field, "type": "removed", "affected_cases": counts["removed"]}
            )
        elif counts["type_changed"] / n_matched >= threshold:
            schema_changes.append(
                {
                    "field": field,
                    "type": "type_changed",
                    "affected_cases": counts["type_changed"],
                }
            )
    return schema_changes


def diff_versions(dataset_id, hash_a, hash_b, fields=None, base_dir=None):
    """对比两个版本，返回结构化 diff（沿用设计 §6.6 结构，schema_changes 补
    affected_cases）。
    """
    va = read_version(dataset_id, hash_a, base_dir=base_dir)
    vb = read_version(dataset_id, hash_b, base_dir=base_dir)
    if va is None:
        raise ValueError(f"版本不存在: {hash_a}")
    if vb is None:
        raise ValueError(f"版本不存在: {hash_b}")

    base = _resolve_base(base_dir)
    cases_a = _read_content(dataset_id, va["content_hash"], base)
    cases_b = _read_content(dataset_id, vb["content_hash"], base)

    by_id_a = {c["case_id"]: c for c in cases_a}
    by_id_b = {c["case_id"]: c for c in cases_b}
    ids_a = set(by_id_a)
    ids_b = set(by_id_b)

    matched_ids = sorted(ids_a & ids_b)
    added_ids = sorted(ids_b - ids_a)
    removed_ids = sorted(ids_a - ids_b)

    matched_changes = []
    modified_cases = []
    for cid in matched_ids:
        changes = diff_case(by_id_a[cid], by_id_b[cid], fields)
        matched_changes.append({"case_id": cid, "changes": changes})
        if changes:
            modified_cases.append({"case_id": cid, "changes": changes})

    added_cases = [
        {"case_id": cid, "changes": [{"field": "*", "type": "added", "after": by_id_b[cid]}]}
        for cid in added_ids
    ]
    removed_cases = [
        {"case_id": cid, "changes": [{"field": "*", "type": "removed", "before": by_id_a[cid]}]}
        for cid in removed_ids
    ]

    n_matched = len(matched_ids)
    schema_changes = detect_schema_changes(matched_changes, n_matched, threshold=0.95)

    return {
        "dataset_id": dataset_id,
        "version_a": hash_a,
        "version_b": hash_b,
        "fields_filter": fields,
        "summary": {
            "n_cases_a": len(cases_a),
            "n_cases_b": len(cases_b),
            "matched": n_matched,
            "added": len(added_ids),
            "removed": len(removed_ids),
            "modified": len(modified_cases),
        },
        "schema_changes": schema_changes,
        "added_cases": added_cases,
        "removed_cases": removed_cases,
        "modified_cases": modified_cases,
    }


# ── Migration ────────────────────────────────────────────────────────────────

def migrate_from_file(source_path, dataset_id, name, description="", base_dir=None):
    """读 source JSON（list）→ 分配 case_id → 推断 schema → 走 create_dataset
    流程写 ``data/datasets/{dataset_id}/``，原文件不动。
    """
    cases = json.loads(Path(source_path).read_text(encoding="utf-8"))
    return create_dataset(
        dataset_id, name, cases, description=description, schema=None, base_dir=base_dir
    )


# ── CLI ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(prog="dataset_versioning", description="Dataset 版本管理")
    sub = parser.add_subparsers(dest="command", required=True)

    p_create = sub.add_parser("create", help="创建新 dataset")
    p_create.add_argument("--dataset-id", required=True)
    p_create.add_argument("--name", required=True)
    p_create.add_argument("--source", required=True, help="test cases JSON 文件路径（list）")
    p_create.add_argument("--description", default="")
    p_create.add_argument("--schema", default=None, help="可选的 schema JSON 文件路径")
    p_create.add_argument("--base-dir", default=None)

    p_cv = sub.add_parser("create-version", help="为现有 dataset 创建新版本快照")
    p_cv.add_argument("--dataset-id", required=True)
    p_cv.add_argument("--base-dir", default=None)

    p_read = sub.add_parser("read", help="读取指定版本")
    p_read.add_argument("--dataset-id", required=True)
    p_read.add_argument("--version-hash", required=True)
    p_read.add_argument("--base-dir", default=None)

    p_list = sub.add_parser("list", help="列出某 dataset 的所有版本")
    p_list.add_argument("--dataset-id", required=True)
    p_list.add_argument("--base-dir", default=None)

    p_diff = sub.add_parser("diff", help="对比两个版本")
    p_diff.add_argument("--dataset-id", required=True)
    p_diff.add_argument("--version-a", required=True)
    p_diff.add_argument("--version-b", required=True)
    p_diff.add_argument("--fields", default=None, help="逗号分隔的字段列表")
    p_diff.add_argument("--base-dir", default=None)

    p_migrate = sub.add_parser("migrate", help="从现有文件迁移")
    p_migrate.add_argument("--source", required=True)
    p_migrate.add_argument("--dataset-id", required=True)
    p_migrate.add_argument("--name", required=True)
    p_migrate.add_argument("--description", default="")
    p_migrate.add_argument("--base-dir", default=None)

    args = parser.parse_args()

    if args.command == "create":
        cases = json.loads(Path(args.source).read_text(encoding="utf-8"))
        schema = None
        if args.schema:
            schema = json.loads(Path(args.schema).read_text(encoding="utf-8"))
        result = create_dataset(
            args.dataset_id,
            args.name,
            cases,
            description=args.description,
            schema=schema,
            base_dir=args.base_dir,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif args.command == "create-version":
        result = create_version(args.dataset_id, base_dir=args.base_dir)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif args.command == "read":
        data = read_version(args.dataset_id, args.version_hash, base_dir=args.base_dir)
        print(json.dumps(data, ensure_ascii=False, indent=2) if data is not None else "null")
    elif args.command == "list":
        items = list_versions(args.dataset_id, base_dir=args.base_dir)
        print(json.dumps(items, ensure_ascii=False, indent=2))
    elif args.command == "diff":
        fields = args.fields.split(",") if args.fields else None
        result = diff_versions(
            args.dataset_id,
            args.version_a,
            args.version_b,
            fields=fields,
            base_dir=args.base_dir,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif args.command == "migrate":
        result = migrate_from_file(
            args.source,
            args.dataset_id,
            args.name,
            description=args.description,
            base_dir=args.base_dir,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
