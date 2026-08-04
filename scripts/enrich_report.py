"""
enrich_report.py — 通用报告丰富化引擎

读取标准 eval_report.json，自动检测指标模式，生成 summary_charts 和 summary_tables。
支持的模式：
  - Recall@k 系列指标 → Recall@k 折线图
  - MRR 指标 → MRR 分布直方图
  - 故障码 expected_output → 按域分拆柱状图
  - 任意指标 → 指标均值汇总柱状图
  - 总是生成：总分分布直方图、失败案例表、逐案明细表

CLI 用法：
    python3 scripts/enrich_report.py data/runs/run_001/results.json
    python3 scripts/enrich_report.py data/runs/run_001/results.json --config my_config.json

作为库导入：
    from scripts.enrich_report import enrich
    enriched = enrich(report_dict)
"""
import argparse
import json
import re
import sys
from collections import defaultdict
from copy import deepcopy
from pathlib import Path


# ─── 核心入口 ─────────────────────────────────────────────────────────────────

def enrich(report: dict, config: dict = None) -> dict:
    """
    接受标准 eval_report.json dict，返回注入 summary_charts + summary_tables 的新 dict。
    不修改原始 report 对象。
    config 可选，支持键：
      domain_field (str): 从 cases 的哪个字段提取域，默认 "expected_output"
      domain_extract (str): "prefix5" | "auto" | "none"，默认 "auto"
      domain_label (str): 图表 x 轴标签，默认 "域"
    """
    config = config or {}
    result = deepcopy(report)

    cases = result.get("cases", [])
    field_summaries = result.get("fields", {})  # {field_name: {field_score, metrics[{name, mean}]}}

    charts = []
    tables = []

    for field_name, field_data in field_summaries.items():
        field_metrics = field_data.get("metrics", [])  # [{name, mean}]
        metric_names = [m["name"] for m in field_metrics]

        # ── 1. Recall@k 折线图 ────────────────────────────────────────────────
        recall_pairs = []
        for m in field_metrics:
            match = re.match(r"Recall@(\d+)", m["name"])
            if match:
                recall_pairs.append((int(match.group(1)), m["mean"], m["name"]))
        if recall_pairs:
            recall_pairs.sort(key=lambda x: x[0])
            charts.append({
                "id": f"{field_name}_recall_curve",
                "type": "line",
                "title": f"Recall@k 曲线（{field_name}）",
                "x_label": "k（召回数量）",
                "y_label": "Recall",
                "y_min": 0.0,
                "y_max": 1.0,
                "series": [{
                    "label": "整体",
                    "color": "#4f46e5",
                    "points": [
                        {"x": k, "y": round(mean, 4), "label": name}
                        for k, mean, name in recall_pairs
                    ]
                }]
            })

        # ── 2. MRR 分布直方图 ─────────────────────────────────────────────────
        if any(m["name"] == "MRR" for m in field_metrics):
            mrr_scores = []
            for case in cases:
                for m in case.get("fields", {}).get(field_name, {}).get("metrics", []):
                    if m["name"] == "MRR":
                        mrr_scores.append(m.get("score", 0))
            if mrr_scores:
                charts.append({
                    "id": f"{field_name}_mrr_dist",
                    "type": "histogram",
                    "title": f"MRR 分布（{field_name}）",
                    "x_label": "MRR 值",
                    "y_label": "案例数",
                    "bins": _make_bins(mrr_scores, n=10, lo=0.0, hi=1.0)
                })

        # ── 3. 任意指标均值汇总柱状图 ─────────────────────────────────────────
        if len(field_metrics) > 1:
            charts.append({
                "id": f"{field_name}_metric_summary",
                "type": "bar",
                "title": f"指标均值汇总（{field_name}）",
                "x_label": "指标",
                "y_label": "均值",
                "y_min": 0.0,
                "y_max": 1.0,
                "series": [{
                    "label": "均值",
                    "color": "#22c55e",
                    "points": [
                        {"x": m["name"], "y": round(m["mean"], 4)}
                        for m in field_metrics
                    ]
                }]
            })

        # ── 4. 按域分拆 Recall@10（如果有的话）────────────────────────────────
        domain_field = config.get("domain_field", "expected_output")
        domain_extract = config.get("domain_extract", "auto")
        domain_label = config.get("domain_label", "域")

        if domain_extract == "auto":
            samples = [c.get(domain_field, "") for c in cases[:20] if c.get(domain_field)]
            code_count = sum(1 for s in samples if re.match(r"[A-Z]{3}\d{5,}", s))
            domain_extract = "prefix5" if code_count >= min(3, len(samples)) else "none"

        if domain_extract == "prefix5" and cases:
            # 找最高 k 的 Recall 指标（如有 Recall@10 优先，否则用最大 k）
            recall_metric_name = None
            best_k = -1
            for mname in metric_names:
                m2 = re.match(r"Recall@(\d+)", mname)
                if m2 and int(m2.group(1)) > best_k:
                    best_k = int(m2.group(1))
                    recall_metric_name = mname
            # 偏好 Recall@10
            if "Recall@10" in metric_names:
                recall_metric_name = "Recall@10"

            if recall_metric_name:
                domain_scores: dict = defaultdict(list)
                for case in cases:
                    expected = case.get(domain_field, "")
                    if not expected or not re.match(r"[A-Z]{3}\d{5,}", expected):
                        continue
                    domain = expected[:5]
                    for m in case.get("fields", {}).get(field_name, {}).get("metrics", []):
                        if m["name"] == recall_metric_name:
                            domain_scores[domain].append(m.get("score", 0))

                if domain_scores:
                    points = sorted(
                        [{"x": d, "y": round(sum(v) / len(v), 4), "n": len(v)}
                         for d, v in domain_scores.items()],
                        key=lambda p: -p["y"]
                    )
                    charts.append({
                        "id": f"{field_name}_domain_breakdown",
                        "type": "bar",
                        "title": f"各{domain_label} {recall_metric_name}",
                        "x_label": domain_label,
                        "y_label": recall_metric_name,
                        "y_min": 0.0,
                        "y_max": 1.0,
                        "series": [{"label": recall_metric_name, "color": "#f59e0b", "points": points}]
                    })

    # ── 5. 总分分布直方图（全局） ─────────────────────────────────────────────
    all_scores = [c.get("overall_score", 0) for c in cases if c.get("overall_score") is not None]
    if all_scores:
        charts.append({
            "id": "overall_score_dist",
            "type": "histogram",
            "title": "总分分布",
            "x_label": "得分",
            "y_label": "案例数",
            "bins": _make_bins(all_scores, n=10, lo=0.0, hi=1.0)
        })

    # ── 6. 失败案例表 ─────────────────────────────────────────────────────────
    bad_cases_raw = [c for c in cases if not c.get("passed", True)]
    if bad_cases_raw:
        # 收集所有字段的所有指标名（用于表头）
        all_metric_names: list = []
        for field_name2 in field_summaries:
            for m in field_summaries[field_name2].get("metrics", []):
                col = m["name"]
                if col not in all_metric_names:
                    all_metric_names.append(col)

        columns = ["case_id", "input", "expected"] + all_metric_names + ["score"]
        rows = []
        for c in bad_cases_raw:
            row: dict = {
                "case_id": c["case_id"],
                "input": c.get("input", "")[:60] + ("…" if len(c.get("input", "")) > 60 else ""),
                "expected": c.get("expected_output", ""),
                "score": round(c.get("overall_score", 0), 4),
            }
            # 从所有字段的 metrics 取分数
            for field_name2 in field_summaries:
                for m in c.get("fields", {}).get(field_name2, {}).get("metrics", []):
                    row[m["name"]] = round(m.get("score", 0), 4)
            rows.append(row)

        tables.append({
            "id": "bad_cases",
            "title": f"失败案例 ({len(bad_cases_raw)} 条)",
            "columns": columns,
            "rows": rows,
            "paginate": False
        })

    # ── 7. 逐案明细表 ─────────────────────────────────────────────────────────
    per_case_metric_names: list = []
    for field_name2 in field_summaries:
        for m in field_summaries[field_name2].get("metrics", []):
            col = m["name"]
            if col not in per_case_metric_names:
                per_case_metric_names.append(col)

    per_case_cols = ["case_id", "input", "expected"] + per_case_metric_names + ["overall_score"]
    per_case_rows = []
    for c in cases:
        row = {
            "case_id": c["case_id"],
            "input": c.get("input", "")[:40] + ("…" if len(c.get("input", "")) > 40 else ""),
            "expected": c.get("expected_output", ""),
            "overall_score": round(c.get("overall_score", 0), 4),
        }
        for field_name2 in field_summaries:
            for m in c.get("fields", {}).get(field_name2, {}).get("metrics", []):
                row[m["name"]] = round(m.get("score", 0), 4)
        per_case_rows.append(row)

    tables.append({
        "id": "per_case",
        "title": f"逐案明细 ({len(cases)} 条)",
        "columns": per_case_cols,
        "rows": per_case_rows,
        "paginate": True
    })

    result["summary_charts"] = charts
    result["summary_tables"] = tables
    return result


