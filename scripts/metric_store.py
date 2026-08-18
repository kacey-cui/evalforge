"""Metric Store — Agent-native API for metric management.

Wraps ``metric_versioning`` with schema validation, structured error returns,
and a unified ``MetricStore`` class.  Provides both Python API and CLI.

Usage:
    from metric_store import MetricStore
    store = MetricStore()
    result = store.create(metric_dict)
"""

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

from mini_json_schema import validate
from metric_versioning import (
    compute_version_hash,
    create_version,
    read_version,
    list_versions,
    diff_versions,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_BASE_DIR = REPO_ROOT / "data" / "metrics"
CATEGORIES = ("llm", "non_llm")

# ── Schema ─────────────────────────────────────────────────────────────

METRIC_SCHEMA = {
    "type": "object",
    "required": ["id", "name", "category", "params", "requires", "code_template"],
    "properties": {
        "id": {"type": "string", "minLength": 1},
        "name": {"type": "string", "minLength": 1},
        "category": {"type": "string", "enum": ["llm", "non_llm"]},
        "description": {"type": "string"},
        "params": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["key", "type", "default"],
                "properties": {
                    "key": {"type": "string"},
                    "label": {"type": "string"},
                    "type": {
                        "type": "string",
                        "enum": ["string", "number", "boolean", "json", "select"],
                    },
                    "default": {},
                    "required": {"type": "boolean"},
                    "min": {"type": "number"},
                    "max": {"type": "number"},
                    "step": {"type": "number"},
                    "options": {"type": "array"},
                },
            },
        },
        "criteria": {"oneOf": [{"type": "string"}, {"type": "null"}]},
        "requires": {"type": "array", "items": {"type": "string"}},
        "code_template": {"type": "string", "minLength": 1},
    },
}

# ── Helpers ────────────────────────────────────────────────────────────


def _error(code, message, details=None):
    """Build a structured error dict."""
    err = {"ok": False, "error": {"code": code, "message": message}}
    if details is not None:
        err["error"]["details"] = details
    return err


def _ok(data):
    """Build a structured success dict."""
    return {"ok": True, "data": data}


def _resolve_base(base_dir):
    """Resolve base_dir to a Path, defaulting to the repo data/metrics."""
    return Path(base_dir) if base_dir is not None else DEFAULT_BASE_DIR


# ── MetricStore ────────────────────────────────────────────────────────


