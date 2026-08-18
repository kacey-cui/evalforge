"""Metric Store 模块测试（pytest）。

覆盖设计文档 §9 全部 20 条用例。
所有 fixture 均使用 tempfile.TemporaryDirectory()，绝不读写真实 data/metrics/。
"""

import json
import sys
import subprocess
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from metric_store import MetricStore, METRIC_SCHEMA


# ── Fixtures ───────────────────────────────────────────────────────────


def _sample_metric(**overrides):
    """Return a valid sample metric dict."""
    m = {
        "id": "sample",
        "name": "样例指标",
        "category": "llm",
        "description": "测试用指标",
        "params": [
            {
                "key": "threshold",
                "label": "阈值",
                "type": "number",
                "default": 0.7,
                "min": 0,
                "max": 1,
                "step": 0.1,
            }
        ],
        "criteria": "评估回答是否准确",
        "requires": ["actual_output", "expected_output"],
        "code_template": "GEval(...)",
    }
    m.update(overrides)
    return m


@pytest.fixture
def store():
    """Create a MetricStore backed by a temporary directory."""
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp) / "metrics"
        base.mkdir()
        yield MetricStore(base_dir=base)


@pytest.fixture
def filled_store(store):
    """A MetricStore with one sample metric already created."""
    store.create(_sample_metric())
    return store


# ── 1. create — valid metric ───────────────────────────────────────────


def test_create_valid_metric(store):
    result = store.create(_sample_metric())
    assert result["ok"] is True
    assert result["data"]["metric_id"] == "sample"
    assert result["data"]["is_new"] is True
    assert len(result["data"]["version_hash"]) == 64
    assert result["data"]["created_at"] is not None

    # File should exist on disk
    metric_file = store.base_dir / "llm" / "sample.json"
    assert metric_file.is_file()

    # Version snapshot should exist
    vh = result["data"]["version_hash"]
    version_file = store.base_dir / "llm" / ".versions" / "sample" / f"{vh}.json"
    assert version_file.is_file()


# ── 2. create — missing id → VALIDATION_ERROR ──────────────────────────


def test_create_missing_id_returns_validation_error(store):
    metric = _sample_metric()
    del metric["id"]
    result = store.create(metric)
    assert result["ok"] is False
    assert result["error"]["code"] == "VALIDATION_ERROR"
    assert "details" in result["error"]


# ── 3. create — invalid category → VALIDATION_ERROR ────────────────────


def test_create_invalid_category_returns_validation_error(store):
    result = store.create(_sample_metric(category="invalid_cat"))
    assert result["ok"] is False
    assert result["error"]["code"] == "VALIDATION_ERROR"


# ── 4. create — duplicate id → DUPLICATE_ID ────────────────────────────


def test_create_duplicate_id_returns_duplicate_error(store):
    store.create(_sample_metric())
    result = store.create(_sample_metric())
    assert result["ok"] is False
    assert result["error"]["code"] == "DUPLICATE_ID"


# ── 5. create — result contains version_hash ───────────────────────────


def test_create_result_contains_version_hash(store):
    result = store.create(_sample_metric())
    assert result["ok"] is True
    vh = result["data"]["version_hash"]
    assert isinstance(vh, str)
    assert len(vh) == 64
    # Hex characters only
    assert all(c in "0123456789abcdef" for c in vh)


# ── 6. get — read existing metric ──────────────────────────────────────


def test_get_existing_metric(filled_store):
    result = filled_store.get("sample")
    assert result["ok"] is True
    assert result["data"]["id"] == "sample"
    assert result["data"]["name"] == "样例指标"
    assert result["data"]["category"] == "llm"


# ── 7. get — nonexistent → NOT_FOUND ───────────────────────────────────


def test_get_nonexistent_metric_returns_not_found(store):
    result = store.get("nonexistent")
    assert result["ok"] is False
    assert result["error"]["code"] == "NOT_FOUND"


