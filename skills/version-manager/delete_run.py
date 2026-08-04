"""
delete_run.py — 软删除一次 Run（打 deleted/{run_id} tag，不清除 git 历史）。

用法:
    python3 skills/version-manager/delete_run.py --run-id run_001
"""
import argparse
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent


def _git(*args):
    result = subprocess.run(
        ["git"] + list(args), capture_output=True, text=True, cwd=REPO_ROOT
    )
    return result.stdout.strip(), result.returncode


def main():
    parser = argparse.ArgumentParser(description="软删除一次 Run")
    parser.add_argument("--run-id", required=True, help="Run ID")
    args = parser.parse_args()

    tag = f"deleted/{args.run_id}"
    # 检查是否已删除
    existing, _ = _git("tag", "-l", tag)
    if existing.strip():
        print(f"⚠️  Run {args.run_id} 已经被软删除过了")
        return

    _, code = _git("tag", tag)
    if code == 0:
        print(f"✅ Run {args.run_id} 已软删除（打 tag: {tag}）")
        print("   注意：git 历史仍然保留，可通过 git tag -d 恢复。")
    else:
        print(f"❌ 软删除失败", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
