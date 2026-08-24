# EvalForge

Agent 原生的 LLM 评测基础设施层 —— 结构化、版本化、可复现。

EvalForge 将评测的全过程（指标、数据集、管线、运行、报告）作为结构化产物来定义、版本化、存储、编排和比较。实际的评测执行委托给 [Deepeval](https://github.com/confident-ai/deepeval) 等评测引擎，在你的本地环境中运行。

它不替代评测引擎，而是提供引擎之上的契约、存储、溯源和编排层。

[English](README.md) · [Concepts](docs/concepts.md) · [Architecture](docs/architecture.md) · [![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

---

## 架构

```
Agent / 人
       │
       │  Python API / CLI / JSON 契约
       ▼
EvalForge
       │
       ├── MetricStore        — 指标 CRUD + 版本化
       ├── DatasetStore       — 数据集 CRUD + 版本化
       ├── RunStore           — Run 提交、查询、对比
       ├── generate_skill     — 管线 → 可执行 Skill 包
       ├── run_manifest       — 溯源 manifest（构建 & 校验）
       ├── eval_diff          — 分数差异根因分析
       └── enrich_report      — 自动检测图表 & 表格
       │
       │  内容寻址存储（SHA256，.versions/）
       ▼
评测包（Skill）
       │
       │  eval_script.py → deepeval → eval_report.json
       ▼
Report + Manifest
       │
       │  manifest.json → verify_manifest() → 可复现性校验
       ▼
可复现的 Run / 可对比
```

EvalForge 是控制面。评测引擎在本地运行，可替换。

---

## 快速开始

一次完整的评测可以表达为：**指标 → 数据集 → Skill → 本地执行 → Run → 对比**。

```bash
# 1. 定义指标
python scripts/metric_store.py create '{
  "id":"accuracy","name":"准确度 (GEval)","category":"llm",
  "params":[{"key":"threshold","type":"number","default":0.7}],
  "criteria":"评估回答是否准确：对比 expected_output 和 actual_output",
  "requires":["actual_output","expected_output"],
  "code_template":"GEval(name=\"Accuracy\", criteria=\"{{criteria}}\", threshold={{threshold}}, model=JUDGE_MODEL)"
}'

# 2. 注册数据集
python scripts/dataset_store.py create \
  --dataset-id my_qa --name "我的问答集" --source test_cases.json

# 3. 生成可执行 Skill
python scripts/generate_skill.py --project my_project --output ./skill_output/

# 4. 本地执行评测（Deepeval）
cd skill_output && pip install -r requirements.txt && python eval_script.py

# 5. 提交 Run（溯源追踪）
python scripts/run_store.py submit \
  --report eval_report.json --manifest manifest.json

# 6. 与历史 Run 对比
python scripts/run_store.py compare --run-a run_20260818_001 --run-b run_20260818_002
```

完整 12 步流程演示： [`examples/agent_workflow/run_workflow.py`](examples/agent_workflow/run_workflow.py)

### GUI（可选的人类客户端）

```bash
bash serve.sh                    # 启动平台 :9090
# 打开 http://localhost:9090    # 浏览指标、Canvas 拖拽编排、导出 Skill
```

GUI 是可视化编排器，读写同一套 JSON 契约。它是一个客户端，不是主接口。

---

## 为什么需要 EvalForge

### 问题

LLM 评测在实践中面临几个超越"选哪个指标"的工程问题：

**1. 指标漂移。** 同一个 "accuracy" 在不同项目、不同时间可能使用不同的 criteria、threshold、requires 或 code_template。没有版本化，很难知道某个分数是用哪个定义跑出来的。

**2. 数据集漂移。** 测试集会变。当 Run 的分数变化时，往往说不清是模型退化了还是数据集被更新了。

**3. Run 可复现性。** 光有一个分数不够。要解读或复现一个结果，需要知道：哪个指标版本、哪个数据集版本、哪个 Skill 版本、哪个模型、哪个 Judge、哪个环境。

**4. 对比。** "分数降了 0.1" 本身没有意义。真正的问题是：**什么变了？**——数据集、指标、阈值、模型、Judge 还是评测配置？

**5. Agent 交互。** 如果评测流程越来越多地由 Agent 自动完成，那么浏览器自动化（Playwright、DOM 操作）就是错误的接口。Agent 需要结构化 API、机器可读的 schema 和确定性命令。

### 方案

EvalForge 将评测产物视为结构化、版本化、可溯源的实体：

| 没有 EvalForge | 有 EvalForge |
|---|---|
| 指标定义分散在各处 ad-hoc 脚本 | 内容寻址版本化——每次语义变化产生新 hash |
| "这次跑用的是哪个版本的指标？"——不知道 | `manifest.json` 记录每个输入的精确 hash |
| "分数为什么掉了？"——靠猜 | `eval_diff` 对比数据集、指标、Skill、模型、Judge |
| Agent 必须用 Playwright 驱动 GUI | Agent 直接调用 Python API，结构化错误响应 |
| 测试用例被悄悄改了 | Dataset 版本化 + content hash |
| 无法复现某次评测 | `verify_manifest()` 校验所有 hash 引用可解析 |

---

## 设计原则

### 契约优先
指标、数据集、报告和 Run 都表示为结构化 JSON 契约。Schema 文档在 [`METRIC_SCHEMA.md`](METRIC_SCHEMA.md) 和 [`REPORT_SCHEMA.md`](REPORT_SCHEMA.md)。

### 内容寻址
语义产物以 SHA256 内容哈希标识。相同内容 → 相同 hash。内容变化 → 新版本。历史版本不可变，存储在 `.versions/` 中。

### 本地优先
评测执行留在你的机器上。平台管理产物、版本化和溯源——不需要中心化数据库或运行时。

### API 优先
每个重要操作都可以通过 Python API 和 CLI 调用，无需浏览器自动化。Web GUI 是使用同一套底层契约的人类客户端。

### 可复现优于便利
一次 Run 应该事后可解释、可追溯。溯源默认记录，不是事后补丁。

---

## 核心概念

### 版本化产物

指标和数据集是一等公民、版本化的产物。

指标的**身份**（`metric_id`）是稳定的。**版本**（`version_hash`）在评测语义发生变化时改变。版本 hash 由影响评测行为的字段计算得出：`category`、`params`、`criteria`、`requires`、`code_template`。展示元数据如 `name`、`description` 不参与 hash。

```
accuracy
├── version a1b2c3...  (threshold=0.7, criteria="factual correctness")
├── version d4e5f6...  (threshold=0.8, criteria="factual correctness + completeness")
└── version g7h8i9...  (当前版本)
```

历史版本保持可寻址，因此过去的 Run 始终可解读。

数据集遵循相同模型：`content_hash` 捕获测试用例，`version_hash` 捕获元数据 + 内容。

### 溯源

每次 Run 都包含一个 `manifest.json`，记录影响评测的所有输入的精确状态：

```json
{
  "run_id": "run_20260818_001",
  "dataset": {
    "dataset_id": "my_qa",
    "version_hash": "abc123...",
    "content_hash": "def456..."
  },
  "metrics": [
    {
      "metric_id": "accuracy",
      "version_hash": "111aaa...",
      "instance": { "weight": 0.5, "strictness": 1.0, "zone": "score" }
    }
  ],
  "skill": {
    "name": "my_eval",
    "content_hash": "222bbb..."
  },
  "model": { "model_id": "gpt-4", "base_url": "https://api.openai.com/v1" },
  "judge_model": null,
  "environment": {
    "python_version": "3.12.0",
    "platform": "macOS-14.0",
    "dependencies": { "deepeval": "1.2.0", "openai": "1.0.0" }
  }
}
```

`verify_manifest()` 校验 manifest 中的每个 hash 引用在 `.versions/` 目录中是否真实存在。

### 可复现的 Run

一次 Run 是 `data/runs/{run_id}/` 下的一个目录，包含：

| 文件 | 用途 |
|---|---|
| `manifest.json` | 完整溯源——所有输入的 hash |
| `results.json` | 丰富化后的评测报告，含图表和表格 |
| `meta.json` | 快速摘要（分数、通过率、指标列表） |
| `config.json` | 评测配置快照 |
| `dataset_ref.json` | 数据集引用（id、版本、内容 hash、样本数） |

给定一个 `run_id`，可以追溯到产生该分数的确切数据集、指标、Skill、模型和环境。

### 评测 Diff

`eval_diff` 从多个维度对比两次 Run——不仅仅是分数：

| 维度 | 检查内容 |
|---|---|
| 分数 | 总分变化、逐字段变化、逐用例变化 |
| 数据集 | 同一数据集？同一版本？哪些用例变了？ |
| 指标 | 新增、移除还是修改？修改了哪些字段？ |
| Skill | 评测脚本是否变化？ |
| 模型 | 被测模型是否相同？base URL 是否相同？ |
| Judge | Judge 模型是否相同？ |

输出包含一份人类可读的摘要，指出分数差异的可能根因。

---

## 核心特性

### 1. 版本化评测产物
指标和数据集使用内容寻址版本化（SHA256）。每次变化创建新的不可变版本。旧版本保留在 `.versions/` 中，始终可寻址。

### 2. 溯源与可复现
每次 Run 携带 `manifest.json`，记录每个输入的精确 hash。`verify_manifest()` 校验所有引用可解析。`eval_diff` 解释**为什么**分数变了。

### 3. 结构化 API
`MetricStore`、`DatasetStore`、`RunStore` 提供 Python API，返回 `{ok, data}` 或 `{ok, error: {code, message, details}}`。业务错误不抛异常，Agent 可程序化处理。

### 4. Agent 原生工作流
JSON 契约（[`METRIC_SCHEMA.md`](METRIC_SCHEMA.md)、[`REPORT_SCHEMA.md`](REPORT_SCHEMA.md)）、Python API、结构化错误、CLI——所有操作无需浏览器即可调用。Agent Skill（[`skills/evalplatform-orchestrator/`](skills/evalplatform-orchestrator/SKILL.md)）提供全流程编排。

### 5. Skill 生成
`generate_skill.py` 将管线配置转为自包含的 Skill 包：`SKILL.md` + `eval_script.py` + `test_cases_template.json` + `requirements.txt` + `manifest.json`。在任何有 Deepeval 的环境中均可执行。

### 6. 评测 Diff
`eval_diff` 进行根因分析：对比两次 Run 的分数、数据集、指标、Skill、模型和 Judge 模型，生成变化摘要。

### 7. 报告丰富化
`enrich_report.py` 自动检测模式（Recall@k 曲线、MRR、域分拆）并生成内联 SVG 图表（折线图、柱状图、直方图）和分页表格。

### 8. Web GUI
单页原生 HTML/CSS/JS 应用，7 个 Tab：概览、指标库、Canvas（拖拽编排管线）、导出、Run 历史、对比、报告。GUI 读写与 API 相同的 JSON 契约。

---

## 指标

EvalForge 内置 9 个预置指标，作为指标契约的演示。自定义指标通过 `MetricStore.create()` 创建。

### 确定性指标（非 LLM，纯 Python）

| 指标 | 描述 |
|---|---|
| `json_schema` | 校验 JSON 结构和字段类型 |
| `keyword_hit` | 检查输出是否包含指定关键词 |
| `latency` | 测量响应时间 |
| `sentence_count` | 统计输出句数 |
| `context_length` | 测量输入上下文长度 |
| `recall_at_k` | 检查 ground truth 是否出现在前 K 个检索结果中 |

### LLM 指标（GEval）

| 指标 | 描述 |
|---|---|
| `accuracy` | 对比 expected_output 评估事实准确性 |
| `completeness` | 评估回答是否覆盖所有必要方面 |
| `no_hallucination` | 检查输出是否编造信息 |

LLM 指标使用 GEval，Judge 模型全局配置。Judge 模型不内置——它调用你自己的模型接口。

---

## 两种使用方式，同一份契约

| 方式 | 入口 | 适合 |
|---|---|---|
| **API / CLI** | `MetricStore`、`DatasetStore`、`RunStore`、`generate_skill` | Agent、自动化、批量、CI/CD |
| **GUI** | `bash serve.sh` 后打开浏览器 | 人、可视化探索、拖拽编排 |

两者操作同一套 JSON 契约，不需要浏览器自动化。

---

## EvalForge 不是什么

- 不是 LLM 推理框架。
- 不是评测模型本身（它不直接打分）。
- 不替代 Deepeval——它在 Deepeval 之上做编排。
- 不强制使用 Web GUI；所有操作均可通过 API 和 CLI 完成。
- 不需要中心化数据库——存储基于文件系统。

---

## 什么时候应该用 EvalForge？

**适合你，如果：**

- 评测逻辑在多个项目或团队成员间共享
- 指标或数据集随时间演变，需要追踪变化
- 需要可复现的评测 Run，带完整溯源
- 评测流程越来越多地由 Agent 自动完成
- 需要对比**为什么**两次评测结果不同，而不仅仅是"不同"
- 希望评测产物可检查、可版本化、可审计

**不一定需要，如果：**

- 只需要一次性评测脚本
- 不需要可复现性或历史记录
- 只是在本地尝试某个指标

---

## 项目结构

```
evalplatform/
├── index.html                       # Web GUI（原生 HTML/CSS/JS，7 个 Tab）
├── serve.sh                         # 启动 :9090 静态服务 + :9091 git 桥接
├── METRIC_SCHEMA.md                 # 指标 JSON 契约
├── REPORT_SCHEMA.md                 # 报告 JSON 契约
├── data/
│   ├── metrics/{llm,non_llm}/       # 9 个预置指标定义 + .versions/
│   ├── datasets/{id}/               # 数据集定义 + test_cases + .versions/
│   ├── runs/{run_id}/               # Run 快照（manifest, results, meta, config, dataset_ref）
│   └── projects/{name}/             # canvas.json 管线配置
├── scripts/
│   ├── metric_store.py              # MetricStore — CRUD + 版本化 + CLI
│   ├── dataset_store.py             # DatasetStore — CRUD + 版本化 + CLI
│   ├── run_store.py                 # RunStore — submit, get, list, compare + CLI
│   ├── generate_skill.py            # SkillSpec → SkillPackage + CLI
│   ├── run_manifest.py              # 构建 & 校验溯源 manifest
│   ├── eval_diff.py                 # 分数差异根因分析
│   ├── enrich_report.py             # 自动图表生成
│   ├── metric_versioning.py         # 内容寻址指标版本化
│   ├── dataset_versioning.py        # 内容寻址数据集版本化
│   ├── mini_json_schema.py          # 轻量 JSON Schema 校验
│   ├── publish_metric.py            # 指标发布/发现/查重
│   └── git_bridge.py                # Flask REST 桥接（git 操作）
├── skills/
│   ├── evalplatform-orchestrator/   # Agent 编排 Skill
│   └── version-manager/             # Run 管理命令
├── templates/skill/                 # SKILL.md.tpl + eval_script.py.tpl
├── examples/agent_workflow/         # 12 步端到端 API 工作流演示
├── docs/
│   ├── architecture.md              # 系统设计与组件图
│   ├── concepts.md                  # 为什么版本化、溯源、Agent 原生设计
│   └── design/                      # 各模块设计文档
├── tests/                           # pytest 测试套件
└── requirements.txt
```

---

## 技术栈

- **API 层**：Python（标准库 + `hashlib`、`json`、`argparse`）
- **Web GUI**：原生 HTML/CSS/JS，HTML5 Drag & Drop，JSZip——零框架、零构建
- **后端桥接**：Flask（仅监听 localhost 的 git 桥接，`:9091`）
- **存储**：文件系统（内容寻址）+ Git（审计追踪）
- **评测引擎**：[Deepeval](https://github.com/confident-ai/deepeval)（Python，本地执行——不内置）
- **图表**：内联 SVG，无第三方图表库

---

## 文档

| 文档 | 内容 |
|---|---|
| [Concepts](docs/concepts.md) | 为什么版本化、为什么 Agent 原生、溯源如何工作、如何运行和对比评测 |
| [Architecture](docs/architecture.md) | 系统设计、组件图、数据流 |
| [Metric Schema](METRIC_SCHEMA.md) | 指标 JSON 契约 |
| [Report Schema](REPORT_SCHEMA.md) | 报告 JSON 契约 |
| [Agent 工作流演示](examples/agent_workflow/README.md) | 12 步端到端 API 工作流 |
| [设计文档](docs/design/) | 各模块设计规范 |

---

## License

[MIT](LICENSE) © 2026 Kacey Cui