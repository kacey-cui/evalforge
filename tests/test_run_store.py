"""RunStore 模块测试（pytest）。

覆盖设计 §9 的 21 条用例。
所有 fixture 均使用 tempfile.TemporaryDirectory()，绝不读写真实 data/。
"""

import json
import re
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import run_manifest as rm
from run_store import (
    RunStore,
    REPORT_SCHEMA,
    _build_dataset_ref,
    _build_meta,
    _extract_config,
    _generate_run_id,
)


# ── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture
def store():
    """Provide a RunStore backed by a temp directory."""
    with tempfile.TemporaryDirectory() as tmp:
        runs_dir = Path(tmp) / "runs"
        runs_dir.mkdir()
        yield RunStore(runs_dir=runs_dir)


def _sample_report():
    """Return a minimal valid report dict."""
    return {
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


def _sample_manifest():
    """Build a minimal valid manifest dict that passes validate_manifest."""
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
    # Compute and inject manifest_hash
    m["manifest_hash"] = rm.compute_manifest_hash(m)
    return m


# ── Test 1: submit — 合法 report + manifest 提交成功 ──────────────────────────


def test_submit_valid(store):
    """Test 1: submit succeeds with valid report and manifest."""
    report = _sample_report()
    manifest = _sample_manifest()
    result = store.submit(report, manifest)
    assert result["ok"] is True
    assert result["data"]["status"] == "completed"
    assert result["data"]["overall_score"] == 0.85
    assert result["data"]["pass_rate"] == 0.8


# ── Test 2: submit — 返回 run_id ─────────────────────────────────────────────


def test_submit_returns_run_id(store):
    """Test 2: submit returns a run_id in data."""
    report = _sample_report()
    manifest = _sample_manifest()
    result = store.submit(report, manifest)
    assert result["ok"] is True
    assert "run_id" in result["data"]
    assert result["data"]["run_id"].startswith("run_")


# ── Test 3: submit — 自动生成 run_id（格式正确）──────────────────────────────


def test_submit_auto_generate_run_id_format(store):
    """Test 3: auto-generated run_id matches run_YYYYMMDD_NNN format."""
    report = _sample_report()
    manifest = _sample_manifest()
    result = store.submit(report, manifest)
    assert result["ok"] is True
    run_id = result["data"]["run_id"]
    assert re.match(r"^run_\d{8}_\d{3}$", run_id), f"run_id format: {run_id}"


# ── Test 4: submit — 重复 run_id 返回 DUPLICATE_RUN ──────────────────────────


def test_submit_duplicate_run_id(store):
    """Test 4: submitting with an existing run_id returns DUPLICATE_RUN."""
    report = _sample_report()
    manifest = _sample_manifest()
    # First submit with explicit run_id
    result1 = store.submit(report, manifest, run_id="run_20260818_001")
    assert result1["ok"] is True

    # Second submit with same run_id
    result2 = store.submit(report, manifest, run_id="run_20260818_001")
    assert result2["ok"] is False
    assert result2["error"]["code"] == "DUPLICATE_RUN"


# ── Test 5: submit — report 缺少 overall_score 返回 VALIDATION_ERROR ─────────


def test_submit_missing_overall_score(store):
    """Test 5: report missing overall_score returns VALIDATION_ERROR."""
    report = _sample_report()
    del report["overall_score"]
    manifest = _sample_manifest()
    result = store.submit(report, manifest)
    assert result["ok"] is False
    assert result["error"]["code"] == "VALIDATION_ERROR"
    assert any("overall_score" in d for d in result["error"].get("details", []))


# ── Test 6: submit — manifest 缺少 dataset 返回 VALIDATION_ERROR ─────────────


def test_submit_missing_dataset(store):
    """Test 6: manifest missing dataset returns VALIDATION_ERROR."""
    report = _sample_report()
    manifest = _sample_manifest()
    # Remove dataset from manifest and recompute hash
    del manifest["dataset"]
    # Recompute hash so it doesn't fail on MANIFEST_MISMATCH first
    manifest["manifest_hash"] = rm.compute_manifest_hash(manifest)
    result = store.submit(report, manifest)
    assert result["ok"] is False
    assert result["error"]["code"] == "VALIDATION_ERROR"
    assert any("dataset" in d.lower() for d in result["error"].get("details", []))


# ── Test 7: submit — manifest_hash 不匹配返回 MANIFEST_MISMATCH ──────────────


def test_submit_manifest_hash_mismatch(store):
    """Test 7: manifest_hash mismatch returns MANIFEST_MISMATCH."""
    report = _sample_report()
    manifest = _sample_manifest()
    manifest["manifest_hash"] = "f" * 64  # Deliberately wrong
    result = store.submit(report, manifest)
    assert result["ok"] is False
    assert result["error"]["code"] == "MANIFEST_MISMATCH"


# ── Test 8: submit — results.json 包含 manifest_hash ─────────────────────────


def test_submit_results_contains_manifest_hash(store):
    """Test 8: results.json includes manifest_hash after submit."""
    report = _sample_report()
    manifest = _sample_manifest()
    result = store.submit(report, manifest)
    assert result["ok"] is True
    run_id = result["data"]["run_id"]

    # Read the written results.json
    results_path = store.runs_dir / run_id / "results.json"
    results = json.loads(results_path.read_text(encoding="utf-8"))
    assert "manifest_hash" in results
    assert results["manifest_hash"] == result["data"]["manifest_hash"]


# ── Test 9: submit — manifest.json 写入正确 ──────────────────────────────────


def test_submit_manifest_written_correctly(store):
    """Test 9: manifest.json is written with correct manifest_hash."""
    report = _sample_report()
    manifest = _sample_manifest()
    result = store.submit(report, manifest)
    assert result["ok"] is True
    run_id = result["data"]["run_id"]

    manifest_path = store.runs_dir / run_id / "manifest.json"
    written_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert written_manifest["manifest_hash"] == result["data"]["manifest_hash"]
    assert written_manifest["dataset"]["dataset_id"] == "test_ds"
    assert written_manifest["triggered_by"] == "agent"


# ── Test 10: submit — meta.json 包含 status ──────────────────────────────────


def test_submit_meta_contains_status(store):
    """Test 10: meta.json contains status field."""
    report = _sample_report()
    manifest = _sample_manifest()
    result = store.submit(report, manifest)
    assert result["ok"] is True
    run_id = result["data"]["run_id"]

    meta_path = store.runs_dir / run_id / "meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    assert meta["status"] == "completed"
    assert meta["run_id"] == run_id
    assert meta["overall_score"] == 0.85
    assert meta["pass_rate"] == 0.8


# ── Test 11: submit — dataset_ref.json 的 content_hash 指向 dataset ──────────


def test_submit_dataset_ref_content_hash(store):
    """Test 11: dataset_ref.json content_hash matches manifest's dataset."""
    report = _sample_report()
    manifest = _sample_manifest()
    result = store.submit(report, manifest)
    assert result["ok"] is True
    run_id = result["data"]["run_id"]

    dataset_ref_path = store.runs_dir / run_id / "dataset_ref.json"
    dataset_ref = json.loads(dataset_ref_path.read_text(encoding="utf-8"))
    assert dataset_ref["content_hash"] == manifest["dataset"]["content_hash"]
    assert dataset_ref["dataset_id"] == manifest["dataset"]["dataset_id"]
    assert dataset_ref["version_hash"] == manifest["dataset"]["version_hash"]
    assert dataset_ref["n_cases"] == manifest["dataset"]["n_cases"]


# ── Test 12: get — 读取已存在的 run ──────────────────────────────────────────


def test_get_existing_run(store):
    """Test 12: get returns all files for an existing run."""
    report = _sample_report()
    manifest = _sample_manifest()
    submit_result = store.submit(report, manifest)
    assert submit_result["ok"] is True
    run_id = submit_result["data"]["run_id"]

    result = store.get(run_id)
    assert result["ok"] is True
    data = result["data"]
    assert data["run_id"] == run_id
    assert data["meta"] is not None
    assert data["manifest"] is not None
    assert data["results"] is not None
    assert data["config"] is not None
    assert data["dataset_ref"] is not None


# ── Test 13: get — 不存在的 run 返回 NOT_FOUND ────────────────────────────────


def test_get_nonexistent_run(store):
    """Test 13: get returns NOT_FOUND for nonexistent run_id."""
    result = store.get("run_nonexistent")
    assert result["ok"] is False
    assert result["error"]["code"] == "NOT_FOUND"


# ── Test 14: list — 列出所有 runs ────────────────────────────────────────────


def test_list_all_runs(store):
    """Test 14: list returns all submitted runs."""
    report = _sample_report()
    manifest = _sample_manifest()

    # Submit two runs
    store.submit(report, manifest, run_id="run_20260818_001")
    store.submit(report, manifest, run_id="run_20260818_002")

    result = store.list()
    assert result["ok"] is True
    assert len(result["data"]) == 2
    run_ids = {r["run_id"] for r in result["data"]}
    assert run_ids == {"run_20260818_001", "run_20260818_002"}


# ── Test 15: list — 按 project 过滤 ──────────────────────────────────────────


def test_list_filter_by_project(store):
    """Test 15: list filters by project."""
    report = _sample_report()
    manifest_a = _sample_manifest()
    manifest_a["skill"]["name"] = "project_a"
    manifest_a["manifest_hash"] = rm.compute_manifest_hash(manifest_a)

    manifest_b = _sample_manifest()
    manifest_b["skill"]["name"] = "project_b"
    manifest_b["manifest_hash"] = rm.compute_manifest_hash(manifest_b)

    store.submit(report, manifest_a, run_id="run_20260818_001")
    store.submit(report, manifest_b, run_id="run_20260818_002")

    result = store.list(project="project_a")
    assert result["ok"] is True
    assert len(result["data"]) == 1
    assert result["data"][0]["run_id"] == "run_20260818_001"
    assert result["data"][0]["project"] == "project_a"


# ── Test 16: compare — 不同分数返回 delta ────────────────────────────────────


def test_compare_different_scores(store):
    """Test 16: compare returns non-zero score_delta for different scores."""
    manifest = _sample_manifest()

    report_a = _sample_report()
    report_a["overall_score"] = 0.7

    report_b = _sample_report()
    report_b["overall_score"] = 0.9

    store.submit(report_a, manifest, run_id="run_20260818_001")
    store.submit(report_b, manifest, run_id="run_20260818_002")

    result = store.compare("run_20260818_001", "run_20260818_002")
    assert result["ok"] is True
    assert result["data"]["score_delta"] == pytest.approx(0.2)
    # Dataset should be the same
    assert result["data"]["dataset_check"]["same_dataset"] is True
    assert result["data"]["dataset_check"]["same_version"] is True


# ── Test 17: compare — 相同分数返回 delta=0 ──────────────────────────────────


def test_compare_same_scores(store):
    """Test 17: compare returns delta=0 for identical scores."""
    report = _sample_report()
    manifest = _sample_manifest()

    store.submit(report, manifest, run_id="run_20260818_001")
    store.submit(report, manifest, run_id="run_20260818_002")

    result = store.compare("run_20260818_001", "run_20260818_002")
    assert result["ok"] is True
    assert result["data"]["score_delta"] == 0.0
    assert result["data"]["field_diffs"] == {}


# ── Test 18: compare — 不存在的 run 返回 NOT_FOUND ───────────────────────────


def test_compare_nonexistent_run(store):
    """Test 18: compare returns NOT_FOUND for nonexistent run_id."""
    report = _sample_report()
    manifest = _sample_manifest()
    store.submit(report, manifest, run_id="run_20260818_001")

    result = store.compare("run_20260818_001", "run_20260818_999")
    assert result["ok"] is False
    assert result["error"]["code"] == "NOT_FOUND"


# ── Test 19: 结构化错误格式一致 ──────────────────────────────────────────────


def test_structured_error_format(store):
    """Test 19: all error responses have consistent {ok, error: {code, message}} format."""
    # Test NOT_FOUND
    result = store.get("run_nonexistent")
    assert result["ok"] is False
    assert "error" in result
    assert "code" in result["error"]
    assert "message" in result["error"]
    assert result["error"]["code"] == "NOT_FOUND"

    # Test VALIDATION_ERROR
    report = _sample_report()
    del report["overall_score"]
    manifest = _sample_manifest()
    result = store.submit(report, manifest)
    assert result["ok"] is False
    assert "error" in result
    assert result["error"]["code"] == "VALIDATION_ERROR"
    assert "details" in result["error"]

    # Test MANIFEST_MISMATCH
    report2 = _sample_report()
    manifest2 = _sample_manifest()
    manifest2["manifest_hash"] = "f" * 64
    result = store.submit(report2, manifest2)
    assert result["ok"] is False
    assert result["error"]["code"] == "MANIFEST_MISMATCH"

    # Test DUPLICATE_RUN
    report3 = _sample_report()
    manifest3 = _sample_manifest()
    store.submit(report3, manifest3, run_id="run_20260818_005")
    result = store.submit(report3, manifest3, run_id="run_20260818_005")
    assert result["ok"] is False
    assert result["error"]["code"] == "DUPLICATE_RUN"


# ── Test 20: CLI submit 命令 ─────────────────────────────────────────────────


def test_cli_submit(store, tmp_path, monkeypatch, capsys):
    """Test 20: CLI submit command works end-to-end."""
    report_path = tmp_path / "report.json"
    manifest_path = tmp_path / "manifest.json"
    report_path.write_text(json.dumps(_sample_report(), ensure_ascii=False), encoding="utf-8")
    manifest_path.write_text(json.dumps(_sample_manifest(), ensure_ascii=False), encoding="utf-8")

    monkeypatch.setattr(sys, "argv", [
        "run_store.py",
        "--runs-dir", str(store.runs_dir),
        "submit",
        "--report", str(report_path),
        "--manifest", str(manifest_path),
    ])

    from run_store import main as cli_main

    with pytest.raises(SystemExit) as exc_info:
        cli_main()
    assert exc_info.value.code == 0

    captured = capsys.readouterr()
    output = json.loads(captured.out)
    assert output["ok"] is True
    assert "run_id" in output["data"]
    assert output["data"]["status"] == "completed"


# ── Test 21: CLI list + compare 端到端 ───────────────────────────────────────


def test_cli_list_and_compare(store, tmp_path, monkeypatch, capsys):
    """Test 21: CLI list and compare commands work end-to-end."""
    report = _sample_report()
    manifest = _sample_manifest()

    # Submit two runs via API
    store.submit(report, manifest, run_id="run_20260818_001")
    report_b = _sample_report()
    report_b["overall_score"] = 0.95
    store.submit(report_b, manifest, run_id="run_20260818_002")

    # Test CLI list
    monkeypatch.setattr(sys, "argv", [
        "run_store.py",
        "--runs-dir", str(store.runs_dir),
        "list",
    ])

    from run_store import main as cli_main

    with pytest.raises(SystemExit) as exc_info:
        cli_main()
    assert exc_info.value.code == 0

    captured = capsys.readouterr()
    list_output = json.loads(captured.out)
    assert list_output["ok"] is True
    assert len(list_output["data"]) == 2

    # Test CLI compare
    monkeypatch.setattr(sys, "argv", [
        "run_store.py",
        "--runs-dir", str(store.runs_dir),
        "compare",
        "--run-a", "run_20260818_001",
        "--run-b", "run_20260818_002",
    ])

    with pytest.raises(SystemExit) as exc_info:
        cli_main()
    assert exc_info.value.code == 0

    captured = capsys.readouterr()
    compare_output = json.loads(captured.out)
    assert compare_output["ok"] is True
    assert compare_output["data"]["score_delta"] == pytest.approx(0.10)


# ── Additional unit tests for internal helpers ───────────────────────────────


def test_generate_run_id_increments(tmp_path):
    """_generate_run_id increments correctly when runs exist."""
    runs_dir = tmp_path / "runs"
    runs_dir.mkdir()
    # Create some existing runs
    (runs_dir / "run_20260818_001").mkdir()
    (runs_dir / "run_20260818_002").mkdir()
    (runs_dir / "run_20260818_005").mkdir()

    # Mock datetime to return a fixed date
    from datetime import datetime, timezone as _tz
    from unittest import mock

    class FakeDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 8, 18, 12, 0, 0, tzinfo=_tz.utc)

    with mock.patch("run_store.datetime", FakeDatetime):
        run_id = _generate_run_id(runs_dir)
        assert run_id == "run_20260818_006"


