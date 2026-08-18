"""Core Reliability — Edge-case & malformed-input tests for EvalForge.

Ensures malformed data is NEVER silently accepted by the system.
All fixtures use tempfile.TemporaryDirectory() — never touches real data.

Modules covered:
  - MetricStore   (20 malformed-input tests)
  - DatasetStore  (11 malformed-input tests)
  - Skill Generation (8 tests)
  - RunStore      (14 malformed-input tests)
  - Immutable Versions (3 tests)
  - Provenance    (4 tests)
  - Structured Errors (3 tests)
"""

import json
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))


# ═══════════════════════════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.fixture
def metric_store():
    """Create a MetricStore backed by a temporary directory."""
    with tempfile.TemporaryDirectory() as tmp:
        from metric_store import MetricStore
        base = Path(tmp) / "metrics"
        base.mkdir()
        yield MetricStore(base_dir=base)


@pytest.fixture
def dataset_store():
    """Create a DatasetStore backed by a temporary directory."""
    with tempfile.TemporaryDirectory() as tmp:
        from dataset_store import DatasetStore
        base = Path(tmp) / "datasets"
        base.mkdir()
        yield DatasetStore(base_dir=base)


@pytest.fixture
def run_store():
    """Create a RunStore backed by a temporary directory."""
    with tempfile.TemporaryDirectory() as tmp:
        from run_store import RunStore
        runs_dir = Path(tmp) / "runs"
        runs_dir.mkdir()
        yield RunStore(runs_dir=runs_dir)


