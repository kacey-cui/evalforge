#!/usr/bin/env python3
"""Metric 发布/发现工具 — 查重 + Git push/pull 到共享仓库"""

import argparse, json, os, re, subprocess, sys, tempfile
from pathlib import Path


def jaccard(text_a: str, text_b: str) -> float:
    """计算两个文本的 Jaccard 相似度（基于 2-gram 字符级）"""
    def ngrams(s, n=2):
        s = re.sub(r'\s+', ' ', s).strip().lower()
        return {s[i:i+n] for i in range(len(s)-n+1)}
    a, b = ngrams(text_a), ngrams(text_b)
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def levenshtein(a: str, b: str) -> int:
    """编辑距离"""
    m, n = len(a), len(b)
    dp = [[0]*(n+1) for _ in range(m+1)]
    for i in range(m+1): dp[i][0] = i
    for j in range(n+1): dp[0][j] = j
    for i in range(1, m+1):
        for j in range(1, n+1):
            dp[i][j] = min(dp[i-1][j]+1, dp[i][j-1]+1,
                           dp[i-1][j-1]+(0 if a[i-1]==b[j-1] else 1))
    return dp[m][n]


def load_existing_metrics(repo_dir: str) -> list[dict]:
    """加载共享仓库中所有已有 metric"""
    metrics = []
    repo = Path(repo_dir)
    for cat in ['non_llm', 'llm']:
        cat_dir = repo / 'data' / 'metrics' / cat
        if cat_dir.exists():
            for f in cat_dir.glob('*.json'):
                try:
                    metrics.append(json.loads(f.read_text()))
                except Exception:
                    pass
    return metrics


def _numeric_suffix(metric_id: str):
    """如果 ID 形如 base_<number>，返回 (base, number)，否则返回 None。"""
    m = re.match(r'^([a-z][a-z0-9]*(?:_[a-z][a-z0-9]*)*)_(\d+)$', metric_id)
    return (m.group(1), int(m.group(2))) if m else None


def _has_numeric_param(metric: dict) -> bool:
    """判断 metric 是否已有数值型的 k/n/top_k 类参数（可参数化 metric 的标志）。"""
    numeric_param_keys = {'k', 'n', 'top_k', 'top_n', 'num', 'limit', 'cutoff'}
    return any(p['key'] in numeric_param_keys for p in metric.get('params', []))


def check_metric(metric: dict, existing: list[dict]) -> list[str]:
    """查重，返回警告列表。空列表 = 通过"""
    warnings = []

    suffix_info = _numeric_suffix(metric['id'])

    for existing_m in existing:
        # 1. ID 完全相同
        if metric['id'] == existing_m['id']:
            warnings.append(f'❌ ID 冲突: "{metric["id"]}" 已存在（{existing_m["name"]}）')
            return warnings

        # 2. 名称高度相似
        dist = levenshtein(metric['name'], existing_m['name'])
        len_diff = abs(len(metric['name']) - len(existing_m['name']))
        if dist <= 3 and len_diff <= 5:
            warnings.append(
                f'⚠️ 名称相似: "{metric["name"]}" vs "{existing_m["name"]}" (编辑距离={dist})')

        # 3. criteria 高度相似（仅 LLM metric）
        if (metric.get('criteria') and existing_m.get('criteria')):
            j = jaccard(metric['criteria'], existing_m['criteria'])
            if j >= 0.7:
                warnings.append(
                    f'⚠️ criteria 相似度 {j:.2f}: "{metric["name"]}" vs "{existing_m["name"]}"')

        # 4. code_template 高度相似
        j = jaccard(metric.get('code_template', ''), existing_m.get('code_template', ''))
        if j >= 0.8:
            warnings.append(
                f'⚠️ 代码模板相似度 {j:.2f}: "{metric["name"]}" vs "{existing_m["name"]}"')

        # 5. 参数化变体检测 ─ 防止 recall_3 / recall_5 / recall_10 泛滥
        if suffix_info:
            base, num = suffix_info
            ex_suffix = _numeric_suffix(existing_m['id'])
            # 5a. 同一 base_<N> 模式的另一个变体已存在 → 强烈建议合并
            if ex_suffix and ex_suffix[0] == base:
                warnings.append(
                    f'❌ 参数化变体冲突: "{metric["id"]}" 与 "{existing_m["id"]}" '
                    f'同属 "{base}_<N>" 系列。请改用一个带 k/n 参数的 metric，'
                    f'在 canvas scorePipeline 中多次引用并设置不同参数值。'
                )
                return warnings
            # 5b. 已有同名 base 的参数化 metric（如 recall_at_k）→ 直接用它
            if _has_numeric_param(existing_m):
                id_similarity = jaccard(base.replace('_', ' '), existing_m['id'].replace('_', ' '))
                if id_similarity >= 0.4:
                    warnings.append(
                        f'⚠️ 已有参数化 metric: "{existing_m["id"]}" ({existing_m["name"]}) '
                        f'支持 k/n 类参数，"{metric["id"]}" 应改为在 canvas 中引用它并传入 '
                        f'参数 k={num}，而非新建 metric。'
                    )

    return warnings


