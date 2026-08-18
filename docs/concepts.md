# EvalForge Concepts

> Core concepts explained — what each piece is, why it exists, and how they fit together.

---

## 1. What problem does EvalForge solve?

Evaluating LLM outputs (LLM-as-Judge) is the most reliable way to assess model quality today. But doing it well requires:

- **Metric definitions** that are precise and versioned
- **Test datasets** that are stable and versioned
- **Evaluation pipelines** that combine gate checks (format, keywords) with score metrics (accuracy, completeness)
- **Reports** that are comparable across runs
- **Provenance** that traces every score back to the exact metric version, dataset version, model, and environment that produced it

Frameworks like Deepeval require writing Python — a barrier for non-developers. Meanwhile, spinning up ad-hoc eval scripts in the AI era is trivially easy, but leads to **metric drift, no shared contract, no versioning, and no way to compare runs**.

EvalForge solves this by providing a **structured, versioned, Agent-native platform** where:
- Metrics and datasets are defined as JSON files with content-addressable versioning
- Evaluation pipelines are composed as configurations (not code)
- Skills are generated from configurations and executed locally
- Reports are submitted with full provenance manifests
- Runs can be compared to understand *why* scores changed

---

## 2. Why Metric / Dataset / Report versioning?

### The Problem

Without versioning, you can't answer basic questions:
- "I changed the accuracy threshold from 0.7 to 0.8 — did scores change because of the threshold, or because the model got worse?"
- "The dataset was updated with 50 new cases — is the score drop real or just harder cases?"
- "Which version of the completeness metric was used in last week's run?"

### How EvalForge solves it

**Content-addressable versioning**: Every metric, dataset, and report is hashed (SHA256). Same content → same hash. Different content → new hash → new version.

- **Metric versioning**: When you change a metric definition (e.g., threshold, criteria), a new version is created. The old version is preserved in `.versions/{id}/{hash}.json`. Both are immutable.
- **Dataset versioning**: Same principle. When test cases change, a new content hash is computed. The old version is preserved.
- **Report versioning**: Each run is a directory with a `manifest.json` that records the exact hash of every input (dataset version, metric versions, skill hash, model, environment). The report itself is immutable once submitted.

This means you can always answer: "What exactly produced this score?"

---

## 3. Why Agent-native?

### The shift from GUI to ANI

Human-computer interaction has evolved through three stages:
- **CLI** — the terminal era: you typed commands
- **GUI** — the personal-computer era: ordinary people got a graphical interface
- **ANI (Agent-Native Interface)** — the AI era: Agents should be able to operate a system *directly*

Today people are already handing GUI tasks to Agents via Playwright (browser automation). But driving a GUI through DOM manipulation is slow, fragile, and not how the future should work.

### What Agent-native means in EvalForge

EvalForge is built Agent-native from the ground up. Its real interface is not the web page — it is a set of:

1. **JSON schemas** (`METRIC_SCHEMA.md`, `REPORT_SCHEMA.md`) — contracts that both humans and Agents can read
2. **Python APIs** (`MetricStore`, `DatasetStore`, `RunStore`, `generate_skill`) — structured, no-exception interfaces
3. **Structured error responses** (`{ok, error: {code, message, details}}`) — Agents can programmatically handle failures
4. **Agent Skills** (`skills/evalplatform-orchestrator/`) — full workflow orchestration that an Agent can execute without a browser

An Agent can generate metrics, configure pipelines, run evaluations, and record runs without ever opening a browser. The Web GUI is just *one client* of that same contract, for humans.

### Concrete example

```python
# An Agent (Claude, GPT, etc.) writes this code directly:
from metric_store import MetricStore
store = MetricStore()
result = store.create({
    "id": "accuracy",
    "name": "Accuracy (GEval)",
    "category": "llm",
    "params": [{"key": "threshold", "type": "number", "default": 0.7}],
    "criteria": "Evaluate factual correctness...",
    "requires": ["actual_output", "expected_output"],
    "code_template": "GEval(name='Accuracy', ...)"
})
# → {ok: true, data: {metric_id: "accuracy", version_hash: "abc123..."}}
```

No browser. No DOM. No Playwright. Just Python and JSON.

---

## 4. Why evaluation execution in Agent/local environment?

### The model stays with you

EvalForge does not run evaluations itself. It generates a **Skill** — a self-contained Python package (`SKILL.md` + `eval_script.py` + `test_cases_template.json` + `requirements.txt`) — that you run on your own machine.

Reasons:
1. **Data privacy**: Your test cases and model outputs never leave your environment
2. **Model access**: Your model API keys stay with you
3. **No platform lock-in**: Deepeval runs locally, not inside the platform. The platform never locks you into a runtime.
4. **Reproducibility**: The Skill is a self-contained artifact. Anyone with the Skill and the dataset can reproduce the exact same evaluation.

### The flow

```
Platform (EvalForge)          Agent's local environment
─────────────────────         ─────────────────────────
Define metrics              
Configure pipeline           →  Export Skill
                             →  Install dependencies
                             →  Run eval_script.py
                             →  Produce eval_report.json
                             ←  Submit report via RunStore
Store run with provenance
```

