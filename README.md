# EvalForge

Agent-native evaluation infrastructure for structured, versioned, and reproducible LLM evaluation.

EvalForge defines, versions, stores, orchestrates, and compares evaluations — metrics, datasets, pipelines, runs, and reports — as structured artifacts. The actual evaluation execution is delegated to evaluation engines such as [Deepeval](https://github.com/confident-ai/deepeval), which run locally on your machine.

It does not replace evaluation engines. It provides the contracts, storage, provenance, and orchestration around them.

[中文文档](README.zh-CN.md) · [Concepts](docs/concepts.md) · [Architecture](docs/architecture.md) · [![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

---

## Architecture

```
Agent / Human
       │
       │  Python API / CLI / JSON contracts
       ▼
EvalForge
       │
       ├── MetricStore        — metric CRUD + versioning
       ├── DatasetStore       — dataset CRUD + versioning
       ├── RunStore           — run submission, query, comparison
       ├── generate_skill     — pipeline → executable Skill package
       ├── run_manifest       — provenance manifest (build & verify)
       ├── eval_diff          — root-cause analysis of score differences
       └── enrich_report      — auto-detected charts & tables
       │
       │  Content-addressable storage (SHA256, .versions/)
       ▼
Evaluation Package (Skill)
       │
       │  eval_script.py → deepeval → eval_report.json
       ▼
Report + Manifest
       │
       │  manifest.json → verify_manifest() → reproducibility check
       ▼
Reproducible Run / Comparison
```

EvalForge is the control plane. The evaluation engine runs locally and remains replaceable.

---

## Quick Start

An end-to-end evaluation can be expressed as: **Metric → Dataset → Skill → Local Evaluation → Run → Compare**.

```bash
# 1. Define a metric
python scripts/metric_store.py create '{
  "id":"accuracy","name":"Accuracy (GEval)","category":"llm",
  "params":[{"key":"threshold","type":"number","default":0.7}],
  "criteria":"Evaluate factual correctness...",
  "requires":["actual_output","expected_output"],
  "code_template":"GEval(name=\"Accuracy\", criteria=\"{{criteria}}\", threshold={{threshold}}, model=JUDGE_MODEL)"
}'

# 2. Register a dataset
python scripts/dataset_store.py create \
  --dataset-id my_qa --name "My Q&A" --source test_cases.json

# 3. Generate an executable Skill
python scripts/generate_skill.py --project my_project --output ./skill_output/

# 4. Run evaluation locally (Deepeval)
cd skill_output && pip install -r requirements.txt && python eval_script.py

# 5. Submit the run (provenance tracked)
python scripts/run_store.py submit \
  --report eval_report.json --manifest manifest.json

# 6. Compare with a previous run
python scripts/run_store.py compare --run-a run_20260818_001 --run-b run_20260818_002
```

See the full 12-step workflow: [`examples/agent_workflow/run_workflow.py`](examples/agent_workflow/run_workflow.py)

### GUI (optional human client)

```bash
bash serve.sh                    # Start platform on :9090
# Open http://localhost:9090    # Browse metrics, compose on Canvas, export Skill
```

The GUI is a visual composer that reads and writes the same JSON contracts. It is one client, not the primary interface.

---

## Why EvalForge?

### The Problem

LLM evaluation in practice suffers from several engineering problems that go beyond choosing a metric:

**1. Metric drift.** The same "accuracy" metric can mean different things across projects or over time — different criteria, thresholds, required fields, or code templates. Without versioning, it is hard to know which definition produced a given score.

**2. Dataset drift.** Test sets change. When a run's score shifts, it is often unclear whether the model regressed or the dataset was updated.

**3. Run reproducibility.** A score alone is not enough. To interpret or reproduce a result, you need to know: which metric version, which dataset version, which skill version, which model, which judge, and which environment produced it.

**4. Comparison.** "Score went down by 0.1" is not actionable. The real question is: *what changed?* — dataset, metric, threshold, model, judge, or evaluation config?

**5. Agent interaction.** If evaluation workflows are increasingly automated by Agents, then browser automation (Playwright, DOM manipulation) is the wrong interface. Agents need structured APIs, machine-readable schemas, and deterministic commands.

### The Approach

EvalForge addresses these problems by treating evaluation artifacts as structured, versioned, and provenance-tracked entities:

| Without EvalForge | With EvalForge |
|---|---|
| Metric definitions drift across ad-hoc scripts | Content-addressable versioning — every semantic change produces a new hash |
| "Which metric version did this run use?" — unknown | `manifest.json` records the exact hash of every input |
| "Why did the score drop?" — guesswork | `eval_diff` compares dataset, metrics, skill, model, and judge |
| Agent must use Playwright to drive a GUI | Agent calls Python APIs directly; structured error responses |
| Test cases change silently | Dataset versioning with content hash |
| No way to reproduce a run | `verify_manifest()` checks all hash references resolve |

---

## Design Principles

### Contract-first
Metrics, datasets, reports, and runs are represented as structured JSON contracts. Schemas are published in [`METRIC_SCHEMA.md`](METRIC_SCHEMA.md) and [`REPORT_SCHEMA.md`](REPORT_SCHEMA.md).

### Content-addressable
Semantic artifacts are identified by SHA256 content hashes. Same content → same hash. Different content → new version. Historical versions are immutable and stored in `.versions/`.

### Local-first
Evaluation execution stays on your machine. The platform manages artifacts, versioning, and provenance — it does not require a centralized database or runtime.

### API-first
Every important operation is callable through Python APIs and CLI without browser automation. The Web GUI is a human-facing client that uses the same underlying contracts.

### Reproducibility over convenience
A run should be explainable and traceable after the fact. Provenance is recorded by default, not as an afterthought.

---

## Core Concepts

### Versioned Artifacts

Metrics and datasets are first-class, versioned artifacts.

A metric's **identity** (`metric_id`) is stable. Its **version** (`version_hash`) changes whenever evaluation semantics change. The version hash is computed from the fields that affect evaluation behavior: `category`, `params`, `criteria`, `requires`, and `code_template`. Display metadata such as `name` and `description` do not affect the hash.

```
accuracy
├── version a1b2c3...  (threshold=0.7, criteria="factual correctness")
├── version d4e5f6...  (threshold=0.8, criteria="factual correctness + completeness")
└── version g7h8i9...  (current)
```

Both historical versions remain addressable, so past runs stay interpretable.

Datasets follow the same model: `content_hash` captures the test cases, and `version_hash` captures the metadata + content.

### Provenance

Every run includes a `manifest.json` that records the exact state of everything that influenced the evaluation:

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

`verify_manifest()` checks that every hash reference in the manifest resolves to a real version in the `.versions/` directories.

### Reproducible Runs

A run is a directory under `data/runs/{run_id}/` containing:

| File | Purpose |
|---|---|
| `manifest.json` | Full provenance — all input hashes |
| `results.json` | Enriched evaluation report with charts and tables |
| `meta.json` | Quick summary (score, pass rate, metrics list) |
| `config.json` | Evaluation configuration snapshot |
| `dataset_ref.json` | Dataset reference (id, version, content hash, n_cases) |

Given a `run_id`, you can trace back to the exact dataset, metrics, skill, model, and environment that produced the score.

### Evaluation Diff

`eval_diff` compares two runs across every dimension — not just scores:

| Dimension | What is checked |
|---|---|
| Scores | Overall delta, per-field deltas, per-case changes |
| Dataset | Same dataset? Same version? What cases changed? |
| Metrics | Added, removed, or modified? What fields changed? |
| Skill | Did the evaluation script change? |
| Model | Same model under test? Same base URL? |
| Judge | Same judge model? |

The output includes a human-readable summary that identifies the likely root causes of score differences.

---

## Core Features

### 1. Versioned Evaluation Artifacts
Metrics and datasets use content-addressable versioning (SHA256). Every change creates a new immutable version. Old versions are preserved in `.versions/` and remain addressable.

### 2. Provenance & Reproducibility
Every run carries a `manifest.json` recording the exact hash of every input. `verify_manifest()` checks that all references resolve. `eval_diff` explains *why* scores changed.

### 3. Structured APIs
`MetricStore`, `DatasetStore`, and `RunStore` provide Python APIs that return `{ok, data}` or `{ok, error: {code, message, details}}`. No exceptions for business-logic errors. Agents can handle failures programmatically.

### 4. Agent-native Workflow
JSON contracts ([`METRIC_SCHEMA.md`](METRIC_SCHEMA.md), [`REPORT_SCHEMA.md`](REPORT_SCHEMA.md)), Python APIs, structured errors, and CLI — every operation is callable without a browser. Agent Skills ([`skills/evalplatform-orchestrator/`](skills/evalplatform-orchestrator/SKILL.md)) provide full workflow orchestration.

### 5. Skill Generation
`generate_skill.py` turns a pipeline configuration into a self-contained Skill package: `SKILL.md` + `eval_script.py` + `test_cases_template.json` + `requirements.txt` + `manifest.json`. Run it anywhere with Deepeval.

### 6. Evaluation Diff
`eval_diff` performs root-cause analysis: it compares scores, datasets, metrics, skill, model, and judge model between two runs, and generates a summary of what changed.

### 7. Report Enrichment
`enrich_report.py` auto-detects patterns (Recall@k curves, MRR, domain breakdowns) and generates inline SVG charts (line, bar, histogram) and paginated tables.

### 8. Web GUI
A single-page vanilla HTML/CSS/JS app with 7 tabs: Overview, Metric Library, Canvas (drag-and-drop pipeline composition), Export, Run History, Diff, and Report. The GUI reads and writes the same JSON contracts as the API.

---

## Metrics

EvalForge ships with 9 preset metrics as a demonstration of the metric contract. Custom metrics are created through `MetricStore.create()`.

### Deterministic metrics (non-LLM, pure Python)

| Metric | Description |
|---|---|
| `json_schema` | Validate JSON structure and field types |
| `keyword_hit` | Check if output contains required keywords |
| `latency` | Measure response time |
| `sentence_count` | Count sentences in output |
| `context_length` | Measure input context length |
| `recall_at_k` | Check if ground truth appears in top-K retrieval results |

### LLM-based metrics (GEval)

| Metric | Description |
|---|---|
| `accuracy` | Evaluate factual correctness against expected output |
| `completeness` | Evaluate whether the answer covers all required aspects |
| `no_hallucination` | Check that the output does not fabricate information |

LLM-based metrics use GEval with a judge model configured globally. The judge model is not bundled — it runs against your own model endpoint.

---

## Two Ways to Use EvalForge

| Style | Entry point | Best for |
|---|---|---|
| **API / CLI** | `MetricStore`, `DatasetStore`, `RunStore`, `generate_skill` | Agents, automation, batch, CI/CD |
| **GUI** | `bash serve.sh` then open browser | Humans, visual exploration, drag-and-drop |

Both operate on the same JSON contracts. No browser automation is required.

---

## What EvalForge Is Not

- It is not an LLM inference framework.
- It is not an evaluation model itself (it does not score outputs).
- It does not replace Deepeval — it orchestrates around it.
- It does not require the Web GUI; all operations are available through the API and CLI.
- It does not require a centralized database — storage is filesystem-based.

---

## When Should You Use EvalForge?

**Use it when:**

- Evaluation logic is shared across multiple projects or team members
- Metrics or datasets evolve over time and you need to track changes
- You need reproducible evaluation runs with full provenance
- Evaluations are increasingly automated by Agents
- You need to compare *why* two evaluation results differ, not just that they differ
- You want evaluation artifacts to be inspectable, versioned, and auditable

**Not necessary when:**

- You only need a one-off evaluation script
- You do not need reproducibility or history
- You are simply trying a metric locally

---

## Project Structure

```
evalplatform/
├── index.html                       # Web GUI (vanilla HTML/CSS/JS, 7 tabs)
├── serve.sh                         # Starts :9090 static + :9091 git bridge
├── METRIC_SCHEMA.md                 # Metric JSON contract
├── REPORT_SCHEMA.md                 # Report JSON contract
├── data/
│   ├── metrics/{llm,non_llm}/       # 9 preset metric definitions + .versions/
│   ├── datasets/{id}/               # Dataset definitions + test cases + .versions/
│   ├── runs/{run_id}/               # Run snapshots (manifest, results, meta, config, dataset_ref)
│   └── projects/{name}/             # canvas.json pipeline configs
├── scripts/
│   ├── metric_store.py              # MetricStore — CRUD + versioning + CLI
│   ├── dataset_store.py             # DatasetStore — CRUD + versioning + CLI
│   ├── run_store.py                 # RunStore — submit, get, list, compare + CLI
│   ├── generate_skill.py            # SkillSpec → SkillPackage + CLI
│   ├── run_manifest.py              # Build & verify provenance manifests
│   ├── eval_diff.py                 # Root-cause analysis of score differences
│   ├── enrich_report.py             # Auto chart generation
│   ├── metric_versioning.py         # Content-addressable metric versioning
│   ├── dataset_versioning.py        # Content-addressable dataset versioning
│   ├── mini_json_schema.py          # Lightweight JSON schema validator
│   ├── publish_metric.py            # Metric share/discover with dedup
│   └── git_bridge.py                # Flask REST bridge for git operations
├── skills/
│   ├── evalplatform-orchestrator/   # Agent orchestration Skill
│   └── version-manager/             # Run management commands
├── templates/skill/                 # SKILL.md.tpl + eval_script.py.tpl
├── examples/agent_workflow/         # 12-step end-to-end API workflow demo
├── docs/
│   ├── architecture.md              # System design and component map
│   ├── concepts.md                  # Why versioning, provenance, agent-native design
│   └── design/                      # Design documents for implemented features
├── tests/                           # pytest test suite
└── requirements.txt
```

---

## Tech Stack

- **API layer**: Python (standard library + `hashlib`, `json`, `argparse`)
- **Web GUI**: Vanilla HTML/CSS/JS, HTML5 Drag & Drop, JSZip — zero framework, zero build step
- **Backend bridge**: Flask (localhost-only git bridge on `:9091`)
- **Storage**: Filesystem (content-addressable) + Git (audit trail)
- **Evaluation engine**: [Deepeval](https://github.com/confident-ai/deepeval) (Python, runs locally — not bundled)
- **Charts**: Inline SVG, no third-party chart libraries

---

## Documentation

| Document | What it covers |
|---|---|
| [Concepts](docs/concepts.md) | Why versioning, why Agent-native, how provenance works, how to run & compare evaluations |
| [Architecture](docs/architecture.md) | System design, component map, data flow diagram |
| [Metric Schema](METRIC_SCHEMA.md) | The JSON contract for metrics |
| [Report Schema](REPORT_SCHEMA.md) | The JSON contract for reports |
| [Agent Workflow Demo](examples/agent_workflow/README.md) | 12-step end-to-end API workflow |
| [Design Docs](docs/design/) | Design specifications for each module |

---

## License

[MIT](LICENSE) © 2026 Kacey Cui