# ─── 工具函数 ─────────────────────────────────────────────────────────────────

def _make_bins(values: list, n: int = 10, lo: float = 0.0, hi: float = 1.0) -> list:
    """将一组浮点数分成 n 个等宽区间，返回 [{x: "0.0-0.1", count: 5}, ...]"""
    step = (hi - lo) / n
    bins = [{"x": f"{lo + i * step:.1f}-{lo + (i+1) * step:.1f}", "count": 0} for i in range(n)]
    for v in values:
        idx = min(int((v - lo) / step), n - 1)
        if 0 <= idx < n:
            bins[idx]["count"] += 1
    return bins


# ─── CLI ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="丰富化 eval_report.json，注入 summary_charts + summary_tables"
    )
    parser.add_argument("report_path", help="eval_report.json 或 results.json 的路径")
    parser.add_argument("--config", default=None, help="可选的 enrich_config.json 路径")
    parser.add_argument("--dry-run", action="store_true", help="不修改文件，只打印结果到 stdout")
    args = parser.parse_args()

    report_path = Path(args.report_path)
    if not report_path.exists():
        print(f"❌ 找不到文件: {report_path}", file=sys.stderr)
        sys.exit(1)

    report = json.loads(report_path.read_text("utf-8"))

    config = {}
    if args.config:
        config_path = Path(args.config)
        if config_path.exists():
            config = json.loads(config_path.read_text("utf-8"))
        else:
            print(f"⚠️  config 文件不存在，使用默认配置: {args.config}", file=sys.stderr)

    enriched = enrich(report, config)
    n_charts = len(enriched.get("summary_charts", []))
    n_tables = len(enriched.get("summary_tables", []))

    if args.dry_run:
        print(json.dumps(enriched, ensure_ascii=False, indent=2))
    else:
        report_path.write_text(json.dumps(enriched, ensure_ascii=False, indent=4), "utf-8")
        print(f"✅ 已丰富化: {report_path}")
        print(f"   生成图表: {n_charts} 个")
        print(f"   生成表格: {n_tables} 个")
        for ch in enriched.get("summary_charts", []):
            print(f"   📊 [{ch['type']}] {ch['title']}")
        for tbl in enriched.get("summary_tables", []):
            print(f"   📋 {tbl['title']}")


if __name__ == "__main__":
    main()