def test_generate_run_id_first_run(tmp_path):
    """_generate_run_id returns 001 when no runs exist."""
    runs_dir = tmp_path / "runs"
    runs_dir.mkdir()

    from datetime import datetime, timezone as _tz
    from unittest import mock

    class FakeDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 8, 18, 12, 0, 0, tzinfo=_tz.utc)

    with mock.patch("run_store.datetime", FakeDatetime):
        run_id = _generate_run_id(runs_dir)
        assert run_id == "run_20260818_001"


def test_build_meta_fields(store):
    """_build_meta includes fields from report."""
    report = _sample_report()
    manifest = _sample_manifest()
    meta = _build_meta("run_test", manifest, report)
    assert "fields" in meta
    assert "diagnosis" in meta["fields"]
    assert meta["fields"]["diagnosis"]["field_score"] == 0.85


def test_build_meta_metrics(store):
    """_build_meta includes metric_ids from manifest."""
    report = _sample_report()
    manifest = _sample_manifest()
    meta = _build_meta("run_test", manifest, report)
    assert "metrics" in meta
    assert "accuracy" in meta["metrics"]


def test_extract_config_from_report(store):
    """_extract_config returns report config when present."""
    report = _sample_report()
    manifest = _sample_manifest()
    config = _extract_config(report, manifest)
    assert config == report["config"]


