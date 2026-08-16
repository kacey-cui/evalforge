# EvalPlatform 🧩

**Agent 原生的 LLM-as-Judge 评测平台** —— 拖拽编排评测管线，也能让 Agent 直接操作平台。

> 平台做设计，Agent 做执行。底层是 [Deepeval](https://github.com/confident-ai/deepeval)，导出为可复用的 Skill。

[English](README.md) · [![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

---

## 为什么做这个

LLM-as-Judge（用大模型当评委）是当下最靠谱的模型评测方式，但 `deepeval` 这类框架需要写 Python——对**没接触过 Python 的人**来说是一道实实在在的门槛。

与此同时，AI 时代随手写一套自己的评测脚本、或拼一个 Skill 太容易了。相比起来，去啃别人的框架反而更费劲，于是人们很自然地绕开那些需要写代码的框架。

但「Skill 堆 Skill」是有隐性代价的：**评测工程会越来越不稳定**——指标口径漂移、没有统一契约、没有版本、没法对比。EvalPlatform 想做的就是**降低这个学习成本：让人在一个框架里工作，底层是成熟的 deepeval**。

---

## Agent 原生，而不只是可视化

真正的目标不是把 UI 做得更好看，而是：在 AI 时代，真正重要的「用户」是 **Agent**。

人机交互经历了三个阶段：

- **CLI** —— 终端时代：人敲命令行。
- **GUI** —— 个人电脑时代：普通人有了图形界面。
- **ANI（Agent-Native Interface，Agent 原生接口）** —— AI 时代：Agent 应该能**直接**操作系统。

现在人们已经懒得点网页，干脆让 Agent 用 Playwright 去干。但用浏览器自动化去驱动 GUI，本质是个别扭的补丁——又脆又慢，不是未来该有的样子。

EvalPlatform 从一开始就是** Agent 原生**设计的：它真正的接口不是网页，而是一套 JSON Schema、文件、Skill。Agent 可以直接生成指标、配置管线、跑评测、记录 Run，**全程不用打开浏览器**。网页 UI 只是同一份契约的一个客户端，给人用的。

---

## 轻量化

- **零构建、零框架** —— 一个 `index.html` + 几个小 Python 脚本。没有 npm、没有打包器、没有前端框架。
- **Git-native** —— 没有数据库。Run、历史、对比就是 git commit 和 tag。
- **引擎在本地** —— deepeval 在你本地跑，不在平台里。平台不绑架你的运行环境。

---

## 怎么用

### 5 分钟上手

```bash
# 1. 启动（同时拉起静态服务 :8080 和 git 桥接服务 :8081）
bash serve.sh

# 2. 浏览器打开
# http://localhost:8080
```

**① 浏览指标**：Metric 库预置 8 个指标（5 个非 LLM：JSON Schema 校验、关键词命中、响应延迟、句子数、上下文 Token；3 个 GEval：准确度、完整性、无幻觉）。

**② 拖拽编排**：在 Canvas 里给每个字段（如 `diagnosis`）拖入指标，组成评测管线：

- 🚪 **门禁区**（红）—— 顺序执行，不过即停。适合格式校验、关键词检查。
- 📊 **打分区**（绿）—— 全部执行，加权平均，支持权重与严格度。

**③ 一键导出**：下载得到一个 Skill zip 包（`SKILL.md` + `eval_script.py` + 测试用例模板）。

**④ 交给 Agent 执行**：把 Skill 装进本地 Agent，它会整理测试数据、跑 Deepeval、输出 `eval_report.json`。

### 完整工作流

```
平台（设计）                本地 Agent（执行）
───────────                ──────────────
拖拽编排指标/权重   ──导出──▶  加载 Skill
配置门禁/阈值             整理测试数据
一键导出 Skill zip        跑 deepeval → 生成报告
                         记录 Run → 回平台看历史/对比/图表
```

### 两种使用方式，同一份契约

| 方式 | 适合 | 入口 |
|------|------|------|
| 🖱️ **Web UI** | 人、想直观 | `bash serve.sh` 后打开网页 |
| 🤖 **Agent 原生** | Agent、自动化、批量 | 安装 `skills/evalplatform-orchestrator/`，直接读写文件 |

两者操作同一套 JSON 契约（`METRIC_SCHEMA.md` / `REPORT_SCHEMA.md`），不需要浏览器自动化。

---

## 核心特性

- **字段级评测管线**：门禁区 + 打分区，支持权重、严格度、阈值。
- **7 个可视化 Tab**：概览 / Metric 库 / Canvas 编排 / 导出 Skill / Run 历史 / 对比 / 报告（SVG 图表 + 分页明细）。
- **Skill 导出与传输**：配置沉淀为可复用 Skill，交给本地 Agent 执行。
- **Git-native 版本管理**：每次 Run = 一个 git commit，对比组 = git tag，diff = `git diff`，零新依赖。
- **报告自动丰富化**：`enrich_report.py` 自动检测 Recall@k / MRR / 域分拆，生成折线图、柱状图、直方图。
- **指标共享**：`publish_metric.py` 支持发布/发现/查重（ID 冲突拒绝、相似度警告）。
- **预置 + 自定义指标**：8 个预置开箱即用，也支持继承 `BaseMetric` 自定义。
- **中英双语 UI**：一键切换。

---

## 项目结构

```
evalplatform/
├── index.html              # 主应用（原生 HTML/CSS/JS，无框架）
├── serve.sh                # 启动 8080 静态服务 + 8081 git 桥接服务
├── METRIC_SCHEMA.md        # 指标 JSON 契约（Agent 读这个生成指标）
├── REPORT_SCHEMA.md        # 报告 JSON 契约
├── data/
│   ├── metrics/            # 预置指标模板（non_llm / llm）
│   ├── projects/           # 项目配置（canvas.json）
│   └── runs/               # Run 历史快照（纳入 git）
├── templates/skill/        # Skill 导出模板
├── scripts/
│   ├── git_bridge.py       # Git REST 桥接（Run 历史/对比）
│   ├── enrich_report.py    # 报告丰富化引擎（自动生成图表）
│   └── publish_metric.py   # 指标发布/发现/查重
└── skills/
    ├── evalplatform-orchestrator/  # 平台编排 Agent Skill
    └── version-manager/            # 版本管理 Skill（5 命令）
```

---

## 技术栈

- **前端**：原生 HTML / CSS / JS，HTML5 Drag & Drop，JSZip 打包，零框架、零构建
- **后端**：Flask（本地 git 桥接服务，仅监听 localhost）
- **存储**：localStorage（按项目隔离）+ 文件系统 + Git（Run 历史）
- **评测引擎**：Deepeval（Python，在本地执行，平台不内置运行环境）
- **图表**：内联 SVG，无第三方图表库

---

## Roadmap（更新计划）

### 近期

- [ ] **后端化**：把 localStorage + Flask 桥接升级为真正后端（FastAPI + SQLite）
- [ ] **内置更多指标**：Faithfulness / AnswerRelevancy / ContextualRecall 等 30+ 指标可视化接入
- [ ] **数据集管理**：测试集上传、版本、tag
- [ ] **模型管理**：被测模型 / Judge 模型独立配置

### 中期

- [ ] **测试用例自动生成**：接入 Deepeval Synthesizer，从文档/上下文合成用例
- [ ] **多轮对话 & Agent 评测**：ConversationalTestCase、工具调用、Agent 轨迹
- [ ] **CI/CD 质量门禁**：`deepeval gate` + GitHub Actions
- [ ] **报告增强**：更多图表、PDF/HTML 导出、飞书/邮件通知

### 远期

- [ ] **更完整的 Agent 原生接口**：把平台契约直接暴露给 Agent（不止是文件），让浏览器自动化彻底不必要
- [ ] **Tracing 可视化**：把 Deepeval 的 trace/span 树可视化，定位扣分原因
- [ ] **多用户协作**：项目级权限、共享指标库、共享对比组

> 欢迎提 Issue / PR。有任何想评测的场景，都欢迎来试试"搭积木代替写代码"。

---

## License

[MIT](LICENSE) © 2026 Kacey Cui
