"""Tests for DatasetStore."""
import json
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from dataset_store import DatasetStore, DATASET_SCHEMA


@pytest.fixture
def store():
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp) / "datasets"
        base.mkdir(parents=True)
        yield DatasetStore(base_dir=base)


def _sample_cases(n=2):
    return [{"input": f"Q{i}", "expected_output": f"A{i}"} for i in range(n)]


def _cases_with_ids(n=2):
    return [
        {"case_id": i, "input": f"Q{i}", "expected_output": f"A{i}"}
        for i in range(n)
    ]


# ── Create ────────────────────────────────────────────────────────────────────

class TestCreate:
    def test_create_success(self, store):
        r = store.create("ds1", "Test", _sample_cases(3))
        assert r["ok"] is True
        assert r["data"]["dataset_id"] == "ds1"
        assert r["data"]["n_cases"] == 3
        assert len(r["data"]["version_hash"]) == 64
        assert len(r["data"]["content_hash"]) == 64
        assert r["data"]["is_new"] is True

    def test_create_duplicate(self, store):
        store.create("ds1", "Test", _sample_cases(2))
        r = store.create("ds1", "Test", _sample_cases(2))
        assert r["ok"] is False
        assert r["error"]["code"] == "DUPLICATE_ID"

    def test_create_invalid_cases_not_list(self, store):
        r = store.create("ds1", "Test", "not_a_list")
        assert r["ok"] is False
        assert r["error"]["code"] == "INVALID_CASES"

    def test_create_empty_cases(self, store):
        r = store.create("ds1", "Test", [])
        assert r["ok"] is False
        assert r["error"]["code"] == "INVALID_CASES"

    def test_create_auto_assign_case_id(self, store):
        r = store.create("ds1", "Test", [{"input": "Q1"}])
        assert r["ok"] is True
        # Verify case_id was assigned (0-based index)
        g = store.get("ds1")
        assert g["data"]["cases"][0]["case_id"] == 0

    def test_create_preserve_case_id(self, store):
        r = store.create("ds1", "Test", [{"case_id": 5, "input": "Q1"}])
        assert r["ok"] is True
        g = store.get("ds1")
        assert g["data"]["cases"][0]["case_id"] == 5

    def test_create_non_dict_case(self, store):
        r = store.create("ds1", "Test", ["not_a_dict"])
        assert r["ok"] is False
        assert r["error"]["code"] == "INVALID_CASES"

    def test_create_with_schema(self, store):
        schema = {
            "type": "object",
            "required": ["input"],
            "properties": {"input": {"type": "string"}},
        }
        r = store.create("ds1", "Test", _sample_cases(2), schema=schema)
        assert r["ok"] is True

    def test_create_with_invalid_schema(self, store):
        schema = {
            "type": "object",
            "required": ["input"],
            "properties": {"input": {"type": "integer"}},
        }
        r = store.create("ds1", "Test", _sample_cases(2), schema=schema)
        assert r["ok"] is False
        assert r["error"]["code"] == "VALIDATION_ERROR"

    def test_create_empty_dataset_id(self, store):
        """DATASET_SCHEMA validation: empty dataset_id should fail."""
        r = store.create("", "Test", _sample_cases(2))
        assert r["ok"] is False
        assert r["error"]["code"] == "VALIDATION_ERROR"

    def test_create_empty_name(self, store):
        """DATASET_SCHEMA validation: empty name should fail."""
        r = store.create("ds1", "", _sample_cases(2))
        assert r["ok"] is False
        assert r["error"]["code"] == "VALIDATION_ERROR"

    def test_create_dataset_id_too_long(self, store):
        """DATASET_SCHEMA validation: dataset_id > 128 chars should fail."""
        long_id = "a" * 129
        r = store.create(long_id, "Test", _sample_cases(2))
        assert r["ok"] is False
        assert r["error"]["code"] == "VALIDATION_ERROR"

    def test_create_name_too_long(self, store):
        """DATASET_SCHEMA validation: name > 256 chars should fail."""
        long_name = "a" * 257
        r = store.create("ds1", long_name, _sample_cases(2))
        assert r["ok"] is False
        assert r["error"]["code"] == "VALIDATION_ERROR"

    def test_create_description_too_long(self, store):
        """DATASET_SCHEMA validation: description > 1024 chars should fail."""
        long_desc = "a" * 1025
        r = store.create("ds1", "Test", _sample_cases(2), description=long_desc)
        assert r["ok"] is False
        assert r["error"]["code"] == "VALIDATION_ERROR"

    def test_create_dataset_id_max_length_ok(self, store):
        """DATASET_SCHEMA: dataset_id exactly 128 chars should pass."""
        valid_id = "a" * 128
        r = store.create(valid_id, "Test", _sample_cases(2))
        assert r["ok"] is True

    def test_create_name_max_length_ok(self, store):
        """DATASET_SCHEMA: name exactly 256 chars should pass."""
        valid_name = "a" * 256
        r = store.create("ds1", valid_name, _sample_cases(2))
        assert r["ok"] is True