# ── 8. list — list all metrics ─────────────────────────────────────────


def test_list_metrics(filled_store):
    # Add a second metric in a different category
    filled_store.create(_sample_metric(id="nonllm_sample", category="non_llm"))
    result = filled_store.list_metrics()
    assert result["ok"] is True
    ids = [m["metric_id"] for m in result["data"]]
    assert "sample" in ids
    assert "nonllm_sample" in ids

    # Each entry has the expected keys
    for m in result["data"]:
        assert "metric_id" in m
        assert "name" in m
        assert "category" in m
        assert "version_hash" in m
        assert len(m["version_hash"]) == 64


def test_list_metrics_empty(store):
    result = store.list_metrics()
    assert result["ok"] is True
    assert result["data"] == []


# ── 9. create_version — modify criteria creates new version ────────────


def test_create_version_modify_criteria_new_version(filled_store):
    original = filled_store.get("sample")
    r1 = filled_store.create_version(
        "sample", _sample_metric(criteria="全新的标准")
    )
    assert r1["ok"] is True
    assert r1["data"]["is_new"] is True
    assert r1["data"]["version_hash"] != ""  # any hash is fine

    # Verify the file was updated
    updated = filled_store.get("sample")
    assert updated["data"]["criteria"] == "全新的标准"


# ── 10. create_version — idempotent (same content) ─────────────────────


def test_create_version_idempotent_same_content(filled_store):
    r1 = filled_store.create_version("sample", _sample_metric())
    assert r1["ok"] is True
    # is_new depends on whether the hash changed: the create() call already
    # wrote the same content, so create_version with the same dict should
    # produce the same hash → is_new = False
    assert r1["data"]["is_new"] is False


# ── 11. create_version — nonexistent metric → NOT_FOUND ────────────────


def test_create_version_nonexistent_metric_returns_not_found(store):
    result = store.create_version("nonexistent", _sample_metric())
    assert result["ok"] is False
    assert result["error"]["code"] == "NOT_FOUND"


# ── 12. create_version — changing id is rejected ───────────────────────


def test_create_version_change_id_rejected(filled_store):
    result = filled_store.create_version(
        "sample", _sample_metric(id="changed")
    )
    assert result["ok"] is False
    assert result["error"]["code"] == "VALIDATION_ERROR"
    assert "metric_id" in result["error"]["message"]

    # Verify the original id is unchanged
    current = filled_store.get("sample")
    assert current["data"]["id"] == "sample"


# ── 13. create_version — old version file preserved ────────────────────


def test_create_version_old_version_preserved(store):
    # Create initial metric
    r1 = store.create(_sample_metric(criteria="标准A"))
    vh1 = r1["data"]["version_hash"]

    # Create a new version with different criteria
    r2 = store.create_version("sample", _sample_metric(criteria="标准B"))
    vh2 = r2["data"]["version_hash"]

    # The two versions should have different hashes
    assert vh1 != vh2

    # Both version files should exist
    vf1 = store.base_dir / "llm" / ".versions" / "sample" / f"{vh1}.json"
    vf2 = store.base_dir / "llm" / ".versions" / "sample" / f"{vh2}.json"
    assert vf1.is_file()
    assert vf2.is_file()

    # Old version content should still have criteria="标准A"
    old_data = json.loads(vf1.read_text(encoding="utf-8"))
    assert old_data["criteria"] == "标准A"


# ── 14. get_version — read specific version ────────────────────────────


def test_get_version(filled_store):
    # Get the version hash from the current metric
    current = filled_store.get("sample")
    vh = filled_store.list_metrics()["data"][0]["version_hash"]

    result = filled_store.get_version("sample", vh)
    assert result["ok"] is True
    assert result["data"]["metric_id"] == "sample"
    assert result["data"]["version_hash"] == vh


