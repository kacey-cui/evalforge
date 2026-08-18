"""eval_diff 模块测试（pytest）。

覆盖所有设计要求的 12 条测试用例。
所有 fixture 均使用 tempfile.TemporaryDirectory()，绝不读写真实 data/。
"""

import json
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from eval_diff import eval_diff, _compare_scores, _compare_dataset, _compare_metrics
from eval_diff import _compare_skill, _compare_model, _compare_judge
from eval_diff import _generate_summary
from metric_store import MetricStore
from dataset_store import DatasetStore


# ── Helpers ────────────────────────────────────────────────────────────────────


def _make_metric_dict(metric_id, name, category="llm", extra_params=None):
    """Build a minimal valid metric dict that passes METRIC_SCHEMA."""
    params = [
        {"key": "threshold", "type": "number", "default": 0.5},
    ]
    if extra_params:
        params.extend(extra_params)
    return {
        "id": metric_id,
        "name": name,
        "category": category,
        "description": f"Test metric: {name}",
        "params": params,
        "criteria": None,
        "requires": [],
        "code_template": "def evaluate(case, response):\n    return 1.0",
    }


def _make_cases(n=3):
    """Build a minimal list of cases."""
    return [
        {"case_id": i, "question": f"Q{i}", "answer": f"A{i}"}
        for i in range(n)
    ]


def _make_manifest(overrides=None):
    """Build a complete manifest dict with sensible defaults."""
    m = {
        "manifest_version": "1.0",
        "manifest_hash": "",
        "run_id": "run_test",
        "created_at": "2026-08-18T10:00:00Z",
        "triggered_by": "agent",
        "dataset": {
            "dataset_id": "ds_test",
            "version_hash": "0" * 64,
            "content_hash": "0" * 64,
            "n_cases": 3,
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
            "model_id": "gpt-4",
            "base_url": "https://api.openai.com/v1",
        },
        "judge_model": None,
        "environment": {
            "python_version": "3.10.0",
            "platform": "test",
            "dependencies": {},
        },
        "extra": {},
    }
    if overrides:
        _deep_update(m, overrides)
    return m


def _make_results(overrides=None):
    """Build a complete results dict with sensible defaults."""
    r = {
        "skill": "my_eval",
        "created_at": "2026-08-18T10:00:00Z",
        "n_cases": 3,
        "n_passed": 3,
        "pass_rate": 1.0,
        "overall_score": 0.9,
        "grade": "A",
        "fields": {
            "diagnosis": {"field_score": 0.9},
            "treatment": {"field_score": 0.85},
        },
        "cases": [
            {"case_id": 0, "question": "Q0", "answer": "A0", "score": 1.0},
            {"case_id": 1, "question": "Q1", "answer": "A1", "score": 0.9},
            {"case_id": 2, "question": "Q2", "answer": "A2", "score": 0.8},
        ],
        "config": {
            "metrics": [{"name": "accuracy", "metricId": "accuracy"}],
        },
    }
    if overrides:
        _deep_update(r, overrides)
    return r


def _deep_update(target, source):
    """Recursively update dict target with dict source."""
    for key, value in source.items():
        if isinstance(value, dict) and isinstance(target.get(key), dict):
            _deep_update(target[key], value)
        else:
            target[key] = value


