# Agent-native Report Submission — Design Document

> 状态：待实现
> 目标：Agent 在自己的机器上运行 Skill 后，可以通过 CLI/Python API 提交 Report 给 EvalForge。

---

## 1. 现有分析

### 已实现

| 组件 | 能力 | Agent 可用？ |
|------|------|:--:|
| `record_run.py` | 从文件路径提交 Run | ⚠️ CLI 需要 `--results` 文件路径 |
| `run_manifest.py` | 构建/验证 manifest | ✅ |
| `enrich_report.py` | 丰富化 report | ✅ |
| `git_bridge.py` GET/POST/DELETE | 读/比较/删除 runs | ✅ 有 REST |
| `git_bridge.py` submit | 提交新 run | ❌ **没有 REST endpoint** |

### 缺失

| 缺失 | 影响 |
|------|------|
| **`submit` 没有 REST endpoint** | Agent 只能通过 CLI + 文件路径提交 |
| **`submit` 不接受 dict** | Agent 必须先写文件再调 CLI |
| **没有 Report schema validation** | 非法 report 可能被静默接受 |
| **没有结构化错误** | 失败时 Agent 只能解析 traceback |
| **没有 `RunStore` 封装** | 逻辑散落在 `record_run.py` + `git_bridge.py` |

---

## 2. 架构

```
Agent
  │
  ▼
RunStore (scripts/run_store.py)
  │
  ├── 输入验证（report schema + manifest schema）
  ├── 业务逻辑（run_id 生成 / 幂等检查 / manifest 一致性校验）
  ├── 文件写入（data/runs/{run_id}/ 下 5 个文件）
  ├── 委托 enrich_report（注入 summary_charts + summary_tables）
  ├── 委托 run_manifest（构建/验证 manifest）
  └── git commit（audit trail）
```

---

## 3. API

### 3.1 操作

| 操作 | 方法 | 输入 | 输出 |
|------|------|------|------|
| **submit** | `RunStore.submit(report, manifest, ...)` | report dict + manifest dict + triggered_by | `{ok, data: {run_id, manifest_hash, overall_score, status}}` |
| **get** | `RunStore.get(run_id)` | 字符串 | `{ok, data: {run_id, meta, manifest, results, config, dataset_ref}}` |
| **list** | `RunStore.list(project=None, limit=20)` | 可选 project | `{ok, data: [{run_id, project, status, overall_score, timestamp}]}` |
| **compare** | `RunStore.compare(run_id_a, run_id_b)` | 两个字符串 | `{ok, data: {score_delta, field_diffs, config_diff, dataset_check}}` |

### 3.2 结构化错误

```python
# 成功
{"ok": true, "data": {...}}

# 失败
{
  "ok": false,
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "report 缺少必填字段 'overall_score'",
    "details": ["缺少必填属性 'overall_score'", "config.metrics[0].name: 缺少必填属性"]
  }
}
```

错误码：

| code | 含义 |
|------|------|
| `VALIDATION_ERROR` | report 或 manifest schema 验证失败 |
| `DUPLICATE_RUN` | run_id 已存在 |
| `MANIFEST_MISMATCH` | manifest_hash 与 manifest 内容不匹配 |
| `NOT_FOUND` | run_id 不存在 |
| `INVALID_REPORT` | report 结构不合法 |

### 3.3 Schema Validation

#### Report Schema

```python
REPORT_SCHEMA = {
    "type": "object",
    "required": ["skill", "created_at", "n_cases", "overall_score", "fields", "cases"],
    "properties": {
        "skill": {"type": "string"},
        "created_at": {"type": "string"},
        "n_cases": {"type": "integer", "minimum": 0},
        "n_passed": {"type": "integer", "minimum": 0},
        "pass_rate": {"type": "number", "minimum": 0.0, "maximum": 1.0},
        "overall_score": {"type": "number", "minimum": 0.0, "maximum": 1.0},
        "grade": {"type": "string"},
        "manifest_hash": {"type": "string"},
        "fields": {"type": "object"},
        "cases": {"type": "array"},
        "bad_cases": {"type": "array"},
        "config": {"type": "object"}
    }
}
```

---

## 4. submit 流程

```
RunStore.submit(report, manifest, triggered_by="agent", run_id=None)
  │
  ├─ 1. 验证 report schema
  │      → 失败：{ok: false, error: {code: "VALIDATION_ERROR"}}
  │
  ├─ 2. 验证 manifest schema
  │      → 失败：{ok: false, error: {code: "VALIDATION_ERROR"}}
  │
  ├─ 3. 校验 manifest 自身一致性
  │      → manifest_hash 必须等于 compute_manifest_hash(manifest)
  │      → 失败：{ok: false, error: {code: "MANIFEST_MISMATCH"}}
  │
  ├─ 4. 生成 run_id（如果未提供）
  │      → 格式：run_YYYYMMDD_NNN
  │      → 自动查找当天已有 run 数，递增序号
  │
  ├─ 5. 检查 run_id 是否已存在
  │      → 存在：{ok: false, error: {code: "DUPLICATE_RUN"}}
  │
  ├─ 6. 注入 manifest_hash 到 report
  │      → report["manifest_hash"] = manifest["manifest_hash"]
  │
  ├─ 7. 丰富化 report
  │      → enrich_report.enrich(report)
  │
  ├─ 8. 创建 run 目录 → data/runs/{run_id}/
  │
  ├─ 9. 写入 5 个文件
  │      ├── manifest.json
  │      ├── results.json   （丰富化后的 report）
  │      ├── meta.json      （快速查询摘要）
  │      ├── config.json     （从 manifest 提取）
  │      └── dataset_ref.json
  │
  ├─ 10. git add + commit
  │
  └─ 11. 返回 {ok: true, data: {run_id, manifest_hash, overall_score, status, pass_rate}}
```

