"""eval_diff — Compare two evaluation runs and explain why scores differ.

Answers the question: "Why did these two evaluations produce different results?"

Usage:
    from eval_diff import eval_diff
    result = eval_diff("run_20260818_001", "run_20260818_002")
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_RUNS_DIR = REPO_ROOT / "data" / "runs"
DEFAULT_METRICS_DIR = REPO_ROOT / "data" / "metrics"
DEFAULT_DATASETS_DIR = REPO_ROOT / "data" / "datasets"

sys.path.insert(0, str(Path(__file__).resolve().parent))

from run_store import RunStore
from metric_store import MetricStore
from dataset_store import DatasetStore
from dataset_versioning import diff_case


# ── Structured response helpers ────────────────────────────────────────────────


def _error(code, message, details=None):
    """Build a structured error response."""
    result = {"ok": False, "error": {"code": code, "message": message}}
    if details is not None:
        result["error"]["details"] = details
    return result


def _ok(**data):
    """Build a success response."""
    return {"ok": True, "data": data}


# ── Internal diff helpers ──────────────────────────────────────────────────────


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


# ── Score comparison ───────────────────────────────────────────────────────────


def _compare_scores(results_a, results_b):
    """Compare scores from two results.json dicts."""
    ra = results_a or {}
    rb = results_b or {}

    overall = {
        "a": ra.get("overall_score"),
        "b": rb.get("overall_score"),
    }
    sa = overall["a"] or 0
    sb = overall["b"] or 0
    overall["delta"] = round(sb - sa, 6)

    # Field-level scores
    fields_a = ra.get("fields") or {}
    fields_b = rb.get("fields") or {}
    field_diffs = {}
    all_field_names = set(fields_a.keys()) | set(fields_b.keys())
    for name in all_field_names:
        fa = fields_a.get(name, {})
        fb = fields_b.get(name, {})
        if isinstance(fa, dict) and isinstance(fb, dict):
            sa = fa.get("field_score", 0)
            sb = fb.get("field_score", 0)
            if sa != sb:
                field_diffs[name] = {"a": sa, "b": sb, "delta": round(sb - sa, 6)}
        else:
            if fa != fb:
                field_diffs[name] = {"a": fa, "b": fb}

    # Case-level scores
    cases_a = ra.get("cases") or []
    cases_b = rb.get("cases") or []
    case_diffs = []
    if isinstance(cases_a, list) and isinstance(cases_b, list):
        # Try to match by case_id or index
        by_id_a = {}
        for i, c in enumerate(cases_a):
            if isinstance(c, dict):
                cid = c.get("case_id", i)
                by_id_a[cid] = c
        by_id_b = {}
        for i, c in enumerate(cases_b):
            if isinstance(c, dict):
                cid = c.get("case_id", i)
                by_id_b[cid] = c

        all_ids = set(by_id_a.keys()) | set(by_id_b.keys())
        for cid in sorted(all_ids, key=lambda x: (str(x) if not isinstance(x, int) else x)):
            ca = by_id_a.get(cid)
            cb = by_id_b.get(cid)
            if ca is None:
                case_diffs.append({"case_id": cid, "status": "added", "b": cb})
            elif cb is None:
                case_diffs.append({"case_id": cid, "status": "removed", "a": ca})
            else:
                # Compare scores if both have them
                score_a = ca.get("score") if isinstance(ca, dict) else None
                score_b = cb.get("score") if isinstance(cb, dict) else None
                if score_a is not None or score_b is not None:
                    if score_a != score_b:
                        case_diffs.append({
                            "case_id": cid,
                            "status": "modified",
                            "score": {"a": score_a, "b": score_b},
                        })

    return {
        "overall": overall,
        "fields": field_diffs,
        "cases": case_diffs,
    }


# ── Dataset comparison ─────────────────────────────────────────────────────────


def _compare_dataset(manifest_a, manifest_b, dataset_store):
    """Compare dataset sections of two manifests."""
    ds_a = (manifest_a or {}).get("dataset")
    ds_b = (manifest_b or {}).get("dataset")

    if ds_a is None and ds_b is None:
        return {
            "status": "unchanged",
            "dataset_id": None,
            "version_a": None,
            "version_b": None,
        }

    if ds_a is None or ds_b is None:
        return {
            "status": "modified",
            "dataset_id": (ds_a or {}).get("dataset_id") if ds_a else (ds_b or {}).get("dataset_id"),
            "version_a": (ds_a or {}).get("version_hash") if ds_a else None,
            "version_b": (ds_b or {}).get("version_hash") if ds_b else None,
            "detail": "一方缺少 dataset 信息",
        }

    dataset_id_a = ds_a.get("dataset_id")
    dataset_id_b = ds_b.get("dataset_id")

    if dataset_id_a != dataset_id_b:
        detail = _diff_dataset_family_versions(dataset_id_a, dataset_id_b, dataset_store)
        return {
            "status": "modified",
            "dataset_id": f"{dataset_id_a} → {dataset_id_b}",
            "version_a": ds_a.get("version_hash"),
            "version_b": ds_b.get("version_hash"),
            "detail": detail or f"数据集不同: {dataset_id_a} vs {dataset_id_b}",
        }

    version_hash_a = ds_a.get("version_hash")
    version_hash_b = ds_b.get("version_hash")

    if version_hash_a == version_hash_b:
        return {
            "status": "unchanged",
            "dataset_id": dataset_id_a,
            "version_a": version_hash_a,
            "version_b": version_hash_b,
        }

    # Same dataset_id, different version — try to get detailed diff
    detail = None
    try:
        diff_result = dataset_store.diff_versions(
            dataset_id_a, version_hash_a, version_hash_b
        )
        if diff_result.get("ok"):
            detail = diff_result["data"]
    except Exception:
        pass

    return {
        "status": "modified",
        "dataset_id": dataset_id_a,
        "version_a": version_hash_a,
        "version_b": version_hash_b,
        "detail": detail or "数据集版本不同，无法获取详细 diff",
    }


def _dataset_family_key(dataset_id):
    """Return family prefix for ids like ``rag_research_v1`` / ``rag_research_v2``."""
    if not dataset_id:
        return None
    parts = str(dataset_id).rsplit("_v", 1)
    if len(parts) != 2 or not parts[1].isdigit():
        return None
    return parts[0]


def _diff_dataset_family_versions(dataset_id_a, dataset_id_b, dataset_store):
    """Compare current case files for versioned dataset ids in the same family."""
    if _dataset_family_key(dataset_id_a) != _dataset_family_key(dataset_id_b):
        return None

    try:
        data_a = dataset_store.get(dataset_id_a)
        data_b = dataset_store.get(dataset_id_b)
    except Exception:
        return None
    if not data_a.get("ok") or not data_b.get("ok"):
        return None

    cases_a = data_a["data"].get("cases") or []
    cases_b = data_b["data"].get("cases") or []
    by_id_a = {c.get("case_id"): c for c in cases_a if isinstance(c, dict)}
    by_id_b = {c.get("case_id"): c for c in cases_b if isinstance(c, dict)}

    ids_a = set(by_id_a)
    ids_b = set(by_id_b)
    matched_ids = sorted(ids_a & ids_b)
    added_ids = sorted(ids_b - ids_a)
    removed_ids = sorted(ids_a - ids_b)

    modified_cases = []
    for cid in matched_ids:
        changes = diff_case(by_id_a[cid], by_id_b[cid])
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

    return {
        "dataset_id_a": dataset_id_a,
        "dataset_id_b": dataset_id_b,
        "summary": {
            "n_cases_a": len(cases_a),
            "n_cases_b": len(cases_b),
            "matched": len(matched_ids),
            "added": len(added_cases),
            "removed": len(removed_cases),
            "modified": len(modified_cases),
        },
        "schema_changes": [],
        "added_cases": added_cases,
        "removed_cases": removed_cases,
        "modified_cases": modified_cases,
    }


# ── Metric comparison ──────────────────────────────────────────────────────────


def _compare_metrics(manifest_a, manifest_b, metric_store):
    """Compare metric sections of two manifests."""
    metrics_a = (manifest_a or {}).get("metrics") or []
    metrics_b = (manifest_b or {}).get("metrics") or []

    # Build lookup by metric_id
    by_id_a = {}
    for m in metrics_a:
        mid = m.get("metric_id")
        if mid:
            by_id_a[mid] = m
    by_id_b = {}
    for m in metrics_b:
        mid = m.get("metric_id")
        if mid:
            by_id_b[mid] = m

    all_ids = set(by_id_a.keys()) | set(by_id_b.keys())
    results = []

    for mid in sorted(all_ids):
        ma = by_id_a.get(mid)
        mb = by_id_b.get(mid)

        if ma is None:
            # Exists only in B → added
            results.append({
                "metric_id": mid,
                "status": "added",
                "version_a": None,
                "version_b": mb.get("version_hash"),
            })
        elif mb is None:
            # Exists only in A → removed
            results.append({
                "metric_id": mid,
                "status": "removed",
                "version_a": ma.get("version_hash"),
                "version_b": None,
            })
        elif ma.get("version_hash") == mb.get("version_hash"):
            # Same hash → unchanged
            results.append({
                "metric_id": mid,
                "status": "unchanged",
                "version_a": ma.get("version_hash"),
                "version_b": mb.get("version_hash"),
            })
        else:
            # Different hash → modified, try to get field-level diff
            detail = None
            try:
                diff_result = metric_store.diff_versions(
                    mid, ma.get("version_hash"), mb.get("version_hash")
                )
                if diff_result.get("ok"):
                    detail = diff_result["data"]
            except Exception:
                pass

            results.append({
                "metric_id": mid,
                "status": "modified",
                "version_a": ma.get("version_hash"),
                "version_b": mb.get("version_hash"),
                "detail": detail,
            })

    return results


# ── Skill comparison ───────────────────────────────────────────────────────────


def _compare_skill(manifest_a, manifest_b):
    """Compare skill sections of two manifests."""
    skill_a = (manifest_a or {}).get("skill")
    skill_b = (manifest_b or {}).get("skill")

    if skill_a is None and skill_b is None:
        return {
            "status": "unchanged",
            "name": None,
            "hash_a": None,
            "hash_b": None,
        }

    if skill_a is None or skill_b is None:
        return {
            "status": "modified",
            "name": (skill_a or skill_b or {}).get("name"),
            "hash_a": (skill_a or {}).get("content_hash") if skill_a else None,
            "hash_b": (skill_b or {}).get("content_hash") if skill_b else None,
        }

    hash_a = skill_a.get("content_hash")
    hash_b = skill_b.get("content_hash")

    status = "unchanged" if hash_a == hash_b else "modified"
    return {
        "status": status,
        "name": skill_a.get("name") or skill_b.get("name"),
        "hash_a": hash_a,
        "hash_b": hash_b,
    }


# ── Model comparison ───────────────────────────────────────────────────────────


def _compare_model(manifest_a, manifest_b):
    """Compare model sections of two manifests."""
    model_a = (manifest_a or {}).get("model")
    model_b = (manifest_b or {}).get("model")

    if model_a is None and model_b is None:
        return {
            "status": "unchanged",
            "model_id_a": None,
            "model_id_b": None,
            "diff": None,
        }

    if model_a is None or model_b is None:
        return {
            "status": "modified",
            "model_id_a": (model_a or {}).get("model_id") if model_a else None,
            "model_id_b": (model_b or {}).get("model_id") if model_b else None,
            "diff": "一方缺少 model 信息",
        }

    model_id_a = model_a.get("model_id")
    model_id_b = model_b.get("model_id")
    base_url_a = model_a.get("base_url")
    base_url_b = model_b.get("base_url")

    is_same = (model_id_a == model_id_b) and (base_url_a == base_url_b)

    if is_same:
        return {
            "status": "unchanged",
            "model_id_a": model_id_a,
            "model_id_b": model_id_b,
            "diff": None,
        }

    # Build field-level diff
    diff = {}
    if model_id_a != model_id_b:
        diff["model_id"] = {"a": model_id_a, "b": model_id_b}
    if base_url_a != base_url_b:
        diff["base_url"] = {"a": base_url_a, "b": base_url_b}

    return {
        "status": "modified",
        "model_id_a": model_id_a,
        "model_id_b": model_id_b,
        "diff": diff,
    }


# ── Judge comparison ───────────────────────────────────────────────────────────


def _compare_judge(manifest_a, manifest_b):
    """Compare judge_model sections of two manifests."""
    judge_a = (manifest_a or {}).get("judge_model")
    judge_b = (manifest_b or {}).get("judge_model")

    if judge_a is None and judge_b is None:
        return {
            "status": "unchanged",
            "diff": None,
        }

    if judge_a is None:
        return {
            "status": "added",
            "diff": {"a": None, "b": judge_b},
        }

    if judge_b is None:
        return {
            "status": "removed",
            "diff": {"a": judge_a, "b": None},
        }

    model_id_a = judge_a.get("model_id")
    model_id_b = judge_b.get("model_id")
    base_url_a = judge_a.get("base_url")
    base_url_b = judge_b.get("base_url")

    is_same = (model_id_a == model_id_b) and (base_url_a == base_url_b)

    if is_same:
        return {
            "status": "unchanged",
            "diff": None,
        }

    diff = {}
    if model_id_a != model_id_b:
        diff["model_id"] = {"a": model_id_a, "b": model_id_b}
    if base_url_a != base_url_b:
        diff["base_url"] = {"a": base_url_a, "b": base_url_b}

    return {
        "status": "modified",
        "diff": diff,
    }


# ── Summary generation ─────────────────────────────────────────────────────────


def _generate_summary(score_comparison, dataset, metrics, skill, model, judge):
    """Generate a human-readable summary in Chinese explaining what changed."""
    parts = []
    score = score_comparison or {}
    overall = score.get("overall") or {}

    # Score change
    delta = overall.get("delta", 0)
    if delta != 0:
        direction = "提升" if delta > 0 else "下降"
        parts.append(
            f"总分从 {overall.get('a')} 变为 {overall.get('b')}，{direction}了 {abs(delta):.4f}"
        )

    # Dataset changes
    ds = dataset or {}
    if ds.get("status") == "modified":
        parts.append("数据集发生了变化")

    # Metric changes
    metrics_changed = [m for m in (metrics or []) if m.get("status") != "unchanged"]
    if metrics_changed:
        added = [m for m in metrics_changed if m["status"] == "added"]
        removed = [m for m in metrics_changed if m["status"] == "removed"]
        modified = [m for m in metrics_changed if m["status"] == "modified"]
        detail_parts = []
        if added:
            detail_parts.append(f"新增了 {len(added)} 个指标")
        if removed:
            detail_parts.append(f"移除了 {len(removed)} 个指标")
        if modified:
            detail_parts.append(f"修改了 {len(modified)} 个指标")
        parts.append("，".join(detail_parts))

    # Skill changes
    sk = skill or {}
    if sk.get("status") == "modified":
        parts.append("技能（skill）内容发生了变化")

    # Model changes
    md = model or {}
    if md.get("status") == "modified":
        parts.append("被测模型发生了变化")

    # Judge changes
    jd = judge or {}
    if jd.get("status") in ("modified", "added", "removed"):
        parts.append("评判模型发生了变化")

    if not parts:
        return "两次评测结果一致，未发现差异"

    # Conclude with root cause analysis
    if delta != 0:
        causes = []
        if ds.get("status") == "modified":
            causes.append("数据集差异")
        if metrics_changed:
            causes.append("指标变动")
        if sk.get("status") == "modified":
            causes.append("技能逻辑变更")
        if md.get("status") == "modified":
            causes.append("被测模型不同")
        if jd.get("status") in ("modified", "added", "removed"):
            causes.append("评判模型不同")
        if causes:
            parts.append("分数差异可能由以下因素导致：" + "、".join(causes))
        else:
            parts.append("分数差异可能由评测数据本身波动导致")

    return "。".join(parts) + "。"


# ── Main API ───────────────────────────────────────────────────────────────────


def eval_diff(run_id_a, run_id_b, runs_dir=None, metrics_dir=None, datasets_dir=None):
    """Compare two evaluation runs and explain why scores differ.

    Args:
        run_id_a: First run ID.
        run_id_b: Second run ID.
        runs_dir: Optional path to runs directory (default: data/runs/).
        metrics_dir: Optional path to metrics directory (default: data/metrics/).
        datasets_dir: Optional path to datasets directory (default: data/datasets/).

    Returns:
        {ok, data: {run_id_a, run_id_b, score_comparison, dataset, metrics,
         skill, model, judge, summary}}
        or {ok: false, error: {code, message, details?}}
    """
    run_store = RunStore(runs_dir=runs_dir)
    metric_store = MetricStore(base_dir=metrics_dir or DEFAULT_METRICS_DIR)
    dataset_store = DatasetStore(base_dir=datasets_dir or DEFAULT_DATASETS_DIR)

    # Load both runs
    result_a = run_store.get(run_id_a)
    if not result_a["ok"]:
        return result_a

    result_b = run_store.get(run_id_b)
    if not result_b["ok"]:
        return result_b

    data_a = result_a["data"]
    data_b = result_b["data"]

    manifest_a = data_a.get("manifest") or {}
    manifest_b = data_b.get("manifest") or {}
    results_a = data_a.get("results") or {}
    results_b = data_b.get("results") or {}

    # 1. Score comparison
    score_comparison = _compare_scores(results_a, results_b)

    # 2. Dataset comparison
    dataset = _compare_dataset(manifest_a, manifest_b, dataset_store)

    # 3. Metric comparison
    metrics = _compare_metrics(manifest_a, manifest_b, metric_store)

    # 4. Skill comparison
    skill = _compare_skill(manifest_a, manifest_b)

    # 5. Model comparison
    model = _compare_model(manifest_a, manifest_b)

    # 6. Judge comparison
    judge = _compare_judge(manifest_a, manifest_b)

    # 7. Summary
    summary = _generate_summary(score_comparison, dataset, metrics, skill, model, judge)

    return _ok(
        run_id_a=run_id_a,
        run_id_b=run_id_b,
        score_comparison=score_comparison,
        dataset=dataset,
        metrics=metrics,
        skill=skill,
        model=model,
        judge=judge,
        summary=summary,
    )


# ── CLI ────────────────────────────────────────────────────────────────────────


def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="eval_diff — Compare two evaluation runs and explain why scores differ"
    )
    parser.add_argument("--run-a", required=True, help="第一个 run_id")
    parser.add_argument("--run-b", required=True, help="第二个 run_id")
    parser.add_argument("--runs-dir", default=None, help="runs 目录（默认 data/runs）")
    parser.add_argument(
        "--json", dest="json_output", action="store_true",
        help="以 JSON 格式输出"
    )

    args = parser.parse_args()

    result = eval_diff(args.run_a, args.run_b, runs_dir=args.runs_dir)

    if args.json_output:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        if result["ok"]:
            data = result["data"]
            print(f"=== 评测对比: {data['run_id_a']} vs {data['run_id_b']} ===")
            print()

            # Score
            sc = data["score_comparison"]
            overall = sc["overall"]
            print(f"总分: {overall['a']} → {overall['b']} (delta={overall['delta']})")
            if sc["fields"]:
                print("字段分数:")
                for name, d in sc["fields"].items():
                    print(f"  {name}: {d['a']} → {d['b']} (delta={d['delta']})")
            if sc["cases"]:
                print(f"用例差异: {len(sc['cases'])} 个用例有变化")

            # Dataset
            ds = data["dataset"]
            print(f"\n数据集: {ds['status']}")

            # Metrics
            print(f"\n指标:")
            for m in data["metrics"]:
                print(f"  {m['metric_id']}: {m['status']}")

            # Skill
            sk = data["skill"]
            print(f"\n技能: {sk['status']}")

            # Model
            md = data["model"]
            print(f"模型: {md['status']}")

            # Judge
            jd = data["judge"]
            print(f"评判模型: {jd['status']}")

            # Summary
            print(f"\n总结: {data['summary']}")
        else:
            err = result["error"]
            print(f"错误 [{err['code']}]: {err['message']}", file=sys.stderr)
            sys.exit(1)

    sys.exit(0 if result["ok"] else 1)


if __name__ == "__main__":
    main()