# ── Get ───────────────────────────────────────────────────────────────────────

class TestGet:
    def test_get_success(self, store):
        store.create("ds1", "Test", _sample_cases(2))
        r = store.get("ds1")
        assert r["ok"] is True
        assert r["data"]["dataset"]["name"] == "Test"
        assert len(r["data"]["cases"]) == 2

    def test_get_not_found(self, store):
        r = store.get("nonexistent")
        assert r["ok"] is False
        assert r["error"]["code"] == "NOT_FOUND"


# ── List ──────────────────────────────────────────────────────────────────────

class TestList:
    def test_list_empty(self, store):
        r = store.list_datasets()
        assert r["ok"] is True
        assert r["data"] == []

    def test_list_with_datasets(self, store):
        store.create("ds1", "One", _sample_cases(1))
        store.create("ds2", "Two", _sample_cases(2))
        r = store.list_datasets()
        assert r["ok"] is True
        assert len(r["data"]) == 2

    def test_list_base_dir_not_exists(self, store):
        # Create a store pointing to a non-existent dir
        s = DatasetStore(base_dir=Path(tempfile.gettempdir()) / "nonexistent_ds_store_test")
        r = s.list_datasets()
        assert r["ok"] is True
        assert r["data"] == []


# ── CreateVersion ─────────────────────────────────────────────────────────────

class TestCreateVersion:
    def test_create_version_new_cases(self, store):
        store.create("ds1", "Test", _sample_cases(2))
        new_cases = [{"case_id": 0, "input": "NewQ", "expected_output": "NewA"}]
        r = store.create_version("ds1", new_cases)
        assert r["ok"] is True
        assert r["data"]["is_new"] is True
        assert r["data"]["n_cases"] == 1

    def test_create_version_idempotent(self, store):
        store.create("ds1", "Test", _sample_cases(2))
        # Same cases (content hash unchanged) → idempotent
        r = store.create_version("ds1", _sample_cases(2))
        assert r["ok"] is True
        assert r["data"]["is_new"] is False

    def test_create_version_not_found(self, store):
        r = store.create_version("nonexistent", _sample_cases(1))
        assert r["ok"] is False
        assert r["error"]["code"] == "NOT_FOUND"

    def test_create_version_old_version_preserved(self, store):
        store.create("ds1", "Test", _sample_cases(2))
        # Get the initial version hash from list_versions
        first_hash = store.list_versions("ds1")["data"][0]["version_hash"]
        new_cases = [{"case_id": 0, "input": "Changed", "expected_output": "Changed"}]
        store.create_version("ds1", new_cases)
        # Old version should still be accessible
        v = store.get_version("ds1", first_hash)
        assert v["ok"] is True

    def test_create_version_invalid_cases(self, store):
        store.create("ds1", "Test", _sample_cases(2))
        r = store.create_version("ds1", "not_a_list")
        assert r["ok"] is False
        assert r["error"]["code"] == "INVALID_CASES"

    def test_create_version_empty_cases(self, store):
        store.create("ds1", "Test", _sample_cases(2))
        r = store.create_version("ds1", [])
        assert r["ok"] is False
        assert r["error"]["code"] == "INVALID_CASES"

    def test_create_version_auto_assign_case_id(self, store):
        store.create("ds1", "Test", _sample_cases(2))
        new_cases = [{"input": "NewQ", "expected_output": "NewA"}]
        r = store.create_version("ds1", new_cases)
        assert r["ok"] is True
        g = store.get("ds1")
        # The new case should have case_id assigned (0-based index)
        assert g["data"]["cases"][0]["case_id"] == 0


