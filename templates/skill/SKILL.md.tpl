---
name: {{skillName}}
description: 自动生成的 Deepeval 评测 Skill，包含 {{metricCount}} 个 metric
---

# {{skillName}}

基于 Deepeval 的自动评测 Skill。

## 评测维度

{{metricList}}

## 使用方法

1. 准备测试用例文件 `test_cases.json`（格式见下方）
2. 安装依赖：`pip install -r requirements.txt`
3. 设置环境变量 `MODEL_API_KEY`（模型 API Key）
4. 运行：`python eval_script.py`

## 测试用例格式

```json
[
  {
    "input": "用户问题或输入",
    "actual_output": "模型实际输出",
    "expected_output": "期望输出",
    "context": ["可选上下文"],
    "retrieval_context": ["可选检索上下文"]
  }
]
```

## 输出

- 控制台打印评测结果（PASS/FAIL + score + reason）
- 生成 `eval_report.json` 详细报告