def test_extract_config_fallback(store):
    """_extract_config falls back to manifest extra or empty dict."""
    report = _sample_report()
    del report["config"]
    manifest = _sample_manifest()
    manifest["extra"] = {"custom": "value"}
    config = _extract_config(report, manifest)
    assert config == {"custom": "value"}


def test_extract_config_empty(store):
    """_extract_config returns {} when no config available."""
    report = _sample_report()
    del report["config"]
    manifest = _sample_manifest()
    manifest["extra"] = {}
    config = _extract_config(report, manifest)
    assert config == {}


def test_build_dataset_ref(store):
    """_build_dataset_ref extracts correct fields from manifest."""
    manifest = _sample_manifest()
    ref = _build_dataset_ref(manifest)
    assert ref["dataset_id"] == "test_ds"
    assert ref["n_cases"] == 10
    assert ref["version_hash"] == "0" * 64
    assert ref["content_hash"] == "0" * 64


def test_list_empty_when_no_runs(store):
    """list returns empty list when no runs exist."""
    result = store.list()
    assert result["ok"] is True
    assert result["data"] == []


def test_compare_with_field_diffs(store):
    """compare detects field-level score differences."""
    manifest = _sample_manifest()

    report_a = _sample_report()
    report_a["fields"] = {"diagnosis": {"field_score": 0.7}}

    report_b = _sample_report()
    report_b["fields"] = {"diagnosis": {"field_score": 0.9}}

    store.submit(report_a, manifest, run_id="run_20260818_001")
    store.submit(report_b, manifest, run_id="run_20260818_002")

    result = store.compare("run_20260818_001", "run_20260818_002")
    assert result["ok"] is True
    assert "diagnosis" in result["data"]["field_diffs"]
    assert result["data"]["field_diffs"]["diagnosis"]["delta"] == pytest.approx(0.2)


