# Agent-native Metric API — Design Document

> 状态：待实现
> 目标：Agent 不需要 GUI 或手动编辑 JSON 文件，就能管理 Metric。提供 CLI + Python API + REST。

---

## 1. 现有分析

### 已实现（`metric_versioning.py`）

| 函数 | 能力 | Agent 可用？ |
|------|------|:--:|
| `compute_version_hash(metric)` | 纯函数，计算 hash | ✅ |
| `create_version(metric_path)` | 从 **文件路径** 创建版本快照 | ❌ 需要先写文件 |
| `read_version(metric_id, hash)` | 读指定版本 | ✅ |
| `list_versions(metric_id)` | 列出版本 | ✅ |
| `diff_versions(metric_id, ha, hb)` | 对比版本 | ✅ |
| `migrate_existing(base_dir)` | 批量迁移 | ✅ |

### 缺失

| 缺失 | 影响 |
|------|------|
| **没有 `create` metric** | Agent 无法从 dict 创建新 metric。必须先手动写文件，再调 `create_version` |
| **没有 `get` current metric** | Agent 无法读当前 metric 定义（不知道最新的 version_hash 是什么） |
| **没有 schema validation** | 非法 metric 不会被拒绝，直接进入系统 |
| **没有结构化错误** | 所有错误都是 `ValueError` + traceback，Agent 无法程序化处理 |
| **`create_version` 依赖文件路径** | Agent 必须先写文件到正确位置 |
| **没有统一 API 对象** | 函数散落在模块中，没有 `MetricStore` 封装 |

---

## 2. 架构

```
Agent
  │
  ▼
MetricStore (scripts/metric_store.py)
  │
  ├── 输入验证（mini_json_schema.validate）
  ├── 业务逻辑（id 唯一性检查、category 推断）
  ├── 文件写入（metric JSON + version 快照）
  └── 委托 metric_versioning（compute_hash / create_version / read / list / diff）
```

---

## 3. API

### 3.1 操作

| 操作 | 方法 | 输入 | 输出 |
|------|------|------|------|
| **create** | `MetricStore.create(metric_dict)` | metric 定义 dict | `{ok, data: {metric_id, version_hash, created_at, is_new}}` |
| **get** | `MetricStore.get(metric_id)` | 字符串 | `{ok, data: {metric 完整定义}}` |
| **list** | `MetricStore.list_metrics()` | 无 | `{ok, data: [{metric_id, name, category, version_hash}]}` |
| **create_version** | `MetricStore.create_version(metric_id, metric_dict)` | metric_id + 新定义 dict | `{ok, data: {version_hash, is_new}}` |
| **get_version** | `MetricStore.get_version(metric_id, hash)` | 两个字符串 | `{ok, data: {version 完整记录}}` |
| **list_versions** | `MetricStore.list_versions(metric_id)` | 字符串 | `{ok, data: [{metric_id, version_hash, created_at, name}]}` |
| **diff_versions** | `MetricStore.diff_versions(metric_id, ha, hb)` | 三个字符串 | `{ok, data: {changes, added_fields, removed_fields, modified_fields}}` |

### 3.2 结构化错误

所有方法返回 `{ok, data}` 或 `{ok, error}`。不抛异常。

```python
# 成功
{"ok": true, "data": {...}}

# 失败
{
  "ok": false,
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "metric 缺少必填字段 'id'",
    "details": ["缺少必填属性 'id'", "params[0].type: 值 'float' 不在枚举中"]
  }
}
```

错误码：

| code | 含义 |
|------|------|
| `VALIDATION_ERROR` | schema 验证失败 |
| `DUPLICATE_ID` | metric_id 已存在 |
| `NOT_FOUND` | metric_id 或 version_hash 不存在 |
| `VERSION_EXISTS` | 版本已存在（幂等，is_new=false） |
| `INVALID_CATEGORY` | category 不是 `llm` 或 `non_llm` |

### 3.3 Schema Validation

```python
METRIC_SCHEMA = {
    "type": "object",
    "required": ["id", "name", "category", "params", "requires", "code_template"],
    "properties": {
        "id": {"type": "string", "minLength": 1},
        "name": {"type": "string", "minLength": 1},
        "category": {"type": "string", "enum": ["llm", "non_llm"]},
        "description": {"type": "string"},
        "params": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["key", "type", "default"],
                "properties": {
                    "key": {"type": "string"},
                    "label": {"type": "string"},
                    "type": {"type": "string", "enum": ["string", "number", "boolean", "json", "select"]},
                    "default": {},
                    "required": {"type": "boolean"},
                    "min": {"type": "number"},
                    "max": {"type": "number"},
                    "step": {"type": "number"},
                    "options": {"type": "array"}
                }
            }
        },
        "criteria": {"oneOf": [{"type": "string"}, {"type": "null"}]},
        "requires": {"type": "array", "items": {"type": "string"}},
        "code_template": {"type": "string", "minLength": 1}
    }
}
```

