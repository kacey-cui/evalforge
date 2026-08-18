# Agent-native Dataset API — Design Document

> 状态：待实现
> 目标：Agent 不需要 GUI 或手动编辑 JSON 文件，就能管理 Dataset。提供 CLI + Python API。

---

## 1. 现有分析

### 已实现（`dataset_versioning.py`）

| 函数 | 能力 | Agent 可用？ |
|------|------|:--:|
| `compute_content_hash(cases)` | 纯函数 | ✅ |
| `compute_version_hash(def, content_hash)` | 纯函数 | ✅ |
| `infer_schema(cases)` | 自动推断 schema | ✅ |
| `validate_dataset(cases, schema)` | 校验 | ✅ |
| `create_dataset(id, name, cases, ...)` | 创建 dataset | ⚠️ CLI 需要 `--source` 文件路径 |
| `create_version(dataset_id)` | 从当前文件创建版本 | ⚠️ 只读文件，不接受新 cases |
| `read_version(dataset_id, hash)` | 读版本 | ✅ |
| `list_versions(dataset_id)` | 列出版本 | ✅ |
| `get_current(dataset_id)` | 读当前 dataset | ✅ |
| `diff_versions(dataset_id, ha, hb, fields)` | 对比版本 | ✅ |
| `migrate_from_file(source_path, ...)` | 迁移 | ✅ |

### 缺失

| 缺失 | 影响 |
|------|------|
| **`create` 需要 `--source` 文件路径** | Agent 必须先写文件才能创建 dataset |
| **`create_version` 不接受新 cases** | Agent 必须手动覆盖 `test_cases.json` 再调 `create_version` |
| **没有 `list_datasets`** | Agent 不知道有哪些 dataset |
| **没有结构化错误** | 所有错误都是 `ValueError` + traceback |
| **没有统一 API 对象** | 函数散落，没有 `DatasetStore` 封装 |

---

## 2. 架构

```
Agent
  │
  ▼
DatasetStore (scripts/dataset_store.py)
  │
  ├── 输入验证（mini_json_schema.validate）
  ├── 业务逻辑（case_id 分配、schema 推断、id 唯一性检查）
  ├── 文件写入（dataset.json + test_cases.json + version 快照）
  └── 委托 dataset_versioning（compute_hash / create_version / read / list / diff）
```

---

## 3. API

### 3.1 操作

| 操作 | 方法 | 输入 | 输出 |
|------|------|------|------|
| **create** | `DatasetStore.create(dataset_id, name, cases, ...)` | dataset_id + name + cases 列表 | `{ok, data: {dataset_id, version_hash, content_hash, n_cases, is_new}}` |
| **list** | `DatasetStore.list_datasets()` | 无 | `{ok, data: [{dataset_id, name, n_cases, version_hash}]}` |
| **get** | `DatasetStore.get(dataset_id)` | 字符串 | `{ok, data: {dataset 定义 + cases}}` |
| **create_version** | `DatasetStore.create_version(dataset_id, cases)` | dataset_id + 新 cases 列表 | `{ok, data: {version_hash, content_hash, is_new}}` |
| **get_version** | `DatasetStore.get_version(dataset_id, hash)` | 两个字符串 | `{ok, data: {version 完整记录}}` |
| **list_versions** | `DatasetStore.list_versions(dataset_id)` | 字符串 | `{ok, data: [{dataset_id, version_hash, created_at, name}]}` |
| **diff_versions** | `DatasetStore.diff_versions(dataset_id, ha, hb, fields)` | 三个字符串 + 可选 fields | `{ok, data: {summary, schema_changes, added_cases, removed_cases, modified_cases}}` |

### 3.2 结构化错误

```python
# 成功
{"ok": true, "data": {...}}

# 失败
{
  "ok": false,
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "cases 缺少 case_id",
    "details": ["case_id=?: 缺少必填属性 'input'"]
  }
}
```

错误码：

| code | 含义 |
|------|------|
| `VALIDATION_ERROR` | schema 验证失败 |
| `DUPLICATE_ID` | dataset_id 已存在 |
| `NOT_FOUND` | dataset_id 或 version_hash 不存在 |
| `VERSION_EXISTS` | 版本已存在（幂等） |
| `INVALID_CASES` | cases 不是合法 list |

### 3.3 Schema Validation

`create()` 和 `create_version()` 在写入前验证。验证分两层：

1. **cases 结构验证**：每个 case 是 dict，`case_id` 是 int 或可分配
2. **dataset schema 验证**：如果提供了 schema，逐 case 校验字段类型

---

## 4. create 流程

```
DatasetStore.create(dataset_id, name, cases, description="", schema=None)
  │
  ├─ 1. 检查 dataset_id 是否已存在
  │      → 存在：{ok: false, error: {code: "DUPLICATE_ID"}}
  │
  ├─ 2. 分配 case_id（委托 _assign_case_ids）
  │      → 失败：{ok: false, error: {code: "INVALID_CASES"}}
  │
  ├─ 3. 推断/校验 schema
  │      → schema=None：自动推断
  │      → schema 给定：逐 case 校验
  │      → 失败：{ok: false, error: {code: "VALIDATION_ERROR"}}
  │
  ├─ 4. 写 dataset.json + test_cases.json
  │
  ├─ 5. 创建初始版本快照
  │
  └─ 6. 返回 {ok: true, data: {dataset_id, version_hash, content_hash, n_cases, is_new: true}}
```

### 4.1 与现有 `create_dataset` 的关键区别

| | 现有 `create_dataset` | `DatasetStore.create` |
|---|---|---|
| 输入 | `cases` 来自 `--source` 文件路径 | `cases` 直接作为 Python list 传入 |
| 错误处理 | 抛 ValueError | 返回 `{ok, error}` |
| schema | 只支持自动推断或文件路径 | 支持 dict 传入 |