class MetricStore:
    """Unified API for metric CRUD + versioning.

    All public methods return ``{ok: bool, data?: dict, error?: {code, message, details?}}``.
    No exceptions are raised for business-logic errors.
    """

    def __init__(self, base_dir=None):
        self.base_dir = _resolve_base(base_dir)

    # ── Internal helpers ────────────────────────────────────────────

    def _find_metric_file(self, metric_id):
        """Search both llm/ and non_llm/ for ``{metric_id}.json``.  Returns the Path or None."""
        for cat in CATEGORIES:
            f = self.base_dir / cat / f"{metric_id}.json"
            if f.is_file():
                return f
        return None

    def _read_metric_file(self, metric_id):
        """Read the current metric definition from disk.  Returns (dict, path) or (None, None)."""
        f = self._find_metric_file(metric_id)
        if f is None:
            return None, None
        try:
            return json.loads(f.read_text(encoding="utf-8")), f
        except Exception:
            return None, None

    def _validate(self, metric_dict):
        """Run schema validation.  Returns list of error strings (empty = pass)."""
        return validate(metric_dict, METRIC_SCHEMA)

    # ── Public API ──────────────────────────────────────────────────

    def create(self, metric_dict):
        """Create a new metric from a dict.

        Validates schema, checks for duplicate id, writes the file, and creates
        the initial version snapshot.

        Returns ``{ok: true, data: {metric_id, version_hash, created_at, is_new}}``
        on success, or ``{ok: false, error: {code, message, details?}}`` on failure.
        """
        if not isinstance(metric_dict, dict):
            return _error("VALIDATION_ERROR", "metric 必须是 JSON 对象（dict）")

        # 1. Schema validation
        errs = self._validate(metric_dict)
        if errs:
            return _error("VALIDATION_ERROR", "schema 验证失败", details=errs)

        metric_id = metric_dict["id"]
        category = metric_dict["category"]

        # 1.5 Validate metric_id format (no special chars that break file paths)
        if not re.match(r'^[a-zA-Z0-9_-]+$', metric_id):
            return _error("VALIDATION_ERROR", f"metric_id 包含非法字符: '{metric_id}'")

        # 2. Check duplicate
        if self._find_metric_file(metric_id) is not None:
            return _error(
                "DUPLICATE_ID",
                f"metric_id '{metric_id}' 已存在，请使用 create_version 更新",
            )

        # 3. Write metric file
        cat_dir = self.base_dir / category
        cat_dir.mkdir(parents=True, exist_ok=True)
        file_path = cat_dir / f"{metric_id}.json"
        file_path.write_text(
            json.dumps(metric_dict, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        # 4. Create version snapshot
        result = create_version(str(file_path), base_dir=self.base_dir)

        return _ok(
            {
                "metric_id": metric_id,
                "version_hash": result["version_hash"],
                "created_at": result["created_at"],
                "is_new": True,
            }
        )

    def get(self, metric_id):
        """Read the current metric definition.

        Returns ``{ok: true, data: {<metric definition>}}`` on success,
        or ``{ok: false, error: {code: "NOT_FOUND"}}`` if not found.
        """
        metric, _ = self._read_metric_file(metric_id)
        if metric is None:
            return _error("NOT_FOUND", f"metric '{metric_id}' 不存在")
        return _ok(metric)

    def list_metrics(self):
        """List all metrics across both categories.

        Returns ``{ok: true, data: [{metric_id, name, category, version_hash}]}``.
        """
        results = []
        for cat in CATEGORIES:
            cat_dir = self.base_dir / cat
            if not cat_dir.is_dir():
                continue
            for f in sorted(cat_dir.glob("*.json")):
                try:
                    metric = json.loads(f.read_text(encoding="utf-8"))
                except Exception:
                    continue
                if not isinstance(metric, dict):
                    continue
                metric_id = metric.get("id") or metric.get("metric_id")
                if not metric_id:
                    continue
                try:
                    vh = compute_version_hash(metric)
                except Exception:
                    continue
                results.append(
                    {
                        "metric_id": metric_id,
                        "name": metric.get("name", ""),
                        "category": metric.get("category", cat),
                        "version_hash": vh,
                    }
                )
        return _ok(results)

    def create_version(self, metric_id, new_metric_dict):
        """Create a new version for an existing metric.

        Validates schema, checks the metric exists, verifies the id wasn't changed,
        overwrites the current file, and creates a version snapshot.

        Returns ``{ok: true, data: {metric_id, version_hash, is_new}}`` on success.
        ``is_new`` is False when the hash is unchanged (idempotent).
        """
        if not isinstance(new_metric_dict, dict):
            return _error("VALIDATION_ERROR", "metric 必须是 JSON 对象（dict）")

        # 1. Schema validation
        errs = self._validate(new_metric_dict)
        if errs:
            return _error("VALIDATION_ERROR", "schema 验证失败", details=errs)

        # 1.5 Validate metric_id format (no special chars that break file paths)
        if not re.match(r'^[a-zA-Z0-9_-]+$', metric_id):
            return _error("VALIDATION_ERROR", f"metric_id 包含非法字符: '{metric_id}'")

        # 2. Check metric exists
        existing_file = self._find_metric_file(metric_id)
        if existing_file is None:
            return _error("NOT_FOUND", f"metric '{metric_id}' 不存在，请先使用 create")

        # 3. Check id wasn't changed
        if new_metric_dict.get("id") != metric_id:
            return _error(
                "VALIDATION_ERROR",
                f"不允许修改 metric_id：原值 '{metric_id}'，新值 '{new_metric_dict.get('id')}'",
            )

        # 4. Overwrite current file
        existing_file.write_text(
            json.dumps(new_metric_dict, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        # 5. Delegate to metric_versioning.create_version
        result = create_version(str(existing_file), base_dir=self.base_dir)

        return _ok(
            {
                "metric_id": metric_id,
                "version_hash": result["version_hash"],
                "is_new": result["is_new"],
            }
        )

    def get_version(self, metric_id, version_hash):
        """Read a specific version snapshot.

        Returns ``{ok: true, data: {<version record>}}`` on success,
        or ``{ok: false, error: {code: "NOT_FOUND"}}`` if not found.
        """
        data = read_version(metric_id, version_hash, base_dir=self.base_dir, category=None)
        if data is None:
            return _error(
                "NOT_FOUND",
                f"版本不存在：metric_id='{metric_id}', version_hash='{version_hash}'",
            )
        return _ok(data)

    def list_versions(self, metric_id):
        """List all versions of a metric.

        Returns ``{ok: true, data: [{metric_id, version_hash, created_at, name}]}``.
        """
        items = list_versions(metric_id, base_dir=self.base_dir, category=None)
        return _ok(items)

    def diff_versions(self, metric_id, hash_a, hash_b):
        """Diff two versions of a metric.

        Returns ``{ok: true, data: {changes, added_fields, removed_fields, modified_fields}}``
        on success, or ``{ok: false, error: {code: "NOT_FOUND"}}`` if either version is missing.
        """
        try:
            result = diff_versions(
                metric_id, hash_a, hash_b, base_dir=self.base_dir, category=None
            )
        except ValueError as exc:
            return _error("NOT_FOUND", str(exc))
        return _ok(result)


# ── CLI ────────────────────────────────────────────────────────────────


def _cli_output(result):
    """Print a result dict as JSON to stdout."""
    print(json.dumps(result, ensure_ascii=False, indent=2))


def _parse_metric_json(raw):
    """Parse a metric JSON string from a CLI positional argument."""
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        return _error("VALIDATION_ERROR", f"无法解析 JSON: {exc}")


def main():
    parser = argparse.ArgumentParser(
        prog="metric_store",
        description="Agent-native metric management API",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # create
    p_create = sub.add_parser("create", help="创建新 metric")
    p_create.add_argument(
        "metric_json",
        help="metric 定义的 JSON 字符串",
    )
    p_create.add_argument(
        "--base-dir",
        default=None,
        help="指标根目录（默认 data/metrics/）",
    )

    # get
    p_get = sub.add_parser("get", help="获取当前 metric 定义")
    p_get.add_argument("--metric-id", required=True, help="metric ID")
    p_get.add_argument("--base-dir", default=None, help="指标根目录")

    # list
    p_list = sub.add_parser("list", help="列出所有 metric")
    p_list.add_argument("--base-dir", default=None, help="指标根目录")

    # create-version
    p_cv = sub.add_parser("create-version", help="为已有 metric 创建新版本")
    p_cv.add_argument("--metric-id", required=True, help="metric ID")
    p_cv.add_argument(
        "metric_json",
        help="新 metric 定义的 JSON 字符串",
    )
    p_cv.add_argument("--base-dir", default=None, help="指标根目录")

    # get-version
    p_gv = sub.add_parser("get-version", help="获取指定版本")
    p_gv.add_argument("--metric-id", required=True, help="metric ID")
    p_gv.add_argument("--version-hash", required=True, help="版本哈希")
    p_gv.add_argument("--base-dir", default=None, help="指标根目录")

    # list-versions
    p_lv = sub.add_parser("list-versions", help="列出某 metric 的所有版本")
    p_lv.add_argument("--metric-id", required=True, help="metric ID")
    p_lv.add_argument("--base-dir", default=None, help="指标根目录")

    # diff
    p_diff = sub.add_parser("diff", help="对比两个版本")
    p_diff.add_argument("--metric-id", required=True, help="metric ID")
    p_diff.add_argument("--version-a", required=True, help="版本 A 的哈希")
    p_diff.add_argument("--version-b", required=True, help="版本 B 的哈希")
    p_diff.add_argument("--base-dir", default=None, help="指标根目录")

    args = parser.parse_args()
    store = MetricStore(base_dir=args.base_dir)

    if args.command == "create":
        result = _parse_metric_json(args.metric_json)
        if isinstance(result, dict) and "ok" in result and result["ok"] is False:
            _cli_output(result)
            return
        _cli_output(store.create(result))

    elif args.command == "get":
        _cli_output(store.get(args.metric_id))

    elif args.command == "list":
        _cli_output(store.list_metrics())

    elif args.command == "create-version":
        result = _parse_metric_json(args.metric_json)
        if isinstance(result, dict) and "ok" in result and result["ok"] is False:
            _cli_output(result)
            return
        _cli_output(store.create_version(args.metric_id, result))

    elif args.command == "get-version":
        _cli_output(store.get_version(args.metric_id, args.version_hash))

    elif args.command == "list-versions":
        _cli_output(store.list_versions(args.metric_id))

    elif args.command == "diff":
        _cli_output(store.diff_versions(args.metric_id, args.version_a, args.version_b))


if __name__ == "__main__":
    main()