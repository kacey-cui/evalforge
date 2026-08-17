"""
record_run.py — 记录一次评测 Run，保存产物到 data/runs/{run_id}/，然后 git commit。

用法:
    python3 skills/version-manager/record_run.py \
        --run-id run_20260804_001 \
        --project diagnosis \
        --results data/projects/diagnosis/eval_report.json \
        --triggered-by agent
"""
import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

# 把 scripts/ 加入 sys.path，以便 import enrich_report
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
from enrich_report import enrich as _enrich_report  # noqa: E402
from run_manifest import build_manifest, validate_manifest, compute_manifest_hash  # noqa: E402

REPO_ROOT = Path(__file__).parent.parent.parent  # skills/version-manager/ 的上上上级


def _git(*args):
    result = subprocess.run(
        ["git"] + list(args), capture_output=True, text=True, cwd=REPO_ROOT
    )
    if result.returncode != 0:
        print(f"[git error] {result.stderr.strip()}", file=sys.stderr)
    return result.stdout.strip(), result.returncode


def _sha256_of_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def main():
    parser = argparse.ArgumentParser(description="记录一次 Run")
    parser.add_argument("--run-id", required=True, help="唯一 Run ID，如 run_20260804_001")
    parser.add_argument("--project", required=True, help="项目名称")
    parser.add_argument("--results", required=True, help="eval_report.json 路径")
    parser.add_argument("--triggered-by", default="agent", choices=["ui", "agent"])
    parser.add_argument("--dataset-id", default=None)
    parser.add_argument("--dataset-version", default=None)
    parser.add_argument("--skill-path", default=None)
    parser.add_argument("--model-id", default=None)
    parser.add_argument("--model-base-url", default=None)
    parser.add_argument("--judge-model-id", default=None)
    parser.add_argument("--judge-model-base-url", default=None)
    args = parser.parse_args()

    run_dir = REPO_ROOT / "data" / "runs" / args.run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    results_path = REPO_ROOT / args.results
    if not results_path.exists():
        print(f"❌ 找不到 results 文件: {results_path}", file=sys.stderr)
        sys.exit(1)

    # 1. 加载并丰富化 results.json（注入 summary_charts + summary_tables）
    results = json.loads(results_path.read_text("utf-8"))
    try:
        results = _enrich_report(results)
        print("  📊 报告丰富化成功")
    except Exception as e:
        print(f"  ⚠️  报告丰富化跳过（{e}）", file=sys.stderr)
    (run_dir / "results.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=4), "utf-8"
    )

    # 2. 复制 config.json（从 canvas.json 生成快照）
    canvas_path = REPO_ROOT / "data" / "projects" / args.project / "canvas.json"
    if canvas_path.exists():
        shutil.copy(canvas_path, run_dir / "config.json")
    else:
        (run_dir / "config.json").write_text("{}", "utf-8")

    # 3. 构建并落盘 manifest.json（provenance 快照）
    manifest = build_manifest(
        run_id=args.run_id,
        triggered_by=args.triggered_by,
        dataset_id=args.dataset_id,
        dataset_version=args.dataset_version,
        project=args.project,
        skill_path=args.skill_path,
        model_id=args.model_id,
        model_base_url=args.model_base_url,
        judge_model_id=args.judge_model_id,
        judge_model_base_url=args.judge_model_base_url,
        config_json_path=str(run_dir / "config.json"),
        results=results,
    )
    errors = validate_manifest(manifest)
    if errors:
        print(f"⚠️  Manifest 校验失败（已降级继续）: {errors}", file=sys.stderr)
    manifest["manifest_hash"] = compute_manifest_hash(manifest)
    (run_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=4), "utf-8"
    )
    results["manifest_hash"] = manifest["manifest_hash"]
    (run_dir / "results.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=4), "utf-8"
    )

    # 4. 生成 dataset_ref.json（content_hash 指向 dataset，保留 sha256/source 兼容）
    ds = manifest.get("dataset")
    dataset_ref = {
        "n_cases": ds["n_cases"] if ds else results.get("n_cases", 0),
        "source": args.results,
        "sha256": (ds["content_hash"] if ds else _sha256_of_file(results_path)),
        "dataset_id": (ds["dataset_id"] if ds else None),
        "version_hash": (ds["version_hash"] if ds else None),
        "content_hash": (ds["content_hash"] if ds else None),
        "source_path": (ds["source_path"] if ds else ""),
    }
    (run_dir / "dataset_ref.json").write_text(
        json.dumps(dataset_ref, ensure_ascii=False, indent=4), "utf-8"
    )

    # 5. 生成 meta.json
    overall_score = results.get("overall_score", 0.0)
    pass_rate = results.get("pass_rate", 0.0)
    status = "pass" if pass_rate >= 0.8 else ("fail" if pass_rate < 0.5 else "partial")
    fields_scores = {
        k: v.get("field_score") for k, v in results.get("fields", {}).items()
    }
    metrics_used = list(
        {m["name"] for m in results.get("config", {}).get("metrics", [])}
    )
    meta = {
        "run_id": args.run_id,
        "project": args.project,
        "triggered_by": args.triggered_by,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "status": status,
        "overall_score": overall_score,
        "pass_rate": pass_rate,
        "fields": fields_scores,
        "metrics": metrics_used,
    }
    (run_dir / "meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=4), "utf-8"
    )

    # 6. git add
    rel_run_dir = f"data/runs/{args.run_id}/"
    _git("add", rel_run_dir)

    # 7. git commit
    fields_str = json.dumps(fields_scores, ensure_ascii=False)
    metrics_str = "[" + ", ".join(metrics_used) + "]"
    commit_msg = (
        f"run: {args.project}/{args.run_id} [{status}]\n\n"
        f"project: {args.project}\n"
        f"triggered_by: {args.triggered_by}\n"
        f"metrics: {metrics_str}\n"
        f"dataset: {args.results}@sha256:{dataset_ref['sha256'][:8]}\n"
        f"overall_score: {overall_score:.4f}\n"
        f"fields: {fields_str}\n"
    )
    _, code = _git("commit", "-m", commit_msg)
    if code == 0:
        print(f"✅ Run {args.run_id} 已记录（git commit）")
    else:
        print(f"⚠️  git commit 失败，产物已保存到 {run_dir}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
