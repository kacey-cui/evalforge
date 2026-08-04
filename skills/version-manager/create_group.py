"""
create_group.py — 创建对比组（git tag）。

用法:
    python3 skills/version-manager/create_group.py \
        --name "换模型对比" \
        --runs run_001,run_002,run_003
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
    parser = argparse.ArgumentParser(description="创建对比组")
    parser.add_argument("--name", required=True, help="对比组名称，如 '换模型对比'")
    parser.add_argument("--runs", required=True, help="run_id 列表，逗号分隔")
    args = parser.parse_args()

    run_ids = [r.strip() for r in args.runs.split(",") if r.strip()]
    if not run_ids:
        print("❌ --runs 不能为空", file=sys.stderr)
        sys.exit(1)

    # 用 / 作分隔符，但名称中可能有空格，用 - 替代
    safe_name = args.name.strip().replace(" ", "-").replace("/", "-")

    # 创建 group-level tag
    group_tag = f"compare/{safe_name}"
    _, code = _git("tag", group_tag)
    if code != 0:
        # tag 可能已存在，不报错
        print(f"⚠️  对比组 tag '{group_tag}' 已存在，继续添加 Run...")

    created = []
    for run_id in run_ids:
        tag = f"compare/{safe_name}/{run_id}"
        _, code = _git("tag", tag)
        if code == 0:
            created.append(run_id)
        else:
            print(f"⚠️  {run_id} tag 创建失败（可能已加入）")

    print(f"✅ 对比组 '{args.name}' 创建成功，包含 {len(created)} 个 Run:")
    for r in created:
        print(f"   - {r}")


if __name__ == "__main__":
    main()
