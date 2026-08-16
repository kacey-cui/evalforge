# EvalPlatform 🧩

**Visual LLM-as-Judge evaluation platform** — build evaluation pipelines by dragging and dropping, not writing code.

> **The platform designs, the Agent executes.** Visually compose [Deepeval](https://github.com/confident-ai/deepeval) evaluation pipelines, export them as a Skill, and let a local Agent run the evaluation and produce reports.

[中文文档](README.zh-CN.md) · [![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

---

## Why EvalPlatform?

LLM-as-Judge — using an LLM to grade another LLM's output — is one of the most reliable ways to evaluate models today. But frameworks like Deepeval require writing Python, which raises the barrier for product managers, QA, and other non-engineers.

EvalPlatform started from a simple observation: *evaluation configs — metrics, weights, thresholds, gates — already read like a drag-and-drop interface. So why not make it one?*

Three goals:

1. **Visual first** — pick metrics, tune weights/thresholds/gates by drag-and-drop, no code.
2. **Skill transmission** — a configured pipeline becomes a reusable **Skill** that you download and hand to any local Agent.
3. **UI ⇄ Agent equivalence** — one JSON contract powers both: click through the UI, or let an Agent read/write files automatically.

The core insight: **the platform designs, the Agent executes**, and they meet through standard schemas. The visual UI is a convenience, not the only entry point.

---

## How to use

### Quick start

```bash
# 1. Start (launches static server :8080 + git bridge :8081)
bash serve.sh

# 2. Open in browser
# http://localhost:8080
```

**① Browse metrics** — the Metric library ships with 8 presets (5 non-LLM: JSON schema, keyword hit, latency, sentence count, context length; 3 GEval: accuracy, completeness, no-hallucination).

**② Compose on the Canvas** — drag metrics into each field (e.g. `diagnosis`) to form a pipeline:

- 🚪 **Gate zone** (red) — runs in order, stops at the first failure. Good for format/keyword checks.
- 📊 **Score zone** (green) — all run, weighted average, with per-metric weight & strictness.

**③ Export** — one click downloads a Skill zip (`SKILL.md` + `eval_script.py` + test-case template).

**④ Hand it to an Agent** — install the Skill locally and the Agent will prepare test data, run Deepeval, and produce `eval_report.json`.

### Full workflow

```
Platform (design)          Local Agent (execute)
───────────────            ─────────────────────
compose metrics/weights  ──export──▶  load Skill
configure gates/thresholds           prepare test data
export Skill zip                    run deepeval → report
                                    record Run → view history/diff/charts
```

### Two ways to use it

| Style | Best for | Entry point |
|-------|----------|-------------|
| 🖱️ **Web UI** | visual, exploratory | `bash serve.sh` then open the browser |
| 🤖 **Agent automation** | automated, batch | install `skills/evalplatform-orchestrator/` and let it read/write files |

Both drive the same JSON contracts (`METRIC_SCHEMA.md` / `REPORT_SCHEMA.md`) — fully equivalent.

---

## Features

- **Field-level evaluation pipeline** — gate zone + score zone with weight, strictness, threshold.
- **7 visual tabs** — Overview / Metric library / Canvas / Export / Run history / Diff / Report (inline SVG charts + paginated tables).
- **Skill export & transmission** — configs become reusable Skills, executed by local Agents.
- **Git-native versioning** — every Run = a git commit, comparison groups = git tags, diff = `git diff`. Zero new dependencies.
- **Auto-enriched reports** — `enrich_report.py` detects Recall@k / MRR / domain breakdowns and generates line/bar/histogram charts.
- **Metric sharing** — `publish_metric.py` supports publish/discover with duplicate detection (ID conflict → reject, similarity → warn).
- **Presets + custom metrics** — 8 presets out of the box, plus custom metrics by subclassing `BaseMetric`.

---

## Project structure

```
evalplatform/
├── index.html              # main app (vanilla HTML/CSS/JS, no framework)
├── serve.sh                # starts :8080 static + :8081 git bridge
├── METRIC_SCHEMA.md        # metric JSON contract (Agents read this)
├── REPORT_SCHEMA.md        # report JSON contract
├── data/
│   ├── metrics/            # preset metric templates (non_llm / llm)
│   ├── projects/           # per-project config (canvas.json)
│   └── runs/               # Run snapshots (git-tracked)
├── templates/skill/        # Skill export templates
├── scripts/
│   ├── git_bridge.py       # Git REST bridge (Run history / diff)
│   ├── enrich_report.py    # report enrichment engine (auto charts)
│   └── publish_metric.py   # metric publish/discover/dedup
└── skills/
    ├── evalplatform-orchestrator/  # orchestration Agent Skill
    └── version-manager/            # version-management Skill (5 commands)
```

---

## Tech stack

- **Frontend**: vanilla HTML/CSS/JS, HTML5 Drag & Drop, JSZip, zero framework/build
- **Backend**: Flask (local git bridge, localhost only)
- **Storage**: localStorage (per project) + filesystem + Git (Run history)
- **Evaluation engine**: Deepeval (Python, runs locally — not bundled)
- **Charts**: inline SVG, no third-party chart libs

---

## Roadmap

### Near term

- [ ] **Real backend** — replace localStorage + Flask bridge with FastAPI + SQLite
- [ ] **More built-in metrics** — surface Deepeval's 30+ metrics (Faithfulness, AnswerRelevancy, ContextualRecall…) visually
- [ ] **Dataset management** — upload, versioning, tags
- [ ] **Model management** — separate configs for model-under-test vs judge model

### Mid term

- [ ] **Test-case synthesis** — Deepeval Synthesizer to auto-generate cases from docs/contexts
- [ ] **Conversational & agent evaluation** — ConversationalTestCase, tool calls, agent traces
- [ ] **CI/CD gates** — `deepeval gate` + GitHub Actions
- [ ] **Report enhancement** — more chart types, PDF/HTML export, notifications

### Long term

- [ ] **Tracing visualization** — visualize Deepeval trace/span trees to pinpoint score reasons
- [ ] **Multi-user collaboration** — per-project permissions, shared metric library, shared groups
- [ ] **Evaluation-as-a-service** — turn Skill transmission into a team evaluation ecosystem

> Issues & PRs welcome. If you have something to evaluate, come try "building blocks instead of code".

---

## License

[MIT](LICENSE) © 2026 Kacey Cui
