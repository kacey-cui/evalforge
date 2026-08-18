#!/usr/bin/env python3
"""Agent-style EvalForge workflow: 从零开始的完整评测流程。

Usage:
    python3 examples/agent_workflow/run_workflow.py

每一步都打印清晰的结果摘要。不依赖 GUI，不修改任何已有文件。
"""

import json, sys, textwrap, tempfile, shutil
from datetime import datetime, timezone
from pathlib import Path

# ── 路径设置 ──────────────────────────────────────────────────────────────────
REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from metric_store import MetricStore
from dataset_store import DatasetStore
from generate_skill import (
    SkillSpec, ModelConfig, FieldPipeline, MetricInstance,
    generate_skill,
)
from run_manifest import (
    compute_manifest_hash, Manifest, DatasetRef, MetricRef,
    MetricInstance as ManMetricInstance, SkillRef, ModelRef, EnvironmentInfo,
)
from run_store import RunStore

# ── 初始化 ────────────────────────────────────────────────────────────────────
def _section(title):
    print(f"\n{'='*70}")
    print(f"  {title}")
    print(f"{'='*70}")

# 使用 temp 目录存放所有产物
WORK_DIR = Path(tempfile.mkdtemp(prefix="evalforge_workflow_"))
METRICS_DIR = WORK_DIR / "metrics"
DATASETS_DIR = WORK_DIR / "datasets"
RUNS_DIR = WORK_DIR / "runs"
PROJECTS_DIR = WORK_DIR / "projects"

for d in [METRICS_DIR, DATASETS_DIR, RUNS_DIR, PROJECTS_DIR]:
    d.mkdir(parents=True, exist_ok=True)

ms = MetricStore(base_dir=METRICS_DIR)
ds = DatasetStore(base_dir=DATASETS_DIR)
rs = RunStore(runs_dir=RUNS_DIR)

PROJECT_NAME = "demo_eval"
PROJECT_DIR = PROJECTS_DIR / PROJECT_NAME
PROJECT_DIR.mkdir(parents=True, exist_ok=True)

print(f"Work directory: {WORK_DIR}")

# ═══════════════════════════════════════════════════════════════════════════════
# Step 1: Create Dataset
# ═══════════════════════════════════════════════════════════════════════════════
_section("Step 1: Create Dataset")

SAMPLE_CASES = [
    {"input": "What is the capital of France?",                    "expected_output": "Paris"},
    {"input": "How many continents are there?",                     "expected_output": "7"},
    {"input": "What is the boiling point of water in Celsius?",     "expected_output": "100"},
    {"input": "Who wrote Romeo and Juliet?",                        "expected_output": "William Shakespeare"},
    {"input": "What is the chemical symbol for gold?",              "expected_output": "Au"},
    {"input": "What year did World War II end?",                    "expected_output": "1945"},
    {"input": "What is the largest planet in our solar system?",    "expected_output": "Jupiter"},
    {"input": "What is the speed of light in km/s?",                "expected_output": "300000"},
    {"input": "Who painted the Mona Lisa?",                         "expected_output": "Leonardo da Vinci"},
    {"input": "What is the square root of 144?",                    "expected_output": "12"},
]

result = ds.create("qa_basics", "Basic Q&A Dataset", SAMPLE_CASES, description="10 basic knowledge questions")
assert result["ok"], f"Dataset creation failed: {result.get('error')}"
print(f"  dataset_id:  {result['data']['dataset_id']}")
print(f"  n_cases:     {result['data']['n_cases']}")
print(f"  version_hash: {result['data']['version_hash'][:16]}...")
print(f"  content_hash: {result['data']['content_hash'][:16]}...")

DATASET_ID = result["data"]["dataset_id"]
DATASET_VERSION = result["data"]["version_hash"]
DATASET_CONTENT = result["data"]["content_hash"]