def test_list_respects_limit(store):
    """list respects the limit parameter."""
    report = _sample_report()
    manifest = _sample_manifest()
    for i in range(5):
        store.submit(report, manifest, run_id=f"run_20260818_{i:03d}")

    result = store.list(limit=3)
    assert result["ok"] is True
    assert len(result["data"]) == 3


def test_submit_custom_run_id(store):
    """submit accepts a custom run_id."""
    report = _sample_report()
    manifest = _sample_manifest()
    result = store.submit(report, manifest, run_id="run_20260818_001")
    assert result["ok"] is True
    assert result["data"]["run_id"] == "run_20260818_001"


def test_submit_invalid_run_id_format(store):
    """submit rejects run_id with invalid format."""
    report = _sample_report()
    manifest = _sample_manifest()
    result = store.submit(report, manifest, run_id="bad_format")
    assert result["ok"] is False
    assert result["error"]["code"] == "VALIDATION_ERROR"


def test_submit_invalid_triggered_by(store):
    """submit rejects triggered_by not in ('agent', 'ui')."""
    report = _sample_report()
    manifest = _sample_manifest()
    result = store.submit(report, manifest, triggered_by="invalid")
    assert result["ok"] is False
    assert result["error"]["code"] == "VALIDATION_ERROR"


def test_submit_report_overall_score_exceeds_maximum(store):
    """submit rejects report with overall_score > 1.0 (maximum)."""
    report = _sample_report()
    report["overall_score"] = 1.5
    manifest = _sample_manifest()
    result = store.submit(report, manifest)
    assert result["ok"] is False
    assert result["error"]["code"] == "VALIDATION_ERROR"


