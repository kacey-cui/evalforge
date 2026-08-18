# Agent Workflow Demo

A complete 12-step EvalForge evaluation workflow — **driven entirely by Python API, no GUI required**.

This is the canonical demonstration of EvalForge's Agent-native design. Every step uses the same `MetricStore`, `DatasetStore`, `RunStore`, and `generate_skill` APIs that an Agent (Claude, GPT, etc.) would call directly.

## Quick Start

```bash
cd /path/to/evalplatform
python3 examples/agent_workflow/run_workflow.py
```

All artifacts are created in a temporary directory (printed at the start). Nothing is written to the repository.

## Flow Overview

```
Step 1  → Create Dataset (10 basic Q&A cases)
Step 2  → Create Metrics (accuracy + json_schema)
Step 3  → Create Evaluation Configuration (canvas.json)
Step 4  → Generate Skill (SKILL.md + eval_script.py + manifest.json)
Step 5  → Execute Skill (simulated — generates eval_report.json)
Step 6  → Submit Report (RunStore.submit → provenance tracked)
Step 7  → View Report (RunStore.get)
Step 8  → Modify Metric — create new version (accuracy threshold 0.7 → 0.8)
Step 9  → Execute Again (stricter threshold, exposes a defect)
Step 10 → Submit Second Report
Step 11 → Compare Reports (score_delta, field_diffs, dataset_check)
Step 12 → List All Runs
```

## Key Design Validation

This workflow validates every core EvalForge principle:

| Principle | Demonstrated by |
|-----------|----------------|
| **Agent-native** | All operations through Python API — no browser, no DOM, no Playwright |
| **Structured errors** | All returns are `{ok, data}` or `{ok, error: {code, message}}` |
| **Metric versioning** | `create_version` produces new hash; old version preserved in `.versions/` |
| **Dataset versioning** | Content-addressed; immutable history |
| **Provenance** | Every run has a `manifest.json` with `manifest_hash` linking all inputs |
| **Idempotency** | `create_version` with same content returns `is_new: false` |
| **Comparability** | Two runs compared via `RunStore.compare()` → `score_delta`, `field_diffs`, `dataset_check` |
| **Root-cause analysis** | `eval_diff` explains *why* scores changed |

## APIs Used

| Step | API | Method |
|------|-----|--------|
| 1 | `DatasetStore` | `create(dataset_id, name, cases)` |
| 2 | `MetricStore` | `create(metric_dict)` |
| 3 | Direct file write | `canvas.json` |
| 4 | `generate_skill` | `generate_skill(spec)` → `SkillPackage` |
| 5 | Simulated | Generates `eval_report.json` |
| 6 | `RunStore` | `submit(report, manifest)` |
| 7 | `RunStore` | `get(run_id)` |
| 8 | `MetricStore` | `create_version(metric_id, new_dict)` + `diff_versions(...)` |
| 9 | Simulated | Generates `eval_report_2.json` |
| 10 | `RunStore` | `submit(report, manifest)` |
| 11 | `RunStore` | `compare(run_a, run_b)` |
| 12 | `RunStore` | `list()` |

## Output Structure

```
{temp_dir}/
├── metrics/
│   ├── llm/accuracy.json
│   ├── llm/.versions/accuracy/{hash}.json
│   ├── non_llm/json_schema.json
│   └── non_llm/.versions/json_schema/{hash}.json
├── datasets/
│   └── qa_basics/
│       ├── dataset.json
│       ├── test_cases.json
│       └── .versions/{hash}.json
├── runs/
│   ├── run_YYYYMMDD_001/
│   │   ├── manifest.json     ← full provenance
│   │   ├── results.json      ← enriched report
│   │   ├── meta.json         ← quick summary
│   │   ├── config.json
│   │   └── dataset_ref.json
│   └── run_YYYYMMDD_002/
│       └── ...
├── projects/demo_eval/canvas.json
├── skill_output/
│   ├── SKILL.md
│   ├── eval_script.py
│   ├── test_cases_template.json
│   ├── requirements.txt
│   └── manifest.json
├── eval_report.json
└── eval_report_2.json
```

## Real Execution (Step 5)

The demo simulates evaluation execution to avoid requiring `deepeval` and `openai` dependencies. To run a real evaluation:

```bash
cd skill_output
pip install -r requirements.txt
python eval_script.py
# → produces eval_report.json
```

Then submit the real report:
```bash
python scripts/run_store.py submit \
  --report skill_output/eval_report.json \
  --manifest skill_output/manifest.json
```

## Step 8: Why Versioning Matters

The demo makes a concrete change: accuracy threshold from `0.7` to `0.8`. This creates a new metric version with a different hash. The second run's manifest references the new version hash. The old version is preserved in `.versions/`.

This means:
- You can always look up the exact metric definition used in any run
- You can diff the two versions to see what changed
- The score delta between runs is attributable to the metric change (since dataset, model, skill stayed the same)

## Cleanup

```bash
# The temp directory path is printed at the start of the script
rm -rf /tmp/evalforge_workflow_*
```

## Related Documentation

- [Architecture](../docs/architecture.md) — system design and component map
- [Concepts](../docs/concepts.md) — why versioning, why Agent-native, how provenance works
- [Metric Schema](../METRIC_SCHEMA.md) — the JSON contract for metrics
- [Report Schema](../REPORT_SCHEMA.md) — the JSON contract for reports