def test_get_version_nonexistent_hash(filled_store):
    result = filled_store.get_version("sample", "0" * 64)
    assert result["ok"] is False
    assert result["error"]["code"] == "NOT_FOUND"


# ── 15. list_versions — list all versions ──────────────────────────────


def test_list_versions(filled_store):
    result = filled_store.list_versions("sample")
    assert result["ok"] is True
    assert isinstance(result["data"], list)
    assert len(result["data"]) >= 1
    for v in result["data"]:
        assert "metric_id" in v
        assert "version_hash" in v
        assert "created_at" in v


def test_list_versions_nonexistent(store):
    result = store.list_versions("nonexistent")
    assert result["ok"] is True
    assert result["data"] == []


# ── 16. diff_versions — detect modifications ───────────────────────────


def test_diff_versions_detect_modifications(store):
    r1 = store.create(_sample_metric(criteria="标准A"))
    r2 = store.create_version("sample", _sample_metric(criteria="标准B"))
    vh1 = r1["data"]["version_hash"]
    vh2 = r2["data"]["version_hash"]

    result = store.diff_versions("sample", vh1, vh2)
    assert result["ok"] is True
    assert "criteria" in result["data"]["modified_fields"]


def test_diff_versions_no_changes(store):
    r1 = store.create(_sample_metric())
    # create_version with same content → is_new=False, same hash
    vh = r1["data"]["version_hash"]

    result = store.diff_versions("sample", vh, vh)
    assert result["ok"] is True
    assert result["data"]["changes"] == []


def test_diff_versions_missing_version(store):
    store.create(_sample_metric())
    vh = store.list_metrics()["data"][0]["version_hash"]
    result = store.diff_versions("sample", vh, "0" * 64)
    assert result["ok"] is False
    assert result["error"]["code"] == "NOT_FOUND"


# ── 17. structured error format consistency ────────────────────────────


def test_error_format_consistency(store):
    result = store.get("nonexistent")
    assert "ok" in result
    assert result["ok"] is False
    assert "error" in result
    assert "code" in result["error"]
    assert "message" in result["error"]
    assert isinstance(result["error"]["code"], str)
    assert isinstance(result["error"]["message"], str)

    # Success format
    result = store.create(_sample_metric())
    assert "ok" in result
    assert result["ok"] is True
    assert "data" in result
    assert isinstance(result["data"], dict)


def test_validation_error_includes_details(store):
    metric = _sample_metric()
    del metric["id"]
    del metric["name"]
    result = store.create(metric)
    assert result["ok"] is False
    assert result["error"]["code"] == "VALIDATION_ERROR"
    assert "details" in result["error"]
    assert isinstance(result["error"]["details"], list)
    assert len(result["error"]["details"]) > 0


# ── 18. CLI create command ─────────────────────────────────────────────