# ═══════════════════════════════════════════════════════════════════════════════
# Step 2: Create Metrics
# ═══════════════════════════════════════════════════════════════════════════════
_section("Step 2: Create Metrics")

ACCURACY_METRIC = {
    "id": "accuracy",
    "name": "准确度 (GEval)",
    "category": "llm",
    "description": "用 LLM 评估回答是否准确",
    "params": [
        {"key": "threshold", "label": "通过阈值", "type": "number", "default": 0.7, "min": 0, "max": 1, "step": 0.1}
    ],
    "criteria": "评估回答是否准确：对比 expected_output 和 actual_output，判断 factual correctness",
    "requires": ["actual_output", "expected_output"],
    "code_template": (
        'GEval(\n'
        '    name="Accuracy",\n'
        '    criteria="{{criteria}}",\n'
        '    evaluation_params=[LLMTestCaseParams.EXPECTED_OUTPUT, LLMTestCaseParams.ACTUAL_OUTPUT],\n'
        '    threshold={{threshold}},\n'
        '    model=JUDGE_MODEL,\n'
        ')'
    ),
}

JSON_SCHEMA_METRIC = {
    "id": "json_schema",
    "name": "JSON Schema 校验",
    "category": "non_llm",
    "description": "检查 actual_output 是否为合法 JSON",
    "params": [
        {"key": "schema", "label": "JSON Schema", "type": "json", "default": "{}", "required": False}
    ],
    "criteria": None,
    "requires": ["actual_output"],
    "code_template": (
        "class JsonSchemaMetric(BaseMetric):\n"
        "    def __init__(self, schema={{schema}}):\n"
        "        self.schema = schema\n"
        "        super().__init__()\n"
        "    def measure(self, test_case):\n"
        "        import json\n"
        "        try:\n"
        "            json.loads(test_case.actual_output or '')\n"
        "            self.score = 1.0\n"
        "            self.success = True\n"
        "        except:\n"
        "            self.score = 0.0\n"
        "            self.success = False\n"
        "    async def a_measure(self, test_case):\n"
        "        return self.measure(test_case)\n"
        "    def is_successful(self):\n"
        "        return self.success\n"
        "    @property\n"
        "    def __name__(self):\n"
        "        return 'JsonSchemaMetric'\n"
    ),
}

r1 = ms.create(ACCURACY_METRIC)
assert r1["ok"], f"Metric creation failed: {r1.get('error')}"
print(f"  [accuracy]    version_hash: {r1['data']['version_hash'][:16]}...")

r2 = ms.create(JSON_SCHEMA_METRIC)
assert r2["ok"], f"Metric creation failed: {r2.get('error')}"
print(f"  [json_schema] version_hash: {r2['data']['version_hash'][:16]}...")

ACCURACY_VERSION = r1["data"]["version_hash"]
JSON_SCHEMA_VERSION = r2["data"]["version_hash"]

# ═══════════════════════════════════════════════════════════════════════════════
# Step 3: Create Evaluation Configuration (canvas.json)
# ═══════════════════════════════════════════════════════════════════════════════
_section("Step 3: Create Evaluation Configuration")

CANVAS = {
    "skillName": "demo_eval",
    "description": "Demo evaluation for basic Q&A",
    "modelId": "mock-model-v1",
    "modelBaseUrl": "https://mock-api.example.com/v1",
    "judgeModelId": "mock-judge-v1",
    "judgeModelBaseUrl": "https://mock-api.example.com/v1",
    "canvasFields": [
        {
            "name": "qa_accuracy",
            "gatePipeline": [
                {"metricId": "json_schema", "params": {"schema": "{}"}},
            ],
            "scorePipeline": [
                {"metricId": "accuracy", "params": {"threshold": 0.7}, "weight": 1.0, "strictness": 1.0},
            ],
        }
    ],
    "metricVersions": {
        "accuracy": ACCURACY_VERSION,
        "json_schema": JSON_SCHEMA_VERSION,
    },
    "dataset": {
        "dataset_id": DATASET_ID,
        "version_hash": DATASET_VERSION,
        "content_hash": DATASET_CONTENT,
        "n_cases": len(SAMPLE_CASES),
    },
    "template": "deepeval",
}

