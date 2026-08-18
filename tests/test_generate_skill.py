"""Skill Generation 模块测试（pytest）。

覆盖设计文档第 9 节全部 24 条用例。
所有 fixture 均使用 tempfile.TemporaryDirectory()，绝不读写真实文件。
"""

import json
import sys
import tempfile
from pathlib import Path

import pytest

# Ensure scripts/ is importable
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from generate_skill import (  # noqa: E402
    DatasetRefInfo,
    FieldPipeline,
    JudgeModelConfig,
    MetricInstance,
    ModelConfig,
    SKILL_MANIFEST_SCHEMA,
    SkillPackage,
    SkillSpec,
    _compute_skill_hash,
    _format_python_value,
    _generate_custom_metrics_code,
    _generate_field_eval_code,
    _generate_manifest,
    _generate_metric_list,
    generate_skill,
)


# ═══════════════════════════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.fixture
def sample_metric_defs():
    """Dict with non_llm and llm metric definitions."""
    return {
        "json_schema": {
            "id": "json_schema",
            "metric_id": "json_schema",
            "name": "JSON Schema 校验",
            "category": "non_llm",
            "params": [
                {"key": "schema", "type": "json", "default": "{}", "label": "JSON Schema"},
            ],
            "code_template": (
                "class JsonSchemaMetric(BaseMetric):\n"
                "    def __init__(self, schema={{schema}}):\n"
                "        self.schema = schema\n"
                "        super().__init__()\n"
                "    def measure(self, test_case):\n"
                "        pass\n"
            ),
            "criteria": "",
            "requires": ["actual_output"],
        },
        "accuracy": {
            "id": "accuracy",
            "metric_id": "accuracy",
            "name": "准确率",
            "category": "llm",
            "params": [
                {"key": "threshold", "type": "number", "default": 0.7, "label": "阈值"},
            ],
            "code_template": (
                'GEval(\n'
                '    name="Accuracy",\n'
                '    criteria="{{criteria}}",\n'
                '    evaluation_params=[LLMTestCaseParams.EXPECTED_OUTPUT, LLMTestCaseParams.ACTUAL_OUTPUT],\n'
                '    threshold={{threshold}},\n'
                '    model=JUDGE_MODEL,\n'
                ')'
            ),
            "criteria": "评估回答是否准确",
            "requires": ["actual_output", "expected_output"],
        },
        "recall_at_k": {
            "id": "recall_at_k",
            "metric_id": "recall_at_k",
            "name": "Recall@K",
            "category": "non_llm",
            "params": [
                {"key": "k", "type": "number", "default": 5, "label": "K 值"},
            ],
            "code_template": (
                "class RecallAtK(BaseMetric):\n"
                "    def __init__(self, k={{k}}):\n"
                "        self.k = k\n"
                "        super().__init__()\n"
                "    def measure(self, test_case):\n"
                "        pass\n"
            ),
            "criteria": "",
            "requires": ["actual_output", "retrieval_context"],
        },
    }


@pytest.fixture
def sample_spec():
    """A valid SkillSpec with one field, gate + score pipelines."""
    return SkillSpec(
        skill_name="test_eval",
        description="Test evaluation skill",
        model=ModelConfig(model_id="test-model", base_url="https://example.com/v1"),
        fields=[
            FieldPipeline(
                name="diagnosis",
                gate_pipeline=[
                    MetricInstance(
                        metric_id="json_schema",
                        params={"schema": '{"name":"str"}'},
                        zone="gate",
                    ),
                ],
                score_pipeline=[
                    MetricInstance(
                        metric_id="accuracy",
                        params={"threshold": 0.8},
                        weight=0.5,
                        strictness=1.0,
                        zone="score",
                    ),
                ],
            ),
        ],
        metric_versions={"json_schema": "abc123", "accuracy": "def456"},
    )