def test_cli_create():
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp) / "metrics"
        base.mkdir()
        metric_json = json.dumps(_sample_metric())
        result = subprocess.run(
            [
                sys.executable,
                str(Path(__file__).resolve().parents[1] / "scripts" / "metric_store.py"),
                "create",
                metric_json,
                "--base-dir",
                str(base),
            ],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert data["ok"] is True
        assert data["data"]["metric_id"] == "sample"
        assert len(data["data"]["version_hash"]) == 64


# ── 19. CLI get command ────────────────────────────────────────────────


def test_cli_get():
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp) / "metrics"
        base.mkdir()
        # First create via CLI
        metric_json = json.dumps(_sample_metric())
        subprocess.run(
            [
                sys.executable,
                str(Path(__file__).resolve().parents[1] / "scripts" / "metric_store.py"),
                "create",
                metric_json,
                "--base-dir",
                str(base),
            ],
            capture_output=True,
            text=True,
        )
        # Then get via CLI
        result = subprocess.run(
            [
                sys.executable,
                str(Path(__file__).resolve().parents[1] / "scripts" / "metric_store.py"),
                "get",
                "--metric-id",
                "sample",
                "--base-dir",
                str(base),
            ],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert data["ok"] is True
        assert data["data"]["id"] == "sample"


# ── 20. CLI create-version + diff end-to-end ───────────────────────────


def test_cli_create_version_and_diff_e2e():
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp) / "metrics"
        base.mkdir()
        script = str(Path(__file__).resolve().parents[1] / "scripts" / "metric_store.py")

        # Create initial metric
        r1 = subprocess.run(
            [sys.executable, script, "create", json.dumps(_sample_metric(criteria="标准A")), "--base-dir", str(base)],
            capture_output=True, text=True,
        )
        assert r1.returncode == 0
        vh1 = json.loads(r1.stdout)["data"]["version_hash"]

        # Create a new version with different criteria
        r2 = subprocess.run(
            [sys.executable, script, "create-version", "--metric-id", "sample",
             json.dumps(_sample_metric(criteria="标准B")), "--base-dir", str(base)],
            capture_output=True, text=True,
        )
        assert r2.returncode == 0
        vh2 = json.loads(r2.stdout)["data"]["version_hash"]

        # Diff the two versions
        r3 = subprocess.run(
            [sys.executable, script, "diff", "--metric-id", "sample",
             "--version-a", vh1, "--version-b", vh2, "--base-dir", str(base)],
            capture_output=True, text=True,
        )
        assert r3.returncode == 0
        diff_result = json.loads(r3.stdout)
        assert diff_result["ok"] is True
        assert "criteria" in diff_result["data"]["modified_fields"]


# ── Additional edge-case tests ─────────────────────────────────────────


def test_create_metric_with_null_criteria(store):
    """null criteria is valid per oneOf schema."""
    result = store.create(_sample_metric(criteria=None))
    assert result["ok"] is True


def test_create_metric_without_optional_description(store):
    """description is not required."""
    metric = _sample_metric()
    del metric["description"]
    result = store.create(metric)
    assert result["ok"] is True


def test_create_version_validation_error_for_invalid_schema(store):
    """create_version rejects invalid schema even if metric exists."""
    store.create(_sample_metric())
    bad = _sample_metric()
    del bad["code_template"]
    result = store.create_version("sample", bad)
    assert result["ok"] is False
    assert result["error"]["code"] == "VALIDATION_ERROR"


def test_create_version_with_new_category_preserves_id(store):
    """Changing category is allowed (id unchanged).  The file is overwritten
    in-place, so the path stays the same even though the content changes."""
    store.create(_sample_metric(category="llm"))
    r2 = store.create_version("sample", _sample_metric(category="non_llm"))
    assert r2["ok"] is True
    # File stays at the original location (in-place overwrite)
    assert (store.base_dir / "llm" / "sample.json").is_file()
    # Content reflects the new category
    current = store.get("sample")
    assert current["data"]["category"] == "non_llm"


def test_list_metrics_computes_hash_from_current_content(store):
    """list_metrics computes hash from the current file content, not from .versions/."""
    store.create(_sample_metric(criteria="标准A"))
    before = store.list_metrics()["data"][0]["version_hash"]

    store.create_version("sample", _sample_metric(criteria="标准B"))
    after = store.list_metrics()["data"][0]["version_hash"]

    assert before != after


def test_create_metric_with_nonexistent_category_returns_error(store):
    """category must be 'llm' or 'non_llm'."""
    result = store.create(_sample_metric(category="unknown"))
    assert result["ok"] is False
    assert result["error"]["code"] == "VALIDATION_ERROR"


def test_create_not_a_dict_returns_validation_error(store):
    result = store.create("not a dict")
    assert result["ok"] is False
    assert result["error"]["code"] == "VALIDATION_ERROR"


def test_create_version_not_a_dict_returns_validation_error(filled_store):
    result = filled_store.create_version("sample", "not a dict")
    assert result["ok"] is False
    assert result["error"]["code"] == "VALIDATION_ERROR"