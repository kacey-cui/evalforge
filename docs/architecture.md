# EvalForge Architecture

> How EvalForge is structured, where each component lives, and how they connect.

## Architecture Diagram

```
┌─────────────────────────────────────────────────┐
│                    Agent (Claude, GPT, etc.)    │
│  Reads METRIC_SCHEMA.md / REPORT_SCHEMA.md      │
│  Calls MetricStore / DatasetStore / RunStore    │
│  Generates Skills via generate_skill.py         │
│  Runs evaluation locally (deepeval)             │
└──────────────┬──────────────────────────────────┘
               │  Python API / CLI / JSON contracts
               ▼
┌─────────────────────────────────────────────────┐
│              EvalForge API Layer                 │
│  ┌───────────────┐ ┌──────────────┐             │
│  │ MetricStore   │ │ DatasetStore │             │
│  │ - create      │ │ - create     │             │
│  │ - get         │ │ - get        │             │
│  │ - list        │ │ - list       │             │
│  │ - versioning  │ │ - versioning │             │
│  │ - diff        │ │ - diff       │             │
│  └───────┬───────┘ └──────┬───────┘             │
│  ┌───────┴───────┐ ┌──────┴────────┐            │
│  │ generate_skill│ │  RunStore     │            │
│  │ - SkillSpec → │ │  - submit     │            │
│  │   SkillPackage│ │  - get/list   │            │
│  │ - manifest    │ │  - compare    │            │
│  └───────────────┘ └───────────────┘            │
│  ┌────────────────────────────────┐             │
│  │ eval_diff    — why scores diff │             │
│  │ run_manifest — provenance      │             │
│  │ enrich_report— auto charts     │             │
│  └────────────────────────────────┘             │
└──────────────┬──────────────────────────────────┘
               │  Content-addressable storage
               ▼
┌─────────────────────────────────────────────────┐
│         Metric / Dataset / Skill / Report       │
│  data/                                          │
│  ├── metrics/{llm,non_llm}/*.json               │
│  │   └── .versions/{id}/{hash}.json             │
│  ├── datasets/{id}/dataset.json + test_cases.json│
│  │   └── .versions/{hash}.json                  │
│  ├── runs/{run_id}/                             │
│  │   ├── manifest.json   (full provenance)      │
│  │   ├── results.json    (enriched report)      │
│  │   ├── meta.json       (quick summary)        │
│  │   ├── config.json      (eval config)         │
│  │   └── dataset_ref.json                       │
│  └── projects/{name}/canvas.json                │
└──────────────┬──────────────────────────────────┘
               │  deepeval (Python, runs locally)
               ▼
┌─────────────────────────────────────────────────┐
│           Local Evaluation Execution            │
│  Skill (eval_script.py)                         │
│    ├── loads test_cases.json                    │
│    ├── runs deepeval metrics (gate + score)     │
│    └── outputs eval_report.json                 │
│                                                 │
│  Agent submits report → RunStore.submit()       │
│    → manifest built → report enriched →         │
│    → run directory created → provenance tracked │
└──────────────┬──────────────────────────────────┘
               │
               ▼
┌─────────────────────────────────────────────────┐
│          Report + Provenance                    │
│  - RunStore.get(run_id) → full run data         │
│  - RunStore.compare(a, b) → score_delta,        │
│    field_diffs, config_diff, dataset_check      │
│  - eval_diff(a, b) → human-readable summary     │
│    of WHY scores differ (dataset? metric?       │
│    model? skill?)                               │
│  - run_manifest.verify_manifest() →             │
│    checks all hash references resolve           │
└─────────────────────────────────────────────────┘
```

## Component Map

### 1. API Layer (`scripts/`)

| File | Purpose | Key interface |
|------|---------|---------------|
| `metric_store.py` | CRUD + versioning for metrics | `MetricStore.create(metric_dict)` → `{ok, data}` |
| `dataset_store.py` | CRUD + versioning for datasets | `DatasetStore.create(id, name, cases)` → `{ok, data}` |
| `run_store.py` | Submit, query, compare runs | `RunStore.submit(report, manifest)` → `{ok, data}` |
| `generate_skill.py` | Generate executable Skill packages | `generate_skill(spec)` → `SkillPackage` |
| `run_manifest.py` | Build & verify provenance manifests | `build_manifest(...)` → manifest dict |
| `eval_diff.py` | Root-cause analysis of score differences | `eval_diff(run_a, run_b)` → `{summary, ...}` |
| `enrich_report.py` | Auto-detect patterns → charts + tables | `enrich(report_dict)` → enriched dict |
| `metric_versioning.py` | Low-level content-addressable versioning | `compute_version_hash`, `create_version`, `diff_versions` |
| `dataset_versioning.py` | Same for datasets | `compute_content_hash`, `create_dataset`, `diff_versions` |
| `mini_json_schema.py` | Lightweight JSON schema validator | `validate(data, schema)` → error list |
| `publish_metric.py` | Share/discover metrics with dedup | `publish`, `discover`, `check` |
| `git_bridge.py` | REST bridge for git-backed operations | Flask server on `:8081` |

### 2. Agent Skills (`skills/`)

| Directory | Purpose |
|-----------|---------|
| `evalplatform-orchestrator/` | Full workflow orchestration: understand business → prepare data → create metrics → configure pipeline → generate Skill → execute → record run |
| `version-manager/` | Run management commands: list, diff, record, delete, create group |

### 3. Data (`data/`)

| Path | Content |
|------|---------|
| `metrics/llm/*.json` | LLM-judge metric definitions (GEval) |
| `metrics/non_llm/*.json` | Non-LLM metric definitions (pure Python) |
| `metrics/*/.versions/{id}/{hash}.json` | Immutable version snapshots |
| `datasets/{id}/dataset.json` | Dataset metadata |
| `datasets/{id}/test_cases.json` | Test cases |
| `datasets/{id}/.versions/{hash}.json` | Immutable version snapshots |
| `runs/{run_id}/` | Run directory: manifest, results, meta, config, dataset_ref |
| `projects/{name}/canvas.json` | Evaluation pipeline configuration |

### 4. Web GUI (`index.html`)

A single-page vanilla HTML/CSS/JS app with 7 tabs:
- **Overview** — project summary
- **Metric Library** — browse & configure metrics
- **Canvas** — drag-and-drop pipeline composition (gate + score zones)
- **Export** — download Skill as zip
- **Run History** — list past runs
- **Diff** — compare two runs side-by-side
- **Report** — detailed results with inline SVG charts

### 5. Templates (`templates/skill/`)

| File | Purpose |
|------|---------|
| `SKILL.md.tpl` | Skill metadata template |
| `eval_script.py.tpl` | Evaluation script template |

## Design Principles

### Content-Addressable Storage
Every metric, dataset, skill, and run is identified by a SHA256 hash of its content. Same content → same hash → deduplication. Different content → different hash → new version. This is the foundation of versioning.

### Structured Error Handling
All API methods return `{ok: bool, data?: dict, error?: {code, message, details?}}`. No exceptions are raised for business-logic errors. Agents can programmatically handle failures.

### No Database
Everything is files on disk. No SQLite, no Postgres, no external services. Git provides audit trail. The filesystem provides storage.

### Engine Runs Locally
Deepeval (the evaluation engine) runs on the Agent's machine, not inside the platform. The platform provides the configuration (metrics, weights, thresholds) and the Agent executes.

### Two Interfaces, One Contract
The Web GUI and the Agent API drive the same JSON schemas (`METRIC_SCHEMA.md`, `REPORT_SCHEMA.md`). No browser automation needed — Agents read/write files directly.