---

## 4. create 流程

```
MetricStore.create(metric_dict)
  │
  ├─ 1. validate(metric_dict, METRIC_SCHEMA)
  │      → 失败：{ok: false, error: {code: "VALIDATION_ERROR", ...}}
  │
  ├─ 2. 检查 metric_id 是否已存在
  │      → 存在：{ok: false, error: {code: "DUPLICATE_ID", ...}}
  │
  ├─ 3. 确定 category 目录 → data/metrics/{category}/
  │
  ├─ 4. 写入 metric JSON 文件 → data/metrics/{category}/{id}.json
  │
  ├─ 5. 调用 metric_versioning.create_version(path)
  │      → 创建 .versions/{id}/{hash}.json
  │
  └─ 6. 返回 {ok: true, data: {metric_id, version_hash, created_at, is_new: true}}
```

---

## 5. create_version 流程

```
MetricStore.create_version(metric_id, new_metric_dict)
  │
  ├─ 1. validate(new_metric_dict, METRIC_SCHEMA)
  │
  ├─ 2. 检查 metric_id 是否存在 → 不存在：NOT_FOUND
  │
  ├─ 3. 检查 new_metric_dict["id"] == metric_id（不允许改 id）
  │
  ├─ 4. 覆盖当前 metric JSON 文件
  │
  ├─ 5. 调用 metric_versioning.create_version(path)
  │      → hash 相同：is_new=false（幂等）
  │      → hash 不同：创建新版本，旧版本在 .versions/ 中保留
  │
  └─ 6. 返回 {ok: true, data: {metric_id, version_hash, is_new}}
```

---

## 6. CLI

```bash
# 创建
python scripts/metric_store.py create '{"id":"empathy","name":"同理心","category":"llm","params":[...],"criteria":"...","requires":["actual_output"],"code_template":"GEval(...)"}'

# 获取当前
python scripts/metric_store.py get --metric-id empathy

# 列出所有
python scripts/metric_store.py list

# 创建新版本
python scripts/metric_store.py create-version --metric-id empathy '{"id":"empathy","name":"同理心","category":"llm","params":[...],"criteria":"新标准","requires":["actual_output"],"code_template":"GEval(...)"}'

# 获取指定版本
python scripts/metric_store.py get-version --metric-id empathy --version-hash a1b2c3d4...

# 列出版本
python scripts/metric_store.py list-versions --metric-id empathy

# 对比
python scripts/metric_store.py diff --metric-id empathy --version-a a1b2c3d4... --version-b e5f6g7h8...
```

---

## 7. REST（可选，添加到 git_bridge.py）

```
POST   /api/metrics                          → MetricStore.create()
GET    /api/metrics                          → MetricStore.list_metrics()
GET    /api/metrics/<id>                     → MetricStore.get()
PUT    /api/metrics/<id>                     → MetricStore.create_version()
GET    /api/metrics/<id>/versions            → MetricStore.list_versions()
GET    /api/metrics/<id>/versions/<h>        → MetricStore.get_version()
GET    /api/metrics/<id>/versions/<ha>/diff/<hb> → MetricStore.diff_versions()
```

---

## 8. 实现文件清单

| 文件 | 操作 | 说明 |
|------|------|------|
| `scripts/metric_store.py` | **新建** | `MetricStore` 类 + CLI + schema |
| `scripts/git_bridge.py` | **修改** | 新增 7 个 REST endpoint |
| `tests/test_metric_store.py` | **新建** | pytest |
| 其他 | 不改动 | `metric_versioning.py` 作为底层保持不变 |

---

## 9. 测试计划

| # | 测试 |
|---|------|
| 1 | `create` — 合法 metric 创建成功 |
| 2 | `create` — 缺少 id 返回 VALIDATION_ERROR |
| 3 | `create` — 非法 category 返回 VALIDATION_ERROR |
| 4 | `create` — 重复 id 返回 DUPLICATE_ID |
| 5 | `create` — 返回结果包含 version_hash |
| 6 | `get` — 读取已存在的 metric |
| 7 | `get` — 不存在的 metric 返回 NOT_FOUND |
| 8 | `list` — 列出所有 metric |
| 9 | `create_version` — 修改 criteria 创建新版本 |
| 10 | `create_version` — 幂等（相同内容不创建重复版本） |
| 11 | `create_version` — 不存在的 metric 返回 NOT_FOUND |
| 12 | `create_version` — 改 id 被拒绝 |
| 13 | `create_version` — 旧版本文件保留不变 |
| 14 | `get_version` — 读取指定版本 |
| 15 | `list_versions` — 列出所有版本 |
| 16 | `diff_versions` — 检测修改 |
| 17 | 结构化错误格式一致 |
| 18 | CLI `create` 命令 |
| 19 | CLI `get` 命令 |
| 20 | CLI `create-version` + `diff` 端到端 |