def _create_run(runs_dir, run_id, manifest, results):
    """Create a complete run directory with all 5 files."""
    run_dir = runs_dir / run_id
    run_dir.mkdir(parents=True)

    # Write manifest.json
    (run_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # Write results.json
    (run_dir / "results.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # Write meta.json (quick summary)
    fields = {}
    for k, v in (results.get("fields") or {}).items():
        if isinstance(v, dict):
            fields[k] = {"field_score": v.get("field_score")}
        else:
            fields[k] = v
    meta = {
        "run_id": run_id,
        "project": (manifest.get("skill") or {}).get("name") or (manifest.get("dataset") or {}).get("dataset_id"),
        "triggered_by": manifest.get("triggered_by", "agent"),
        "timestamp": manifest.get("created_at", ""),
        "status": "completed",
        "overall_score": results.get("overall_score"),
        "pass_rate": results.get("pass_rate"),
        "fields": fields,
        "metrics": [m.get("metric_id") for m in manifest.get("metrics", [])],
    }
    (run_dir / "meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # Write config.json
    config = results.get("config") or {}
    (run_dir / "config.json").write_text(
        json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # Write dataset_ref.json
    ds = manifest.get("dataset") or {}
    dataset_ref = {
        "n_cases": ds.get("n_cases", 0),
        "dataset_id": ds.get("dataset_id"),
        "version_hash": ds.get("version_hash"),
        "content_hash": ds.get("content_hash"),
        "source_path": ds.get("source_path"),
    }
    (run_dir / "dataset_ref.json").write_text(
        json.dumps(dataset_ref, ensure_ascii=False, indent=2), encoding="utf-8"
    )


# ── Fixtures ───────────────────────────────────────────────────────────────────


@pytest.fixture
def tmp_env():
    """Provide temp directories for runs, metrics, and datasets with pre-created versions."""
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        runs_dir = base / "runs"
        runs_dir.mkdir()
        metrics_dir = base / "metrics"
        metrics_dir.mkdir()
        datasets_dir = base / "datasets"
        datasets_dir.mkdir()

        # Create metric version v1
        metric_store = MetricStore(base_dir=metrics_dir)
        m1 = _make_metric_dict("accuracy", "Accuracy")
        r1 = metric_store.create(m1)
        assert r1["ok"], f"Create metric v1 failed: {r1}"
        v1_hash = r1["data"]["version_hash"]

        # Create metric version v2 (modified — adds a param)
        m2 = _make_metric_dict("accuracy", "Accuracy", extra_params=[
            {"key": "strict", "type": "boolean", "default": False},
        ])
        r2 = metric_store.create_version("accuracy", m2)
        assert r2["ok"], f"Create metric v2 failed: {r2}"
        v2_hash = r2["data"]["version_hash"]

        # Create a second metric for added/removed tests
        m3 = _make_metric_dict("completeness", "Completeness", category="non_llm")
        r3 = metric_store.create(m3)
        assert r3["ok"], f"Create metric completeness failed: {r3}"
        completeness_hash = r3["data"]["version_hash"]

        # Create dataset version v1
        dataset_store = DatasetStore(base_dir=datasets_dir)
        cases_v1 = _make_cases(3)
        d1 = dataset_store.create("ds_test", "Test Dataset", cases_v1)
        assert d1["ok"], f"Create dataset v1 failed: {d1}"
        ds_v1_hash = d1["data"]["version_hash"]
        ds_v1_content = d1["data"]["content_hash"]

        # Create dataset version v2 (different cases)
        cases_v2 = [
            {"case_id": 0, "question": "Q0 modified", "answer": "A0"},
            {"case_id": 1, "question": "Q1", "answer": "A1 modified"},
            {"case_id": 2, "question": "Q2", "answer": "A2"},
        ]
        d2 = dataset_store.create_version("ds_test", cases_v2)
        assert d2["ok"], f"Create dataset v2 failed: {d2}"
        ds_v2_hash = d2["data"]["version_hash"]
        ds_v2_content = d2["data"]["content_hash"]

        yield {
            "runs_dir": runs_dir,
            "metrics_dir": metrics_dir,
            "datasets_dir": datasets_dir,
            "metric_v1_hash": v1_hash,
            "metric_v2_hash": v2_hash,
            "completeness_hash": completeness_hash,
            "ds_v1_hash": ds_v1_hash,
            "ds_v1_content": ds_v1_content,
            "ds_v2_hash": ds_v2_hash,
            "ds_v2_content": ds_v2_content,
        }


def _eval_diff_in_env(env, run_id_a, run_id_b):
    """Call eval_diff using the temp env directories."""
    return eval_diff(
        run_id_a, run_id_b,
        runs_dir=env["runs_dir"],
        metrics_dir=env["metrics_dir"],
        datasets_dir=env["datasets_dir"],
    )


# ── Test 1: Same runs → no diffs, score_delta=0 ────────────────────────────────


def test_same_runs_no_diff(tmp_env):
    """Test 1: Two identical runs produce no diffs."""
    env = tmp_env
    manifest = _make_manifest({
        "dataset": {
            "dataset_id": "ds_test",
            "version_hash": env["ds_v1_hash"],
            "content_hash": env["ds_v1_content"],
            "n_cases": 3,
        },
        "metrics": [{
            "metric_id": "accuracy",
            "version_hash": env["metric_v1_hash"],
            "instance": {
                "label": "Accuracy",
                "params": {},
                "weight": 1.0,
                "strictness": 1.0,
                "zone": "score",
            },
        }],
    })
    results = _make_results()

    _create_run(env["runs_dir"], "run_a", manifest, results)
    _create_run(env["runs_dir"], "run_b", manifest, results)

    result = _eval_diff_in_env(env, "run_a", "run_b")
    assert result["ok"], f"eval_diff failed: {result}"

    data = result["data"]
    assert data["score_comparison"]["overall"]["delta"] == 0.0
    assert data["dataset"]["status"] == "unchanged"
    assert data["skill"]["status"] == "unchanged"
    assert data["model"]["status"] == "unchanged"
    assert data["judge"]["status"] == "unchanged"
    for m in data["metrics"]:
        assert m["status"] == "unchanged"


# ── Test 2: Different dataset → dataset status "modified" ──────────────────────


def test_different_dataset_modified(tmp_env):
    """Test 2: Different dataset version produces status 'modified'."""
    env = tmp_env
    manifest_a = _make_manifest({
        "dataset": {
            "dataset_id": "ds_test",
            "version_hash": env["ds_v1_hash"],
            "content_hash": env["ds_v1_content"],
            "n_cases": 3,
        },
        "metrics": [{
            "metric_id": "accuracy",
            "version_hash": env["metric_v1_hash"],
            "instance": {
                "label": "Accuracy",
                "params": {},
                "weight": 1.0,
                "strictness": 1.0,
                "zone": "score",
            },
        }],
    })
    manifest_b = _make_manifest({
        "dataset": {
            "dataset_id": "ds_test",
            "version_hash": env["ds_v2_hash"],
            "content_hash": env["ds_v2_content"],
            "n_cases": 3,
        },
        "metrics": [{
            "metric_id": "accuracy",
            "version_hash": env["metric_v1_hash"],
            "instance": {
                "label": "Accuracy",
                "params": {},
                "weight": 1.0,
                "strictness": 1.0,
                "zone": "score",
            },
        }],
    })
    results = _make_results()

    _create_run(env["runs_dir"], "run_a", manifest_a, results)
    _create_run(env["runs_dir"], "run_b", manifest_b, results)

    result = _eval_diff_in_env(env, "run_a", "run_b")
    assert result["ok"], f"eval_diff failed: {result}"

    data = result["data"]
    assert data["dataset"]["status"] == "modified"
    assert data["dataset"]["dataset_id"] == "ds_test"
    assert data["dataset"]["version_a"] == env["ds_v1_hash"]
    assert data["dataset"]["version_b"] == env["ds_v2_hash"]
    assert data["dataset"]["detail"] is not None


# ── Test 3: Different metric version → status "modified" with field_diff ───────


def test_metric_version_modified(tmp_env):
    """Test 3: Different metric version hash produces status 'modified' with field_diff."""
    env = tmp_env
    manifest_a = _make_manifest({
        "dataset": {
            "dataset_id": "ds_test",
            "version_hash": env["ds_v1_hash"],
            "content_hash": env["ds_v1_content"],
            "n_cases": 3,
        },
        "metrics": [{
            "metric_id": "accuracy",
            "version_hash": env["metric_v1_hash"],
            "instance": {
                "label": "Accuracy",
                "params": {},
                "weight": 1.0,
                "strictness": 1.0,
                "zone": "score",
            },
        }],
    })
    manifest_b = _make_manifest({
        "dataset": {
            "dataset_id": "ds_test",
            "version_hash": env["ds_v1_hash"],
            "content_hash": env["ds_v1_content"],
            "n_cases": 3,
        },
        "metrics": [{
            "metric_id": "accuracy",
            "version_hash": env["metric_v2_hash"],
            "instance": {
                "label": "Accuracy",
                "params": {},
                "weight": 1.0,
                "strictness": 1.0,
                "zone": "score",
            },
        }],
    })
    results = _make_results()

    _create_run(env["runs_dir"], "run_a", manifest_a, results)
    _create_run(env["runs_dir"], "run_b", manifest_b, results)

    result = _eval_diff_in_env(env, "run_a", "run_b")
    assert result["ok"], f"eval_diff failed: {result}"

    data = result["data"]
    accuracy = [m for m in data["metrics"] if m["metric_id"] == "accuracy"]
    assert len(accuracy) == 1
    acc = accuracy[0]
    assert acc["status"] == "modified"
    assert acc["version_a"] == env["metric_v1_hash"]
    assert acc["version_b"] == env["metric_v2_hash"]
    # Should have detail with field-level diff
    assert acc["detail"] is not None
    assert "changes" in acc["detail"]


# ── Test 4a: Metric added → status "added" ─────────────────────────────────────


def test_metric_added(tmp_env):
    """Test 4a: Metric only in run B produces status 'added'."""
    env = tmp_env
    manifest_a = _make_manifest({
        "dataset": {
            "dataset_id": "ds_test",
            "version_hash": env["ds_v1_hash"],
            "content_hash": env["ds_v1_content"],
            "n_cases": 3,
        },
        "metrics": [{
            "metric_id": "accuracy",
            "version_hash": env["metric_v1_hash"],
            "instance": {
                "label": "Accuracy",
                "params": {},
                "weight": 1.0,
                "strictness": 1.0,
                "zone": "score",
            },
        }],
    })
    manifest_b = _make_manifest({
        "dataset": {
            "dataset_id": "ds_test",
            "version_hash": env["ds_v1_hash"],
            "content_hash": env["ds_v1_content"],
            "n_cases": 3,
        },
        "metrics": [
            {
                "metric_id": "accuracy",
                "version_hash": env["metric_v1_hash"],
                "instance": {
                    "label": "Accuracy",
                    "params": {},
                    "weight": 1.0,
                    "strictness": 1.0,
                    "zone": "score",
                },
            },
            {
                "metric_id": "completeness",
                "version_hash": env["completeness_hash"],
                "instance": {
                    "label": "Completeness",
                    "params": {},
                    "weight": 0.5,
                    "strictness": 1.0,
                    "zone": "score",
                },
            },
        ],
    })
    results = _make_results()

    _create_run(env["runs_dir"], "run_a", manifest_a, results)
    _create_run(env["runs_dir"], "run_b", manifest_b, results)

    result = _eval_diff_in_env(env, "run_a", "run_b")
    assert result["ok"], f"eval_diff failed: {result}"

    data = result["data"]
    completeness = [m for m in data["metrics"] if m["metric_id"] == "completeness"]
    assert len(completeness) == 1
    assert completeness[0]["status"] == "added"
    assert completeness[0]["version_a"] is None
    assert completeness[0]["version_b"] == env["completeness_hash"]


# ── Test 4b: Metric removed → status "removed" ─────────────────────────────────


def test_metric_removed(tmp_env):
    """Test 4b: Metric only in run A produces status 'removed'."""
    env = tmp_env
    manifest_a = _make_manifest({
        "dataset": {
            "dataset_id": "ds_test",
            "version_hash": env["ds_v1_hash"],
            "content_hash": env["ds_v1_content"],
            "n_cases": 3,
        },
        "metrics": [
            {
                "metric_id": "accuracy",
                "version_hash": env["metric_v1_hash"],
                "instance": {
                    "label": "Accuracy",
                    "params": {},
                    "weight": 1.0,
                    "strictness": 1.0,
                    "zone": "score",
                },
            },
            {
                "metric_id": "completeness",
                "version_hash": env["completeness_hash"],
                "instance": {
                    "label": "Completeness",
                    "params": {},
                    "weight": 0.5,
                    "strictness": 1.0,
                    "zone": "score",
                },
            },
        ],
    })
    manifest_b = _make_manifest({
        "dataset": {
            "dataset_id": "ds_test",
            "version_hash": env["ds_v1_hash"],
            "content_hash": env["ds_v1_content"],
            "n_cases": 3,
        },
        "metrics": [{
            "metric_id": "accuracy",
            "version_hash": env["metric_v1_hash"],
            "instance": {
                "label": "Accuracy",
                "params": {},
                "weight": 1.0,
                "strictness": 1.0,
                "zone": "score",
            },
        }],
    })
    results = _make_results()

    _create_run(env["runs_dir"], "run_a", manifest_a, results)
    _create_run(env["runs_dir"], "run_b", manifest_b, results)

    result = _eval_diff_in_env(env, "run_a", "run_b")
    assert result["ok"], f"eval_diff failed: {result}"

    data = result["data"]
    completeness = [m for m in data["metrics"] if m["metric_id"] == "completeness"]
    assert len(completeness) == 1
    assert completeness[0]["status"] == "removed"
    assert completeness[0]["version_a"] == env["completeness_hash"]
    assert completeness[0]["version_b"] is None


# ── Test 5: Different skill hash → skill status "modified" ─────────────────────


def test_skill_modified(tmp_env):
    """Test 5: Different skill content_hash produces status 'modified'."""
    env = tmp_env
    manifest_a = _make_manifest({
        "dataset": {
            "dataset_id": "ds_test",
            "version_hash": env["ds_v1_hash"],
            "content_hash": env["ds_v1_content"],
            "n_cases": 3,
        },
        "metrics": [{
            "metric_id": "accuracy",
            "version_hash": env["metric_v1_hash"],
            "instance": {
                "label": "Accuracy",
                "params": {},
                "weight": 1.0,
                "strictness": 1.0,
                "zone": "score",
            },
        }],
        "skill": {
            "name": "my_eval",
            "content_hash": "a" * 64,
        },
    })
    manifest_b = _make_manifest({
        "dataset": {
            "dataset_id": "ds_test",
            "version_hash": env["ds_v1_hash"],
            "content_hash": env["ds_v1_content"],
            "n_cases": 3,
        },
        "metrics": [{
            "metric_id": "accuracy",
            "version_hash": env["metric_v1_hash"],
            "instance": {
                "label": "Accuracy",
                "params": {},
                "weight": 1.0,
                "strictness": 1.0,
                "zone": "score",
            },
        }],
        "skill": {
            "name": "my_eval",
            "content_hash": "b" * 64,
        },
    })
    results = _make_results()

    _create_run(env["runs_dir"], "run_a", manifest_a, results)
    _create_run(env["runs_dir"], "run_b", manifest_b, results)

    result = _eval_diff_in_env(env, "run_a", "run_b")
    assert result["ok"], f"eval_diff failed: {result}"

    data = result["data"]
    assert data["skill"]["status"] == "modified"
    assert data["skill"]["hash_a"] == "a" * 64
    assert data["skill"]["hash_b"] == "b" * 64


# ── Test 6: Different model → model status "modified" ──────────────────────────


def test_model_modified(tmp_env):
    """Test 6: Different model produces status 'modified'."""
    env = tmp_env
    manifest_a = _make_manifest({
        "dataset": {
            "dataset_id": "ds_test",
            "version_hash": env["ds_v1_hash"],
            "content_hash": env["ds_v1_content"],
            "n_cases": 3,
        },
        "metrics": [{
            "metric_id": "accuracy",
            "version_hash": env["metric_v1_hash"],
            "instance": {
                "label": "Accuracy",
                "params": {},
                "weight": 1.0,
                "strictness": 1.0,
                "zone": "score",
            },
        }],
        "model": {
            "model_id": "gpt-4",
            "base_url": "https://api.openai.com/v1",
        },
    })
    manifest_b = _make_manifest({
        "dataset": {
            "dataset_id": "ds_test",
            "version_hash": env["ds_v1_hash"],
            "content_hash": env["ds_v1_content"],
            "n_cases": 3,
        },
        "metrics": [{
            "metric_id": "accuracy",
            "version_hash": env["metric_v1_hash"],
            "instance": {
                "label": "Accuracy",
                "params": {},
                "weight": 1.0,
                "strictness": 1.0,
                "zone": "score",
            },
        }],
        "model": {
            "model_id": "gpt-4o",
            "base_url": "https://api.openai.com/v1",
        },
    })
    results = _make_results()

    _create_run(env["runs_dir"], "run_a", manifest_a, results)
    _create_run(env["runs_dir"], "run_b", manifest_b, results)

    result = _eval_diff_in_env(env, "run_a", "run_b")
    assert result["ok"], f"eval_diff failed: {result}"

    data = result["data"]
    assert data["model"]["status"] == "modified"
    assert data["model"]["model_id_a"] == "gpt-4"
    assert data["model"]["model_id_b"] == "gpt-4o"
    assert data["model"]["diff"] is not None
    assert "model_id" in data["model"]["diff"]


# ── Test 7: Different judge → judge status "modified" ──────────────────────────


def test_judge_modified(tmp_env):
    """Test 7: Different judge model produces status 'modified'."""
    env = tmp_env
    manifest_a = _make_manifest({
        "dataset": {
            "dataset_id": "ds_test",
            "version_hash": env["ds_v1_hash"],
            "content_hash": env["ds_v1_content"],
            "n_cases": 3,
        },
        "metrics": [{
            "metric_id": "accuracy",
            "version_hash": env["metric_v1_hash"],
            "instance": {
                "label": "Accuracy",
                "params": {},
                "weight": 1.0,
                "strictness": 1.0,
                "zone": "score",
            },
        }],
        "judge_model": {
            "model_id": "gpt-4",
            "base_url": "https://api.openai.com/v1",
        },
    })
    manifest_b = _make_manifest({
        "dataset": {
            "dataset_id": "ds_test",
            "version_hash": env["ds_v1_hash"],
            "content_hash": env["ds_v1_content"],
            "n_cases": 3,
        },
        "metrics": [{
            "metric_id": "accuracy",
            "version_hash": env["metric_v1_hash"],
            "instance": {
                "label": "Accuracy",
                "params": {},
                "weight": 1.0,
                "strictness": 1.0,
                "zone": "score",
            },
        }],
        "judge_model": {
            "model_id": "gpt-4o",
            "base_url": "https://api.openai.com/v1",
        },
    })
    results = _make_results()

    _create_run(env["runs_dir"], "run_a", manifest_a, results)
    _create_run(env["runs_dir"], "run_b", manifest_b, results)

    result = _eval_diff_in_env(env, "run_a", "run_b")
    assert result["ok"], f"eval_diff failed: {result}"

    data = result["data"]
    assert data["judge"]["status"] == "modified"
    assert data["judge"]["diff"] is not None
    assert "model_id" in data["judge"]["diff"]


def test_judge_added(tmp_env):
    """Test 7b: Judge added (was None, now has a model) produces status 'added'."""
    env = tmp_env
    manifest_a = _make_manifest({
        "dataset": {
            "dataset_id": "ds_test",
            "version_hash": env["ds_v1_hash"],
            "content_hash": env["ds_v1_content"],
            "n_cases": 3,
        },
        "metrics": [{
            "metric_id": "accuracy",
            "version_hash": env["metric_v1_hash"],
            "instance": {
                "label": "Accuracy",
                "params": {},
                "weight": 1.0,
                "strictness": 1.0,
                "zone": "score",
            },
        }],
        "judge_model": None,
    })
    manifest_b = _make_manifest({
        "dataset": {
            "dataset_id": "ds_test",
            "version_hash": env["ds_v1_hash"],
            "content_hash": env["ds_v1_content"],
            "n_cases": 3,
        },
        "metrics": [{
            "metric_id": "accuracy",
            "version_hash": env["metric_v1_hash"],
            "instance": {
                "label": "Accuracy",
                "params": {},
                "weight": 1.0,
                "strictness": 1.0,
                "zone": "score",
            },
        }],
        "judge_model": {
            "model_id": "gpt-4o",
            "base_url": "https://api.openai.com/v1",
        },
    })
    results = _make_results()

    _create_run(env["runs_dir"], "run_a", manifest_a, results)
    _create_run(env["runs_dir"], "run_b", manifest_b, results)

    result = _eval_diff_in_env(env, "run_a", "run_b")
    assert result["ok"], f"eval_diff failed: {result}"

    data = result["data"]
    assert data["judge"]["status"] == "added"
    assert data["judge"]["diff"]["a"] is None
    assert data["judge"]["diff"]["b"] is not None


def test_judge_removed(tmp_env):
    """Test 7c: Judge removed (was a model, now None) produces status 'removed'."""
    env = tmp_env
    manifest_a = _make_manifest({
        "dataset": {
            "dataset_id": "ds_test",
            "version_hash": env["ds_v1_hash"],
            "content_hash": env["ds_v1_content"],
            "n_cases": 3,
        },
        "metrics": [{
            "metric_id": "accuracy",
            "version_hash": env["metric_v1_hash"],
            "instance": {
                "label": "Accuracy",
                "params": {},
                "weight": 1.0,
                "strictness": 1.0,
                "zone": "score",
            },
        }],
        "judge_model": {
            "model_id": "gpt-4",
            "base_url": "https://api.openai.com/v1",
        },
    })
    manifest_b = _make_manifest({
        "dataset": {
            "dataset_id": "ds_test",
            "version_hash": env["ds_v1_hash"],
            "content_hash": env["ds_v1_content"],
            "n_cases": 3,
        },
        "metrics": [{
            "metric_id": "accuracy",
            "version_hash": env["metric_v1_hash"],
            "instance": {
                "label": "Accuracy",
                "params": {},
                "weight": 1.0,
                "strictness": 1.0,
                "zone": "score",
            },
        }],
        "judge_model": None,
    })
    results = _make_results()

    _create_run(env["runs_dir"], "run_a", manifest_a, results)
    _create_run(env["runs_dir"], "run_b", manifest_b, results)

    result = _eval_diff_in_env(env, "run_a", "run_b")
    assert result["ok"], f"eval_diff failed: {result}"

    data = result["data"]
    assert data["judge"]["status"] == "removed"
    assert data["judge"]["diff"]["a"] is not None
    assert data["judge"]["diff"]["b"] is None


# ── Test 8: Score changes → correct delta ──────────────────────────────────────


def test_score_changes_delta(tmp_env):
    """Test 8: Score differences produce correct delta."""
    env = tmp_env
    manifest = _make_manifest({
        "dataset": {
            "dataset_id": "ds_test",
            "version_hash": env["ds_v1_hash"],
            "content_hash": env["ds_v1_content"],
            "n_cases": 3,
        },
        "metrics": [{
            "metric_id": "accuracy",
            "version_hash": env["metric_v1_hash"],
            "instance": {
                "label": "Accuracy",
                "params": {},
                "weight": 1.0,
                "strictness": 1.0,
                "zone": "score",
            },
        }],
    })
    results_a = _make_results({"overall_score": 0.9})
    results_b = _make_results({"overall_score": 0.75})

    _create_run(env["runs_dir"], "run_a", manifest, results_a)
    _create_run(env["runs_dir"], "run_b", manifest, results_b)

    result = _eval_diff_in_env(env, "run_a", "run_b")
    assert result["ok"], f"eval_diff failed: {result}"

    data = result["data"]
    overall = data["score_comparison"]["overall"]
    assert overall["a"] == 0.9
    assert overall["b"] == 0.75
    assert overall["delta"] == -0.15


def test_field_score_delta(tmp_env):
    """Test 8b: Field-level score differences produce correct delta."""
    env = tmp_env
    manifest = _make_manifest({
        "dataset": {
            "dataset_id": "ds_test",
            "version_hash": env["ds_v1_hash"],
            "content_hash": env["ds_v1_content"],
            "n_cases": 3,
        },
        "metrics": [{
            "metric_id": "accuracy",
            "version_hash": env["metric_v1_hash"],
            "instance": {
                "label": "Accuracy",
                "params": {},
                "weight": 1.0,
                "strictness": 1.0,
                "zone": "score",
            },
        }],
    })
    results_a = _make_results({
        "fields": {
            "diagnosis": {"field_score": 0.9},
            "treatment": {"field_score": 0.85},
        },
    })
    results_b = _make_results({
        "fields": {
            "diagnosis": {"field_score": 0.7},
            "treatment": {"field_score": 0.95},
        },
    })

    _create_run(env["runs_dir"], "run_a", manifest, results_a)
    _create_run(env["runs_dir"], "run_b", manifest, results_b)

    result = _eval_diff_in_env(env, "run_a", "run_b")
    assert result["ok"], f"eval_diff failed: {result}"

    data = result["data"]
    fields = data["score_comparison"]["fields"]
    assert "diagnosis" in fields
    assert fields["diagnosis"]["a"] == 0.9
    assert fields["diagnosis"]["b"] == 0.7
    assert fields["diagnosis"]["delta"] == -0.2
    assert "treatment" in fields
    assert fields["treatment"]["a"] == 0.85
    assert fields["treatment"]["b"] == 0.95
    assert fields["treatment"]["delta"] == 0.1


# ── Test 9: Case-level diff → if cases have scores ─────────────────────────────


def test_case_level_diff(tmp_env):
    """Test 9: Case-level score differences are detected."""
    env = tmp_env
    manifest = _make_manifest({
        "dataset": {
            "dataset_id": "ds_test",
            "version_hash": env["ds_v1_hash"],
            "content_hash": env["ds_v1_content"],
            "n_cases": 3,
        },
        "metrics": [{
            "metric_id": "accuracy",
            "version_hash": env["metric_v1_hash"],
            "instance": {
                "label": "Accuracy",
                "params": {},
                "weight": 1.0,
                "strictness": 1.0,
                "zone": "score",
            },
        }],
    })
    results_a = _make_results({
        "cases": [
            {"case_id": 0, "score": 1.0},
            {"case_id": 1, "score": 0.9},
            {"case_id": 2, "score": 0.8},
        ],
    })
    results_b = _make_results({
        "cases": [
            {"case_id": 0, "score": 0.5},
            {"case_id": 1, "score": 0.9},
            {"case_id": 2, "score": 0.6},
        ],
    })

    _create_run(env["runs_dir"], "run_a", manifest, results_a)
    _create_run(env["runs_dir"], "run_b", manifest, results_b)

    result = _eval_diff_in_env(env, "run_a", "run_b")
    assert result["ok"], f"eval_diff failed: {result}"

    data = result["data"]
    case_diffs = data["score_comparison"]["cases"]
    # Cases 0 and 2 should differ
    assert len(case_diffs) == 2
    case_ids = {c["case_id"] for c in case_diffs}
    assert case_ids == {0, 2}
    for c in case_diffs:
        assert c["status"] == "modified"
        assert "score" in c


# ── Test 10: Summary is non-empty string ───────────────────────────────────────


def test_summary_non_empty(tmp_env):
    """Test 10: Summary is a non-empty Chinese string."""
    env = tmp_env
    manifest = _make_manifest({
        "dataset": {
            "dataset_id": "ds_test",
            "version_hash": env["ds_v1_hash"],
            "content_hash": env["ds_v1_content"],
            "n_cases": 3,
        },
        "metrics": [{
            "metric_id": "accuracy",
            "version_hash": env["metric_v1_hash"],
            "instance": {
                "label": "Accuracy",
                "params": {},
                "weight": 1.0,
                "strictness": 1.0,
                "zone": "score",
            },
        }],
    })
    results_a = _make_results({"overall_score": 0.9})
    results_b = _make_results({"overall_score": 0.75})

    _create_run(env["runs_dir"], "run_a", manifest, results_a)
    _create_run(env["runs_dir"], "run_b", manifest, results_b)

    result = _eval_diff_in_env(env, "run_a", "run_b")
    assert result["ok"], f"eval_diff failed: {result}"

    summary = result["data"]["summary"]
    assert isinstance(summary, str)
    assert len(summary) > 0


def test_summary_no_diff(tmp_env):
    """Test 10b: Summary for identical runs is also non-empty."""
    env = tmp_env
    manifest = _make_manifest({
        "dataset": {
            "dataset_id": "ds_test",
            "version_hash": env["ds_v1_hash"],
            "content_hash": env["ds_v1_content"],
            "n_cases": 3,
        },
        "metrics": [{
            "metric_id": "accuracy",
            "version_hash": env["metric_v1_hash"],
            "instance": {
                "label": "Accuracy",
                "params": {},
                "weight": 1.0,
                "strictness": 1.0,
                "zone": "score",
            },
        }],
    })
    results = _make_results()

    _create_run(env["runs_dir"], "run_a", manifest, results)
    _create_run(env["runs_dir"], "run_b", manifest, results)

    result = _eval_diff_in_env(env, "run_a", "run_b")
    assert result["ok"], f"eval_diff failed: {result}"

    summary = result["data"]["summary"]
    assert isinstance(summary, str)
    assert len(summary) > 0


# ── Test 11: Missing run → NOT_FOUND error ─────────────────────────────────────


def test_missing_run_not_found(tmp_env):
    """Test 11: Missing run ID produces NOT_FOUND error."""
    env = tmp_env
    manifest = _make_manifest({
        "dataset": {
            "dataset_id": "ds_test",
            "version_hash": env["ds_v1_hash"],
            "content_hash": env["ds_v1_content"],
            "n_cases": 3,
        },
        "metrics": [{
            "metric_id": "accuracy",
            "version_hash": env["metric_v1_hash"],
            "instance": {
                "label": "Accuracy",
                "params": {},
                "weight": 1.0,
                "strictness": 1.0,
                "zone": "score",
            },
        }],
    })
    results = _make_results()
    _create_run(env["runs_dir"], "run_a", manifest, results)
    # Do NOT create run_b

    result = _eval_diff_in_env(env, "run_a", "run_b")
    assert result["ok"] is False
    assert result["error"]["code"] == "NOT_FOUND"


def test_both_missing_runs(tmp_env):
    """Test 11b: Both runs missing → NOT_FOUND for the first one."""
    env = tmp_env
    result = _eval_diff_in_env(env, "nonexistent_a", "nonexistent_b")
    assert result["ok"] is False
    assert result["error"]["code"] == "NOT_FOUND"


# ── Test 12: Structured error format ───────────────────────────────────────────


def test_error_format(tmp_env):
    """Test 12: Error response has the required {ok, error: {code, message}} structure."""
    env = tmp_env
    result = _eval_diff_in_env(env, "nonexistent", "also_nonexistent")
    assert "ok" in result
    assert result["ok"] is False
    assert "error" in result
    assert "code" in result["error"]
    assert "message" in result["error"]
    assert isinstance(result["error"]["code"], str)
    assert isinstance(result["error"]["message"], str)


def test_success_format(tmp_env):
    """Test 12b: Success response has all required top-level keys."""
    env = tmp_env
    manifest = _make_manifest({
        "dataset": {
            "dataset_id": "ds_test",
            "version_hash": env["ds_v1_hash"],
            "content_hash": env["ds_v1_content"],
            "n_cases": 3,
        },
        "metrics": [{
            "metric_id": "accuracy",
            "version_hash": env["metric_v1_hash"],
            "instance": {
                "label": "Accuracy",
                "params": {},
                "weight": 1.0,
                "strictness": 1.0,
                "zone": "score",
            },
        }],
    })
    results = _make_results()

    _create_run(env["runs_dir"], "run_a", manifest, results)
    _create_run(env["runs_dir"], "run_b", manifest, results)

    result = _eval_diff_in_env(env, "run_a", "run_b")
    assert result["ok"] is True
    data = result["data"]
    required_keys = [
        "run_id_a", "run_id_b", "score_comparison", "dataset",
        "metrics", "skill", "model", "judge", "summary",
    ]
    for key in required_keys:
        assert key in data, f"Missing key: {key}"
    assert isinstance(data["metrics"], list)


# ── Unit tests for internal helpers ────────────────────────────────────────────


def test_compare_scores_no_results():
    """Unit test: _compare_scores with None results."""
    result = _compare_scores(None, None)
    assert result["overall"]["a"] is None
    assert result["overall"]["b"] is None
    assert result["overall"]["delta"] == 0
    assert result["fields"] == {}
    assert result["cases"] == []


def test_compare_dataset_none():
    """Unit test: _compare_dataset with None manifests."""
    result = _compare_dataset(None, None, None)
    assert result["status"] == "unchanged"


def test_compare_metrics_empty():
    """Unit test: _compare_metrics with empty manifests."""
    result = _compare_metrics({}, {}, None)
    assert result == []


def test_compare_skill_none():
    """Unit test: _compare_skill with None manifests."""
    result = _compare_skill(None, None)
    assert result["status"] == "unchanged"


def test_compare_model_none():
    """Unit test: _compare_model with None manifests."""
    result = _compare_model(None, None)
    assert result["status"] == "unchanged"


def test_compare_judge_none():
    """Unit test: _compare_judge with None manifests."""
    result = _compare_judge(None, None)
    assert result["status"] == "unchanged"


def test_generate_summary_no_changes():
    """Unit test: _generate_summary with no changes."""
    score = {"overall": {"a": 0.9, "b": 0.9, "delta": 0.0}}
    dataset = {"status": "unchanged"}
    metrics = [{"metric_id": "m1", "status": "unchanged"}]
    skill = {"status": "unchanged"}
    model = {"status": "unchanged"}
    judge = {"status": "unchanged"}

    summary = _generate_summary(score, dataset, metrics, skill, model, judge)
    assert isinstance(summary, str)
    assert len(summary) > 0


# ── Test: manifest.json missing handled gracefully ─────────────────────────────


def test_manifest_missing_handled_gracefully(tmp_env):
    """Test: Missing manifest.json is handled without crashing."""
    env = tmp_env
    manifest = _make_manifest({
        "dataset": {
            "dataset_id": "ds_test",
            "version_hash": env["ds_v1_hash"],
            "content_hash": env["ds_v1_content"],
            "n_cases": 3,
        },
        "metrics": [{
            "metric_id": "accuracy",
            "version_hash": env["metric_v1_hash"],
            "instance": {
                "label": "Accuracy",
                "params": {},
                "weight": 1.0,
                "strictness": 1.0,
                "zone": "score",
            },
        }],
    })
    results = _make_results()

    _create_run(env["runs_dir"], "run_a", manifest, results)
    _create_run(env["runs_dir"], "run_b", manifest, results)

    # Remove manifest.json from run_b
    (env["runs_dir"] / "run_b" / "manifest.json").unlink()

    result = _eval_diff_in_env(env, "run_a", "run_b")
    # Should still succeed (manifest defaults to empty dict)
    assert result["ok"], f"eval_diff failed on missing manifest: {result}"
    data = result["data"]
    # When one side lacks dataset info, it's reported as "modified"
    assert data["dataset"]["status"] == "modified"


def test_results_missing_handled_gracefully(tmp_env):
    """Test: Missing results.json is handled without crashing."""
    env = tmp_env
    manifest = _make_manifest({
        "dataset": {
            "dataset_id": "ds_test",
            "version_hash": env["ds_v1_hash"],
            "content_hash": env["ds_v1_content"],
            "n_cases": 3,
        },
        "metrics": [{
            "metric_id": "accuracy",
            "version_hash": env["metric_v1_hash"],
            "instance": {
                "label": "Accuracy",
                "params": {},
                "weight": 1.0,
                "strictness": 1.0,
                "zone": "score",
            },
        }],
    })
    results = _make_results()

    _create_run(env["runs_dir"], "run_a", manifest, results)
    _create_run(env["runs_dir"], "run_b", manifest, results)

    # Remove results.json from run_b
    (env["runs_dir"] / "run_b" / "results.json").unlink()

    result = _eval_diff_in_env(env, "run_a", "run_b")
    # Should still succeed (results defaults to empty dict)
    assert result["ok"], f"eval_diff failed on missing results: {result}"


# ── Test: Judge none vs none is unchanged ──────────────────────────────────────


def test_judge_both_none_unchanged(tmp_env):
    """Test: Both judges None means status 'unchanged'."""
    env = tmp_env
    manifest = _make_manifest({
        "dataset": {
            "dataset_id": "ds_test",
            "version_hash": env["ds_v1_hash"],
            "content_hash": env["ds_v1_content"],
            "n_cases": 3,
        },
        "metrics": [{
            "metric_id": "accuracy",
            "version_hash": env["metric_v1_hash"],
            "instance": {
                "label": "Accuracy",
                "params": {},
                "weight": 1.0,
                "strictness": 1.0,
                "zone": "score",
            },
        }],
        "judge_model": None,
    })
    results = _make_results()

    _create_run(env["runs_dir"], "run_a", manifest, results)
    _create_run(env["runs_dir"], "run_b", manifest, results)

    result = _eval_diff_in_env(env, "run_a", "run_b")
    assert result["ok"]
    assert result["data"]["judge"]["status"] == "unchanged"