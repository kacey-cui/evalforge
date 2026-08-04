# Report JSON Schema

> 评测报告的标准格式。`eval_script.py` 跑完输出此格式，Agent 和平台都能读。

## 顶层结构

```json
{
  "skill": "my-eval-skill",
  "created_at": "2026-07-30T12:00:00",
  "n_cases": 10,
  "n_passed": 8,
  "pass_rate": 0.8,
  "overall_score": 0.72,
  "grade": "C",
  "fields": {
    "diagnosis": { "field_score": 0.85, "metrics": [...] },
    "repair": { "field_score": 0.60, "metrics": [...] }
  },
  "cases": [
    {
      "case_id": 1,
      "input": "...",
      "expected_output": "...",
      "actual_output": "...",
      "passed": true,
      "overall_score": 0.85,
      "fields": {
        "diagnosis": {
          "gate_passed": true,
          "final_score": 0.90,
          "metrics": [
            { "name": "JSON Schema 校验", "score": 1.0, "passed": true, "reason": "..." },
            { "name": "准确度 (GEval)", "score": 0.90, "raw": 0.95, "strictness": 1.0, "weight": 0.5, "reason": "..." }
          ]
        }
      }
    }
  ],
  "bad_cases": [
    { "case_id": 3, "field": "repair", "metric": "准确度", "score": 0.2, "reason": "..." }
  ],
  "config": {
    "model_base_url": "https://...",
    "model_id": "your-model-id",
    "metrics": [
      { "name": "JSON Schema 校验", "type": "gate", "threshold": 1.0 },
      { "name": "准确度 (GEval)", "type": "score", "weight": 0.5, "strictness": 1.0 }
    ]
  }
}
```

## 字段说明

### 顶层

| 字段 | 类型 | 说明 |
|------|------|------|
| `skill` | string | Skill 名称 |
| `created_at` | string | ISO 8601 时间戳 |
| `n_cases` | int | 总 case 数 |
| `n_passed` | int | 通过数（门禁全过 + 总分 >= 0.6） |
| `pass_rate` | float | 通过率 |
| `overall_score` | float | 所有 case 所有字段的加权平均分 |
| `grade` | string | 等级：A(>=0.9) B(>=0.8) C(>=0.7) D(>=0.6) F(<0.6) |
| `fields` | object | 按字段汇总的分数 |
| `cases` | array | 每个 case 的详细结果 |
| `bad_cases` | array | 失败样本汇总 |
| `config` | object | 本次评测的配置（模型、指标、权重） |

### fields.{field_name}

| 字段 | 类型 | 说明 |
|------|------|------|
| `field_score` | float | 该字段所有 case 的加权平均分 |
| `metrics` | array | 每个打分指标的均值、标准差 |

### cases[].fields.{field_name}

| 字段 | 类型 | 说明 |
|------|------|------|
| `gate_passed` | bool | 门禁是否通过 |
| `gate_failed_at` | string | 门禁卡在哪个指标（null=全过） |
| `final_score` | float | 打分的加权平均分（门禁未过则为 N/A） |
| `metrics` | array | 每个指标的打分详情 |

### cases[].fields.{field_name}.metrics[]

| 字段 | 类型 | 说明 |
|------|------|------|
| `name` | string | 指标名 |
| `score` | float | 调整后的分数（已应用严格度） |
| `raw` | float | 原始分数（仅打分指标） |
| `strictness` | float | 严格度（仅打分指标） |
| `weight` | float | 权重（仅打分指标） |
| `passed` | bool | 是否通过阈值 |
| `reason` | string | 评分理由 |

### bad_cases[]

| 字段 | 类型 | 说明 |
|------|------|------|
| `case_id` | int | 哪个 case |
| `field` | string | 哪个字段 |
| `metric` | string | 哪个指标 |
| `score` | float | 得分 |
| `reason` | string | 失败原因 |

## Agent 怎么读报告

Agent 拿到 report.json 后可以：

1. **看 overall_score 和 grade** → 判断整体质量
2. **看 bad_cases** → 知道哪些 case 有问题
3. **看 fields.{name}.field_score** → 知道哪个字段表现差
4. **看 cases[].fields.{name}.metrics[].reason** → 知道具体扣分原因
5. **生成优化建议** → 基于 bad_cases 的 pattern 分析

## 等级标准

| 分数 | 等级 | 含义 |
|------|------|------|
| >= 0.9 | A | 优秀 |
| >= 0.8 | B | 良好 |
| >= 0.7 | C | 一般 |
| >= 0.6 | D | 及格 |
| < 0.6 | F | 不及格 |

---

## summary_charts（自动生成，由 enrich_report.py 注入）

由 `scripts/enrich_report.py` 自动检测指标模式并生成，**不需要手写**。
`record_run.py` 调用 `enrich()` 后，每份 `data/runs/{run_id}/results.json` 自动含此字段。

```json
"summary_charts": [
  {
    "id": "retrieval_recall_curve",
    "type": "line",
    "title": "Recall@k 曲线（retrieval）",
    "x_label": "k（召回数量）",
    "y_label": "Recall",
    "y_min": 0, "y_max": 1,
    "series": [
      {
        "label": "整体",
        "color": "#4f46e5",
        "points": [
          {"x": 1,  "y": 0.612,  "label": "Recall@1"},
          {"x": 3,  "y": 0.7829, "label": "Recall@3"},
          {"x": 10, "y": 0.9026, "label": "Recall@10"}
        ]
      }
    ]
  },
  {
    "id": "retrieval_domain_breakdown",
    "type": "bar",
    "title": "各域 Recall@10",
    "x_label": "域", "y_label": "Recall@10",
    "y_min": 0, "y_max": 1,
    "series": [{"label": "Recall@10", "color": "#f59e0b", "points": [{"x": "ABC22", "y": 0.91, "n": 34}]}]
  },
  {
    "id": "overall_score_dist",
    "type": "histogram",
    "title": "总分分布",
    "x_label": "得分", "y_label": "案例数",
    "bins": [{"x": "0.0-0.1", "count": 2}, {"x": "0.8-0.9", "count": 45}]
  }
]
```

支持的 `type` 值：`line`（折线图）、`bar`（柱状图）、`histogram`（直方图）

---

## summary_tables（自动生成，由 enrich_report.py 注入）

```json
"summary_tables": [
  {
    "id": "bad_cases",
    "title": "失败案例 (30 条)",
    "columns": ["case_id", "input", "expected", "Recall@1", "MRR", "score"],
    "rows": [{"case_id": 5, "input": "用户反映...", "expected": "ABC22110", "Recall@1": 0, "MRR": 0.167, "score": 0.533}],
    "paginate": false
  },
  {
    "id": "per_case",
    "title": "逐案明细 (195 条)",
    "columns": ["case_id", "input", "expected", "Recall@1", "Recall@10", "MRR", "overall_score"],
    "rows": [...],
    "paginate": true
  }
]
```

## 复用指南

新项目无需任何代码变更：
1. `eval_script.py` 正常输出标准 `eval_report.json`
2. 运行 `record_run.py`，自动调用 `enrich()` 注入图表数据
3. UI 的 📊 报告 Tab 自动渲染，无需配置

如需定制域分拆行为，在项目目录创建 `enrich_config.json`：
```json
{
  "domain_field": "expected_output",
  "domain_extract": "prefix5",
  "domain_label": "故障域"
}
```