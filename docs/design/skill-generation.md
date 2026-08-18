# Skill Generation — Design Document

> 状态：待实现
> 目标：将 Skill generation 从 frontend 抽离为 Python 模块，Agent 可通过 CLI/Python API 生成 Skill。

---

## 1. 当前问题

| # | 问题 | 根因 |
|---|------|------|
| 1 | Skill generation 只在 `index.html` 的 JavaScript 中 | `generateSkillCode()` + `downloadSkillZip()` 在前端 |
| 2 | Agent 无法程序化生成 Skill | 必须打开浏览器，点 GUI |
| 3 | 模板替换逻辑是 JS 的 `replaceAll` | 没有 Python 实现 |
| 4 | 生成的 Skill 没有 manifest.json | 无 provenance |
| 5 | GUI 和 Agent 各自维护生成逻辑 | 如果 Agent 也要生成 Skill，必须重复实现 |

---

## 2. 架构

```
Agent / CLI / GUI
  │
  ▼
generate_skill.py (scripts/generate_skill.py)
  │
  ├── 输入验证（schema validation）
  ├── 模板渲染（templates/skill/*.tpl）
  ├── 文件生成（SKILL.md, eval_script.py, test_cases_template.json, requirements.txt, manifest.json）
  └── 输出 Skill 目录（或 zip）
```

**GUI 后续调用同一个 Python 模块**，不再维护独立的 JS 生成逻辑。

---

## 3. 输入模型

### 3.1 SkillSpec

```python
@dataclass
class SkillSpec:
    """生成 Skill 的完整输入规范"""
    skill_name: str                          # skill 名称
    description: str = ""                    # skill 描述
    model: ModelConfig = field(...)          # 被测模型
    judge_model: JudgeModelConfig = None     # judge 模型（可选）
    fields: list[FieldPipeline] = field(...) # 评测管线
    dataset_ref: DatasetRefInfo = None       # dataset 引用（可选）
    metric_versions: dict[str, str] = field(...)  # metric_id → version_hash
    template: str = "deepeval"               # 模板名（deepeval | custom）
    extra_files: dict[str, str] = field(...) # 额外文件（文件名 → 内容）
```

### 3.2 子模型

```python
@dataclass
class ModelConfig:
    model_id: str
    base_url: str = ""
    api_key_env: str = "MODEL_API_KEY"

@dataclass
class JudgeModelConfig:
    model_id: str
    base_url: str = ""
    api_key_env: str = "MODEL_API_KEY"

@dataclass
class FieldPipeline:
    name: str                                # 字段名
    gate_pipeline: list[MetricInstance] = [] # 门禁
    score_pipeline: list[MetricInstance] = []# 打分

@dataclass
class MetricInstance:
    metric_id: str                           # 引用哪个 metric
    version_hash: str = ""                   # 版本 hash
    params: dict = {}                        # 实例参数
    weight: float = 0.3                      # 权重（仅 score）
    strictness: float = 1.0                  # 严格度（仅 score）
    zone: str = "score"                      # "gate" | "score"

@dataclass
class DatasetRefInfo:
    dataset_id: str = ""
    version_hash: str = ""
    content_hash: str = ""
    n_cases: int = 0
```

---

## 4. 输出结构

```
{skill_name}/
├── SKILL.md                  # Skill 元数据
├── eval_script.py            # 评测脚本
├── test_cases_template.json  # 测试用例模板
├── requirements.txt          # Python 依赖
└── manifest.json             # 生成 provenance
```

### 4.1 manifest.json

```json
{
  "skill_name": "my_eval",
  "skill_hash": "a1b2c3d4...",
  "generated_at": "2026-08-18T10:00:00Z",
  "generator_version": "1.0",
  "template": "deepeval",
  "model": {
    "model_id": "your-model-id",
    "base_url": "https://your-model-gateway.example.com/v1"
  },
  "judge_model": {
    "model_id": "your-model-id",
    "base_url": "https://your-model-gateway.example.com/v1"
  },
  "dataset": {
    "dataset_id": "my_dataset_v1",
    "version_hash": "a1b2c3d4...",
    "content_hash": "x1y2z3..."
  },
  "metric_versions": {
    "accuracy": "e5f6g7h8...",
    "json_schema": "f5b6ed16..."
  },
  "fields": [
    {
      "name": "diagnosis",
      "gate_count": 1,
      "score_count": 2
    }
  ],
  "file_hashes": {
    "SKILL.md": "abc123...",
    "eval_script.py": "def456...",
    "test_cases_template.json": "ghi789...",
    "requirements.txt": "jkl012..."
  }
}
```

