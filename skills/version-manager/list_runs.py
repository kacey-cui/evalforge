"""
list_runs.py — 列出 Run 历史。

用法:
    python3 skills/version-manager/list_runs.py --project diagnosis --limit 10
"""
import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent


def _git(*args):
    result = subprocess.run(
        ["git"] + list(args), capture_output=True, text=True, cwd=REPO_ROOT
    )
    return result.stdout.strip()


def main():
    parser = argparse.ArgumentParser(description="列出 Run 历史")
    parser.add_argument("--project", default="", help="按项目过滤（可选）")
    parser.add_argument("--limit", type=int, default=20, help="最多显示多少条")
    args = parser.parse_args()

    log = _git("log", "--format=%H|%s|%ci", "--", "data/runs/")
    if not log:
        print("暂无 Run 历史。")
        return

    runs = []
    for line in log.splitlines():
        parts = line.split("|", 2)
        if len(parts) < 3:
            continue
        sha, subject, timestamp = parts
        m = re.match(r"run:\s+(\S+)/(\S+)\s+\[(\w+)\]", subject)
        if not m:
            continue
        project, run_id, status = m.groups()
        if args.project and project != args.project:
            continue
        # 跳过软删除
        if _git("tag", "-l", f"deleted/{run_id}").strip():
            continue
        runs.append(
            {
                "run_id": run_id,
                "project": project,
                "status": status,
                "timestamp": timestamp,
                "sha": sha[:8],
            }
        )
        if len(runs) >= args.limit:
            break

    if not runs:
        print("没有符合条件的 Run。")
        return

    print(f"\n{'RUN ID':<25} {'PROJECT':<15} {'STATUS':<10} {'SCORE':<8} {'TIME'}")
    print("-" * 85)
    for r in runs:
        # 尝试从 meta.json 读分数
        meta_path = REPO_ROOT / "data" / "runs" / r["run_id"] / "meta.json"
        score = "N/A"
        if meta_path.exists():
            try:
                meta = json.loads(meta_path.read_text("utf-8"))
                score = f"{meta.get('overall_score', 0):.2f}"
            except Exception:
                pass
        status_icon = {"pass": "✅", "fail": "❌", "partial": "⚠️"}.get(r["status"], "?")
        print(
            f"{r['run_id']:<25} {r['project']:<15} "
            f"{status_icon} {r['status']:<8} {score:<8} {r['timestamp'][:19]}"
        )
    print()


if __name__ == "__main__":
    main()
