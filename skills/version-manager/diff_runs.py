"""
diff_runs.py — 对比两次 Run，输出 Markdown 报告。

用法:
    python3 skills/version-manager/diff_runs.py --run-a run_001 --run-b run_002
"""
import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent


def _load_json(run_id, fname):
    p = REPO_ROOT / "data" / "runs" / run_id / fname
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text("utf-8"))
    except Exception:
        return {}


def _diff_dicts(d1, d2, prefix=""):
    """递归比较两个 dict，返回变化列表"""
    changes = []
    for k in sorted(set(list(d1.keys()) + list(d2.keys()))):
        full_key = f"{prefix}.{k}" if prefix else k
        v1 = d1.get(k, "<不存在>")
        v2 = d2.get(k, "<不存在>")
        if isinstance(v1, dict) and isinstance(v2, dict):
            changes.extend(_diff_dicts(v1, v2, full_key))
        elif v1 != v2:
            changes.append({"key": full_key, "before": v1, "after": v2})
    return changes


def main():
    parser = argparse.ArgumentParser(description="对比两次 Run")
    parser.add_argument("--run-a", required=True, help="基准 Run ID")
    parser.add_argument("--run-b", required=True, help="对比 Run ID")
    args = parser.parse_args()

    meta_a = _load_json(args.run_a, "meta.json")
    meta_b = _load_json(args.run_b, "meta.json")
    config_a = _load_json(args.run_a, "config.json")
    config_b = _load_json(args.run_b, "config.json")
    dataset_a = _load_json(args.run_a, "dataset_ref.json")
    dataset_b = _load_json(args.run_b, "dataset_ref.json")
    results_a = _load_json(args.run_a, "results.json")
    results_b = _load_json(args.run_b, "results.json")

    if not meta_a and not meta_b:
        print(f"❌ 找不到 {args.run_a} 或 {args.run_b} 的数据", file=sys.stderr)
        sys.exit(1)

    score_a = meta_a.get("overall_score", 0)
    score_b = meta_b.get("overall_score", 0)
    delta = score_b - score_a
    delta_icon = "🔺" if delta > 0 else ("🔻" if delta < 0 else "➡️")

    lines = [
        f"# Run 对比报告",
        f"",
        f"| | {args.run_a} | {args.run_b} |",
        f"|---|---|---|",
        f"| 时间 | {meta_a.get('timestamp', 'N/A')[:19]} | {meta_b.get('timestamp', 'N/A')[:19]} |",
        f"| 项目 | {meta_a.get('project', 'N/A')} | {meta_b.get('project', 'N/A')} |",
        f"| 触发方式 | {meta_a.get('triggered_by', 'N/A')} | {meta_b.get('triggered_by', 'N/A')} |",
        f"| 总分 | {score_a:.4f} | {score_b:.4f} |",
        f"| 变化 | | {delta_icon} {delta:+.4f} |",
        f"| 状态 | {meta_a.get('status', 'N/A')} | {meta_b.get('status', 'N/A')} |",
        f"",
    ]

    # 字段分数对比
    fields_a = meta_a.get("fields", {})
    fields_b = meta_b.get("fields", {})
    all_fields = sorted(set(list(fields_a.keys()) + list(fields_b.keys())))
    if all_fields:
        lines += ["## 字段分数对比", ""]
        lines += [f"| 字段 | {args.run_a} | {args.run_b} | 变化 |", "|---|---|---|---|"]
        for field in all_fields:
            fa = fields_a.get(field, 0) or 0
            fb = fields_b.get(field, 0) or 0
            d = fb - fa
            icon = "🔺" if d > 0.01 else ("🔻" if d < -0.01 else "➡️")
            lines.append(f"| {field} | {fa:.4f} | {fb:.4f} | {icon} {d:+.4f} |")
        lines.append("")

    # Dataset 对比
    lines += ["## 数据集对比", ""]
    if dataset_a.get("sha256") == dataset_b.get("sha256") and dataset_a.get("sha256"):
        lines.append("✅ 两次 Run 使用相同数据集")
    else:
        lines.append("⚠️ 数据集不同")
        lines.append(f"- {args.run_a}: `{dataset_a.get('source', 'N/A')}` sha256前8位: `{str(dataset_a.get('sha256',''))[:8]}`")
        lines.append(f"- {args.run_b}: `{dataset_b.get('source', 'N/A')}` sha256前8位: `{str(dataset_b.get('sha256',''))[:8]}`")
    lines.append("")

    # Config diff
    config_changes = _diff_dicts(config_a, config_b)
    lines += ["## 配置变更", ""]
    if not config_changes:
        lines.append("✅ 配置无变化")
    else:
        lines += [f"| 配置项 | 变更前 | 变更后 |", "|---|---|---|"]
        for ch in config_changes:
            lines.append(f"| `{ch['key']}` | `{ch['before']}` | `{ch['after']}` |")
    lines.append("")

    report = "\n".join(lines)
    print(report)


if __name__ == "__main__":
    main()