### 4.2 skill_hash

`skill_hash = SHA256(manifest.json 的规范化内容，移除 skill_hash 和 file_hashes 字段)`

作用：相同输入 → 相同 skill_hash → 生成完全相同的 Skill。

---

## 5. 核心流程

```
generate_skill(spec: SkillSpec) → SkillPackage
  │
  ├─ 1. 验证 spec（schema validation）
  │
  ├─ 2. 加载 metric definitions
  │     ├─ 从 MetricStore 读取每个 metric 的当前 definition
  │     └─ 用 version_hash 校验（如果提供）
  │
  ├─ 3. 渲染 eval_script.py
  │     ├─ 对每个 metric instance，替换 code_template 中的 {{param}} 占位符
  │     ├─ 生成 customMetricsCode（所有 metric 类定义）
  │     ├─ 生成 fieldEvalCode（每个 field 的 gate + score 评测逻辑）
  │     └─ 替换模板中的 {{skillName}}, {{modelId}}, {{modelBaseUrl}}, 等
  │
  ├─ 4. 渲染 SKILL.md
  │     └─ 替换 {{skillName}}, {{metricCount}}, {{metricList}}
  │
  ├─ 5. 生成 test_cases_template.json
  │     ├─ 如果提供了 dataset_ref → 从 DatasetStore 读取，生成模板
  │     └─ 否则 → 生成默认模板（1 条示例）
  │
  ├─ 6. 生成 requirements.txt
  │     └─ 根据 template 类型写入依赖
  │
  ├─ 7. 生成 manifest.json
  │     ├─ 收集所有 provenance 信息
  │     ├─ 计算每个文件的 hash
  │     └─ 计算 skill_hash
  │
  └─ 8. 返回 SkillPackage（包含所有文件路径和内容）
```

---

## 6. 模板渲染（核心逻辑）

从 `index.html` 的 `generateSkillCode()` 移植过来，做以下改进：

### 6.1 当前 JS 逻辑 → Python 逻辑

| JS | Python |
|----|--------|
| `MetricStore.getById(id)` | `MetricStore.get(id)` → Python API |
| `code.replace(/\{\{key\}\}/g, val)` | `code.replace("{{" + key + "}}", str(val))` |
| `formatCodeValue(val, type)` | `_format_python_value(val, type)` |
| `JSON.stringify(fc.weights)` | `json.dumps(weights)` |
| `canvasFields.forEach(...)` | 遍历 `spec.fields` |

### 6.2 代码生成函数

```python
def _generate_custom_metrics_code(fields, metric_defs) -> str:
    """生成所有 custom metric 类定义"""

def _generate_field_eval_code(fields, metric_defs) -> str:
    """生成每个 field 的评测代码（gate + score）"""

def _format_python_value(val, param_type) -> str:
    """将 JS 值转为 Python 代码字符串"""
    if param_type == "json":
        return json.dumps(json.loads(val) if isinstance(val, str) else val)
    if param_type == "string":
        return json.dumps(str(val))
    if param_type == "boolean":
        return "True" if val else "False"
    if param_type == "number":
        return str(float(val) if '.' in str(val) else int(val))
    return str(val)

def _render_metric_instance(metric_def, instance_params) -> str:
    """渲染单个 metric instance 的代码"""
    if metric_def["category"] == "non_llm":
        # class MyMetric(BaseMetric): ... → MyMetric(param1=val1, param2=val2)
        class_name = _extract_class_name(metric_def["code_template"])
        args = _build_constructor_args(metric_def["params"], instance_params)
        return f"{class_name}({args})"
    else:
        # GEval(name="...", criteria="...", threshold=0.7, model=JUDGE_MODEL)
        code = metric_def["code_template"]
        code = code.replace("{{criteria}}", metric_def.get("criteria") or "")
        for p in metric_def["params"]:
            val = instance_params.get(p["key"], p["default"])
            code = code.replace("{{" + p["key"] + "}}", _format_python_value(val, p["type"]))
        return code
```

---

## 7. API

### 7.1 Python API

