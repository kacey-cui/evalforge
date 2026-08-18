"""Skill Generation — 从 SkillSpec 生成 Skill 目录（Python 模块）。

将 index.html 的 generateSkillCode() / generateFieldEvalCode() / downloadSkillZip()
逻辑移植到 Python，供 Agent/CLI/GUI 统一调用。

Usage:
    # Python API
    from scripts.generate_skill import generate_skill, SkillSpec, ModelConfig, FieldPipeline, MetricInstance

    spec = SkillSpec(
        skill_name="my_eval",
        model=ModelConfig(model_id="your-model-id", base_url="https://..."),
        fields=[...],
    )
    package = generate_skill(spec)

    # CLI
    python scripts/generate_skill.py --project my_project --output ./output/
    python scripts/generate_skill.py --spec skill_spec.json --output ./output/
    python scripts/generate_skill.py --project my_project --output ./my_skill.zip
"""

import argparse
import hashlib
import json
import os
import re
import sys
import tempfile
import zipfile
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

REPO_ROOT = Path(__file__).resolve().parent.parent
TEMPLATES_DIR = REPO_ROOT / "templates" / "skill"
GENERATOR_VERSION = "1.0"

# Add scripts/ to path for mini_json_schema import
sys.path.insert(0, str(Path(__file__).resolve().parent))
from mini_json_schema import validate as _js_validate

SKILL_MANIFEST_SCHEMA = {
    "type": "object",
    "required": ["skill_name", "generated_at", "generator_version", "template", "model", "metric_versions", "fields"],
    "properties": {
        "skill_name": {"type": "string", "minLength": 1},
        "generated_at": {"type": "string", "minLength": 1},
        "generator_version": {"type": "string", "minLength": 1},
        "template": {"type": "string", "enum": ["deepeval", "custom"]},
        "model": {
            "type": "object",
            "required": ["model_id"],
            "properties": {
                "model_id": {"type": "string", "minLength": 1},
                "base_url": {"type": "string"},
            },
        },
        "metric_versions": {"type": "object"},
        "fields": {"type": "array"},
    },
}


# ═══════════════════════════════════════════════════════════════════════════════
# Data Models
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class ModelConfig:
    """被测模型配置。"""
    model_id: str
    base_url: str = ""
    api_key_env: str = "MODEL_API_KEY"

    @classmethod
    def from_dict(cls, d: dict) -> "ModelConfig":
        if not isinstance(d, dict):
            return cls(model_id=str(d))
        return cls(
            model_id=d.get("model_id", ""),
            base_url=d.get("base_url", ""),
            api_key_env=d.get("api_key_env", "MODEL_API_KEY"),
        )


@dataclass
class JudgeModelConfig:
    """Judge 模型配置。"""
    model_id: str
    base_url: str = ""
    api_key_env: str = "MODEL_API_KEY"

    @classmethod
    def from_dict(cls, d: dict) -> "JudgeModelConfig":
        if not isinstance(d, dict):
            return cls(model_id=str(d))
        return cls(
            model_id=d.get("model_id", ""),
            base_url=d.get("base_url", ""),
            api_key_env=d.get("api_key_env", "MODEL_API_KEY"),
        )


@dataclass
class MetricInstance:
    """评测管线中的单个 metric 实例。"""
    metric_id: str
    version_hash: str = ""
    params: dict = field(default_factory=dict)
    weight: float = 0.3
    strictness: float = 1.0
    zone: str = "score"  # "gate" | "score"

    @classmethod
    def from_dict(cls, d: dict) -> "MetricInstance":
        return cls(
            metric_id=d.get("metric_id", d.get("metricId", "")),
            version_hash=d.get("version_hash", ""),
            params=d.get("params", {}),
            weight=float(d.get("weight", 0.3)),
            strictness=float(d.get("strictness", 1.0)),
            zone=d.get("zone", "score"),
        )