canvas_path = PROJECT_DIR / "canvas.json"
canvas_path.write_text(json.dumps(CANVAS, ensure_ascii=False, indent=2), "utf-8")
print(f"  canvas.json written to: {canvas_path}")
print(f"  fields: 1 (qa_accuracy)")
print(f"  metrics: accuracy, json_schema")

# ═══════════════════════════════════════════════════════════════════════════════
# Step 4: Generate Skill
# ═══════════════════════════════════════════════════════════════════════════════
_section("Step 4: Generate Skill")

# Load metric definitions from the store
acc_def = ms.get("accuracy")["data"]
js_def = ms.get("json_schema")["data"]
metric_defs = {"accuracy": acc_def, "json_schema": js_def}

spec = SkillSpec(
    skill_name="demo_eval",
    description="Demo evaluation for basic Q&A",
    model=ModelConfig(model_id="mock-model-v1", base_url="https://mock-api.example.com/v1"),
    fields=[
        FieldPipeline(
            name="qa_accuracy",
            gate_pipeline=[
                MetricInstance(metric_id="json_schema", params={"schema": "{}"}, zone="gate"),
            ],
            score_pipeline=[
                MetricInstance(metric_id="accuracy", params={"threshold": 0.7}, zone="score", weight=1.0),
            ],
        ),
    ],
    metric_versions={"accuracy": ACCURACY_VERSION, "json_schema": JSON_SCHEMA_VERSION},
    template="deepeval",
)

skill_dir = WORK_DIR / "skill_output"
skill_dir.mkdir(parents=True, exist_ok=True)
package = generate_skill(spec, metric_defs=metric_defs, output_dir=skill_dir)

print(f"  skill_hash: {package.skill_hash[:16]}...")
print(f"  output:     {skill_dir}")
for name in sorted(package.files.keys()):
    print(f"    {name}")

# ═══════════════════════════════════════════════════════════════════════════════
# Step 5: Execute Skill (Simulated)
# ═══════════════════════════════════════════════════════════════════════════════
_section("Step 5: Execute Skill (Simulated)")

# In a real scenario, the agent would run:
#   cd skill_output && python eval_script.py
# This requires deepeval to be installed. For demo purposes, we simulate the
# execution by generating a valid eval_report.json that matches the expected schema.

SIMULATED_OUTPUTS = [
    "Paris", "7", "100", "William Shakespeare", "Au",
    "1945", "Jupiter", "300000", "Leonardo da Vinci", "12",
]

cases = []
for i, (case, expected) in enumerate(zip(SAMPLE_CASES, SIMULATED_OUTPUTS)):
    is_correct = case["expected_output"] == expected
    cases.append({
        "case_id": i,
        "input": case["input"],
        "actual_output": expected,
        "expected_output": case["expected_output"],
        "metrics": {
            "json_schema": {"score": 1.0, "success": True},
            "accuracy": {
                "score": 1.0 if is_correct else 0.0,
                "success": is_correct,
                "reason": "Correct" if is_correct else "Mismatch",
            },
        },
    })

n_passed = sum(1 for c in cases if all(
    m.get("success", False) for m in c["metrics"].values()
))
pass_rate = n_passed / len(cases) if cases else 0.0
overall_score = sum(
    c["metrics"]["accuracy"]["score"] for c in cases
) / len(cases) if cases else 0.0