```python
from scripts.generate_skill import generate_skill, SkillSpec, SkillPackage

spec = SkillSpec(
    skill_name="my_eval",
    model=ModelConfig(model_id="your-model-id", base_url="https://..."),
    fields=[
        FieldPipeline(
            name="diagnosis",
            gate_pipeline=[MetricInstance(metric_id="json_schema", params={"schema": '{"name":"str"}'})],
            score_pipeline=[MetricInstance(metric_id="accuracy", params={"threshold": 0.7}, weight=0.5)],
        )
    ],
    metric_versions={"json_schema": "f5b6ed16...", "accuracy": "106e6571..."},
)

package: SkillPackage = generate_skill(spec)
# package.path → 生成的目录路径
# package.files → {"SKILL.md": "...", "eval_script.py": "...", ...}
# package.manifest → manifest dict
# package.skill_hash → SHA256
```

### 7.2 CLI

```bash
# 从 canvas.json 生成
python scripts/generate_skill.py \
  --project my_project \
  --output ./output/

# 从 JSON spec 生成
python scripts/generate_skill.py \
  --spec skill_spec.json \
  --output ./output/

# 输出 zip
python scripts/generate_skill.py \
  --project my_project \
  --output ./my_skill.zip
```

### 7.3 GUI 集成（未来）

```javascript
// index.html 后续改为调用 Python API
async function downloadSkillZip() {
  const spec = buildSkillSpec();  // 用现有 canvasFields 构建 SkillSpec
  const response = await fetch('/api/skills/generate', {
    method: 'POST',
    body: JSON.stringify(spec)
  });
  const blob = await response.blob();
  // 触发下载...
}
```

---

## 8. 实现文件清单

| 文件 | 操作 | 说明 |
|------|------|------|
| `scripts/generate_skill.py` | **新建** | 核心模块：SkillSpec, generate_skill(), 模板渲染, CLI |
| `tests/test_generate_skill.py` | **新建** | pytest |
| `docs/design/skill-generation.md` | **已创建** | 本设计文档 |
| `index.html` | **不改** | 本次不改 GUI |
| `templates/skill/*.tpl` | **不改** | 复用现有模板 |

---

## 9. 测试计划

| # | 测试 |
|---|------|
| 1 | `generate_skill` — 生成完整 Skill 目录 |
| 2 | 生成目录包含所有 5 个文件 |
| 3 | `eval_script.py` 语法有效（`compile()` 通过） |
| 4 | `SKILL.md` 包含 skill name |
| 5 | `manifest.json` 包含所有必填字段 |
| 6 | `manifest.json` 的 metric_versions 正确 |
| 7 | `manifest.json` 的 dataset 引用正确 |
| 8 | `manifest.json` 的 file_hashes 与实际文件匹配 |
| 9 | `skill_hash` 确定性（相同输入 → 相同 hash） |
| 10 | `skill_hash` 不同输入 → 不同 hash |
| 11 | non-LLM metric 代码生成正确 |
| 12 | LLM metric 代码生成正确（GEval） |
| 13 | 参数化 metric（recall_at_k 多个 k）正确渲染 |
| 14 | gate pipeline 代码生成正确 |
| 15 | score pipeline 权重和严格度正确 |
| 16 | `_format_python_value` — json 类型 |
| 17 | `_format_python_value` — number 类型 |
| 18 | `_format_python_value` — boolean 类型 |
| 19 | `_format_python_value` — string 类型 |
| 20 | 空 pipeline 不报错 |
| 21 | 缺少 metric_id 报错 |
| 22 | CLI `--project` 模式 |
| 23 | CLI `--spec` 模式 |
| 24 | 生成的文件 encoding 为 UTF-8 |

---

## 10. 不做什么

- ❌ 不修改 GUI（本次不改 `index.html`）
- ❌ 不修改 evaluation execution engine
- ❌ 不添加数据库
- ❌ 不修改 Metric/Dataset API
- ❌ 不修改模板文件（`templates/skill/*.tpl`）

---

## 11. 设计决策

| 决策 | 理由 |
|------|------|
| 从 `index.html` 移植逻辑到 Python | 保持生成结果一致，Agent 可用 |
| `SkillSpec` dataclass 作为输入 | 类型安全，可序列化，GUI 可直接构建 |
| manifest.json 包含 skill_hash | 相同输入 → 相同 Skill，可验证 |
| manifest.json 包含 file_hashes | 每个文件可独立校验 |
| 模板文件保持不变 | 复用现有模板，减少改动范围 |
| GUI 后续调用 Python API | 单一实现，不重复维护 |