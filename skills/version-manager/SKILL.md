---
name: version-manager
description: EvalForge 版本管理 Skill。记录 Run 历史、查询历史、创建对比组、对比两次 Run、软删除 Run。所有命令在 evalplatform/ 根目录下运行。
---

# Version Manager Skill

## 前提

所有命令必须在 `evalplatform/` 目录下运行（即 `serve.sh` 所在的目录）。

## 命令速查

### 记录一次 Run（evaluator 跑完后调用）

```bash
python3 skills/version-manager/record_run.py \
  --run-id run_20260804_001 \
  --project diagnosis \
  --results data/projects/diagnosis/eval_report.json \
  --triggered-by agent
```

参数说明：
- `--run-id`：唯一 ID，建议格式 `run_YYYYMMDD_NNN`
- `--project`：项目名（与 canvas.json 所在目录同名）
- `--results`：eval_report.json 路径
- `--triggered-by`：`ui` 或 `agent`（默认 `agent`）

### 查询历史

```bash
python3 skills/version-manager/list_runs.py --project diagnosis --limit 10
```

### 创建对比组

```bash
python3 skills/version-manager/create_group.py \
  --name "换模型对比" \
  --runs run_001,run_002,run_003
```

### 对比两次 Run

```bash
python3 skills/version-manager/diff_runs.py --run-a run_001 --run-b run_002
```

输出 Markdown 格式，可直接汇报给用户。

### 软删除 Run

```bash
python3 skills/version-manager/delete_run.py --run-id run_001
```

软删除不会清除 git 历史，只是打 `deleted/{run_id}` tag，UI 和 list 不再显示。