### 4.1 与现有 `record_run.py` 的区别

| | 现有 `record_run` | `RunStore.submit` |
|---|---|---|
| 输入 | `--results` 文件路径 | `report` dict 直接传入 |
| manifest | 从 CLI 参数构建 | 直接传入 manifest dict |
| 错误 | print + sys.exit | 返回 `{ok, error}` |
| REST | 无 | 可被 REST endpoint 调用 |

---

## 5. get / list / compare

### 5.1 get

```
RunStore.get(run_id)
  → 读取 data/runs/{run_id}/ 下所有文件
  → 返回 {ok, data: {run_id, meta, manifest, results, config, dataset_ref}}
```

### 5.2 list

```
RunStore.list(project=None, limit=20)
  → 委托 git_bridge._run_ids_from_log(project)
  → 返回摘要列表
```

### 5.3 compare

```
RunStore.compare(run_id_a, run_id_b)
  → 读取两个 run 的 meta.json + config.json + dataset_ref.json
  → 返回 {score_delta, field_diffs, config_diff, dataset_check}
```

---

## 6. CLI

```bash
# 提交 report（从文件）
python scripts/run_store.py submit \
  --report eval_report.json \
  --manifest manifest.json \
  --triggered-by agent

# 提交 report（从 stdin）
cat eval_report.json | python scripts/run_store.py submit --stdin-report --manifest manifest.json

# 获取 run
python scripts/run_store.py get --run-id run_20260804_001

# 列出 runs
python scripts/run_store.py list --project my_project --limit 10

# 对比 runs
python scripts/run_store.py compare --run-a run_20260804_001 --run-b run_20260805_001
```

---

## 7. REST（添加到 git_bridge.py）

```
POST   /api/runs                → RunStore.submit()
GET    /api/runs                → RunStore.list()
GET    /api/runs/<id>           → RunStore.get()
GET    /api/runs/<a>/diff/<b>   → RunStore.compare()
```

---

## 8. 实现文件清单

| 文件 | 操作 | 说明 |
|------|------|------|
| `scripts/run_store.py` | **新建** | `RunStore` 类 + CLI + schema |
| `scripts/git_bridge.py` | **修改** | 新增 `POST /api/runs` |
| `tests/test_run_store.py` | **新建** | pytest |
| 其他 | 不改动 | `record_run.py` 保留，未来可委托 `RunStore` |

---

## 9. 测试计划

| # | 测试 |
|---|------|
| 1 | `submit` — 合法 report + manifest 提交成功 |
| 2 | `submit` — 返回 run_id |
| 3 | `submit` — 自动生成 run_id（格式正确） |
| 4 | `submit` — 重复 run_id 返回 DUPLICATE_RUN |
| 5 | `submit` — report 缺少 overall_score 返回 VALIDATION_ERROR |
| 6 | `submit` — manifest 缺少 dataset 返回 VALIDATION_ERROR |
| 7 | `submit` — manifest_hash 不匹配返回 MANIFEST_MISMATCH |
| 8 | `submit` — results.json 包含 manifest_hash |
| 9 | `submit` — manifest.json 写入正确 |
| 10 | `submit` — meta.json 包含 status |
| 11 | `submit` — dataset_ref.json 的 content_hash 指向 dataset |
| 12 | `get` — 读取已存在的 run |
| 13 | `get` — 不存在的 run 返回 NOT_FOUND |
| 14 | `list` — 列出所有 runs |
| 15 | `list` — 按 project 过滤 |
| 16 | `compare` — 不同分数返回 delta |
| 17 | `compare` — 相同分数返回 delta=0 |
| 18 | `compare` — 不存在的 run 返回 NOT_FOUND |
| 19 | 结构化错误格式一致 |
| 20 | CLI `submit` 命令 |
| 21 | CLI `list` + `compare` 端到端 |

---

## 10. 与其他 Store 的对称设计

| | MetricStore | DatasetStore | RunStore |
|---|---|---|---|
| **create/submit** | `create(metric_dict)` | `create(id, name, cases)` | `submit(report, manifest)` |
| **list** | `list_metrics()` | `list_datasets()` | `list(project)` |
| **get** | `get(metric_id)` | `get(dataset_id)` | `get(run_id)` |
| **create_version** | `create_version(...)` | `create_version(...)` | —（Run 不可变） |
| **get_version** | `get_version(id, hash)` | `get_version(id, hash)` | —（get 就是 get） |
| **list_versions** | `list_versions(id)` | `list_versions(id)` | — |
| **diff/compare** | `diff_versions(id, ha, hb)` | `diff_versions(id, ha, hb)` | `compare(run_a, run_b)` |
| **错误格式** | `{ok, error: {code, msg, details}}` | 同 | 同 |
| **底层委托** | `metric_versioning` | `dataset_versioning` | `run_manifest` + `enrich_report` |

---

## 11. 不做什么

- ❌ 不修改 GUI
- ❌ 不修改 evaluation execution engine
- ❌ 不添加数据库
- ❌ 不修改 Metric/Dataset API
- ❌ 不删除 `record_run.py`（保留，未来委托 `RunStore`）