# ── GetVersion ────────────────────────────────────────────────────────────────

class TestGetVersion:
    def test_get_version_success(self, store):
        r = store.create("ds1", "Test", _sample_cases(2))
        vh = r["data"]["version_hash"]
        v = store.get_version("ds1", vh)
        assert v["ok"] is True
        assert v["data"]["version_hash"] == vh

    def test_get_version_not_found(self, store):
        r = store.get_version("ds1", "nonexistent_hash")
        assert r["ok"] is False
        assert r["error"]["code"] == "NOT_FOUND"


# ── ListVersions ──────────────────────────────────────────────────────────────

class TestListVersions:
    def test_list_versions(self, store):
        store.create("ds1", "Test", _sample_cases(2))
        r = store.list_versions("ds1")
        assert r["ok"] is True
        assert len(r["data"]) >= 1

    def test_list_versions_not_found(self, store):
        r = store.list_versions("nonexistent")
        # list_versions returns empty list for non-existent datasets
        assert r["ok"] is True
        assert r["data"] == []


# ── DiffVersions ──────────────────────────────────────────────────────────────

class TestDiffVersions:
    def test_diff_added_cases(self, store):
        store.create("ds1", "Test", _sample_cases(2))
        first = store.list_versions("ds1")["data"][0]["version_hash"]
        new_cases = _sample_cases(3)
        r2 = store.create_version("ds1", new_cases)
        second = r2["data"]["version_hash"]
        r = store.diff_versions("ds1", first, second)
        assert r["ok"] is True
        assert r["data"]["summary"]["added"] == 1

    def test_diff_modified_case(self, store):
        store.create("ds1", "Test", _sample_cases(2))
        first = store.list_versions("ds1")["data"][0]["version_hash"]
        new_cases = [{"case_id": 0, "input": "Changed", "expected_output": "A0"}]
        r2 = store.create_version("ds1", new_cases)
        second = r2["data"]["version_hash"]
        r = store.diff_versions("ds1", first, second)
        assert r["ok"] is True
        assert r["data"]["summary"]["modified"] >= 1

    def test_diff_field_filter(self, store):
        store.create("ds1", "Test", _sample_cases(2))
        first = store.list_versions("ds1")["data"][0]["version_hash"]
        new_cases = [{"case_id": 0, "input": "NewQ", "expected_output": "NewA"}]
        r2 = store.create_version("ds1", new_cases)
        second = r2["data"]["version_hash"]
        r = store.diff_versions("ds1", first, second, fields=["input"])
        assert r["ok"] is True
        # With field filter, only "input" changes should be reported
        mc = r["data"]["modified_cases"]
        if mc:
            assert all(ch["field"] == "input" for ch in mc[0]["changes"])

    def test_diff_not_found(self, store):
        r = store.diff_versions("ds1", "a" * 64, "b" * 64)
        assert r["ok"] is False
        assert r["error"]["code"] == "NOT_FOUND"


# ── StructuredError ───────────────────────────────────────────────────────────

class TestStructuredError:
    def test_error_format(self, store):
        r = store.get("nonexistent")
        assert r["ok"] is False
        assert "error" in r
        assert "code" in r["error"]
        assert "message" in r["error"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])