@pytest.fixture
def sample_metric_defs():
    """Return a dict of valid sample metric definitions."""
    return {
        "json_schema": {
            "id": "json_schema",
            "metric_id": "json_schema",
            "name": "JSON Schema",
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
            "name": "Accuracy",
            "category": "llm",
            "params": [
                {"key": "threshold", "type": "number", "default": 0.7, "label": "Threshold"},
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
            "criteria": "Evaluate accuracy",
            "requires": ["actual_output", "expected_output"],
        },
    }


@pytest.fixture
def sample_spec(sample_metric_defs):
    """Return a valid SkillSpec."""
    from generate_skill import SkillSpec, ModelConfig, FieldPipeline, MetricInstance
    return SkillSpec(
        skill_name="test",
        model=ModelConfig(model_id="test-model"),
        fields=[
            FieldPipeline(
                name="f1",
                score_pipeline=[
                    MetricInstance(
                        metric_id="accuracy",
                        params={"threshold": 0.7},
                        zone="score",
                    ),
                ],
            ),
        ],
        metric_versions={"accuracy": "a" * 64},
    )


@pytest.fixture
def temp_output_dir():
    """Create a temporary directory for skill output."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _sample_metric(**overrides):
    """Return a valid sample metric dict."""
    m = {
        "id": "sample",
        "name": "Sample Metric",
        "category": "llm",
        "description": "Test metric",
        "params": [
            {
                "key": "threshold",
                "label": "Threshold",
                "type": "number",
                "default": 0.7,
                "min": 0,
                "max": 1,
                "step": 0.1,
            }
        ],
        "criteria": "Evaluate accuracy",
        "requires": ["actual_output", "expected_output"],
        "code_template": "GEval(...)",
    }
    m.update(overrides)
    return m


def _sample_cases(n=2):
    """Return a list of valid sample cases."""
    return [{"input": f"Q{i}", "expected_output": f"A{i}"} for i in range(n)]


def _sample_report(**overrides):
    """Return a minimal valid report dict."""
    r = {
        "skill": "my_eval",
        "created_at": "2026-08-18T10:00:00Z",
        "n_cases": 10,
        "n_passed": 8,
        "pass_rate": 0.8,
        "overall_score": 0.85,
        "grade": "B",
        "fields": {"diagnosis": {"field_score": 0.85}},
        "cases": [],
        "config": {"metrics": [{"name": "accuracy", "metricId": "accuracy"}]},
    }
    r.update(overrides)
    return r


def _sample_manifest(**overrides):
    """Build a minimal valid manifest dict that passes validate_manifest."""
    import run_manifest as rm
    m = {
        "manifest_version": "1.0",
        "manifest_hash": "",
        "run_id": "run_test",
        "created_at": "2026-08-18T10:00:00Z",
        "triggered_by": "agent",
        "dataset": {
            "dataset_id": "test_ds",
            "version_hash": "0" * 64,
            "content_hash": "0" * 64,
            "n_cases": 10,
        },
        "metrics": [
            {
                "metric_id": "accuracy",
                "version_hash": "0" * 64,
                "instance": {
                    "label": "Accuracy",
                    "params": {},
                    "weight": 1.0,
                    "strictness": 1.0,
                    "zone": "score",
                },
            }
        ],
        "skill": {
            "name": "my_eval",
            "content_hash": "0" * 64,
        },
        "model": {
            "model_id": "test_model",
        },
        "judge_model": None,
        "environment": {
            "python_version": "3.10.0",
            "platform": "test",
            "dependencies": {},
        },
        "extra": {},
    }
    m.update(overrides)
    m["manifest_hash"] = rm.compute_manifest_hash(m)
    return m


# ═══════════════════════════════════════════════════════════════════════════════
# 1. Metric Store — Malformed Input Tests
# ═══════════════════════════════════════════════════════════════════════════════

class TestMetricMalformedInput:
    """Verify MetricStore rejects all forms of malformed input."""

    def test_create_not_dict(self, metric_store):
        """create rejects a string with VALIDATION_ERROR."""
        result = metric_store.create("not a dict")
        assert result["ok"] is False
        assert result["error"]["code"] == "VALIDATION_ERROR"

    def test_create_none(self, metric_store):
        """create rejects None with VALIDATION_ERROR."""
        result = metric_store.create(None)
        assert result["ok"] is False
        assert result["error"]["code"] == "VALIDATION_ERROR"

    def test_create_empty_dict(self, metric_store):
        """create rejects an empty dict (missing all required fields)."""
        result = metric_store.create({})
        assert result["ok"] is False
        assert result["error"]["code"] == "VALIDATION_ERROR"
        assert "details" in result["error"]

    def test_create_missing_id(self, metric_store):
        """create rejects a dict without 'id'."""
        m = _sample_metric()
        del m["id"]
        result = metric_store.create(m)
        assert result["ok"] is False
        assert result["error"]["code"] == "VALIDATION_ERROR"

    def test_create_missing_name(self, metric_store):
        """create rejects a dict without 'name'."""
        m = _sample_metric()
        del m["name"]
        result = metric_store.create(m)
        assert result["ok"] is False
        assert result["error"]["code"] == "VALIDATION_ERROR"

    def test_create_missing_category(self, metric_store):
        """create rejects a dict without 'category'."""
        m = _sample_metric()
        del m["category"]
        result = metric_store.create(m)
        assert result["ok"] is False
        assert result["error"]["code"] == "VALIDATION_ERROR"

    def test_create_missing_params(self, metric_store):
        """create rejects a dict without 'params'."""
        m = _sample_metric()
        del m["params"]
        result = metric_store.create(m)
        assert result["ok"] is False
        assert result["error"]["code"] == "VALIDATION_ERROR"

    def test_create_missing_code_template(self, metric_store):
        """create rejects a dict without 'code_template'."""
        m = _sample_metric()
        del m["code_template"]
        result = metric_store.create(m)
        assert result["ok"] is False
        assert result["error"]["code"] == "VALIDATION_ERROR"

    def test_create_invalid_category(self, metric_store):
        """create rejects a category not in {llm, non_llm}."""
        result = metric_store.create(_sample_metric(category="invalid_cat"))
        assert result["ok"] is False
        assert result["error"]["code"] == "VALIDATION_ERROR"

    def test_create_params_not_list(self, metric_store):
        """create rejects params that is not a list."""
        m = _sample_metric()
        m["params"] = {"key": "bad", "type": "string"}
        result = metric_store.create(m)
        assert result["ok"] is False
        assert result["error"]["code"] == "VALIDATION_ERROR"

    def test_create_param_missing_key(self, metric_store):
        """create rejects a param without 'key'."""
        m = _sample_metric()
        m["params"] = [{"type": "string", "default": ""}]
        result = metric_store.create(m)
        assert result["ok"] is False
        assert result["error"]["code"] == "VALIDATION_ERROR"

    def test_create_param_missing_type(self, metric_store):
        """create rejects a param without 'type'."""
        m = _sample_metric()
        m["params"] = [{"key": "x", "default": ""}]
        result = metric_store.create(m)
        assert result["ok"] is False
        assert result["error"]["code"] == "VALIDATION_ERROR"

    def test_create_param_invalid_type_enum(self, metric_store):
        """create rejects a param type not in the allowed enum."""
        m = _sample_metric()
        m["params"] = [{"key": "x", "type": "invalid_type", "default": ""}]
        result = metric_store.create(m)
        assert result["ok"] is False
        assert result["error"]["code"] == "VALIDATION_ERROR"

    def test_create_duplicate_id(self, metric_store):
        """create rejects a duplicate metric_id with DUPLICATE_ID."""
        metric_store.create(_sample_metric())
        result = metric_store.create(_sample_metric())
        assert result["ok"] is False
        assert result["error"]["code"] == "DUPLICATE_ID"

    def test_create_version_nonexistent(self, metric_store):
        """create_version rejects a nonexistent metric with NOT_FOUND."""
        result = metric_store.create_version("nonexistent", _sample_metric())
        assert result["ok"] is False
        assert result["error"]["code"] == "NOT_FOUND"

    def test_create_version_id_changed(self, metric_store):
        """create_version rejects changing the metric_id."""
        metric_store.create(_sample_metric())
        result = metric_store.create_version("sample", _sample_metric(id="changed"))
        assert result["ok"] is False
        assert result["error"]["code"] == "VALIDATION_ERROR"
        assert "metric_id" in result["error"]["message"]

    def test_create_version_not_dict(self, metric_store):
        """create_version rejects non-dict input with VALIDATION_ERROR."""
        metric_store.create(_sample_metric())
        result = metric_store.create_version("sample", "not a dict")
        assert result["ok"] is False
        assert result["error"]["code"] == "VALIDATION_ERROR"

    def test_get_nonexistent(self, metric_store):
        """get returns NOT_FOUND for a nonexistent metric."""
        result = metric_store.get("nonexistent")
        assert result["ok"] is False
        assert result["error"]["code"] == "NOT_FOUND"

    def test_diff_nonexistent(self, metric_store):
        """diff_versions returns NOT_FOUND for a nonexistent metric."""
        result = metric_store.diff_versions("nonexistent", "a" * 64, "b" * 64)
        assert result["ok"] is False
        assert result["error"]["code"] == "NOT_FOUND"


# ═══════════════════════════════════════════════════════════════════════════════
# 2. Dataset Store — Malformed Input Tests
# ═══════════════════════════════════════════════════════════════════════════════

class TestDatasetMalformedInput:
    """Verify DatasetStore rejects all forms of malformed input."""

    def test_create_cases_not_list(self, dataset_store):
        """create rejects cases that is not a list with INVALID_CASES."""
        result = dataset_store.create("ds1", "Test", "not_a_list")
        assert result["ok"] is False
        assert result["error"]["code"] == "INVALID_CASES"

    def test_create_cases_empty(self, dataset_store):
        """create rejects empty cases with INVALID_CASES."""
        result = dataset_store.create("ds1", "Test", [])
        assert result["ok"] is False
        assert result["error"]["code"] == "INVALID_CASES"

    def test_create_case_not_dict(self, dataset_store):
        """create rejects non-dict cases with INVALID_CASES."""
        result = dataset_store.create("ds1", "Test", ["not_a_dict"])
        assert result["ok"] is False
        assert result["error"]["code"] == "INVALID_CASES"

    def test_create_duplicate_id(self, dataset_store):
        """create rejects duplicate dataset_id with DUPLICATE_ID."""
        dataset_store.create("ds1", "Test", _sample_cases(2))
        result = dataset_store.create("ds1", "Test", _sample_cases(2))
        assert result["ok"] is False
        assert result["error"]["code"] == "DUPLICATE_ID"

    def test_create_version_nonexistent(self, dataset_store):
        """create_version rejects nonexistent dataset with NOT_FOUND."""
        result = dataset_store.create_version("nonexistent", _sample_cases(1))
        assert result["ok"] is False
        assert result["error"]["code"] == "NOT_FOUND"

    def test_create_version_cases_not_list(self, dataset_store):
        """create_version rejects non-list cases with INVALID_CASES."""
        dataset_store.create("ds1", "Test", _sample_cases(2))
        result = dataset_store.create_version("ds1", "not_a_list")
        assert result["ok"] is False
        assert result["error"]["code"] == "INVALID_CASES"

    def test_create_version_cases_empty(self, dataset_store):
        """create_version rejects empty cases with INVALID_CASES."""
        dataset_store.create("ds1", "Test", _sample_cases(2))
        result = dataset_store.create_version("ds1", [])
        assert result["ok"] is False
        assert result["error"]["code"] == "INVALID_CASES"

    def test_create_version_case_not_dict(self, dataset_store):
        """create_version rejects non-dict cases with INVALID_CASES."""
        dataset_store.create("ds1", "Test", _sample_cases(2))
        result = dataset_store.create_version("ds1", ["not_a_dict"])
        assert result["ok"] is False
        assert result["error"]["code"] == "INVALID_CASES"

    def test_get_nonexistent(self, dataset_store):
        """get returns NOT_FOUND for a nonexistent dataset."""
        result = dataset_store.get("nonexistent")
        assert result["ok"] is False
        assert result["error"]["code"] == "NOT_FOUND"

    def test_create_empty_dataset_id(self, dataset_store):
        """create with empty dataset_id is rejected by DATASET_SCHEMA."""
        result = dataset_store.create("", "Test", _sample_cases(2))
        assert result["ok"] is False
        assert result["error"]["code"] == "VALIDATION_ERROR"

    def test_create_empty_name(self, dataset_store):
        """create with empty name is rejected by DATASET_SCHEMA."""
        result = dataset_store.create("ds1", "", _sample_cases(2))
        assert result["ok"] is False
        assert result["error"]["code"] == "VALIDATION_ERROR"


# ═══════════════════════════════════════════════════════════════════════════════
# 3. Skill Generation — Malformed Input Tests
# ═══════════════════════════════════════════════════════════════════════════════

class TestSkillMalformedInput:
    """Verify skill generation rejects malformed input and produces valid output."""

    def test_empty_skill_name_raises(self, sample_metric_defs, temp_output_dir):
        """Empty skill_name raises ValueError."""
        from generate_skill import generate_skill, SkillSpec, ModelConfig
        spec = SkillSpec(skill_name="", model=ModelConfig(model_id="test-model"))
        with pytest.raises(ValueError, match="skill_name"):
            generate_skill(spec, metric_defs=sample_metric_defs, output_dir=temp_output_dir)

    def test_empty_model_id_raises(self, sample_metric_defs, temp_output_dir):
        """Empty model.model_id raises ValueError."""
        from generate_skill import generate_skill, SkillSpec, ModelConfig
        spec = SkillSpec(skill_name="test", model=ModelConfig(model_id=""))
        with pytest.raises(ValueError, match="model.model_id"):
            generate_skill(spec, metric_defs=sample_metric_defs, output_dir=temp_output_dir)

    def test_no_fields_works(self, sample_metric_defs, temp_output_dir):
        """Spec with no fields generates a valid skill package."""
        from generate_skill import generate_skill, SkillSpec, ModelConfig
        spec = SkillSpec(
            skill_name="test_empty",
            model=ModelConfig(model_id="test-model"),
            fields=[],
        )
        package = generate_skill(spec, metric_defs=sample_metric_defs, output_dir=temp_output_dir)
        assert package is not None
        assert len(package.skill_hash) == 64
        assert package.manifest["skill_name"] == "test_empty"

    def test_metric_not_found_raises(self, temp_output_dir):
        """Referencing a metric_id not in metric_defs raises ValueError."""
        from generate_skill import generate_skill, SkillSpec, ModelConfig, FieldPipeline, MetricInstance
        spec = SkillSpec(
            skill_name="test_missing",
            model=ModelConfig(model_id="test-model"),
            fields=[
                FieldPipeline(
                    name="f1",
                    score_pipeline=[
                        MetricInstance(metric_id="nonexistent_metric", zone="score"),
                    ],
                ),
            ],
        )
        with pytest.raises(ValueError, match="Metric definition not found"):
            generate_skill(spec, metric_defs={}, output_dir=temp_output_dir)

    def test_metric_instance_no_metric_id_raises(self, sample_metric_defs, temp_output_dir):
        """MetricInstance with empty metric_id raises ValueError."""
        from generate_skill import generate_skill, SkillSpec, ModelConfig, FieldPipeline, MetricInstance
        spec = SkillSpec(
            skill_name="test_empty_id",
            model=ModelConfig(model_id="test-model"),
            fields=[
                FieldPipeline(
                    name="f1",
                    score_pipeline=[
                        MetricInstance(metric_id="", zone="score"),
                    ],
                ),
            ],
        )
        with pytest.raises(ValueError, match="missing metric_id"):
            generate_skill(spec, metric_defs=sample_metric_defs, output_dir=temp_output_dir)

    def test_manifest_has_all_required_fields(self, sample_spec, sample_metric_defs, temp_output_dir):
        """manifest.json contains all required fields."""
        from generate_skill import generate_skill
        package = generate_skill(sample_spec, metric_defs=sample_metric_defs, output_dir=temp_output_dir)
        manifest = package.manifest
        required = [
            "skill_name", "skill_hash", "generated_at", "generator_version",
            "template", "model", "metric_versions", "fields", "file_hashes",
        ]
        for field in required:
            assert field in manifest, f"Missing required field: {field}"

    def test_manifest_skill_hash_not_empty(self, sample_spec, sample_metric_defs, temp_output_dir):
        """manifest skill_hash is a non-empty 64-char hex string."""
        from generate_skill import generate_skill
        package = generate_skill(sample_spec, metric_defs=sample_metric_defs, output_dir=temp_output_dir)
        sh = package.manifest["skill_hash"]
        assert len(sh) == 64
        assert all(c in "0123456789abcdef" for c in sh)

    def test_manifest_metric_versions_match(self, sample_spec, sample_metric_defs, temp_output_dir):
        """manifest metric_versions match the spec's metric_versions."""
        from generate_skill import generate_skill
        package = generate_skill(sample_spec, metric_defs=sample_metric_defs, output_dir=temp_output_dir)
        manifest = package.manifest
        assert "metric_versions" in manifest
        assert manifest["metric_versions"]["accuracy"] == "a" * 64


# ═══════════════════════════════════════════════════════════════════════════════
# 4. Run Store — Malformed Input Tests
# ═══════════════════════════════════════════════════════════════════════════════

class TestRunMalformedInput:
    """Verify RunStore rejects all forms of malformed input."""

    def test_submit_report_not_dict(self, run_store):
        """submit rejects a string report with VALIDATION_ERROR."""
        manifest = _sample_manifest()
        result = run_store.submit("not a dict", manifest)
        assert result["ok"] is False
        assert result["error"]["code"] == "VALIDATION_ERROR"

    def test_submit_manifest_not_dict(self, run_store):
        """submit rejects a string manifest with VALIDATION_ERROR."""
        report = _sample_report()
        result = run_store.submit(report, "not a dict")
        assert result["ok"] is False
        assert result["error"]["code"] == "VALIDATION_ERROR"

    def test_submit_report_missing_skill(self, run_store):
        """submit rejects report missing 'skill' with VALIDATION_ERROR."""
        report = _sample_report()
        del report["skill"]
        manifest = _sample_manifest()
        result = run_store.submit(report, manifest)
        assert result["ok"] is False
        assert result["error"]["code"] == "VALIDATION_ERROR"

    def test_submit_report_missing_overall_score(self, run_store):
        """submit rejects report missing 'overall_score' with VALIDATION_ERROR."""
        report = _sample_report()
        del report["overall_score"]
        manifest = _sample_manifest()
        result = run_store.submit(report, manifest)
        assert result["ok"] is False
        assert result["error"]["code"] == "VALIDATION_ERROR"

    def test_submit_report_missing_fields(self, run_store):
        """submit rejects report missing 'fields' with VALIDATION_ERROR."""
        report = _sample_report()
        del report["fields"]
        manifest = _sample_manifest()
        result = run_store.submit(report, manifest)
        assert result["ok"] is False
        assert result["error"]["code"] == "VALIDATION_ERROR"

    def test_submit_report_missing_cases(self, run_store):
        """submit rejects report missing 'cases' with VALIDATION_ERROR."""
        report = _sample_report()
        del report["cases"]
        manifest = _sample_manifest()
        result = run_store.submit(report, manifest)
        assert result["ok"] is False
        assert result["error"]["code"] == "VALIDATION_ERROR"

    def test_submit_report_overall_score_negative(self, run_store):
        """submit rejects negative overall_score (minimum: 0.0)."""
        report = _sample_report(overall_score=-0.1)
        manifest = _sample_manifest()
        result = run_store.submit(report, manifest)
        assert result["ok"] is False
        assert result["error"]["code"] == "VALIDATION_ERROR"

    def test_submit_report_pass_rate_negative(self, run_store):
        """submit rejects negative pass_rate (minimum: 0.0)."""
        report = _sample_report(pass_rate=-0.1)
        manifest = _sample_manifest()
        result = run_store.submit(report, manifest)
        assert result["ok"] is False
        assert result["error"]["code"] == "VALIDATION_ERROR"

    def test_submit_report_n_cases_negative(self, run_store):
        """submit rejects negative n_cases (minimum: 0)."""
        report = _sample_report(n_cases=-1)
        manifest = _sample_manifest()
        result = run_store.submit(report, manifest)
        assert result["ok"] is False
        assert result["error"]["code"] == "VALIDATION_ERROR"

    def test_submit_manifest_hash_mismatch(self, run_store):
        """submit rejects manifest with wrong hash with MANIFEST_MISMATCH."""
        report = _sample_report()
        manifest = _sample_manifest()
        manifest["manifest_hash"] = "f" * 64
        result = run_store.submit(report, manifest)
        assert result["ok"] is False
        assert result["error"]["code"] == "MANIFEST_MISMATCH"

    def test_submit_duplicate_run_id(self, run_store):
        """submit rejects duplicate run_id with DUPLICATE_RUN."""
        import run_manifest as rm
        report = _sample_report()
        manifest = _sample_manifest(run_id="run_20260818_001")
        manifest["manifest_hash"] = rm.compute_manifest_hash(manifest)
        r1 = run_store.submit(report, manifest, run_id="run_20260818_001")
        assert r1["ok"] is True
        r2 = run_store.submit(report, manifest, run_id="run_20260818_001")
        assert r2["ok"] is False
        assert r2["error"]["code"] == "DUPLICATE_RUN"

    def test_submit_invalid_triggered_by(self, run_store):
        """submit rejects manifest with invalid triggered_by (enum: agent, ui)."""
        import run_manifest as rm
        report = _sample_report()
        manifest = _sample_manifest(triggered_by="invalid_trigger")
        manifest["manifest_hash"] = rm.compute_manifest_hash(manifest)
        result = run_store.submit(report, manifest)
        assert result["ok"] is False
        assert result["error"]["code"] == "VALIDATION_ERROR"

    def test_get_nonexistent(self, run_store):
        """get returns NOT_FOUND for a nonexistent run."""
        result = run_store.get("run_nonexistent")
        assert result["ok"] is False
        assert result["error"]["code"] == "NOT_FOUND"

    def test_compare_nonexistent(self, run_store):
        """compare returns NOT_FOUND for a nonexistent run."""
        report = _sample_report()
        manifest = _sample_manifest()
        run_store.submit(report, manifest)
        # Get the auto-generated run_id
        list_result = run_store.list()
        run_id = list_result["data"][0]["run_id"]
        result = run_store.compare(run_id, "run_nonexistent")
        assert result["ok"] is False
        assert result["error"]["code"] == "NOT_FOUND"


# ═══════════════════════════════════════════════════════════════════════════════
# 5. Immutable Version Tests
# ═══════════════════════════════════════════════════════════════════════════════

class TestImmutableVersions:
    """Verify version data is truly immutable — never silently overwritten."""

    def test_metric_version_never_overwritten(self, metric_store):
        """Creating a new version preserves the old version file."""
        r1 = metric_store.create(_sample_metric(criteria="Standard A"))
        vh1 = r1["data"]["version_hash"]

        r2 = metric_store.create_version("sample", _sample_metric(criteria="Standard B"))
        vh2 = r2["data"]["version_hash"]

        assert vh1 != vh2, "Different content should produce different hashes"

        # Both version files should exist
        vf1 = metric_store.base_dir / "llm" / ".versions" / "sample" / f"{vh1}.json"
        vf2 = metric_store.base_dir / "llm" / ".versions" / "sample" / f"{vh2}.json"
        assert vf1.is_file(), "Old version file should still exist"
        assert vf2.is_file(), "New version file should exist"

        # Old version content should be intact
        old_data = json.loads(vf1.read_text(encoding="utf-8"))
        assert old_data["criteria"] == "Standard A"

    def test_dataset_version_never_overwritten(self, dataset_store):
        """Creating a new dataset version preserves the old version file."""
        r1 = dataset_store.create("ds1", "Test", [{"case_id": 0, "input": "Q0", "expected_output": "A0"}])
        vh1 = r1["data"]["version_hash"]

        r2 = dataset_store.create_version("ds1", [{"case_id": 0, "input": "Q1", "expected_output": "A1"}])
        vh2 = r2["data"]["version_hash"]

        assert vh1 != vh2, "Different content should produce different hashes"

        # Both version files should exist
        vf1 = dataset_store.base_dir / "ds1" / ".versions" / f"{vh1}.json"
        vf2 = dataset_store.base_dir / "ds1" / ".versions" / f"{vh2}.json"
        assert vf1.is_file(), "Old version file should still exist"
        assert vf2.is_file(), "New version file should exist"

        # Old version content should be intact
        old_data = json.loads(vf1.read_text(encoding="utf-8"))
        assert old_data["n_cases"] == 1

    def test_run_never_overwritten(self, run_store):
        """Submitting a duplicate run_id is rejected — never overwrites."""
        import run_manifest as rm
        report = _sample_report()
        manifest = _sample_manifest()
        # First submit succeeds
        r1 = run_store.submit(report, manifest, run_id="run_20260818_009")
        assert r1["ok"] is True

        # Second submit with same run_id must fail
        manifest2 = _sample_manifest()
        manifest2["manifest_hash"] = rm.compute_manifest_hash(manifest2)
        r2 = run_store.submit(report, manifest2, run_id="run_20260818_009")
        assert r2["ok"] is False
        assert r2["error"]["code"] == "DUPLICATE_RUN"

        # The original run data should still be intact
        get_result = run_store.get("run_20260818_009")
        assert get_result["ok"] is True
        assert get_result["data"]["meta"]["overall_score"] == 0.85


# ═══════════════════════════════════════════════════════════════════════════════
# 6. Provenance Tests
# ═══════════════════════════════════════════════════════════════════════════════

class TestProvenance:
    """Verify provenance information is correctly recorded and verifiable."""

    def test_manifest_hash_in_report(self, run_store):
        """After submit, results.json contains the manifest_hash."""
        report = _sample_report()
        manifest = _sample_manifest()
        result = run_store.submit(report, manifest)
        assert result["ok"] is True
        run_id = result["data"]["run_id"]

        results_path = run_store.runs_dir / run_id / "results.json"
        results = json.loads(results_path.read_text(encoding="utf-8"))
        assert "manifest_hash" in results
        assert results["manifest_hash"] == result["data"]["manifest_hash"]
        assert len(results["manifest_hash"]) == 64

    def test_metric_versions_in_manifest(self, run_store):
        """After submit, manifest.json contains metric version_hashes."""
        report = _sample_report()
        manifest = _sample_manifest()
        result = run_store.submit(report, manifest)
        assert result["ok"] is True
        run_id = result["data"]["run_id"]

        manifest_path = run_store.runs_dir / run_id / "manifest.json"
        written = json.loads(manifest_path.read_text(encoding="utf-8"))
        assert "metrics" in written
        assert len(written["metrics"]) >= 1
        for m in written["metrics"]:
            assert "metric_id" in m
            assert "version_hash" in m
            assert len(m["version_hash"]) == 64

    def test_dataset_version_in_manifest(self, run_store):
        """After submit, manifest.json contains dataset version info."""
        report = _sample_report()
        manifest = _sample_manifest()
        result = run_store.submit(report, manifest)
        assert result["ok"] is True
        run_id = result["data"]["run_id"]

        manifest_path = run_store.runs_dir / run_id / "manifest.json"
        written = json.loads(manifest_path.read_text(encoding="utf-8"))
        assert "dataset" in written
        ds = written["dataset"]
        assert ds["dataset_id"] == "test_ds"
        assert len(ds["version_hash"]) == 64
        assert len(ds["content_hash"]) == 64
        assert ds["n_cases"] == 10

    def test_skill_in_manifest(self, run_store):
        """After submit, manifest.json contains skill info."""
        report = _sample_report()
        manifest = _sample_manifest()
        result = run_store.submit(report, manifest)
        assert result["ok"] is True
        run_id = result["data"]["run_id"]

        manifest_path = run_store.runs_dir / run_id / "manifest.json"
        written = json.loads(manifest_path.read_text(encoding="utf-8"))
        assert "skill" in written
        assert written["skill"]["name"] == "my_eval"
        assert len(written["skill"]["content_hash"]) == 64


# ═══════════════════════════════════════════════════════════════════════════════
# 7. Structured Error Tests
# ═══════════════════════════════════════════════════════════════════════════════

class TestStructuredErrors:
    """Verify all error responses have a consistent structure."""

    def test_all_errors_have_code(self, metric_store, dataset_store, run_store):
        """Every error response has an 'error.code' field."""
        # MetricStore errors
        r1 = metric_store.get("nonexistent")
        assert r1["ok"] is False
        assert "code" in r1["error"]
        assert isinstance(r1["error"]["code"], str)

        r2 = metric_store.create("not a dict")
        assert r2["ok"] is False
        assert "code" in r2["error"]

        r3 = metric_store.create(_sample_metric())
        r3b = metric_store.create(_sample_metric())
        assert r3b["ok"] is False
        assert "code" in r3b["error"]

        # DatasetStore errors
        r4 = dataset_store.get("nonexistent")
        assert r4["ok"] is False
        assert "code" in r4["error"]

        r5 = dataset_store.create("ds1", "Test", [])
        assert r5["ok"] is False
        assert "code" in r5["error"]

        # RunStore errors
        r6 = run_store.get("run_nonexistent")
        assert r6["ok"] is False
        assert "code" in r6["error"]

        report = _sample_report()
        del report["overall_score"]
        manifest = _sample_manifest()
        r7 = run_store.submit(report, manifest)
        assert r7["ok"] is False
        assert "code" in r7["error"]

    def test_all_errors_have_message(self, metric_store, dataset_store, run_store):
        """Every error response has a non-empty 'error.message' field."""
        # MetricStore
        r1 = metric_store.get("nonexistent")
        assert "message" in r1["error"]
        assert isinstance(r1["error"]["message"], str)
        assert len(r1["error"]["message"]) > 0

        # DatasetStore
        r2 = dataset_store.get("nonexistent")
        assert "message" in r2["error"]
        assert len(r2["error"]["message"]) > 0

        # RunStore
        r3 = run_store.get("run_nonexistent")
        assert "message" in r3["error"]
        assert len(r3["error"]["message"]) > 0

    def test_error_codes_are_consistent(self, metric_store, dataset_store, run_store):
        """Error codes are from a known, consistent set."""
        valid_codes = {
            "VALIDATION_ERROR",
            "NOT_FOUND",
            "DUPLICATE_ID",
            "DUPLICATE_RUN",
            "MANIFEST_MISMATCH",
            "INVALID_CASES",
            "INVALID_REPORT",
            "INTERNAL_ERROR",
        }

        # Collect errors from all stores
        errors = []

        # MetricStore
        errors.append(metric_store.get("nonexistent"))
        errors.append(metric_store.create("not a dict"))
        metric_store.create(_sample_metric())
        errors.append(metric_store.create(_sample_metric()))  # duplicate

        # DatasetStore
        errors.append(dataset_store.get("nonexistent"))
        errors.append(dataset_store.create("ds1", "Test", []))  # empty cases
        dataset_store.create("ds1", "Test", _sample_cases(2))
        errors.append(dataset_store.create("ds1", "Test", _sample_cases(2)))  # duplicate

        # RunStore
        errors.append(run_store.get("run_nonexistent"))
        report = _sample_report()
        del report["overall_score"]
        manifest = _sample_manifest()
        errors.append(run_store.submit(report, manifest))

        manifest2 = _sample_manifest()
        manifest2["manifest_hash"] = "f" * 64
        errors.append(run_store.submit(_sample_report(), manifest2))

        for err in errors:
            if err["ok"] is False:
                code = err["error"]["code"]
                assert code in valid_codes, (
                    f"Unknown error code: '{code}'. "
                    f"Expected one of: {sorted(valid_codes)}"
                )