def cmd_check(args):
    """查重命令"""
    if not os.path.exists(args.metric):
        print(f'❌ 文件不存在: {args.metric}')
        sys.exit(1)

    metric = json.loads(Path(args.metric).read_text())

    with tempfile.TemporaryDirectory() as tmpdir:
        if args.repo:
            print(f'📥 拉取共享仓库...')
            subprocess.run(['git', 'clone', '--depth', '1', args.repo, tmpdir],
                         capture_output=True, check=True)
        else:
            # 检查本地 data/metrics/
            tmpdir = os.getcwd()

        existing = load_existing_metrics(tmpdir)
        print(f'已有 {len(existing)} 个 metric')

        warnings = check_metric(metric, existing)
        if not warnings:
            print(f'✅ 通过查重: {metric["id"]} ({metric["name"]})')
        else:
            for w in warnings:
                print(w)
            has_error = any(w.startswith('❌') for w in warnings)
            if has_error:
                print('\n❌ 存在 ID 冲突，无法发布。')
                sys.exit(1)
            else:
                print('\n⚠️ 存在相似警告，仍可发布（需确认）。')
                if args.force:
                    print('已使用 --force，跳过确认。')
                else:
                    r = input('确认发布？[y/N] ')
                    if r.lower() != 'y':
                        print('已取消。')
                        sys.exit(0)


def cmd_publish(args):
    """发布命令"""
    if not os.path.exists(args.metric):
        print(f'❌ 文件不存在: {args.metric}')
        sys.exit(1)

    metric = json.loads(Path(args.metric).read_text())
    mid = metric['id']
    cat = metric['category']

    with tempfile.TemporaryDirectory() as tmpdir:
        print(f'📥 克隆共享仓库...')
        subprocess.run(['git', 'clone', args.repo, tmpdir], capture_output=True, check=True)

        existing = load_existing_metrics(tmpdir)
        warnings = check_metric(metric, existing)
        has_error = any(w.startswith('❌') for w in warnings)
        if has_error:
            for w in warnings: print(w)
            sys.exit(1)

        for w in warnings: print(w)

        # 复制 metric 文件到仓库
        target_dir = Path(tmpdir) / 'data' / 'metrics' / cat
        target_dir.mkdir(parents=True, exist_ok=True)
        target_file = target_dir / f'{mid}.json'
        target_file.write_text(json.dumps(metric, ensure_ascii=False, indent=2))
        print(f'📄 已复制: {target_file}')

        # Git 提交
        subprocess.run(['git', 'add', str(target_file)], cwd=tmpdir, check=True)
        subprocess.run(['git', 'commit', '-m', f'publish: {mid} ({metric["name"]})'],
                      cwd=tmpdir, check=True)
        subprocess.run(['git', 'push'], cwd=tmpdir, check=True)
        print(f'✅ 已发布: {mid} ({metric["name"]})')


def cmd_discover(args):
    """发现命令"""
    with tempfile.TemporaryDirectory() as tmpdir:
        print(f'📥 拉取共享仓库...')
        subprocess.run(['git', 'clone', '--depth', '1', args.repo, tmpdir],
                     capture_output=True, check=True)

        existing = load_existing_metrics(tmpdir)
        print(f'共享仓库中有 {len(existing)} 个 metric:')

        target = Path(args.target)
        for m in existing:
            cat = m['category']
            dest = target / cat / f'{m["id"]}.json'
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(json.dumps(m, ensure_ascii=False, indent=2))
            print(f'  📥 {m["id"]} ({m["name"]}) → {dest}')

        print(f'✅ 已同步 {len(existing)} 个 metric 到 {args.target}')


def main():
    parser = argparse.ArgumentParser(description='Metric 发布/发现工具')
    sub = parser.add_subparsers(dest='command')

    p_check = sub.add_parser('check', help='查重检查')
    p_check.add_argument('--metric', required=True, help='metric JSON 文件路径')
    p_check.add_argument('--repo', help='共享仓库 URL（不指定则检查本地）')
    p_check.add_argument('--force', action='store_true', help='跳过相似警告确认')

    p_pub = sub.add_parser('publish', help='发布到共享仓库')
    p_pub.add_argument('--metric', required=True)
    p_pub.add_argument('--repo', required=True, help='共享仓库 URL')

    p_dis = sub.add_parser('discover', help='拉取共享指标')
    p_dis.add_argument('--repo', required=True)
    p_dis.add_argument('--target', required=True, help='目标目录，如 data/metrics/')

    args = parser.parse_args()

    if args.command == 'check':
        cmd_check(args)
    elif args.command == 'publish':
        cmd_publish(args)
    elif args.command == 'discover':
        cmd_discover(args)
    else:
        parser.print_help()


if __name__ == '__main__':
    main()