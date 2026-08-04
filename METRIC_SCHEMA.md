# Metric JSON Schema

> Agent 和平台之间的共享契约。Agent 生成指标 JSON 文件放到 `data/metrics/` 下，平台自动加载。

## 文件位置

```
data/metrics/
├── non_llm/          # 非 LLM 指标（纯 Python 逻辑）
│   └── {id}.json
└── llm/              # LLM 指标（GEval，需调模型）
    └── {id}.json
```

## 完整 JSON 结构

```json
{
  "id": "string",
  "name": "string",
  "category": "non_llm | llm",
  "description": "string",
  "params": [
    {
      "key": "string",
      "label": "string",
      "type": "string | number | boolean | json | select",
      "default": "any",
      "required": "boolean",
      "min": "number (optional)",
      "max": "number (optional)",
      "step": "number (optional)",
      "options": ["string (optional, only for select type)"]
    }
  ],
  "criteria": "string | null",
  "requires": ["actual_output", "expected_output", ...],
  "code_template": "string"
}
```

## 字段说明

| 字段 | 必填 | 说明 |
|------|------|------|
| `id` | ✅ | 唯一标识，英文 snake_case，如 `accuracy`、`json_schema` |
| `name` | ✅ | 中文显示名，如 `准确度 (GEval)` |
| `category` | ✅ | `non_llm` 或 `llm` |
| `description` | ✅ | 一句话描述这个指标做什么 |
| `params` | ✅ | 用户可配置的参数列表 |
| `criteria` | ❌ | 仅 LLM 指标需要，GEval 的评分标准文本 |
| `requires` | ✅ | 运行需要哪些数据字段：`actual_output`、`expected_output`、`retrieval_context`、`completion_time` |
| `code_template` | ✅ | 导出 Skill 时的 Python 代码模板 |

## 两种类型的区别

### Non-LLM 指标

纯 Python 逻辑，不调模型。`code_template` 是完整的 `BaseMetric` 子类：

```python
class MyMetric(BaseMetric):
    def __init__(self, param1, threshold={{threshold}}):
        ...
    def measure(self, test_case): ...
    async def a_measure(self, test_case): ...
    def is_successful(self): ...
```

模板中用 `{{param_key}}` 引用参数，导出时自动替换为用户配置的值。

### LLM 指标

调用 GEval（LLM 评委）。`code_template` 是 GEval 调用代码：

```python
GEval(
    name="{{name}}",
    criteria="{{criteria}}",
    evaluation_params=[LLMTestCaseParams.EXPECTED_OUTPUT, LLMTestCaseParams.ACTUAL_OUTPUT],
    threshold={{threshold}},
    model=JUDGE_MODEL,
)
```

`criteria` 字段是评分标准文本，会被注入到 `{{criteria}}` 占位符。

## 示例

### Non-LLM 示例：关键词命中率

```json
{
  "id": "keyword_hit",
  "name": "关键词命中率",
  "category": "non_llm",
  "description": "检查 actual_output 是否包含所有指定关键词",
  "params": [
    {"key": "required_keywords", "label": "关键词列表", "type": "json", "default": "[\"全额退款\"]", "required": true},
    {"key": "threshold", "label": "通过阈值", "type": "number", "default": 0.8, "min": 0, "max": 1, "step": 0.1}
  ],
  "criteria": null,
  "requires": ["actual_output"],
  "code_template": "class KeywordHitMetric(BaseMetric):\n    def __init__(self, required_keywords, threshold={{threshold}}):\n        self.threshold = threshold\n        self.required_keywords = required_keywords\n        self.evaluation_model = \"keyword-checker\"\n    def measure(self, test_case, *args, **kwargs):\n        actual = (test_case.actual_output or \"\").lower()\n        hits = [kw for kw in self.required_keywords if kw.lower() in actual]\n        self.score = round(len(hits) / len(self.required_keywords), 3)\n        self.success = self.score >= self.threshold\n        self.reason = f\"命中 {len(hits)}/{len(self.required_keywords)}\"\n        return self.score\n    async def a_measure(self, test_case, *args, **kwargs):\n        return self.measure(test_case)\n    def is_successful(self):\n        return bool(self.score and self.score >= self.threshold)\n    @property\n    def __name__(self):\n        return \"Keyword Hit Rate\""
}
```

### LLM 示例：准确度

```json
{
  "id": "accuracy",
  "name": "准确度 (GEval)",
  "category": "llm",
  "description": "用 LLM 评估回答是否准确，对比 expected_output 和 actual_output",
  "params": [
    {"key": "threshold", "label": "通过阈值", "type": "number", "default": 0.7, "min": 0, "max": 1, "step": 0.1}
  ],
  "criteria": "评估回答是否准确：对比 expected_output 和 actual_output，判断 factual correctness",
  "requires": ["actual_output", "expected_output"],
  "code_template": "GEval(\n    name=\"Accuracy\",\n    criteria=\"{{criteria}}\",\n    evaluation_params=[LLMTestCaseParams.EXPECTED_OUTPUT, LLMTestCaseParams.ACTUAL_OUTPUT],\n    threshold={{threshold}},\n    model=JUDGE_MODEL,\n)"
}
```

## Agent 生成指标指南

Agent 生成指标时，遵循以下步骤：

1. **理解业务场景** — 从用户描述中反推评测目标
2. **生成 Non-LLM 指标** — 先想哪些是纯规则检查（格式、关键词、长度等）
3. **生成 LLM 指标** — 再想哪些需要语义判断（准确度、完整性、语气等）
4. **写 JSON 文件** — 每个指标一个文件，放到 `data/metrics/` 对应目录
5. **写清楚 criteria** — LLM 指标的 criteria 要具体、可操作，不能模糊

### 注意事项

- `code_template` 中引用参数用 `{{param_key}}`，不能有拼写错误
- `requires` 要准确，不然导出的脚本会缺数据
- LLM 指标的 `code_template` 中 `model=JUDGE_MODEL` 固定不变，模型由平台全局配置
- 指标 id 不能和已有指标重复

## 发布到共享仓库

### 查重规则

发布到共享仓库前，脚本自动执行以下查重。任一命中则拒绝或警告：

| 检查项 | 规则 | 动作 |
|--------|------|------|
| **ID 完全相同** | `id` 与共享仓库中已有 metric 一致 | ❌ 拒绝，提示已有相同 ID |
| **名称高度相似** | `name` 与已有 metric 的编辑距离 ≤ 3 且字符长度差 ≤ 5 | ⚠️ 警告，建议改名 |
| **criteria 高度相似** | `criteria` 与已有 LLM metric 的 Jaccard 相似度 ≥ 0.7 | ⚠️ 警告，可能重复 |
| **code_template 高度相似** | `code_template` 与已有 metric 的 Jaccard 相似度 ≥ 0.8 | ⚠️ 警告，可能是变体 |

**Jaccard 相似度** = 两个文本分词后的交集大小 / 并集大小。值域 0~1，越高越相似。

**编辑距离**（Levenshtein）= 把字符串 A 变成 B 需要多少步操作（插入/删除/替换）。

### 发布流程

```bash
# 1. 查重
python scripts/publish_metric.py --check --metric data/metrics/llm/empathy.json

# 2. 通过后发布
python scripts/publish_metric.py --publish --metric data/metrics/llm/empathy.json \
  --repo https://github.com/your-org/evalplatform-metrics.git
```

### 发现（拉取共享指标）

```bash
python scripts/publish_metric.py --discover \
  --repo https://github.com/your-org/evalplatform-metrics.git \
  --target data/metrics/
```