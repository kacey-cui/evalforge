# EvalPlatform — Deepeval 可视化评测平台

> 用拖拽代替写代码，让 LLM 评测变得像搭积木一样简单。

## 这是什么

一个纯前端 HTML 工具，帮你**可视化配置 Deepeval 评测管线**，一键导出为 Skill，交给 Agent 跑评测、出报告。

**核心思路：** 平台做"设计"，Agent 做"执行"。你在平台上拖拽编排指标，导出 Skill，Agent 加载后自动跑完评测全流程。

## 快速开始

```bash
# 1. 启动
bash serve.sh

# 2. 浏览器打开
open http://localhost:8080
```

三个 Tab：
- **📦 Metric 库** — 查看/新建/编辑评测指标
- **🎨 Canvas 编排** — 拖拽指标，配置门禁和打分
- **📥 导出 Skill** — 下载 Skill zip，交给 Agent 执行

## 5 分钟上手

### 1. 浏览预置指标

Metric 库中已预置 8 个指标：

| 类型 | 指标 | 用途 |
|------|------|------|
| 非 LLM | JSON Schema 校验 | 检查输出格式 |
| 非 LLM | 关键词命中率 | 检查是否包含必要关键词 |
| 非 LLM | 句子数检查 | 检查回答长度 |
| 非 LLM | 响应延迟 | 检查响应速度 |
| 非 LLM | 上下文 Token 数 | 检查检索上下文长度 |
| LLM | 准确度 (GEval) | 语义评估回答准确性 |
| LLM | 完整性 (GEval) | 评估信息覆盖度 |
| LLM | 无幻觉 (GEval) | 检测编造事实 |

### 2. 创建评测字段

切换到 **Canvas 编排**，点击顶部标签栏的 **+ 新建**，输入字段名（如 `diagnosis`）。

### 3. 拖拽配置管线

从左侧"可用 Metric"拖入指标到字段的对应区域：

- **🚪 门禁区**（红色）— 顺序执行，不通过就停。适合格式校验、关键词检查
- **📊 打分区**（绿色）— 全部执行，加权平均。适合语义评估

点击指标卡片的 ⚙️ 调参数，打分区支持**权重**和**严格度**。

### 4. 导出

切换到 **📥 导出 Skill**，点击下载。得到一个 zip 包：

```
my-eval-skill.zip
├── SKILL.md              # Skill 元数据
├── eval_script.py        # 评测脚本
├── test_cases_template.json  # 测试用例模板
└── requirements.txt
```

### 5. 交给 Agent 执行

把 Skill 装到你的 Agent 里，Agent 会：
1. 帮你整理测试数据
2. 跑 eval_script.py
3. 输出 eval_report.json 报告

## 项目结构

```
evalplatform/
├── index.html              # 主应用（纯前端，零依赖）
├── serve.sh                # 启动脚本
├── METRIC_SCHEMA.md         # 指标 JSON 格式规范（Agent 读这个）
├── REPORT_SCHEMA.md         # 报告 JSON 格式规范
├── data/metrics/            # 预置指标模板
│   ├── non_llm/             # 非 LLM 指标（纯 Python 逻辑）
│   └── llm/                 # LLM 指标（GEval）
├── templates/skill/         # Skill 导出模板
├── scripts/
│   └── publish_metric.py    # 指标发布/发现/查重工具
└── skills/
    └── evalplatform-orchestrator/  # 平台编排 Agent Skill
```

## 高级功能

### 项目管理

页面顶部有项目选择器，不同项目数据隔离。新建项目 → 独立的指标和管线配置。

### 指标共享

```bash
# 发布到共享仓库（带查重）
python scripts/publish_metric.py publish \
  --metric data/metrics/llm/empathy.json \
  --repo https://github.com/<your-org>/evalplatform-metrics.git

# 拉取共享指标
python scripts/publish_metric.py discover \
  --repo https://github.com/<your-org>/evalplatform-metrics.git \
  --target data/metrics/
```

查重规则：ID 冲突 → 拒绝；名称/代码相似 → 警告。

### Agent 全自动模式

不需要打开网页。安装 `skills/evalplatform-orchestrator/` Skill，Agent 可以：
1. 理解业务场景 → 反推评测目标
2. 整理测试数据 → 转换标准格式
3. 生成指标 → 按 METRIC_SCHEMA.md 写 JSON
4. 配置管线 → 写 canvas.json
5. 导出执行 → 跑评测出报告

可视化 UI 只是备选方案。

## 技术栈

- 纯 HTML/CSS/JS，无框架依赖
- HTML5 Drag & Drop API
- JSZip 前端打包
- 数据存储：localStorage（按项目隔离）
- 评测引擎：Deepeval (Python)

## 设计理念

```
平台（设计）          Agent（执行）
───────────          ───────────
可视化编排指标   →   导出 Skill
拖拽配置权重     →   加载测试数据
一键导出         →   跑评测 → 出报告
```

评测指标、测试用例、评测报告都有标准 JSON Schema，平台和 Agent 通过这套格式互通。