report = {
    "skill": "demo_eval",
    "created_at": datetime.now(timezone.utc).isoformat(),
    "n_cases": len(cases),
    "n_passed": n_passed,
    "pass_rate": round(pass_rate, 4),
    "overall_score": round(overall_score, 4),
    "grade": "A" if pass_rate >= 0.9 else ("B" if pass_rate >= 0.7 else "C"),
    "fields": {
        "qa_accuracy": {
            "field_score": round(overall_score, 4),
            "n_passed": n_passed,
            "n_total": len(cases),
        }
    },
    "cases": cases,
    "bad_cases": [c for c in cases if not all(
        m.get("success", False) for m in c["metrics"].values()
    )],
    "config": {
        "metrics": [
            {"name": "JSON Schema 校验", "metricId": "json_schema"},
            {"name": "准确度 (GEval)", "metricId": "accuracy"},
        ],
        "model": {"modelId": "mock-model-v1"},
    },
}

report_path = WORK_DIR / "eval_report.json"
report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), "utf-8")
print(f"  n_cases:       {report['n_cases']}")
print(f"  n_passed:      {report['n_passed']}")
print(f"  pass_rate:     {report['pass_rate']}")
print(f"  overall_score: {report['overall_score']}")
print(f"  grade:         {report['grade']}")
print(f"  report saved:  {report_path}")

# ═══════════════════════════════════════════════════════════════════════════════
# Step 6: Submit Report
# ═══════════════════════════════════════════════════════════════════════════════
_section("Step 6: Submit Report")

# Build manifest (replicating what record_run.py does)
import platform as _platform

env = EnvironmentInfo(
    python_version=sys.version.split()[0],
    platform=_platform.platform(),
    dependencies={"deepeval": "1.0.0", "openai": "1.0.0"},
)

# Pre-generate run_id so it passes manifest validation
from run_store import _generate_run_id
temp_run_id = _generate_run_id(RUNS_DIR)

manifest_dict = {
    "manifest_version": "1.0",
    "run_id": temp_run_id,
    "created_at": datetime.now(timezone.utc).isoformat(),
    "triggered_by": "agent",
    "dataset": {
        "dataset_id": DATASET_ID,
        "version_hash": DATASET_VERSION,
        "content_hash": DATASET_CONTENT,
        "n_cases": len(SAMPLE_CASES),
        "source_path": str(DATASETS_DIR / DATASET_ID / "test_cases.json"),
    },
    "metrics": [
        {"metric_id": "json_schema", "version_hash": JSON_SCHEMA_VERSION, "instance": {"zone": "gate"}},
        {"metric_id": "accuracy", "version_hash": ACCURACY_VERSION, "instance": {"zone": "score", "weight": 1.0}},
    ],
    "skill": {"name": "demo_eval", "content_hash": package.skill_hash},
    "model": {"model_id": "mock-model-v1", "base_url": "https://mock-api.example.com/v1"},
    "judge_model": {"model_id": "mock-judge-v1", "base_url": "https://mock-api.example.com/v1"},
    "environment": {
        "python_version": env.python_version,
        "platform": env.platform,
        "dependencies": env.dependencies,
    },
    "extra": {},
}

manifest_dict["manifest_hash"] = compute_manifest_hash(manifest_dict)

result = rs.submit(report, manifest_dict, triggered_by="agent")
assert result["ok"], f"Submit failed: {result.get('error')}"

RUN_ID_1 = result["data"]["run_id"]
print(f"  run_id:         {RUN_ID_1}")
print(f"  manifest_hash:  {result['data']['manifest_hash'][:16]}...")
print(f"  overall_score:  {result['data']['overall_score']}")
print(f"  status:         {result['data']['status']}")

# ═══════════════════════════════════════════════════════════════════════════════
# Step 7: View Report
# ═══════════════════════════════════════════════════════════════════════════════
_section("Step 7: View Report")

result = rs.get(RUN_ID_1)
assert result["ok"], f"Get failed: {result.get('error')}"

data = result["data"]
meta = data["meta"]
print(f"  run_id:         {meta['run_id']}")
print(f"  project:        {meta['project']}")
print(f"  overall_score:  {meta['overall_score']}")
print(f"  pass_rate:      {meta['pass_rate']}")
print(f"  fields:         {json.dumps(meta['fields'], ensure_ascii=False)}")
print(f"  metrics:        {meta['metrics']}")