@dataclass
class FieldPipeline:
    """单个字段的评测管线（门禁 + 打分）。"""
    name: str
    gate_pipeline: list = field(default_factory=list)   # list[MetricInstance]
    score_pipeline: list = field(default_factory=list)  # list[MetricInstance]

    @classmethod
    def from_dict(cls, d: dict) -> "FieldPipeline":
        return cls(
            name=d.get("name", ""),
            gate_pipeline=[MetricInstance.from_dict(m) for m in (d.get("gate_pipeline", d.get("gatePipeline", [])) or [])],
            score_pipeline=[MetricInstance.from_dict(m) for m in (d.get("score_pipeline", d.get("scorePipeline", [])) or [])],
        )


@dataclass
class DatasetRefInfo:
    """Dataset 引用信息。"""
    dataset_id: str = ""
    version_hash: str = ""
    content_hash: str = ""
    n_cases: int = 0

    @classmethod
    def from_dict(cls, d: dict) -> "DatasetRefInfo":
        if not isinstance(d, dict):
            return cls()
        return cls(
            dataset_id=d.get("dataset_id", ""),
            version_hash=d.get("version_hash", ""),
            content_hash=d.get("content_hash", ""),
            n_cases=int(d.get("n_cases", 0)),
        )


@dataclass
class SkillSpec:
    """生成 Skill 的完整输入规范。"""
    skill_name: str
    description: str = ""
    model: ModelConfig = field(default_factory=lambda: ModelConfig(model_id=""))
    judge_model: Optional[JudgeModelConfig] = None
    fields: list = field(default_factory=list)  # list[FieldPipeline]
    dataset_ref: Optional[DatasetRefInfo] = None
    metric_versions: dict = field(default_factory=dict)  # metric_id -> version_hash
    template: str = "deepeval"
    extra_files: dict = field(default_factory=dict)

    @classmethod
    def from_dict(cls, d: dict) -> "SkillSpec":
        """从 JSON 字典构建 SkillSpec。"""
        model = ModelConfig.from_dict(d.get("model", {}))
        judge_model = None
        if d.get("judge_model"):
            judge_model = JudgeModelConfig.from_dict(d["judge_model"])
        fields = [FieldPipeline.from_dict(f) for f in (d.get("fields", []) or [])]
        dataset_ref = None
        if d.get("dataset_ref"):
            dataset_ref = DatasetRefInfo.from_dict(d["dataset_ref"])
        return cls(
            skill_name=d.get("skill_name", d.get("skillName", "")),
            description=d.get("description", ""),
            model=model,
            judge_model=judge_model,
            fields=fields,
            dataset_ref=dataset_ref,
            metric_versions=d.get("metric_versions", d.get("metricVersions", {})),
            template=d.get("template", "deepeval"),
            extra_files=d.get("extra_files", d.get("extraFiles", {})),
        )


@dataclass
class SkillPackage:
    """生成的 Skill 输出包。"""
    path: Path            # 输出目录路径
    files: dict           # {"SKILL.md": content, "eval_script.py": content, ...}
    manifest: dict        # manifest dict
    skill_hash: str       # SHA256 of manifest


# ═══════════════════════════════════════════════════════════════════════════════
# Value Formatting Helpers
# ═══════════════════════════════════════════════════════════════════════════════

def _format_python_value(val, param_type: str = "string") -> str:
    """Format a value as a Python code literal (ported from JS formatCodeValue).

    Args:
        val: The value to format.
        param_type: One of "json", "string", "boolean", "number".

    Returns:
        Python code literal string.
    """
    if param_type == "json":
        if isinstance(val, str):
            try:
                return json.dumps(json.loads(val), separators=(",", ":"))
            except (json.JSONDecodeError, TypeError):
                return json.dumps(val, separators=(",", ":"))
        return json.dumps(val, separators=(",", ":"))
    if param_type == "string":
        return json.dumps(str(val))
    if param_type == "boolean":
        return "True" if val else "False"
    if param_type == "number":
        s = str(val)
        if "." in s:
            return str(float(val))
        return str(int(val))
    return str(val)


def _extract_class_name(code_template: str) -> str:
    """Extract the class name from a Python class definition code template.

    Args:
        code_template: Python code containing a class definition.

    Returns:
        The class name, or 'UnknownMetric' if not found.
    """
    m = re.search(r'class\s+(\w+)\s*\(', code_template)
    return m.group(1) if m else "UnknownMetric"