def test_submit_report_pass_rate_exceeds_maximum(store):
    """submit rejects report with pass_rate > 1.0 (maximum)."""
    report = _sample_report()
    report["pass_rate"] = 1.5
    manifest = _sample_manifest()
    result = store.submit(report, manifest)
    assert result["ok"] is False
    assert result["error"]["code"] == "VALIDATION_ERROR"


def test_submit_manifest_hash_in_result(store):
    """submit returns the manifest_hash in data."""
    report = _sample_report()
    manifest = _sample_manifest()
    result = store.submit(report, manifest)
    assert result["ok"] is True
    assert len(result["data"]["manifest_hash"]) == 64
    assert result["data"]["manifest_hash"] == manifest["manifest_hash"]


def test_compare_config_diff(store):
    """compare detects config differences."""
    manifest = _sample_manifest()

    report_a = _sample_report()
    report_a["config"] = {"metrics": [{"name": "accuracy"}]}

    report_b = _sample_report()
    report_b["config"] = {"metrics": [{"name": "accuracy"}, {"name": "precision"}]}

    store.submit(report_a, manifest, run_id="run_20260818_001")
    store.submit(report_b, manifest, run_id="run_20260818_002")

    result = store.compare("run_20260818_001", "run_20260818_002")
    assert result["ok"] is True
    assert result["data"]["config_diff"] != {}


