"""run_store — Agent-native Run submission, query, and comparison.

Wraps run_manifest, enrich_report, and mini_json_schema to provide a
structured API for run management. Never raises exceptions — all errors
are returned as structured {ok, error} responses.

Usage:
    from run_store import RunStore

    store = RunStore()
    result = store.submit(report=report_dict, manifest=manifest_dict)
"""

from __future__ import annotations

import json
import re
import sys
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

from mini_json_schema import validate as _js_validate, UnsupportedKeywordError
import run_manifest as rm
import enrich_report

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_RUNS_DIR = REPO_ROOT / "data" / "runs"

# ── Report Schema（设计 §3.3）────────────────────────────────────────────────

REPORT_SCHEMA = {
    "type": "object",
    "required": ["skill", "created_at", "n_cases", "overall_score", "fields", "cases"],
    "properties": {
        "skill": {"type": "string", "minLength": 1},
        "created_at": {"type": "string", "minLength": 1},
        "n_cases": {"type": "integer", "minimum": 0},
        "n_passed": {"type": "integer", "minimum": 0},
        "pass_rate": {"type": "number", "minimum": 0.0, "maximum": 1.0},
        "overall_score": {"type": "number", "minimum": 0.0, "maximum": 1.0},
        "grade": {"type": "string"},
        "manifest_hash": {"type": "string"},
        "fields": {"type": "object"},
        "cases": {"type": "array"},
        "bad_cases": {"type": "array"},
        "config": {"type": "object"},
    },
}


# ── Structured error helpers ─────────────────────────────────────────────────

def _error(code, message, details=None):
    """Build a structured error response."""
    result = {"ok": False, "error": {"code": code, "message": message}}
    if details is not None:
        result["error"]["details"] = details
    return result


def _ok(**data):
    """Build a success response."""
    return {"ok": True, "data": data}


# ── Internal helpers ─────────────────────────────────────────────────────────

def _generate_run_id(runs_dir):
    """Generate run_YYYYMMDD_NNN based on today's existing runs."""
    today = datetime.now(timezone.utc).strftime("%Y%m%d")
    prefix = f"run_{today}_"
    max_n = 0
    if runs_dir.is_dir():
        for d in runs_dir.iterdir():
            if d.is_dir() and d.name.startswith(prefix):
                try:
                    n = int(d.name[len(prefix):])
                    if n > max_n:
                        max_n = n
                except ValueError:
                    pass
    return f"{prefix}{max_n + 1:03d}"


def _build_meta(run_id, manifest, report):
    """Build meta.json summary dict."""
    ds = manifest.get("dataset") or {}
    skill = manifest.get("skill") or {}
    return {
        "run_id": run_id,
        "project": skill.get("name") or ds.get("dataset_id"),
        "triggered_by": manifest.get("triggered_by", "agent"),
        "timestamp": manifest.get("created_at", ""),
        "status": "completed",
        "overall_score": report.get("overall_score"),
        "pass_rate": report.get("pass_rate"),
        "fields": {
            k: {"field_score": v.get("field_score") if isinstance(v, dict) else v}
            for k, v in report.get("fields", {}).items()
        },
        "metrics": [m.get("metric_id") for m in manifest.get("metrics", [])],
    }


def _extract_config(report, manifest):
    """Extract config.json from report or manifest."""
    config = report.get("config")
    if config and isinstance(config, dict):
        return config
    extra = manifest.get("extra", {})
    if extra:
        return extra
    return {}


def _build_dataset_ref(manifest):
    """Build dataset_ref.json from manifest's dataset."""
    ds = manifest.get("dataset") or {}
    return {
        "n_cases": ds.get("n_cases", 0),
        "dataset_id": ds.get("dataset_id"),
        "version_hash": ds.get("version_hash"),
        "content_hash": ds.get("content_hash"),
        "source_path": ds.get("source_path"),
    }


def _diff_dicts(a, b):
    """Recursively diff two dicts. Returns a dict of differences."""
    diffs = {}
    all_keys = set(a.keys()) | set(b.keys())
    for key in all_keys:
        va = a.get(key)
        vb = b.get(key)
        if isinstance(va, dict) and isinstance(vb, dict):
            nested = _diff_dicts(va, vb)
            if nested:
                diffs[key] = nested
        elif va != vb:
            diffs[key] = {"a": va, "b": vb}
    return diffs


# ── RunStore ─────────────────────────────────────────────────────────────────

