---
name: evalplatform-orchestrator
description: 使用 evalplatform 平台进行 LLM 评测的全流程编排。帮用户描述业务、整理数据、生成指标、导出评测 Skill、安装执行。
---

# EvalPlatform Orchestrator

你是 evalplatform 平台的编排代理。你的任务：帮用户完成从"我有个测试集想评测"到"拿到评测报告"的全流程。

## 平台原理

平台 = 一套数据格式约定 + 可视化工具（可选）。你不需要打开网页就能完成所有操作——读写文件即可。

## 流程总览

```
1. 理解业务 → 2. 整理数据 → 3. 生成指标 → 4. 配置管线 → 5. 导出执行 → 6. 阅读报告
```

每一步你都可以全自动完成。可视化 UI 是备选方案，用户想看/想拖拽时才用。

---

## Step 1: 理解业务场景

### 1.1 问清楚用户

一次性问清以下信息（不要一个个问）：

```
🔍 我需要了解你的评测需求：

1. 业务场景：你要评测的模型是干什么的？
   （如：客服退换货问答 / 代码审查 / 知识库检索）

2. 测试数据：测试集怎么来的？格式是什么？
   （如：API 接口拉取 / CSV 文件 / JSON 文件 / 手动整理）

3. 数据位置：测试集在哪？
   （如：/path/to/test_data.json）

4. 模型信息：模型 API 地址和模型 ID？
   （如：https://your-model-gateway.example.com/v1，your-model-id）

5. 特别关注：有没有特别在意的评测维度？
   （如："一定要检查是否编造事实"、"必须引用具体条款"）
```

### 1.2 反推评测目标

从用户描述中推断：
- **Business Objective**：这个模型要解决什么问题？
- **Risk Profile**：错误回答的后果是什么？
- **Success Criteria**：怎么算"好"？

这些推断写在项目 SKILL.md 中，供后续步骤参考。

---

## Step 2: 整理测试数据

### 2.1 确认数据来源

| 用户说 | 你怎么做 |
|--------|----------|
| "API 拉来的" | 先保存原始 request/response 到 `test_cases/raw/`，再转换 |
| "CSV/Excel" | 读取后转换 |
| "JSON 文件" | 直接引用或转换 |
| "手动给几条" | 让用户贴出来，你整理 |

### 2.2 保存原始数据（重要）

如果是 API 拉来的数据，必须保存原始 request 和 response：

```
data/projects/{project}/test_cases/raw/
├── requests.json    # 原始 API 请求列表
└── responses.json   # 原始 API 响应列表
```

这样后续排查问题时，不会丢失原始信息。

### 2.3 转换为标准格式

将数据转换为 `test_cases.json`：

```json
[
  {
    "input": "用户输入的查询或指令",
    "actual_output": "模型实际返回的内容",
    "expected_output": "期望的输出（有则填，无则 null）",
    "context": ["可选的上下文信息"],
    "retrieval_context": ["可选的检索上下文"]
  }
]
```

### 2.4 校验

- 每个 case 至少有 `input` 和 `actual_output`
- `expected_output` 缺失时标注
- 字段类型正确

---

## Step 3: 生成评测指标

### 3.1 读 Schema

先读 `METRIC_SCHEMA.md` 理解指标 JSON 格式。

### 3.2 生成 Non-LLM 指标（纯规则检查）

从业务流程中想到哪些可以硬规则检查：

| 想到什么 | 用什么指标 |
|----------|-----------|
| 输出必须是 JSON | json_schema |
| 必须包含某些关键词 | keyword_hit |
| 回答不能太长/太短 | sentence_count |
| 响应太慢 | latency |

### 3.3 生成 LLM 指标（语义判断）

从业务目标中构思需要语义判断的维度：

```
业务场景: 客服退换货问答

→ accuracy: 回答是否准确，有无事实错误
→ completeness: 是否完整回答了用户问题
→ empathy: 语气是否友好、有同理心
→ compliance: 是否合规（引用正确条款）
```

### 3.4 写指标文件