---

## 5. What is the GUI's role?

The Web GUI (`index.html`) is a **visual composer** for evaluation pipelines. It serves humans who want to:

- Browse the metric library visually
- Drag-and-drop metrics into gate and score zones
- Adjust weights, thresholds, strictness with sliders
- Export the configuration as a downloadable Skill zip
- View run history, diff reports, and charts

The GUI is **not** the primary interface. It is a convenience layer that reads/writes the same JSON contracts as the Agent API. Every operation available in the GUI is also available programmatically.

> If the GUI disappeared tomorrow, an Agent could still do everything through the Python API.

---

## 6. How to run an evaluation?

### Agent/API workflow (recommended)

```bash
# 1. Create metrics
python scripts/metric_store.py create '{"id":"accuracy","name":"Accuracy","category":"llm",...}'

# 2. Create dataset
python scripts/dataset_store.py create --dataset-id qa_basics --name "Basic Q&A" --source test_cases.json

# 3. Generate Skill
python scripts/generate_skill.py --project my_project --output ./skill_output/

# 4. Execute Skill locally
cd skill_output && pip install -r requirements.txt && python eval_script.py

# 5. Submit report
python scripts/run_store.py submit --report eval_report.json --manifest manifest.json
```

### GUI workflow

```bash
bash serve.sh                    # Start platform
# Open http://localhost:8080
# Browse metrics → Compose on Canvas → Export Skill → Run locally → View in Run History
```

### Full end-to-end example

See `examples/agent_workflow/run_workflow.py` — a 12-step script that creates metrics, datasets, generates a Skill, simulates execution, submits reports, and compares them.

---

## 7. How to compare two evaluations?

### Quick comparison

```python
from run_store import RunStore
rs = RunStore()
result = rs.compare("run_20260818_001", "run_20260818_002")
# → {score_delta: -0.1, field_diffs: {...}, config_diff: {...}, dataset_check: {...}}
```

### Root-cause analysis

```python
from eval_diff import eval_diff
result = eval_diff("run_20260818_001", "run_20260818_002")
# → {
#     score_comparison: {overall: {a: 0.9, b: 0.8, delta: -0.1}},
#     dataset: {status: "unchanged"},
#     metrics: [{metric_id: "accuracy", status: "modified", detail: {...}}],
#     skill: {status: "unchanged"},
#     model: {status: "unchanged"},
#     summary: "总分从 0.9 变为 0.8，下降了 0.1。修改了 1 个指标。分数差异可能由以下因素导致：指标变动。"
#   }
```

`eval_diff` answers the question: **"Why did these two evaluations produce different results?"** by comparing every dimension: scores, datasets, metrics, skill, model, and judge model.

### What gets compared

| Dimension | What's checked |
|-----------|---------------|
| **Scores** | Overall score delta, per-field score deltas, per-case changes |
| **Dataset** | Same dataset_id? Same version? If different, what cases changed? |
| **Metrics** | Which metrics were added/removed/modified? For modified metrics, what fields changed? |
| **Skill** | Did the evaluation script change? |
| **Model** | Same model under test? Same base URL? |
| **Judge** | Same judge model? |

---

## 8. How to track provenance?

### The manifest

Every run includes a `manifest.json` that records the exact state of everything that influenced the evaluation:

```json
{
  "manifest_version": "1.0",
  "manifest_hash": "sha256 of the manifest itself",
  "run_id": "run_20260818_001",
  "created_at": "2026-08-18T12:00:00Z",
  "triggered_by": "agent",
  "dataset": {
    "dataset_id": "qa_basics",
    "version_hash": "abc123...",
    "content_hash": "def456...",
    "n_cases": 100
  },
  "metrics": [
    {
      "metric_id": "accuracy",
      "version_hash": "111aaa...",
      "instance": {"weight": 0.5, "strictness": 1.0, "zone": "score"}
    }
  ],
  "skill": {
    "name": "my_eval",
    "content_hash": "222bbb..."
  },
  "model": {
    "model_id": "gpt-4",
    "base_url": "https://api.openai.com/v1"
  },
  "environment": {
    "python_version": "3.12.0",
    "platform": "macOS-14.0",
    "dependencies": {"deepeval": "1.2.0", "openai": "1.0.0"}
  }
}
```

### Verifying provenance

```python
from run_manifest import verify_manifest
result = verify_manifest(manifest_dict)
# → {valid: true, checks: [{object: "dataset qa_basics", status: "ok"}, ...]}
```

`verify_manifest` checks that every hash reference in the manifest actually resolves to a real version in the `.versions/` directories. This proves the run is reproducible.

### The provenance chain

```
Dataset version hash  ──┐
Metric version hashes ──┤
Skill content hash    ──┼──→ manifest_hash ──→ stored in manifest.json
Model config          ──┤                      and injected into report
Environment info      ──┘
```

Given a `run_id`, you can always trace back to:
- The exact dataset content (via `content_hash`)
- The exact metric definitions (via `version_hash`)
- The exact evaluation script (via `skill.content_hash`)
- The exact model and environment

This is the foundation for reproducible, auditable LLM evaluation.