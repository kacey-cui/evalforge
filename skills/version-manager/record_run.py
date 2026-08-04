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
    args = parser.parse_args()

    run_dir = REPO_ROOT / "data" / "runs" / args.run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    results_path = REPO_ROOT / args.results
    if not results_path.exists():
        print(f"❌ 找不到 results 文件: {results_path}", file=sys.stderr)
        sys.exit(1)

    # 1. 复制 results.json
    results = json.loads(results_path.read_text("utf-8"))
    (run_dir / "results.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=4), "utf-8"
    )

    # 2. 复制 config.json（从 canvas.json 生成快照）
    canvas_path = REPO_ROOT / "data" / "projects" / args.project / "canvas.json"
    if canvas_path.exists():
        shutil.copy(canvas_path, run_dir / "config.json")
    else:
        (run_dir / "config.json").write_text("{}", "utf-8")

    # 3. 生成 dataset_ref.json（引用 results 里的 test cases 数量）
    dataset_ref = {
        "n_cases": results.get("n_cases", 0),
        "source": args.results,
        "sha256": _sha256_of_file(results_path),
    }
    (run_dir / "dataset_ref.json").write_text(
        json.dumps(dataset_ref, ensure_ascii=False, indent=4), "utf-8"
    )

    # 4. 生成 meta.json
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

    # 5. git add
    rel_run_dir = f"data/runs/{args.run_id}/"
    _git("add", rel_run_dir)

    # 6. git commit
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