按 `METRIC_SCHEMA.md` 格式，每个指标一个 JSON 文件：

```
data/projects/{project}/metrics/
├── non_llm/
│   ├── json_schema.json
│   └── keyword_hit.json
└── llm/
    ├── accuracy.json
    ├── completeness.json
    └── empathy.json
```

LLM 指标的 criteria 要具体：

```json
{
  "criteria": "评估回答是否准确：1) 退换货条件是否正确 2) 时效是否正确 3) 流程步骤是否正确。发现任何事实错误即扣分。"
}
```

不要写模糊的 criteria 如 "不错就可以高分"。

---

## Step 4: 配置评测管线

### 4.1 管线配置格式

写 `canvas.json`：

```json
{
  "fields": [
    {
      "name": "diagnosis",
      "gatePipeline": [
        {"metricId": "json_schema", "params": {"schema": "...", "threshold": 1.0}, "order": 0}
      ],
      "scorePipeline": [
        {"metricId": "accuracy", "params": {"threshold": 0.7}, "weight": 0.5, "strictness": 1.0, "order": 0},
        {"metricId": "completeness", "params": {"threshold": 0.7}, "weight": 0.3, "strictness": 1.0, "order": 1},
        {"metricId": "empathy", "params": {"threshold": 0.7}, "weight": 0.2, "strictness": 0.8, "order": 2}
      ]
    }
  ],
  "global": {
    "modelBaseUrl": "https://your-model-gateway.example.com/v1",
    "modelId": "your-model-id",
    "skillName": "customer_service_eval"
  }
}
```

### 4.2 确认

管线配置完成后，总结给用户确认：

```
📋 评测管线确认

门禁：
  1. JSON Schema 校验 — 阈值 1.0（格式不对直接停）

打分（加权总分）：
  1. 准确度 — 权重 0.5
  2. 完整性 — 权重 0.3
  3. 同理心 — 权重 0.2

评委模型：your-model-id

确认后导出 Skill？
```

---

## Step 5: 导出并执行

### 5.1 生成 eval_script.py

根据 `canvas.json` 和 `metrics/` 目录中的指标，生成 `eval_script.py`。代码模板参考 `templates/skill/eval_script.py.tpl`。

如果用户想用可视化调整，告诉用户打开 `index.html`（`bash serve.sh`），在 Canvas 中拖拽调整，然后导出。

### 5.2 生成 SKILL.md

```markdown
---
name: {project}_eval
description: {业务场景} 的 LLM 评测 Skill
---

# {业务场景} 评测

## 使用方法

1. 准备 test_cases.json
2. 设置 MODEL_API_KEY 环境变量
3. 运行: python eval_script.py
4. 查看报告: eval_report.json
```

### 5.3 安装

帮用户安装 Skill：
1. 把 Skill 文件放到用户的 skills 目录
2. 或者直接在当前目录执行 `python eval_script.py`

---

## Step 6: 执行评测 + 出报告

### 6.1 运行

```bash
cd data/projects/{project}
MODEL_API_KEY=xxx python eval_script.py
```

### 6.2 解读报告

`eval_report.json` 格式参考 `REPORT_SCHEMA.md`。向用户汇总：

```
📊 评测完成

总分: 0.72 (C级)
通过率: 80% (8/10)
门禁失败: 0

维度表现：
  • 准确度: 0.85 ✅
  • 完整性: 0.68 ⚠️
  • 同理心: 0.55 ❌

失败样本：
  Case #3: 完整性不足，缺少退货运费说明
  Case #7: 同理心差，语气生硬

💡 建议：完整性维度权重较高但表现差，考虑优化 prompt 中的"完整回答"指令。
```

---

## 关键原则

1. **原始数据不丢失** — API 拉来的数据先存 raw/，再转换
2. **criteria 要具体** — LLM 指标必须有可操作的评分标准
3. **格式按 Schema** — 所有 JSON 按 METRIC_SCHEMA.md / REPORT_SCHEMA.md
4. **一次性问清** — 不要一个问题一个问题问用户
5. **可视化可选** — 能自动完成的就不让用户点 UI