# ═══════════════════════════════════════════════════════════════════════════════
# Metric Definition Loading
# ═══════════════════════════════════════════════════════════════════════════════

def _load_metric_defs(metric_versions: dict, metric_defs: dict = None) -> dict:
    """Load metric definitions, optionally from MetricStore.

    If metric_defs is provided, use it directly. Otherwise, try to import
    MetricStore from metric_store.py and fetch definitions for each metric_id.

    Args:
        metric_versions: dict of metric_id -> version_hash.
        metric_defs: Optional pre-loaded metric definitions dict.

    Returns:
        dict of metric_id -> metric definition dict.
    """
    if metric_defs is not None:
        return metric_defs

    # Try to use MetricStore from metric_store.py (being built in parallel)
    try:
        sys.path.insert(0, str(REPO_ROOT / "scripts"))
        from metric_store import MetricStore  # type: ignore
        store = MetricStore()
        result = {}
        for metric_id in metric_versions:
            resp = store.get(metric_id)
            if resp and resp.get("ok") and resp.get("data"):
                result[metric_id] = resp["data"]
        return result
    except ImportError:
        pass

    # Fallback: try loading from data/metrics/{llm,non_llm}/*.json
    result = {}
    metrics_base = REPO_ROOT / "data" / "metrics"
    for category in ("llm", "non_llm"):
        cat_dir = metrics_base / category
        if not cat_dir.is_dir():
            continue
        for f in sorted(cat_dir.glob("*.json")):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
            except Exception:
                continue
            if not isinstance(data, dict):
                continue
            mid = data.get("id") or data.get("metric_id")
            if mid and mid in metric_versions:
                result[mid] = data
    return result


# ═══════════════════════════════════════════════════════════════════════════════
# Code Generation (ported from index.html generateSkillCode())
# ═══════════════════════════════════════════════════════════════════════════════

def _generate_custom_metrics_code(fields: list, metric_defs: dict) -> str:
    """Generate all custom metric class definitions for the Custom Metrics section.

    Only non_llm metrics produce class definitions that go here.
    LLM metrics (GEval) are instantiated inline in the field eval code.

    Args:
        fields: list of FieldPipeline.
        metric_defs: dict of metric_id -> metric definition.

    Returns:
        Python code string of all custom metric class definitions.
    """
    custom_metrics = set()

    for field in fields:
        for item in (field.gate_pipeline or []) + (field.score_pipeline or []):
            # Handle both dict (from JSON) and MetricInstance
            if isinstance(item, dict):
                metric_id = item.get("metric_id", item.get("metricId", ""))
                params = item.get("params", {})
            else:
                metric_id = item.metric_id
                params = item.params

            metric = metric_defs.get(metric_id)
            if not metric:
                continue

            if metric.get("category") == "non_llm":
                # Non-LLM: the code_template is the full class definition
                code = metric.get("code_template", "")
                for p in metric.get("params", []):
                    key = p.get("key", "")
                    val = params.get(key, p.get("default"))
                    code = code.replace("{{" + key + "}}", _format_python_value(val, p.get("type", "string")))
                custom_metrics.add(code)

    return "\n\n".join(sorted(custom_metrics))