# ═══════════════════════════════════════════════════════════════════════════════
# Step 8: Modify Metric — Create New Version
# ═══════════════════════════════════════════════════════════════════════════════
_section("Step 8: Modify Metric — Create New Version")

# Change accuracy threshold from 0.7 to 0.8
new_accuracy = dict(ACCURACY_METRIC)
new_accuracy["params"] = [
    {"key": "threshold", "label": "通过阈值", "type": "number", "default": 0.8, "min": 0, "max": 1, "step": 0.1}
]
new_accuracy["criteria"] = "评估回答是否准确：对比 expected_output 和 actual_output，判断 factual correctness。严格要求。"

result = ms.create_version("accuracy", new_accuracy)
assert result["ok"], f"Create version failed: {result.get('error')}"

NEW_ACCURACY_VERSION = result["data"]["version_hash"]
print(f"  old version_hash: {ACCURACY_VERSION[:16]}...")
print(f"  new version_hash: {NEW_ACCURACY_VERSION[:16]}...")
print(f"  is_new:           {result['data']['is_new']}")

# Show diff
diff = ms.diff_versions("accuracy", ACCURACY_VERSION, NEW_ACCURACY_VERSION)
assert diff["ok"], f"Diff failed: {diff.get('error')}"
print(f"  diff: {json.dumps(diff['data'], ensure_ascii=False, indent=2)[:300]}")

# ═══════════════════════════════════════════════════════════════════════════════
# Step 9: Execute Again (Simulated with stricter threshold)
# ═══════════════════════════════════════════════════════════════════════════════
_section("Step 9: Execute Again (Stricter Threshold)")

# Simulate with the same outputs but stricter threshold: some previously passing
# cases now fail because threshold is 0.8 instead of 0.7
# For demo, we use the same scores but the interpretation changes
SIMULATED_OUTPUTS_2 = [
    "Paris", "7", "100", "William Shakespeare", "Au",
    "1945", "Jupiter", "300000", "Leonardo da Vinci", "wrong answer",
]

cases2 = []
for i, (case, expected) in enumerate(zip(SAMPLE_CASES, SIMULATED_OUTPUTS_2)):
    is_correct = case["expected_output"] == expected
    score = 1.0 if is_correct else 0.0
    success = score >= 0.8  # stricter threshold
    cases2.append({
        "case_id": i,
        "input": case["input"],
        "actual_output": expected,
        "expected_output": case["expected_output"],
        "metrics": {
            "json_schema": {"score": 1.0, "success": True},
            "accuracy": {
                "score": score,
                "success": success,
                "reason": "Correct" if is_correct else "Mismatch",
            },
        },
    })

n_passed2 = sum(1 for c in cases2 if all(
    m.get("success", False) for m in c["metrics"].values()
))
pass_rate2 = n_passed2 / len(cases2) if cases2 else 0.0
overall_score2 = sum(
    c["metrics"]["accuracy"]["score"] for c in cases2
) / len(cases2) if cases2 else 0.0

report2 = {
    "skill": "demo_eval",
    "created_at": datetime.now(timezone.utc).isoformat(),
    "n_cases": len(cases2),
    "n_passed": n_passed2,
    "pass_rate": round(pass_rate2, 4),
    "overall_score": round(overall_score2, 4),
    "grade": "A" if pass_rate2 >= 0.9 else ("B" if pass_rate2 >= 0.7 else "C"),
    "fields": {
        "qa_accuracy": {
            "field_score": round(overall_score2, 4),
            "n_passed": n_passed2,
            "n_total": len(cases2),
        }
    },
    "cases": cases2,
    "bad_cases": [c for c in cases2 if not all(
        m.get("success", False) for m in c["metrics"].values()
    )],
    "config": {
        "metrics": [
            {"name": "JSON Schema 校验", "metricId": "json_schema"},
            {"name": "准确度 (GEval)", "metricId": "accuracy"},
        ],
        "model": {"modelId": "mock-model-v1"},
    },
}