class RunStore:
    """Agent-native run management with structured error handling.

    All methods return {ok: bool, data?: dict, error?: {code, message, details?}}.
    Never raises exceptions.
    """

    def __init__(self, runs_dir=None):
        self.runs_dir = Path(runs_dir) if runs_dir else DEFAULT_RUNS_DIR

    # ── submit（设计 §4）─────────────────────────────────────────────────

    def submit(self, report, manifest, triggered_by="agent", run_id=None):
        """Submit a run. Accepts report dict and manifest dict directly.

        Returns:
            {ok, data: {run_id, manifest_hash, overall_score, status, pass_rate}}
            or {ok: false, error: {code, message, details?}}
        """
        try:
            # 0. Validate triggered_by
            if triggered_by not in ("agent", "ui"):
                return _error("VALIDATION_ERROR", f"triggered_by 必须是 'agent' 或 'ui'，实际为 '{triggered_by}'")

            # 0.5 Validate run_id format if provided
            if run_id is not None and not re.match(r"^run_\d{8}_\d{3}$", run_id):
                return _error(
                    "VALIDATION_ERROR",
                    f"run_id 格式无效: '{run_id}'，期望格式 run_YYYYMMDD_NNN",
                )

            # 1. Validate report schema
            report_errors = _js_validate(report, REPORT_SCHEMA)
            if report_errors:
                return _error("VALIDATION_ERROR", "report schema 验证失败", report_errors)

            # 2. Validate manifest schema
            manifest_errors = rm.validate_manifest(manifest)
            if manifest_errors:
                return _error("VALIDATION_ERROR", "manifest schema 验证失败", manifest_errors)

            # 3. Verify manifest_hash consistency
            expected_hash = rm.compute_manifest_hash(manifest)
            actual_hash = manifest.get("manifest_hash", "")
            if actual_hash != expected_hash:
                return _error(
                    "MANIFEST_MISMATCH",
                    f"manifest_hash 不匹配: 期望 {expected_hash[:8]}..., "
                    f"实际 {actual_hash[:8] if actual_hash else '无'}...",
                )

            # 4. Generate run_id if not provided
            if run_id is None:
                run_id = _generate_run_id(self.runs_dir)

            # 5. Check run_id doesn't already exist
            run_dir = self.runs_dir / run_id
            if run_dir.exists():
                return _error("DUPLICATE_RUN", f"run_id {run_id} 已存在")

            # 6. Inject manifest_hash into report
            report = deepcopy(report)
            report["manifest_hash"] = expected_hash

            # 7. Enrich report
            enriched = enrich_report.enrich(report)

            # 8. Create run directory
            run_dir.mkdir(parents=True, exist_ok=False)

            # 9. Write manifest.json
            manifest_with_hash = deepcopy(manifest)
            manifest_with_hash["manifest_hash"] = expected_hash
            (run_dir / "manifest.json").write_text(
                json.dumps(manifest_with_hash, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

            # 10. Write results.json (enriched report)
            (run_dir / "results.json").write_text(
                json.dumps(enriched, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

            # 11. Generate and write meta.json
            meta = _build_meta(run_id, manifest, report)
            (run_dir / "meta.json").write_text(
                json.dumps(meta, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

            # 12. Generate and write config.json
            config = _extract_config(report, manifest)
            (run_dir / "config.json").write_text(
                json.dumps(config, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

            # 13. Generate and write dataset_ref.json
            dataset_ref = _build_dataset_ref(manifest)
            (run_dir / "dataset_ref.json").write_text(
                json.dumps(dataset_ref, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

            # 14. Return structured result
            return _ok(
                run_id=run_id,
                manifest_hash=expected_hash,
                overall_score=report.get("overall_score"),
                status="completed",
                pass_rate=report.get("pass_rate"),
            )

        except (UnsupportedKeywordError, ValueError) as exc:
            return _error("VALIDATION_ERROR", f"schema 校验异常: {exc}")
        except Exception as exc:
            return _error("INVALID_REPORT", f"submit 失败: {exc}")

    # ── get（设计 §5.1）──────────────────────────────────────────────────

    def get(self, run_id):
        """Read all files from a run directory.

        Returns:
            {ok, data: {run_id, meta, manifest, results, config, dataset_ref}}
        """
        run_dir = self.runs_dir / run_id
        if not run_dir.is_dir():
            return _error("NOT_FOUND", f"run_id {run_id} 不存在")

        try:
            result = {"run_id": run_id}
            for filename in ("meta", "manifest", "results", "config", "dataset_ref"):
                filepath = run_dir / f"{filename}.json"
                if filepath.exists():
                    result[filename] = json.loads(filepath.read_text(encoding="utf-8"))
                else:
                    result[filename] = None
            return _ok(**result)
        except Exception as exc:
            return _error("INVALID_REPORT", f"读取 run {run_id} 失败: {exc}")

    # ── list（设计 §5.2）─────────────────────────────────────────────────

    def list(self, project=None, limit=20):
        """List runs, optionally filtered by project.

        Returns:
            {ok, data: [{run_id, project, status, overall_score, timestamp}]}
        """
        if not self.runs_dir.is_dir():
            return {"ok": True, "data": []}

        runs = []
        for run_dir in self.runs_dir.iterdir():
            if not run_dir.is_dir():
                continue
            meta_path = run_dir / "meta.json"
            if not meta_path.exists():
                continue
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
            except Exception:
                continue

            if project is not None and meta.get("project") != project:
                continue

            runs.append({
                "run_id": meta.get("run_id", run_dir.name),
                "project": meta.get("project"),
                "status": meta.get("status"),
                "overall_score": meta.get("overall_score"),
                "timestamp": meta.get("timestamp"),
            })

        # Sort by timestamp descending (newest first)
        runs.sort(key=lambda r: r.get("timestamp") or "", reverse=True)

        return {"ok": True, "data": runs[:limit]}

    # ── compare（设计 §5.3）──────────────────────────────────────────────

    def compare(self, run_id_a, run_id_b):
        """Compare two runs.

        Returns:
            {ok, data: {score_delta, field_diffs, config_diff, dataset_check}}
        """
        result_a = self.get(run_id_a)
        if not result_a["ok"]:
            return result_a

        result_b = self.get(run_id_b)
        if not result_b["ok"]:
            return result_b

        data_a = result_a["data"]
        data_b = result_b["data"]

        meta_a = data_a.get("meta") or {}
        meta_b = data_b.get("meta") or {}

        config_a = data_a.get("config") or {}
        config_b = data_b.get("config") or {}

        dataset_a = data_a.get("dataset_ref") or {}
        dataset_b = data_b.get("dataset_ref") or {}

        score_a = meta_a.get("overall_score", 0)
        score_b = meta_b.get("overall_score", 0)
        score_delta = round(score_b - score_a, 6)

        # Field-level diffs
        fields_a = meta_a.get("fields") or {}
        fields_b = meta_b.get("fields") or {}
        field_diffs = {}
        all_fields = set(fields_a.keys()) | set(fields_b.keys())
        for field in all_fields:
            fa = fields_a.get(field, {})
            fb = fields_b.get(field, {})
            if isinstance(fa, dict) and isinstance(fb, dict):
                sa = fa.get("field_score", 0)
                sb = fb.get("field_score", 0)
                if sa != sb:
                    field_diffs[field] = {"a": sa, "b": sb, "delta": round(sb - sa, 6)}
            else:
                if fa != fb:
                    field_diffs[field] = {"a": fa, "b": fb}

        # Config diff
        config_diff = _diff_dicts(config_a, config_b)

        # Dataset check
        dataset_check = {
            "same_dataset": dataset_a.get("dataset_id") == dataset_b.get("dataset_id"),
            "same_version": dataset_a.get("version_hash") == dataset_b.get("version_hash"),
            "same_content": dataset_a.get("content_hash") == dataset_b.get("content_hash"),
        }

        return _ok(
            score_delta=score_delta,
            field_diffs=field_diffs,
            config_diff=config_diff,
            dataset_check=dataset_check,
        )


# ── CLI（设计 §6）────────────────────────────────────────────────────────────

def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="RunStore — Agent-native run submission, query, and comparison"
    )
    parser.add_argument("--runs-dir", default=None, help="runs 目录（默认 data/runs）")
    sub = parser.add_subparsers(dest="command", help="子命令")

    # submit
    p_submit = sub.add_parser("submit", help="提交一个 run")
    p_submit.add_argument("--report", help="eval_report.json 的路径")
    p_submit.add_argument(
        "--stdin-report", action="store_true", help="从 stdin 读取 report"
    )
    p_submit.add_argument("--manifest", required=True, help="manifest.json 的路径")
    p_submit.add_argument("--triggered-by", default="agent", help="触发者（默认 agent）")
    p_submit.add_argument("--run-id", default=None, help="指定 run_id（不指定则自动生成）")

    # get
    p_get = sub.add_parser("get", help="获取一个 run")
    p_get.add_argument("--run-id", required=True, help="run_id")

    # list
    p_list = sub.add_parser("list", help="列出 runs")
    p_list.add_argument("--project", default=None, help="按 project 过滤")
    p_list.add_argument("--limit", type=int, default=20, help="最大返回数（默认 20）")

    # compare
    p_compare = sub.add_parser("compare", help="对比两个 runs")
    p_compare.add_argument("--run-a", required=True, help="第一个 run_id")
    p_compare.add_argument("--run-b", required=True, help="第二个 run_id")

    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        sys.exit(1)

    store = RunStore(runs_dir=args.runs_dir)

    if args.command == "submit":
        if args.stdin_report:
            report = json.loads(sys.stdin.read())
        elif args.report:
            report = json.loads(Path(args.report).read_text(encoding="utf-8"))
        else:
            print("Error: 需要 --report 或 --stdin-report", file=sys.stderr)
            sys.exit(1)
        manifest = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
        result = store.submit(report, manifest, args.triggered_by, args.run_id)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        sys.exit(0 if result["ok"] else 1)

    elif args.command == "get":
        result = store.get(args.run_id)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        sys.exit(0 if result["ok"] else 1)

    elif args.command == "list":
        result = store.list(args.project, args.limit)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        sys.exit(0 if result["ok"] else 1)

    elif args.command == "compare":
        result = store.compare(args.run_a, args.run_b)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        sys.exit(0 if result["ok"] else 1)


if __name__ == "__main__":
    main()