def _generate_field_eval_code(fields: list, metric_defs: dict) -> str:
    """Generate per-field evaluation code (gate + score) for each field.

    Ported from index.html generateFieldEvalCode().

    Args:
        fields: list of FieldPipeline.
        metric_defs: dict of metric_id -> metric definition.

    Returns:
        Python code string for the field evaluation loop.
    """
    field_blocks = []

    for field in fields:
        gate_parts = []
        score_parts = []
        weights = []
        strictness = []

        def _process_metric(item, zone: str):
            """Process a single metric instance, building gate/score code."""
            if isinstance(item, dict):
                metric_id = item.get("metric_id", item.get("metricId", ""))
                params = item.get("params", {})
            else:
                metric_id = item.metric_id
                params = item.params

            metric = metric_defs.get(metric_id)
            if not metric:
                return

            if metric.get("category") == "non_llm":
                # Non-LLM: extract class name, build constructor args
                code_template = metric.get("code_template", "")
                class_name = _extract_class_name(code_template)

                # Build constructor args
                args_parts = []
                for p in metric.get("params", []):
                    key = p.get("key", "")
                    val = params.get(key, p.get("default"))
                    args_parts.append(f"{key}={_format_python_value(val, p.get('type', 'string'))}")
                args = ", ".join(args_parts)

                if zone == "gate":
                    gate_parts.append(f"{class_name}({args})")
                else:
                    score_parts.append(f"{class_name}({args})")
            else:
                # LLM metric: use code_template directly (GEval instantiation)
                code = metric.get("code_template", "")
                code = code.replace("{{criteria}}", metric.get("criteria") or "")
                for p in metric.get("params", []):
                    key = p.get("key", "")
                    val = params.get(key, p.get("default"))
                    code = code.replace("{{" + key + "}}", _format_python_value(val, p.get("type", "string")))
                if zone == "gate":
                    gate_parts.append(code)
                else:
                    score_parts.append(code)

        # Process gate pipeline
        for item in (field.gate_pipeline or []):
            _process_metric(item, "gate")

        # Process score pipeline
        for item in (field.score_pipeline or []):
            _process_metric(item, "score")
            w = item.weight if isinstance(item, MetricInstance) else item.get("weight", 0.3)
            s = item.strictness if isinstance(item, MetricInstance) else item.get("strictness", 1.0)
            weights.append(w)
            strictness.append(s)

        field_name = field.name or "(全量)"

        # Build the gate+score code block for this field
        gate_code = ",\n                ".join(gate_parts)
        score_code = ",\n                ".join(score_parts)

        block = (
            f"        # ====== Field: {field_name} ======\n"
            f"        gate_metrics = [{gate_code}]\n"
            f"        for m in gate_metrics:\n"
            f"            evaluate([test_case], [m], run_async=False)\n"
            f"            if not m.is_successful():\n"
            f"                print(f\"  [GATE FAIL on '{field_name}'] {{m.__name__}}: score={{m.score:.3f}}\")\n"
            f"                return  # skip this case\n"
            f"        score_metrics = [{score_code}]\n"
            f"        if score_metrics:\n"
            f"            evaluate([test_case], score_metrics, run_async=False)\n"
            f"            weights = {json.dumps(weights)}\n"
            f"            strictness = {json.dumps(strictness)}\n"
            f"            weighted = 0; total_w = 0\n"
            f"            for i, m in enumerate(score_metrics):\n"
            f"                raw = m.score or 0.0\n"
            f"                adj = math.pow(raw, strictness[i] if i < len(strictness) else 1.0)\n"
            f"                w = weights[i] if i < len(weights) else 0.3\n"
            f"                weighted += adj * w; total_w += w\n"
            f"                print(f\"  [SCORE on '{field_name}'] {{m.__name__}}: raw={{raw:.3f}}, adj={{adj:.3f}}, w={{w}}\")\n"
            f"            final = round(weighted/total_w, 4) if total_w > 0 else 0.0\n"
            f"            print(f\"  => {field_name} final score: {{final}}\")"
        )
        field_blocks.append(block)

    return "\n\n".join(field_blocks)


def _generate_metric_list(fields: list, metric_defs: dict) -> str:
    """Generate the markdown metric list for SKILL.md.

    Args:
        fields: list of FieldPipeline.
        metric_defs: dict of metric_id -> metric definition.

    Returns:
        Markdown string listing all fields and their metrics.
    """
    parts = []
    for field in fields:
        name = field.name or "(全量)"

        gate_names = []
        for item in (field.gate_pipeline or []):
            mid = item.metric_id if isinstance(item, MetricInstance) else item.get("metric_id", item.get("metricId", ""))
            mdef = metric_defs.get(mid, {})
            gate_names.append(mdef.get("name", mid) if mdef else mid)

        score_names = []
        for item in (field.score_pipeline or []):
            mid = item.metric_id if isinstance(item, MetricInstance) else item.get("metric_id", item.get("metricId", ""))
            mdef = metric_defs.get(mid, {})
            score_names.append(mdef.get("name", mid) if mdef else mid)

        gate_str = ", ".join(gate_names) if gate_names else "无"
        score_str = ", ".join(score_names) if score_names else "无"
        parts.append(f"📌 {name}\n  门禁: {gate_str}\n  打分: {score_str}")

    return "\n\n".join(parts)


