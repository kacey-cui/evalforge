# EvalPlatform 🧩

**拖拽式 LLM-as-Judge 评测平台** —— 把写评测代码，变成搭积木。

> **平台做设计，Agent 做执行。** 可视化编排 [Deepeval](https://github.com/confident-ai/deepeval) 评测管线，一键导出 Skill，交给本地 Agent 跑评测、出报告。

[English](README.md) · [![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

---

## 为什么做这个

LLM-as-Judge（用大模型当评委）是当下最靠谱的模型评测方式，但 `deepeval` 这类框架需要写 Python，对产品、测试等非工程同学很不友好。

做 EvalPlatform 的出发点很简单：**评测里的指标、权重、阈值、门禁这些配置，本来就长得像拖拽界面——那为什么不干脆做成拖拽呢？**

想解决三件事：

1. **可视化优先**：指标、权重、阈值、门禁都拖拽完成，不写代码。
2. **Skill 传输**：配置好的评测管线沉淀为一个可复用的 **Skill**，下载到本地、交给任何 Agent 执行。
3. **UI 与 Agent 等价**：同一套 JSON 契约，可以全程点鼠标，也可以全程让 Agent 读写文件自动完成。

**核心洞察**：平台负责「设计」，Agent 负责「执行」，两者通过标准 Schema 互通。可视化 UI 只是备选入口，不是唯一入口。

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

### 两种使用方式

| 方式 | 适合 | 入口 |
|------|------|------|
| 🖱️ **Web UI** | 想拖拽、想直观 | `bash serve.sh` 后打开网页 |
| 🤖 **Agent 全自动** | 想自动化、批量 | 安装 `skills/evalplatform-orchestrator/` Skill，读写文件即可 |

两者操作同一套 JSON 契约（`METRIC_SCHEMA.md` / `REPORT_SCHEMA.md`），完全等价。

---

## 核心特性

- **字段级评测管线**：门禁区 + 打分区，支持权重、严格度、阈值。
- **7 个可视化 Tab**：概览 / Metric 库 / Canvas 编排 / 导出 Skill / Run 历史 / 对比 / 报告（SVG 图表 + 分页明细）。
- **Skill 导出与传输**：配置沉淀为可复用 Skill，交给本地 Agent 执行。
- **Git-native 版本管理**：每次 Run = 一个 git commit，对比组 = git tag，diff = `git diff`，零新依赖。
- **报告自动丰富化**：`enrich_report.py` 自动检测 Recall@k / MRR / 域分拆，生成折线图、柱状图、直方图。
- **指标共享**：`publish_metric.py` 支持发布/发现/查重（ID 冲突拒绝、相似度警告）。
- **预置 + 自定义指标**：8 个预置开箱即用，也支持继承 `BaseMetric` 自定义。

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

- [ ] **Tracing 可视化**：把 Deepeval 的 trace/span 树可视化，定位扣分原因
- [ ] **多用户协作**：项目级权限、共享指标库、共享对比组
- [ ] **评测即服务**：把 Skill 传输扩展成团队评测生态

> 欢迎提 Issue / PR。有任何想评测的场景，都欢迎来试试"搭积木代替写代码"。

---

## License

[MIT](LICENSE) © 2026 Kacey Cui