---

## 5. create_version 流程

```
DatasetStore.create_version(dataset_id, new_cases)
  │
  ├─ 1. 检查 dataset_id 是否存在
  │      → 不存在：{ok: false, error: {code: "NOT_FOUND"}}
  │
  ├─ 2. 分配 case_id（保留已有 case_id，新 case 自动分配）
  │
  ├─ 3. 读取当前 schema，校验 new_cases
  │      → 失败：{ok: false, error: {code: "VALIDATION_ERROR"}}
  │
  ├─ 4. 覆盖 test_cases.json + 更新 dataset.json（n_cases、content_hash）
  │
  ├─ 5. 委托 dataset_versioning.create_version(dataset_id)
  │      → hash 相同：is_new=false（幂等）
  │      → hash 不同：创建新版本
  │
  └─ 6. 返回 {ok: true, data: {version_hash, content_hash, is_new}}
```

### 5.1 与现有 `create_version` 的关键区别

| | 现有 `create_version` | `DatasetStore.create_version` |
|---|---|---|
| 输入 | 无（从文件读当前 cases） | 接受新的 cases list |
| 能力 | 只能给当前文件状态做快照 | 可以修改 cases 并创建新版本 |
| 幂等 | 是 | 是 |

---

## 6. CLI

```bash
# 创建（从文件）
python scripts/dataset_store.py create \
  --dataset-id my_dataset \
  --name "我的评测集" \
  --source test_cases.json

# 创建（从 stdin）
echo '[{"input":"问题1","expected_output":"答案1"}]' | \
  python scripts/dataset_store.py create --dataset-id my_dataset --name "我的评测集" --stdin

# 列出所有 dataset
python scripts/dataset_store.py list

# 获取当前
python scripts/dataset_store.py get --dataset-id my_dataset

# 创建新版本（从文件）
python scripts/dataset_store.py create-version \
  --dataset-id my_dataset \
  --source new_cases.json

# 创建新版本（从 stdin）
cat new_cases.json | \
  python scripts/dataset_store.py create-version --dataset-id my_dataset --stdin

# 获取指定版本
python scripts/dataset_store.py get-version \
  --dataset-id my_dataset --version-hash a1b2c3d4...

# 列出版本
python scripts/dataset_store.py list-versions --dataset-id my_dataset

# 对比
python scripts/dataset_store.py diff \
  --dataset-id my_dataset \
  --version-a a1b2c3d4... --version-b e5f6g7h8...

# 对比（只看指定字段）
python scripts/dataset_store.py diff \
  --dataset-id my_dataset \
  --version-a a1b2c3d4... --version-b e5f6g7h8... \
  --fields input,expected_output
```

---

## 7. 实现文件清单

| 文件 | 操作 | 说明 |
|------|------|------|
| `scripts/dataset_store.py` | **新建** | `DatasetStore` 类 + CLI |
| `tests/test_dataset_store.py` | **新建** | pytest |
| 其他 | 不改动 | `dataset_versioning.py` 作为底层保持不变 |

---

## 8. 测试计划

| # | 测试 |
|---|------|
| 1 | `create` — 合法 cases 创建成功 |
| 2 | `create` — 自动分配 case_id |
| 3 | `create` — 保留已有 case_id |
| 4 | `create` — 重复 dataset_id 返回 DUPLICATE_ID |
| 5 | `create` — 无效 cases 返回 INVALID_CASES |
| 6 | `create` — schema 校验失败返回 VALIDATION_ERROR |
| 7 | `get` — 读取已存在的 dataset |
| 8 | `get` — 不存在的 dataset 返回 NOT_FOUND |
| 9 | `list` — 列出所有 dataset |
| 10 | `list` — 空目录返回空列表 |
| 11 | `create_version` — 新增 case 创建新版本 |
| 12 | `create_version` — 修改 case 字段创建新版本 |
| 13 | `create_version` — 幂等（相同 cases 不创建重复版本） |
| 14 | `create_version` — 不存在的 dataset 返回 NOT_FOUND |
| 15 | `create_version` — 旧版本内容文件保留不变 |
| 16 | `get_version` — 读取指定版本 |
| 17 | `list_versions` — 列出所有版本 |
| 18 | `diff_versions` — 检测 added cases |
| 19 | `diff_versions` — 检测 removed cases |
| 20 | `diff_versions` — 检测 modified cases（字段值变化） |
| 21 | `diff_versions` — 检测 schema 级变化 |
| 22 | `diff_versions` — 字段过滤 |
| 23 | 结构化错误格式一致 |
| 24 | CLI `create` 命令 |
| 25 | CLI `create-version` + `diff` 端到端 |

---

## 9. 与 MetricStore 的对称设计

| | MetricStore | DatasetStore |
|---|---|---|
| **create** | `create(metric_dict)` | `create(dataset_id, name, cases, ...)` |
| **list** | `list_metrics()` | `list_datasets()` |
| **get** | `get(metric_id)` | `get(dataset_id)` |
| **create_version** | `create_version(metric_id, new_dict)` | `create_version(dataset_id, new_cases)` |
| **get_version** | `get_version(metric_id, hash)` | `get_version(dataset_id, hash)` |
| **list_versions** | `list_versions(metric_id)` | `list_versions(dataset_id)` |
| **diff_versions** | `diff_versions(metric_id, ha, hb)` | `diff_versions(dataset_id, ha, hb, fields)` |
| **错误格式** | `{ok, error: {code, message, details}}` | 同 |
| **底层委托** | `metric_versioning` | `dataset_versioning` |