def _compute_metric_count(fields: list) -> int:
    """Count total metric instances across all fields.

    Args:
        fields: list of FieldPipeline.

    Returns:
        Total number of metric instances.
    """
    total = 0
    for field in fields:
        total += len(field.gate_pipeline or [])
        total += len(field.score_pipeline or [])
    return total


# ═══════════════════════════════════════════════════════════════════════════════
# Manifest Generation
# ═══════════════════════════════════════════════════════════════════════════════

def _compute_file_hash(content: str) -> str:
    """Compute SHA256 hash of file content.

    Args:
        content: File content string.

    Returns:
        Hex digest string.
    """
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _compute_skill_hash(manifest: dict) -> str:
    """Compute skill_hash from manifest (excluding dynamic fields).

    Excludes: skill_hash, file_hashes, generated_at (timestamp varies between runs).

    Canonicalization: sort_keys=True, ensure_ascii=False, no whitespace.

    Args:
        manifest: Complete manifest dict.

    Returns:
        SHA256 hex digest string.
    """
    d = deepcopy(manifest)
    # Remove dynamic fields that are not part of the semantic input
    d.pop("skill_hash", None)
    d.pop("file_hashes", None)
    d.pop("generated_at", None)
    canonical = json.dumps(d, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _generate_manifest(spec: SkillSpec, metric_defs: dict, file_hashes: dict) -> dict:
    """Generate manifest.json content.

    Args:
        spec: The SkillSpec input.
        metric_defs: dict of metric_id -> metric definition.
        file_hashes: dict of filename -> SHA256 hash.

    Returns:
        Manifest dict.
    """
    manifest = {
        "skill_name": spec.skill_name,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "generator_version": GENERATOR_VERSION,
        "template": spec.template,
        "model": {
            "model_id": spec.model.model_id,
            "base_url": spec.model.base_url,
        },
        "metric_versions": dict(spec.metric_versions),
        "fields": [],
        "file_hashes": dict(file_hashes),
    }

    if spec.judge_model:
        manifest["judge_model"] = {
            "model_id": spec.judge_model.model_id,
            "base_url": spec.judge_model.base_url,
        }

    if spec.dataset_ref:
        manifest["dataset"] = {
            "dataset_id": spec.dataset_ref.dataset_id,
            "version_hash": spec.dataset_ref.version_hash,
            "content_hash": spec.dataset_ref.content_hash,
        }

    for field in spec.fields:
        manifest["fields"].append({
            "name": field.name,
            "gate_count": len(field.gate_pipeline or []),
            "score_count": len(field.score_pipeline or []),
        })

    # Compute skill_hash last (after all other fields are set)
    manifest["skill_hash"] = _compute_skill_hash(manifest)

    # Validate manifest against SKILL_MANIFEST_SCHEMA
    manifest_errors = _js_validate(manifest, SKILL_MANIFEST_SCHEMA)
    if manifest_errors:
        raise ValueError(f"manifest schema 验证失败: {manifest_errors}")

    return manifest


# ═══════════════════════════════════════════════════════════════════════════════
# Template Rendering
# ═══════════════════════════════════════════════════════════════════════════════

def _load_template(name: str) -> str:
    """Load a template file from templates/skill/.

    Args:
        name: Template filename (e.g., "SKILL.md.tpl").

    Returns:
        Template content string.
    """
    path = TEMPLATES_DIR / name
    if path.exists():
        return path.read_text(encoding="utf-8")
    # Fallback for testing when templates dir doesn't exist
    raise FileNotFoundError(f"Template not found: {path}")


def _render_eval_script(spec: SkillSpec, custom_metrics_code: str, field_eval_code: str) -> str:
    """Render eval_script.py from template.

    Args:
        spec: The SkillSpec input.
        custom_metrics_code: Generated custom metric class definitions.
        field_eval_code: Generated field evaluation code.

    Returns:
        Rendered Python script string.
    """
    tpl = _load_template("eval_script.py.tpl")
    return (tpl
        .replace("{{skillName}}", spec.skill_name)
        .replace("{{modelBaseUrl}}", spec.model.base_url)
        .replace("{{modelId}}", spec.model.model_id)
        .replace("{{customMetricsCode}}", custom_metrics_code)
        .replace("{{fieldEvalCode}}", field_eval_code))


def _render_skill_md(spec: SkillSpec, metric_count: int, metric_list: str) -> str:
    """Render SKILL.md from template.

    Args:
        spec: The SkillSpec input.
        metric_count: Total number of metrics.
        metric_list: Markdown metric list.

    Returns:
        Rendered markdown string.
    """
    tpl = _load_template("SKILL.md.tpl")
    return (tpl
        .replace("{{skillName}}", spec.skill_name)
        .replace("{{metricCount}}", str(metric_count))
        .replace("{{metricList}}", metric_list))


def _generate_test_cases_template(spec: SkillSpec) -> str:
    """Generate test_cases_template.json content.

    If dataset_ref is provided, generates a minimal template referencing it.
    Otherwise, generates a default template with one example.

    Args:
        spec: The SkillSpec input.

    Returns:
        JSON string.
    """
    if spec.dataset_ref and spec.dataset_ref.dataset_id:
        template = [
            {
                "input": "示例问题",
                "actual_output": "模型输出",
                "expected_output": "期望输出",
                "_dataset_ref": {
                    "dataset_id": spec.dataset_ref.dataset_id,
                    "version_hash": spec.dataset_ref.version_hash,
                },
            }
        ]
    else:
        template = [
            {
                "input": "示例问题",
                "actual_output": "模型输出",
                "expected_output": "期望输出",
            }
        ]
    return json.dumps(template, ensure_ascii=False, indent=2) + "\n"


def _generate_requirements_txt(spec: SkillSpec) -> str:
    """Generate requirements.txt content.

    Args:
        spec: The SkillSpec input.

    Returns:
        Requirements string.
    """
    if spec.template == "deepeval":
        return "deepeval>=1.0.0\nopenai>=1.0.0\n"
    return "deepeval>=1.0.0\nopenai>=1.0.0\n"


# ═══════════════════════════════════════════════════════════════════════════════
# Core Function
# ═══════════════════════════════════════════════════════════════════════════════

def generate_skill(
    spec: SkillSpec,
    metric_defs: dict = None,
    output_dir: Path = None,
) -> SkillPackage:
    """Generate a complete Skill package from a SkillSpec.

    Args:
        spec: The SkillSpec describing the evaluation pipeline.
        metric_defs: Optional dict of metric_id -> metric definition.
            If not provided, attempts to load from MetricStore or data/metrics/.
        output_dir: Optional output directory. If not provided, a temp directory
            is created. If provided and doesn't exist, it is created.

    Returns:
        SkillPackage with path, files, manifest, and skill_hash.

    Raises:
        ValueError: If spec validation fails.
    """
    # ── 1. Validate spec ──────────────────────────────────────────────────
    if not spec.skill_name:
        raise ValueError("skill_name is required")
    if not spec.model.model_id:
        raise ValueError("model.model_id is required")

    # Collect all metric_ids referenced in the spec
    all_metric_ids = set()
    for field in spec.fields:
        for item in (field.gate_pipeline or []) + (field.score_pipeline or []):
            if isinstance(item, dict):
                mid = item.get("metric_id", item.get("metricId", ""))
            else:
                mid = item.metric_id
            if mid:
                all_metric_ids.add(mid)
            else:
                raise ValueError(f"MetricInstance missing metric_id in field '{field.name}'")

    # ── 2. Load metric definitions ────────────────────────────────────────
    metric_versions = spec.metric_versions or {}
    # Merge: include all metric_ids from fields, even if not in metric_versions
    for mid in all_metric_ids:
        if mid not in metric_versions:
            metric_versions[mid] = ""

    loaded_defs = _load_metric_defs(metric_versions, metric_defs)

    # Validate that all referenced metrics have definitions
    for mid in all_metric_ids:
        if mid not in loaded_defs:
            raise ValueError(f"Metric definition not found for '{mid}'")

    # ── 3. Generate code ──────────────────────────────────────────────────
    custom_metrics_code = _generate_custom_metrics_code(spec.fields, loaded_defs)
    field_eval_code = _generate_field_eval_code(spec.fields, loaded_defs)
    metric_list = _generate_metric_list(spec.fields, loaded_defs)
    metric_count = _compute_metric_count(spec.fields)

    # ── 4. Render templates ───────────────────────────────────────────────
    eval_script = _render_eval_script(spec, custom_metrics_code, field_eval_code)
    skill_md = _render_skill_md(spec, metric_count, metric_list)

    # ── 5. Generate auxiliary files ───────────────────────────────────────
    test_cases_template = _generate_test_cases_template(spec)
    requirements_txt = _generate_requirements_txt(spec)

    files = {
        "SKILL.md": skill_md,
        "eval_script.py": eval_script,
        "test_cases_template.json": test_cases_template,
        "requirements.txt": requirements_txt,
    }

    # Add extra files from spec
    for filename, content in (spec.extra_files or {}).items():
        files[filename] = content

    # ── 6. Compute file hashes ────────────────────────────────────────────
    file_hashes = {name: _compute_file_hash(content) for name, content in files.items()}

    # ── 7. Generate manifest ──────────────────────────────────────────────
    manifest = _generate_manifest(spec, loaded_defs, file_hashes)
    files["manifest.json"] = json.dumps(manifest, ensure_ascii=False, indent=2) + "\n"
    file_hashes["manifest.json"] = _compute_file_hash(files["manifest.json"])
    manifest["file_hashes"] = file_hashes

    # ── 8. Write to output directory ──────────────────────────────────────
    if output_dir is None:
        output_dir = Path(tempfile.mkdtemp(prefix="skill_"))
    else:
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

    for name, content in files.items():
        (output_dir / name).write_text(content, encoding="utf-8")

    # ── 9. Return SkillPackage ────────────────────────────────────────────
    return SkillPackage(
        path=output_dir,
        files=files,
        manifest=manifest,
        skill_hash=manifest["skill_hash"],
    )


# ═══════════════════════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════════════════════

def _build_spec_from_project(project_name: str) -> SkillSpec:
    """Build a SkillSpec from a project's canvas.json.

    Args:
        project_name: Project name (directory under data/projects/).

    Returns:
        SkillSpec instance.

    Raises:
        FileNotFoundError: If the project's canvas.json doesn't exist.
        ValueError: If the canvas.json is malformed.
    """
    canvas_path = REPO_ROOT / "data" / "projects" / project_name / "canvas.json"
    if not canvas_path.exists():
        raise FileNotFoundError(f"Project canvas not found: {canvas_path}")

    canvas = json.loads(canvas_path.read_text(encoding="utf-8"))

    # Extract top-level fields
    skill_name = canvas.get("skillName", project_name)
    model = ModelConfig(
        model_id=canvas.get("modelId", ""),
        base_url=canvas.get("modelBaseUrl", ""),
    )
    judge_model = None
    if canvas.get("judgeModelId"):
        judge_model = JudgeModelConfig(
            model_id=canvas.get("judgeModelId", ""),
            base_url=canvas.get("judgeModelBaseUrl", ""),
        )

    # Build fields from canvasFields
    fields = []
    canvas_fields = canvas.get("canvasFields", [])
    if isinstance(canvas_fields, dict):
        # canvasFields might be a dict keyed by field name
        canvas_fields = list(canvas_fields.values())
    for cf in (canvas_fields or []):
        if not isinstance(cf, dict):
            continue
        gate_pipeline = []
        for item in (cf.get("gatePipeline", []) or []):
            if isinstance(item, dict):
                gate_pipeline.append(MetricInstance(
                    metric_id=item.get("metricId", ""),
                    params=item.get("params", {}),
                    zone="gate",
                ))
        score_pipeline = []
        for item in (cf.get("scorePipeline", []) or []):
            if isinstance(item, dict):
                score_pipeline.append(MetricInstance(
                    metric_id=item.get("metricId", ""),
                    params=item.get("params", {}),
                    weight=float(item.get("weight", 0.3)),
                    strictness=float(item.get("strictness", 1.0)),
                    zone="score",
                ))
        fields.append(FieldPipeline(
            name=cf.get("name", ""),
            gate_pipeline=gate_pipeline,
            score_pipeline=score_pipeline,
        ))

    # Extract metric_versions
    metric_versions = {}
    canvas_metrics = canvas.get("metricVersions", canvas.get("metric_versions", {}))
    if isinstance(canvas_metrics, list):
        for mv in canvas_metrics:
            if isinstance(mv, dict):
                mid = mv.get("metric_id", mv.get("metricId", ""))
                vh = mv.get("version_hash", mv.get("versionHash", ""))
                if mid:
                    metric_versions[mid] = vh
    elif isinstance(canvas_metrics, dict):
        metric_versions = dict(canvas_metrics)

    # Extract dataset_ref
    dataset_ref = None
    ds = canvas.get("dataset", canvas.get("dataset_ref", {}))
    if ds:
        dataset_ref = DatasetRefInfo(
            dataset_id=ds.get("dataset_id", ds.get("datasetId", "")),
            version_hash=ds.get("version_hash", ds.get("versionHash", "")),
            content_hash=ds.get("content_hash", ds.get("contentHash", "")),
            n_cases=int(ds.get("n_cases", ds.get("nCases", 0))),
        )

    return SkillSpec(
        skill_name=skill_name,
        description=canvas.get("description", ""),
        model=model,
        judge_model=judge_model,
        fields=fields,
        dataset_ref=dataset_ref,
        metric_versions=metric_versions,
        template=canvas.get("template", "deepeval"),
    )


def main():
    parser = argparse.ArgumentParser(
        prog="generate_skill",
        description="Generate a Skill package from a SkillSpec or project canvas.",
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--project", help="Project name (reads data/projects/<name>/canvas.json)")
    group.add_argument("--spec", help="Path to JSON SkillSpec file")
    parser.add_argument("--output", required=True, help="Output directory or .zip path")
    parser.add_argument("--metric-defs", default=None, help="Optional path to JSON metric definitions file")

    args = parser.parse_args()

    # Build spec
    try:
        if args.project:
            spec = _build_spec_from_project(args.project)
        else:
            spec_path = Path(args.spec)
            if not spec_path.exists():
                print(f"Error: spec file not found: {spec_path}", file=sys.stderr)
                sys.exit(1)
            spec_dict = json.loads(spec_path.read_text(encoding="utf-8"))
            spec = SkillSpec.from_dict(spec_dict)
    except Exception as e:
        print(f"Error building spec: {e}", file=sys.stderr)
        sys.exit(1)

    # Load metric definitions if provided
    metric_defs = None
    if args.metric_defs:
        mdefs_path = Path(args.metric_defs)
        if mdefs_path.exists():
            metric_defs = json.loads(mdefs_path.read_text(encoding="utf-8"))

    # Generate
    output_path = Path(args.output)
    is_zip = output_path.suffix.lower() == ".zip"

    try:
        if is_zip:
            # Generate to temp dir, then zip
            with tempfile.TemporaryDirectory() as tmpdir:
                tmp_path = Path(tmpdir)
                package = generate_skill(spec, metric_defs=metric_defs, output_dir=tmp_path)
                _write_zip(package, output_path)
        else:
            package = generate_skill(spec, metric_defs=metric_defs, output_dir=output_path)

        print(f"Skill generated: {package.skill_hash}")
        print(f"Output: {output_path}")
        if not is_zip:
            print(f"Files: {list(package.files.keys())}")
    except Exception as e:
        print(f"Error generating skill: {e}", file=sys.stderr)
        sys.exit(1)


def _write_zip(package: SkillPackage, zip_path: Path):
    """Write a SkillPackage to a zip file.

    Args:
        package: The SkillPackage to write.
        zip_path: Path to the output .zip file.
    """
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(str(zip_path), "w", zipfile.ZIP_DEFLATED) as zf:
        for name, content in package.files.items():
            zf.writestr(name, content)


if __name__ == "__main__":
    main()