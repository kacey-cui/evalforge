# EvalPlatform — 拖拽式 LLM-as-Judge 评测平台

> 用拖拽代替写代码，让 LLM 评测像搭积木一样简单。
> **平台做设计，Agent 做执行。**

EvalPlatform 是一个**可视化 LLM-as-Judge 评测编排工具**：你在网页上拖拽编排评测指标与管线，一键导出为一个 **Skill**，交给本地 Agent（或你自己）用 [Deepeval](https://github.com/confident-ai/deepeval) 跑真实评测、生成报告。

评测指标、测试用例、评测报告都有标准 JSON Schema，**UI 操作和 Agent Skill 操作是等价的一等公民**——你可以全程点鼠标，也可以全程让 Agent 读写文件自动完成。

---

## 为什么做这个

- **写评测代码不友好**：deepeval 的 GEval / 自定义 Metric 需要写 Python，对产品、测试等非工程同学门槛高。
- **配置更适合可视化**：指标选择、权重、阈值、门禁这些"配置项"天生适合拖拽。
- **产物要可复用**：配置好的评测管线应能沉淀为 Skill、版本化、分享给团队复用。

---

## 功能特性

### 可视化编排（Web UI）

| Tab | 说明 |
|-----|------|
| 🏠 概览 | 当前项目配置摘要 + 最近一次 Run 卡片 |
| 📦 Metric 库 | 指标增删改查，预置 8 个指标（5 非 LLM + 3 GEval） |
| 🎨 Canvas 编排 | 字段级评测管线：**门禁区**（顺序执行，不过即停）+ **打分区**（加权平均），支持权重、严格度 |
| 📥 导出 Skill | 一键打包 Skill zip |
| 🕐 Run 历史 | 评测历史时间线，多选、详情、软删除 |
| 🔀 对比 | 两次 Run 的配置 / 结果 / 数据集 diff |
| 📊 报告 | SVG 图表（折线/柱状/直方图）+ 分页明细表，自动生成 |

### Agent 全自动（Skill）

不打开网页也能完成全流程。安装 `skills/evalplatform-orchestrator/` Skill 后，Agent 可以：

1. 理解业务场景 → 反推评测目标
2. 整理测试数据 → 转换为标准格式
3. 生成指标 → 按 `METRIC_SCHEMA.md` 写 JSON
4. 配置管线 → 写 `canvas.json`
5. 导出执行 → 跑评测、出报告

### Git-native 版本管理

不引入数据库。每次 Run = 一个 git commit，对比组 = git tag，diff = `git diff`。配套 `skills/version-manager/` Skill（record / list / diff / create_group / delete），UI 和 Agent 都能操作。

---

## 快速开始

```bash
# 启动（同时拉起静态服务 :8080 和 git 桥接服务 :8081）
bash serve.sh
```

浏览器打开 <http://localhost:8080>。

> 需要 Python 3.9+，依赖仅 `flask`（见 `requirements.txt`）。
> 评测本身在**本地**用 Deepeval 执行（导出 Skill 后 `python eval_script.py`），平台不内置评测引擎。

---

## 工作流

```
平台（设计）                本地 Agent（执行）
───────────                ──────────────
拖拽编排指标/权重   ──导出──▶  加载 Skill
配置门禁/阈值             整理测试数据
一键导出 Skill zip        跑 deepeval → 生成 eval_report.json
```

1. 在 Metric 库挑指标，在 Canvas 拖拽成管线，配置权重/阈值/门禁。
2. 导出 Skill zip（`SKILL.md` + `eval_script.py` + 测试用例模板 + `requirements.txt`）。
3. 在本地环境装好 Deepeval，设置 `MODEL_API_KEY`，运行 `python eval_script.py`。
4. 用 `version-manager` 记录 Run，回到平台看历史、对比、图表报告。

---

## 项目结构

```
evalplatform/
├── index.html              # 主应用（原生 HTML/CSS/JS）
├── serve.sh                # 启动 8080 静态服务 + 8081 git 桥接服务
├── METRIC_SCHEMA.md        # 指标 JSON 契约（Agent 读这个生成指标）
├── REPORT_SCHEMA.md        # 报告 JSON 契约
├── data/
│   ├── metrics/            # 预置指标模板（non_llm / llm）
│   ├── projects/           # 项目配置（canvas.json 等）
│   └── runs/               # Run 历史（每次评测一个快照，纳入 git）
├── templates/skill/        # Skill 导出模板
├── scripts/
│   ├── git_bridge.py       # Git REST 桥接服务（Run 历史/对比）
│   ├── enrich_report.py    # 报告丰富化引擎（自动生成图表数据）
│   └── publish_metric.py   # 指标发布/发现/查重
└── skills/
    ├── evalplatform-orchestrator/  # 平台编排 Agent Skill
    └── version-manager/            # 版本管理 Skill（5 个命令）
```

---

## Schema 契约

平台与 Agent 通过两套 JSON Schema 互通，这是本项目的核心设计：

- **`METRIC_SCHEMA.md`** — 指标如何描述（id / 参数 / criteria / 代码模板），Agent 照此生成指标 JSON。
- **`REPORT_SCHEMA.md`** — 评测报告如何组织（字段级分数 / 逐案明细 / 失败样本），UI 照此渲染图表。

---

## 技术栈

- **前端**：原生 HTML / CSS / JS，HTML5 Drag & Drop，JSZip 打包，无框架、无构建
- **后端**：Flask（本地 git 桥接服务，仅监听 localhost）
- **存储**：localStorage（按项目隔离）+ 文件系统 + Git（Run 历史）
- **评测引擎**：Deepeval（Python，在本地执行，不内置）
- **图表**：内联 SVG，无第三方图表库

---

## 设计理念

| 平台（设计） | Agent（执行） |
|-------------|--------------|
| 可视化编排指标 | 导出 Skill 后本地运行 |
| 拖拽配置权重/阈值 | 加载测试数据、跑 Deepeval |
| 一键导出 | 出报告 → 记录 Run → 版本对比 |

**核心原则：**

1. **两种语言等价**——UI 操作和 Agent Skill 操作是同一套数据契约的两面。
2. **平台只管设计，不管执行**——评测引擎（Deepeval）在用户本地跑，平台不绑定运行环境。
3. **Git-native**——版本管理、历史、对比直接复用 Git 能力，零新依赖。
4. **契约优先**——指标、用例、报告都有标准 Schema，平台与 Agent 通过格式互通。