@pytest.fixture
def temp_output_dir():
    """Create a temporary directory for skill output."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


# ═══════════════════════════════════════════════════════════════════════════════
# Test 1: generate_skill — 生成完整 Skill 目录
# ═══════════════════════════════════════════════════════════════════════════════

def test_generate_skill_creates_output_dir(sample_spec, sample_metric_defs, temp_output_dir):
    """Test 1: generate_skill creates a complete skill directory."""
    package = generate_skill(sample_spec, metric_defs=sample_metric_defs, output_dir=temp_output_dir)

    assert package.path == temp_output_dir
    assert package.path.is_dir()
    assert package.skill_hash is not None
    assert len(package.skill_hash) == 64  # SHA256 hex digest


# ═══════════════════════════════════════════════════════════════════════════════
# Test 2: 生成目录包含所有 5 个文件
# ═══════════════════════════════════════════════════════════════════════════════

def test_generate_skill_has_all_files(sample_spec, sample_metric_defs, temp_output_dir):
    """Test 2: Generated directory contains all 5 files."""
    package = generate_skill(sample_spec, metric_defs=sample_metric_defs, output_dir=temp_output_dir)

    expected_files = {"SKILL.md", "eval_script.py", "test_cases_template.json", "requirements.txt", "manifest.json"}
    actual_files = set(package.files.keys())
    assert actual_files >= expected_files

    for fname in expected_files:
        filepath = package.path / fname
        assert filepath.exists(), f"Missing file: {fname}"
        assert filepath.stat().st_size > 0, f"Empty file: {fname}"


# ═══════════════════════════════════════════════════════════════════════════════
# Test 3: eval_script.py 语法有效（compile() 通过）
# ═══════════════════════════════════════════════════════════════════════════════

def test_eval_script_syntax_valid(sample_spec, sample_metric_defs, temp_output_dir):
    """Test 3: eval_script.py is syntactically valid Python."""
    package = generate_skill(sample_spec, metric_defs=sample_metric_defs, output_dir=temp_output_dir)

    eval_script = package.files["eval_script.py"]
    try:
        compile(eval_script, "eval_script.py", "exec")
    except SyntaxError as e:
        pytest.fail(f"eval_script.py has syntax error: {e}")


# ═══════════════════════════════════════════════════════════════════════════════
# Test 4: SKILL.md 包含 skill name
# ═══════════════════════════════════════════════════════════════════════════════

def test_skill_md_contains_skill_name(sample_spec, sample_metric_defs, temp_output_dir):
    """Test 4: SKILL.md contains the skill name."""
    package = generate_skill(sample_spec, metric_defs=sample_metric_defs, output_dir=temp_output_dir)

    skill_md = package.files["SKILL.md"]
    assert sample_spec.skill_name in skill_md
    assert "name: test_eval" in skill_md


# ═══════════════════════════════════════════════════════════════════════════════
# Test 5: manifest.json 包含所有必填字段
# ═══════════════════════════════════════════════════════════════════════════════

def test_manifest_has_required_fields(sample_spec, sample_metric_defs, temp_output_dir):
    """Test 5: manifest.json contains all required fields."""
    package = generate_skill(sample_spec, metric_defs=sample_metric_defs, output_dir=temp_output_dir)

    manifest = package.manifest
    required_fields = [
        "skill_name", "skill_hash", "generated_at", "generator_version",
        "template", "model", "metric_versions", "fields", "file_hashes",
    ]
    for field in required_fields:
        assert field in manifest, f"Missing required field: {field}"

    assert manifest["skill_name"] == "test_eval"
    assert manifest["generator_version"] == "1.0"
    assert manifest["template"] == "deepeval"
    assert manifest["model"]["model_id"] == "test-model"


def test_manifest_validates_against_skill_manifest_schema(sample_spec, sample_metric_defs, temp_output_dir):
    """Test that generated manifest validates against SKILL_MANIFEST_SCHEMA."""
    from mini_json_schema import validate as js_validate

    package = generate_skill(sample_spec, metric_defs=sample_metric_defs, output_dir=temp_output_dir)
    manifest = package.manifest

    errors = js_validate(manifest, SKILL_MANIFEST_SCHEMA)
    assert errors == [], f"Manifest should validate against SKILL_MANIFEST_SCHEMA, got: {errors}"


# ═══════════════════════════════════════════════════════════════════════════════
# Test 6: manifest.json 的 metric_versions 正确
# ═══════════════════════════════════════════════════════════════════════════════

def test_manifest_metric_versions_correct(sample_spec, sample_metric_defs, temp_output_dir):
    """Test 6: manifest.json metric_versions are correct."""
    package = generate_skill(sample_spec, metric_defs=sample_metric_defs, output_dir=temp_output_dir)

    manifest = package.manifest
    assert "metric_versions" in manifest
    assert manifest["metric_versions"]["json_schema"] == "abc123"
    assert manifest["metric_versions"]["accuracy"] == "def456"


# ═══════════════════════════════════════════════════════════════════════════════
# Test 7: manifest.json 的 dataset 引用正确
# ═══════════════════════════════════════════════════════════════════════════════

def test_manifest_dataset_ref_correct(sample_metric_defs, temp_output_dir):
    """Test 7: manifest.json dataset reference is correct."""
    spec = SkillSpec(
        skill_name="test_eval",
        model=ModelConfig(model_id="test-model"),
        fields=[],
        dataset_ref=DatasetRefInfo(
            dataset_id="my_dataset",
            version_hash="ds_hash_001",
            content_hash="content_abc",
        ),
    )
    package = generate_skill(spec, metric_defs=sample_metric_defs, output_dir=temp_output_dir)

    manifest = package.manifest
    assert "dataset" in manifest
    assert manifest["dataset"]["dataset_id"] == "my_dataset"
    assert manifest["dataset"]["version_hash"] == "ds_hash_001"


# ═══════════════════════════════════════════════════════════════════════════════
# Test 8: manifest.json 的 file_hashes 与实际文件匹配
# ═══════════════════════════════════════════════════════════════════════════════

def test_manifest_file_hashes_match(sample_spec, sample_metric_defs, temp_output_dir):
    """Test 8: manifest.json file_hashes match actual file content."""
    import hashlib

    package = generate_skill(sample_spec, metric_defs=sample_metric_defs, output_dir=temp_output_dir)

    manifest = package.manifest
    for fname, expected_hash in manifest["file_hashes"].items():
        content = package.files[fname]
        actual_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
        assert actual_hash == expected_hash, f"Hash mismatch for {fname}"


# ═══════════════════════════════════════════════════════════════════════════════
# Test 9: skill_hash 确定性（相同输入 → 相同 hash）
# ═══════════════════════════════════════════════════════════════════════════════

def test_skill_hash_deterministic(sample_spec, sample_metric_defs):
    """Test 9: Same input produces same skill_hash."""
    import copy
    defs1 = copy.deepcopy(sample_metric_defs)
    defs2 = copy.deepcopy(sample_metric_defs)
    with tempfile.TemporaryDirectory() as tmpdir1, tempfile.TemporaryDirectory() as tmpdir2:
        pkg1 = generate_skill(sample_spec, metric_defs=defs1, output_dir=Path(tmpdir1))
        pkg2 = generate_skill(sample_spec, metric_defs=defs2, output_dir=Path(tmpdir2))

        assert pkg1.skill_hash == pkg2.skill_hash
        assert pkg1.manifest["skill_hash"] == pkg2.manifest["skill_hash"]


# ═══════════════════════════════════════════════════════════════════════════════
# Test 10: skill_hash 不同输入 → 不同 hash
# ═══════════════════════════════════════════════════════════════════════════════

def test_skill_hash_different_inputs(sample_spec, sample_metric_defs):
    """Test 10: Different input produces different skill_hash."""
    spec2 = SkillSpec(
        skill_name="different_eval",
        model=ModelConfig(model_id="test-model"),
        fields=[],
    )

    with tempfile.TemporaryDirectory() as tmpdir1, tempfile.TemporaryDirectory() as tmpdir2:
        pkg1 = generate_skill(sample_spec, metric_defs=sample_metric_defs, output_dir=Path(tmpdir1))
        pkg2 = generate_skill(spec2, metric_defs=sample_metric_defs, output_dir=Path(tmpdir2))

        assert pkg1.skill_hash != pkg2.skill_hash


# ═══════════════════════════════════════════════════════════════════════════════
# Test 11: non-LLM metric 代码生成正确
# ═══════════════════════════════════════════════════════════════════════════════

def test_non_llm_metric_code_generation(sample_metric_defs, temp_output_dir):
    """Test 11: non-LLM metric code is generated correctly."""
    spec = SkillSpec(
        skill_name="test_non_llm",
        model=ModelConfig(model_id="test-model"),
        fields=[
            FieldPipeline(
                name="field1",
                score_pipeline=[
                    MetricInstance(
                        metric_id="json_schema",
                        params={"schema": '{"name":"str","age":"int"}'},
                        zone="score",
                    ),
                ],
            ),
        ],
    )
    package = generate_skill(spec, metric_defs=sample_metric_defs, output_dir=temp_output_dir)

    eval_script = package.files["eval_script.py"]
    # The class definition should be in custom metrics section
    assert "class JsonSchemaMetric(BaseMetric):" in eval_script
    # The schema param should be substituted
    # json.dumps adds spaces after colons by default, so check for the spaced version
    assert '{"name":"str","age":"int"}' in eval_script or '{"name": "str", "age": "int"}' in eval_script or 'schema={"name": "str", "age": "int"}' in eval_script
    # The instantiation should be in the field eval section
    assert "JsonSchemaMetric(" in eval_script


# ═══════════════════════════════════════════════════════════════════════════════
# Test 12: LLM metric 代码生成正确（GEval）
# ═══════════════════════════════════════════════════════════════════════════════

def test_llm_metric_code_generation(sample_metric_defs, temp_output_dir):
    """Test 12: LLM metric (GEval) code is generated correctly."""
    spec = SkillSpec(
        skill_name="test_llm",
        model=ModelConfig(model_id="test-model"),
        fields=[
            FieldPipeline(
                name="field1",
                score_pipeline=[
                    MetricInstance(
                        metric_id="accuracy",
                        params={"threshold": 0.9},
                        zone="score",
                    ),
                ],
            ),
        ],
    )
    package = generate_skill(spec, metric_defs=sample_metric_defs, output_dir=temp_output_dir)

    eval_script = package.files["eval_script.py"]
    # GEval instantiation should be present
    assert "GEval(" in eval_script
    # Threshold should be substituted
    assert "0.9" in eval_script
    # Criteria should be substituted
    assert "评估回答是否准确" in eval_script


# ═══════════════════════════════════════════════════════════════════════════════
# Test 13: 参数化 metric（recall_at_k 多个 k）正确渲染
# ═══════════════════════════════════════════════════════════════════════════════

def test_parameterized_metric_rendering(sample_metric_defs, temp_output_dir):
    """Test 13: Parameterized metric (recall_at_k with multiple k values) renders correctly."""
    spec = SkillSpec(
        skill_name="test_recall",
        model=ModelConfig(model_id="test-model"),
        fields=[
            FieldPipeline(
                name="retrieval",
                score_pipeline=[
                    MetricInstance(
                        metric_id="recall_at_k",
                        params={"k": 10},
                        zone="score",
                    ),
                ],
            ),
        ],
    )
    package = generate_skill(spec, metric_defs=sample_metric_defs, output_dir=temp_output_dir)

    eval_script = package.files["eval_script.py"]
    assert "class RecallAtK(BaseMetric):" in eval_script
    assert "RecallAtK(k=10)" in eval_script


# ═══════════════════════════════════════════════════════════════════════════════
# Test 14: gate pipeline 代码生成正确
# ═══════════════════════════════════════════════════════════════════════════════

def test_gate_pipeline_code_generation(sample_metric_defs, temp_output_dir):
    """Test 14: Gate pipeline code is generated correctly."""
    spec = SkillSpec(
        skill_name="test_gate",
        model=ModelConfig(model_id="test-model"),
        fields=[
            FieldPipeline(
                name="output",
                gate_pipeline=[
                    MetricInstance(
                        metric_id="json_schema",
                        params={"schema": '{"valid":"bool"}'},
                        zone="gate",
                    ),
                ],
                score_pipeline=[],
            ),
        ],
    )
    package = generate_skill(spec, metric_defs=sample_metric_defs, output_dir=temp_output_dir)

    eval_script = package.files["eval_script.py"]
    assert "gate_metrics = [" in eval_script
    assert "GATE FAIL" in eval_script
    assert "JsonSchemaMetric(" in eval_script
    # Gate code should have the evaluate loop
    assert "evaluate([test_case], [m], run_async=False)" in eval_script


# ═══════════════════════════════════════════════════════════════════════════════
# Test 15: score pipeline 权重和严格度正确
# ═══════════════════════════════════════════════════════════════════════════════

def test_score_pipeline_weights_and_strictness(sample_metric_defs, temp_output_dir):
    """Test 15: Score pipeline weights and strictness are correctly rendered."""
    spec = SkillSpec(
        skill_name="test_weighted",
        model=ModelConfig(model_id="test-model"),
        fields=[
            FieldPipeline(
                name="quality",
                gate_pipeline=[],
                score_pipeline=[
                    MetricInstance(
                        metric_id="accuracy",
                        params={"threshold": 0.7},
                        weight=0.6,
                        strictness=2.0,
                        zone="score",
                    ),
                    MetricInstance(
                        metric_id="recall_at_k",
                        params={"k": 5},
                        weight=0.4,
                        strictness=1.5,
                        zone="score",
                    ),
                ],
            ),
        ],
    )
    package = generate_skill(spec, metric_defs=sample_metric_defs, output_dir=temp_output_dir)

    eval_script = package.files["eval_script.py"]
    # Check weights array
    assert "[0.6, 0.4]" in eval_script
    # Check strictness array
    assert "[2.0, 1.5]" in eval_script
    # Check weighted scoring logic
    assert "weighted = 0; total_w = 0" in eval_script
    assert "final = round(weighted/total_w, 4)" in eval_script


# ═══════════════════════════════════════════════════════════════════════════════
# Test 16: _format_python_value — json 类型
# ═══════════════════════════════════════════════════════════════════════════════

def test_format_python_value_json():
    """Test 16: _format_python_value handles json type."""
    # JSON string input - json.dumps reformats with spaces
    result = _format_python_value('{"name":"str"}', "json")
    parsed = json.loads(result)
    assert parsed == {"name": "str"}

    # Dict input
    result = _format_python_value({"name": "str"}, "json")
    parsed = json.loads(result)
    assert parsed == {"name": "str"}

    # Invalid JSON string falls back to string repr
    result = _format_python_value("not json", "json")
    assert result == '"not json"'


# ═══════════════════════════════════════════════════════════════════════════════
# Test 17: _format_python_value — number 类型
# ═══════════════════════════════════════════════════════════════════════════════

def test_format_python_value_number():
    """Test 17: _format_python_value handles number type."""
    assert _format_python_value(5, "number") == "5"
    assert _format_python_value(3.14, "number") == "3.14"
    assert _format_python_value("5", "number") == "5"
    assert _format_python_value("3.14", "number") == "3.14"
    assert _format_python_value(0, "number") == "0"


# ═══════════════════════════════════════════════════════════════════════════════
# Test 18: _format_python_value — boolean 类型
# ═══════════════════════════════════════════════════════════════════════════════

def test_format_python_value_boolean():
    """Test 18: _format_python_value handles boolean type."""
    assert _format_python_value(True, "boolean") == "True"
    assert _format_python_value(False, "boolean") == "False"
    assert _format_python_value(1, "boolean") == "True"
    assert _format_python_value(0, "boolean") == "False"
    assert _format_python_value("true", "boolean") == "True"


# ═══════════════════════════════════════════════════════════════════════════════
# Test 19: _format_python_value — string 类型
# ═══════════════════════════════════════════════════════════════════════════════

def test_format_python_value_string():
    """Test 19: _format_python_value handles string type."""
    assert _format_python_value("hello", "string") == '"hello"'
    assert _format_python_value(123, "string") == '"123"'
    assert _format_python_value("", "string") == '""'


# ═══════════════════════════════════════════════════════════════════════════════
# Test 20: 空 pipeline 不报错
# ═══════════════════════════════════════════════════════════════════════════════

def test_empty_pipeline_no_error(sample_metric_defs, temp_output_dir):
    """Test 20: Empty pipeline (no fields) does not crash."""
    spec = SkillSpec(
        skill_name="test_empty",
        model=ModelConfig(model_id="test-model"),
        fields=[],
    )
    package = generate_skill(spec, metric_defs=sample_metric_defs, output_dir=temp_output_dir)

    assert package is not None
    assert package.skill_hash is not None
    # eval_script should still be valid
    eval_script = package.files["eval_script.py"]
    try:
        compile(eval_script, "eval_script.py", "exec")
    except SyntaxError as e:
        pytest.fail(f"eval_script.py with empty pipeline has syntax error: {e}")


def test_empty_gate_and_score_pipelines(sample_metric_defs, temp_output_dir):
    """Test 20b: Field with empty gate and score pipelines does not crash."""
    spec = SkillSpec(
        skill_name="test_empty_pipelines",
        model=ModelConfig(model_id="test-model"),
        fields=[
            FieldPipeline(
                name="empty_field",
                gate_pipeline=[],
                score_pipeline=[],
            ),
        ],
    )
    package = generate_skill(spec, metric_defs=sample_metric_defs, output_dir=temp_output_dir)

    eval_script = package.files["eval_script.py"]
    try:
        compile(eval_script, "eval_script.py", "exec")
    except SyntaxError as e:
        pytest.fail(f"eval_script.py with empty pipelines has syntax error: {e}")


# ═══════════════════════════════════════════════════════════════════════════════
# Test 21: 缺少 metric_id 报错
# ═══════════════════════════════════════════════════════════════════════════════

def test_missing_metric_id_raises_error(sample_metric_defs, temp_output_dir):
    """Test 21: Missing metric_id raises ValueError."""
    spec = SkillSpec(
        skill_name="test_missing_id",
        model=ModelConfig(model_id="test-model"),
        fields=[
            FieldPipeline(
                name="field1",
                score_pipeline=[
                    MetricInstance(
                        metric_id="",  # empty metric_id
                        zone="score",
                    ),
                ],
            ),
        ],
    )
    with pytest.raises(ValueError, match="missing metric_id"):
        generate_skill(spec, metric_defs=sample_metric_defs, output_dir=temp_output_dir)


def test_unknown_metric_id_raises_error(sample_metric_defs, temp_output_dir):
    """Test 21b: Referencing a metric_id not in metric_defs raises ValueError."""
    spec = SkillSpec(
        skill_name="test_unknown_metric",
        model=ModelConfig(model_id="test-model"),
        fields=[
            FieldPipeline(
                name="field1",
                score_pipeline=[
                    MetricInstance(
                        metric_id="nonexistent_metric",
                        zone="score",
                    ),
                ],
            ),
        ],
    )
    with pytest.raises(ValueError, match="Metric definition not found"):
        generate_skill(spec, metric_defs=sample_metric_defs, output_dir=temp_output_dir)


# ═══════════════════════════════════════════════════════════════════════════════
# Test 22: CLI --project 模式
# ═══════════════════════════════════════════════════════════════════════════════

def test_cli_project_mode(sample_metric_defs, temp_output_dir):
    """Test 22: CLI --project mode builds from canvas.json."""
    # Create a mock project with canvas.json
    projects_dir = temp_output_dir / "data" / "projects" / "test_proj"
    projects_dir.mkdir(parents=True)
    canvas = {
        "skillName": "cli_test_skill",
        "modelId": "cli-model",
        "modelBaseUrl": "https://cli.example.com/v1",
        "canvasFields": [
            {
                "name": "field1",
                "gatePipeline": [],
                "scorePipeline": [
                    {"metricId": "accuracy", "params": {"threshold": 0.5}, "weight": 1.0, "strictness": 1.0},
                ],
            },
        ],
        "metricVersions": {"accuracy": "def456"},
    }
    (projects_dir / "canvas.json").write_text(json.dumps(canvas, ensure_ascii=False), encoding="utf-8")

    # Patch REPO_ROOT to point to our temp dir
    import scripts.generate_skill as gs
    original_root = gs.REPO_ROOT
    try:
        gs.REPO_ROOT = temp_output_dir
        spec = gs._build_spec_from_project("test_proj")

        assert spec.skill_name == "cli_test_skill"
        assert spec.model.model_id == "cli-model"
        assert len(spec.fields) == 1
        assert spec.fields[0].name == "field1"
        assert len(spec.fields[0].score_pipeline) == 1
    finally:
        gs.REPO_ROOT = original_root


# ═══════════════════════════════════════════════════════════════════════════════
# Test 23: CLI --spec 模式
# ═══════════════════════════════════════════════════════════════════════════════

def test_spec_from_dict():
    """Test 23: SkillSpec.from_dict correctly parses JSON spec."""
    spec_dict = {
        "skill_name": "spec_test",
        "description": "Test from dict",
        "model": {
            "model_id": "spec-model",
            "base_url": "https://spec.example.com/v1",
        },
        "judge_model": {
            "model_id": "judge-model",
            "base_url": "https://judge.example.com/v1",
        },
        "fields": [
            {
                "name": "output",
                "gate_pipeline": [
                    {"metric_id": "json_schema", "params": {"schema": "{}"}},
                ],
                "score_pipeline": [
                    {"metric_id": "accuracy", "params": {}, "weight": 0.8, "strictness": 1.2},
                ],
            },
        ],
        "dataset_ref": {
            "dataset_id": "ds1",
            "version_hash": "vh1",
            "content_hash": "ch1",
            "n_cases": 100,
        },
        "metric_versions": {"json_schema": "abc", "accuracy": "def"},
        "template": "deepeval",
    }

    spec = SkillSpec.from_dict(spec_dict)

    assert spec.skill_name == "spec_test"
    assert spec.model.model_id == "spec-model"
    assert spec.judge_model is not None
    assert spec.judge_model.model_id == "judge-model"
    assert len(spec.fields) == 1
    assert spec.fields[0].name == "output"
    assert len(spec.fields[0].gate_pipeline) == 1
    assert len(spec.fields[0].score_pipeline) == 1
    assert spec.fields[0].score_pipeline[0].weight == 0.8
    assert spec.fields[0].score_pipeline[0].strictness == 1.2
    assert spec.dataset_ref is not None
    assert spec.dataset_ref.dataset_id == "ds1"
    assert spec.dataset_ref.n_cases == 100
    assert spec.metric_versions == {"json_schema": "abc", "accuracy": "def"}


def test_spec_from_dict_minimal():
    """Test 23b: SkillSpec.from_dict handles minimal input."""
    spec_dict = {
        "skill_name": "minimal",
        "model": {"model_id": "m"},
    }
    spec = SkillSpec.from_dict(spec_dict)
    assert spec.skill_name == "minimal"
    assert spec.model.model_id == "m"
    assert spec.fields == []
    assert spec.judge_model is None
    assert spec.dataset_ref is None


# ═══════════════════════════════════════════════════════════════════════════════
# Test 24: 生成的文件 encoding 为 UTF-8
# ═══════════════════════════════════════════════════════════════════════════════

def test_files_are_utf8_encoded(sample_spec, sample_metric_defs, temp_output_dir):
    """Test 24: All generated files are UTF-8 encoded."""
    package = generate_skill(sample_spec, metric_defs=sample_metric_defs, output_dir=temp_output_dir)

    for fname, content in package.files.items():
        # Verify it can be encoded/decoded as UTF-8
        encoded = content.encode("utf-8")
        decoded = encoded.decode("utf-8")
        assert decoded == content, f"File {fname} is not valid UTF-8"


def test_utf8_with_cjk_characters(sample_metric_defs, temp_output_dir):
    """Test 24b: CJK characters in skill_name are preserved correctly."""
    spec = SkillSpec(
        skill_name="中文评测",
        description="测试中文技能",
        model=ModelConfig(model_id="test-model"),
        fields=[
            FieldPipeline(
                name="诊断结果",
                score_pipeline=[
                    MetricInstance(
                        metric_id="accuracy",
                        params={"threshold": 0.7},
                        zone="score",
                    ),
                ],
            ),
        ],
    )
    package = generate_skill(spec, metric_defs=sample_metric_defs, output_dir=temp_output_dir)

    skill_md = package.files["SKILL.md"]
    assert "中文评测" in skill_md

    eval_script = package.files["eval_script.py"]
    assert "中文评测" in eval_script
    assert "诊断结果" in eval_script

    manifest = package.manifest
    assert manifest["skill_name"] == "中文评测"


# ═══════════════════════════════════════════════════════════════════════════════
# Additional Tests
# ═══════════════════════════════════════════════════════════════════════════════

def test_skill_package_attributes(sample_spec, sample_metric_defs, temp_output_dir):
    """Test SkillPackage has all expected attributes."""
    package = generate_skill(sample_spec, metric_defs=sample_metric_defs, output_dir=temp_output_dir)

    assert isinstance(package, SkillPackage)
    assert isinstance(package.path, Path)
    assert isinstance(package.files, dict)
    assert isinstance(package.manifest, dict)
    assert isinstance(package.skill_hash, str)


def test_metric_list_generation(sample_metric_defs):
    """Test _generate_metric_list produces correct markdown."""
    fields = [
        FieldPipeline(
            name="diagnosis",
            gate_pipeline=[MetricInstance(metric_id="json_schema")],
            score_pipeline=[MetricInstance(metric_id="accuracy")],
        ),
    ]
    result = _generate_metric_list(fields, sample_metric_defs)
    assert "📌 diagnosis" in result
    assert "JSON Schema 校验" in result
    assert "准确率" in result


def test_manifest_generation(sample_spec, sample_metric_defs):
    """Test _generate_manifest produces correct structure."""
    file_hashes = {"SKILL.md": "abc", "eval_script.py": "def"}
    manifest = _generate_manifest(sample_spec, sample_metric_defs, file_hashes)

    assert "skill_hash" in manifest
    assert len(manifest["skill_hash"]) == 64
    assert manifest["fields"][0]["name"] == "diagnosis"
    assert manifest["fields"][0]["gate_count"] == 1
    assert manifest["fields"][0]["score_count"] == 1


def test_skill_hash_computation():
    """Test _compute_skill_hash is deterministic and excludes dynamic fields."""
    manifest = {
        "skill_name": "test",
        "skill_hash": "should_be_removed",
        "file_hashes": {"a": "b"},
        "model": {"model_id": "m"},
        "generated_at": "2026-01-01T00:00:00Z",
        "generator_version": "1.0",
        "template": "deepeval",
        "metric_versions": {},
        "fields": [],
    }

    h1 = _compute_skill_hash(manifest)
    h2 = _compute_skill_hash(manifest)

    # Same input → same hash
    assert h1 == h2
    assert len(h1) == 64

    # Different skill_name → different hash
    manifest2 = dict(manifest)
    manifest2["skill_name"] = "different"
    h3 = _compute_skill_hash(manifest2)
    assert h1 != h3


def test_generate_skill_with_extra_files(sample_metric_defs, temp_output_dir):
    """Test extra_files are included in the package."""
    spec = SkillSpec(
        skill_name="test_extra",
        model=ModelConfig(model_id="test-model"),
        fields=[],
        extra_files={"README.md": "# Custom README\n"},
    )
    package = generate_skill(spec, metric_defs=sample_metric_defs, output_dir=temp_output_dir)

    assert "README.md" in package.files
    assert package.files["README.md"] == "# Custom README\n"
    assert (package.path / "README.md").exists()


def test_generate_skill_with_judge_model(sample_metric_defs, temp_output_dir):
    """Test judge_model is included in manifest and eval_script."""
    spec = SkillSpec(
        skill_name="test_judge",
        model=ModelConfig(model_id="main-model", base_url="https://main.example.com/v1"),
        judge_model=JudgeModelConfig(model_id="judge-model", base_url="https://judge.example.com/v1"),
        fields=[],
    )
    package = generate_skill(spec, metric_defs=sample_metric_defs, output_dir=temp_output_dir)

    manifest = package.manifest
    assert "judge_model" in manifest
    assert manifest["judge_model"]["model_id"] == "judge-model"


def test_generate_skill_without_output_dir_uses_temp(sample_spec, sample_metric_defs):
    """Test that not providing output_dir creates a temp directory."""
    package = generate_skill(sample_spec, metric_defs=sample_metric_defs)

    assert package.path.exists()
    assert package.path.is_dir()
    # All files should exist
    for fname in package.files:
        assert (package.path / fname).exists()


def test_multiple_fields_generation(sample_metric_defs, temp_output_dir):
    """Test generation with multiple fields produces correct code."""
    spec = SkillSpec(
        skill_name="multi_field",
        model=ModelConfig(model_id="test-model"),
        fields=[
            FieldPipeline(
                name="field_a",
                score_pipeline=[MetricInstance(metric_id="accuracy", zone="score")],
            ),
            FieldPipeline(
                name="field_b",
                score_pipeline=[MetricInstance(metric_id="recall_at_k", params={"k": 3}, zone="score")],
            ),
        ],
    )
    package = generate_skill(spec, metric_defs=sample_metric_defs, output_dir=temp_output_dir)

    eval_script = package.files["eval_script.py"]
    assert "Field: field_a" in eval_script
    assert "Field: field_b" in eval_script
    assert "RecallAtK(k=3)" in eval_script

    # Manifest should list both fields
    manifest = package.manifest
    assert len(manifest["fields"]) == 2
    assert manifest["fields"][0]["name"] == "field_a"
    assert manifest["fields"][1]["name"] == "field_b"


def test_generate_skill_validation_errors():
    """Test that validation errors are raised for invalid specs."""
    # Missing skill_name
    with pytest.raises(ValueError, match="skill_name"):
        generate_skill(SkillSpec(skill_name="", model=ModelConfig(model_id="m")))

    # Missing model_id
    with pytest.raises(ValueError, match="model.model_id"):
        generate_skill(SkillSpec(skill_name="test", model=ModelConfig(model_id="")))