report_path2 = WORK_DIR / "eval_report_2.json"
report_path2.write_text(json.dumps(report2, ensure_ascii=False, indent=2), "utf-8")
print(f"  n_cases:       {report2['n_cases']}")
print(f"  n_passed:      {report2['n_passed']}")
print(f"  pass_rate:     {report2['pass_rate']}")
print(f"  overall_score: {report2['overall_score']}")
print(f"  grade:         {report2['grade']}")
print(f"  (1 case changed to wrong answer → stricter threshold exposes it)")

# ═══════════════════════════════════════════════════════════════════════════════
# Step 10: Submit Second Report
# ═══════════════════════════════════════════════════════════════════════════════
_section("Step 10: Submit Second Report")

manifest_dict2 = dict(manifest_dict)
temp_run_id2 = _generate_run_id(RUNS_DIR)
manifest_dict2["run_id"] = temp_run_id2
manifest_dict2["created_at"] = datetime.now(timezone.utc).isoformat()
manifest_dict2["metrics"] = [
    {"metric_id": "json_schema", "version_hash": JSON_SCHEMA_VERSION, "instance": {"zone": "gate"}},
    {"metric_id": "accuracy", "version_hash": NEW_ACCURACY_VERSION, "instance": {"zone": "score", "weight": 1.0}},
]
manifest_dict2["manifest_hash"] = compute_manifest_hash(manifest_dict2)

result = rs.submit(report2, manifest_dict2, triggered_by="agent")
assert result["ok"], f"Submit failed: {result.get('error')}"

RUN_ID_2 = result["data"]["run_id"]
print(f"  run_id:         {RUN_ID_2}")
print(f"  overall_score:  {result['data']['overall_score']}")

# ═══════════════════════════════════════════════════════════════════════════════
# Step 11: Compare Reports
# ═══════════════════════════════════════════════════════════════════════════════
_section("Step 11: Compare Reports")

result = rs.compare(RUN_ID_1, RUN_ID_2)
assert result["ok"], f"Compare failed: {result.get('error')}"

comp = result["data"]
print(f"  Run 1 score: {meta['overall_score']}")
print(f"  Run 2 score: {comp.get('run_b_score', report2['overall_score'])}")
print(f"  score_delta: {comp.get('score_delta', 'N/A')}")

if comp.get("dataset_check"):
    ds_check = comp["dataset_check"]
    print(f"  dataset:     {'same' if ds_check.get('same') else 'different'}")

if comp.get("field_diffs"):
    print(f"  field_diffs: {json.dumps(comp['field_diffs'], ensure_ascii=False)[:200]}")

# ═══════════════════════════════════════════════════════════════════════════════
# Step 12: List All Runs
# ═══════════════════════════════════════════════════════════════════════════════
_section("Step 12: List All Runs")

result = rs.list()
assert result["ok"], f"List failed: {result.get('error')}"

print(f"  Total runs: {len(result['data'])}")
for run in result["data"]:
    print(f"    {run['run_id']}  score={run.get('overall_score', 'N/A')}  status={run.get('status', 'N/A')}")

# ═══════════════════════════════════════════════════════════════════════════════
# Done
# ═══════════════════════════════════════════════════════════════════════════════
_section("Workflow Complete")

print(f"""
All artifacts saved to: {WORK_DIR}

Directory structure:
  metrics/          — Metric definitions + versions
  datasets/         — Dataset with test cases + versions
  runs/             — Two submitted runs
  projects/         — Project canvas.json
  skill_output/     — Generated Skill package
  eval_report.json  — First evaluation report
  eval_report_2.json— Second evaluation report

To clean up:
  rm -rf {WORK_DIR}
""")