def test_compare_dataset_check_different(store):
    """compare detects different datasets."""
    manifest_a = _sample_manifest()
    manifest_a["dataset"]["dataset_id"] = "ds_a"
    manifest_a["dataset"]["version_hash"] = "a" * 64
    manifest_a["dataset"]["content_hash"] = "b" * 64
    manifest_a["manifest_hash"] = rm.compute_manifest_hash(manifest_a)

    manifest_b = _sample_manifest()
    manifest_b["dataset"]["dataset_id"] = "ds_b"
    manifest_b["dataset"]["version_hash"] = "c" * 64
    manifest_b["dataset"]["content_hash"] = "d" * 64
    manifest_b["manifest_hash"] = rm.compute_manifest_hash(manifest_b)

    report = _sample_report()
    store.submit(report, manifest_a, run_id="run_20260818_001")
    store.submit(report, manifest_b, run_id="run_20260818_002")

    result = store.compare("run_20260818_001", "run_20260818_002")
    assert result["ok"] is True
    assert result["data"]["dataset_check"]["same_dataset"] is False
    assert result["data"]["dataset_check"]["same_version"] is False
    assert result["data"]["dataset_check"]["same_content"] is False


def test_submit_missing_skill(store):
    """submit returns VALIDATION_ERROR when report is missing skill."""
    report = _sample_report()
    del report["skill"]
    manifest = _sample_manifest()
    result = store.submit(report, manifest)
    assert result["ok"] is False
    assert result["error"]["code"] == "VALIDATION_ERROR"


def test_submit_missing_fields(store):
    """submit returns VALIDATION_ERROR when report is missing fields."""
    report = _sample_report()
    del report["fields"]
    manifest = _sample_manifest()
    result = store.submit(report, manifest)
    assert result["ok"] is False
    assert result["error"]["code"] == "VALIDATION_ERROR"


def test_submit_report_with_bad_cases(store):
    """submit accepts report with bad_cases array."""
    report = _sample_report()
    report["bad_cases"] = [{"case_id": 1, "reason": "test"}]
    manifest = _sample_manifest()
    result = store.submit(report, manifest)
    assert result["ok"] is True


def test_submit_report_with_grade(store):
    """submit accepts report with grade string."""
    report = _sample_report()
    report["grade"] = "A"
    manifest = _sample_manifest()
    result = store.submit(report, manifest)
    assert result["ok"] is True


def test_get_missing_files_are_none(store):
    """get returns None for files that don't exist in run dir."""
    report = _sample_report()
    manifest = _sample_manifest()
    result = store.submit(report, manifest)
    assert result["ok"] is True
    run_id = result["data"]["run_id"]

    # Delete a file to simulate missing
    (store.runs_dir / run_id / "config.json").unlink()

    get_result = store.get(run_id)
    assert get_result["ok"] is True
    assert get_result["data"]["config"] is None


def test_validate_manifest_errors_after_submit(store):
    """After submit, the written manifest.json is valid."""
    report = _sample_report()
    manifest = _sample_manifest()
    result = store.submit(report, manifest)
    assert result["ok"] is True
    run_id = result["data"]["run_id"]

    manifest_path = store.runs_dir / run_id / "manifest.json"
    written = json.loads(manifest_path.read_text(encoding="utf-8"))
    errors = rm.validate_manifest(written)
    assert errors == [], f"Written manifest should be valid, got: {errors}"