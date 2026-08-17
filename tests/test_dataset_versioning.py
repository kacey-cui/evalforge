"""Dataset Versioning 模块测试（标准库 unittest）。

覆盖设计 §12 全部 29 条用例 + 审计新增用例 + mini_json_schema 子集校验。
所有 fixture 均使用 tempfile.TemporaryDirectory()，绝不读写真实 data/datasets/、
data/projects/。
"""

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import dataset_versioning as dv
import mini_json_schema as mjs


def _cases_ab():
    return [
        {
            "case_id": 1,
            "input": "查询账户余额",
            "expected_output": "result_a",
            "actual_output": None,
        },
        {
            "case_id": 2,
            "input": "如何修改密码",
            "expected_output": "result_b",
            "actual_output": "result_b",
        },
    ]


class DatasetVersioningTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.base_dir = Path(self._tmp.name) / "datasets"
        self.base_dir.mkdir(parents=True)

    def tearDown(self):
        self._tmp.cleanup()

    def _create(self, cases, dataset_id="ds", name="测试集", **kw):
        return dv.create_dataset(dataset_id, name, cases, base_dir=self.base_dir, **kw)

    def _write_cases(self, dataset_id, cases):
        ds_dir = self.base_dir / dataset_id
        cases_sorted = sorted(cases, key=lambda c: c["case_id"])
        (ds_dir / "test_cases.json").write_text(
            json.dumps(cases_sorted, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return dv.create_version(dataset_id, base_dir=self.base_dir)

    # ── 1-3 compute_content_hash ─────────────────────────────────────────

    def test_content_hash_same_cases_same_hash(self):
        h1 = dv.compute_content_hash(_cases_ab())
        h2 = dv.compute_content_hash(_cases_ab())
        self.assertEqual(h1, h2)
        self.assertEqual(len(h1), 64)

    def test_content_hash_different_cases_different_hash(self):
        a = _cases_ab()
        b = _cases_ab()
        b[1]["expected_output"] = "CHANGED"
        self.assertNotEqual(dv.compute_content_hash(a), dv.compute_content_hash(b))

    def test_content_hash_order_independent(self):
        a = _cases_ab()
        b = list(reversed(_cases_ab()))
        self.assertEqual(dv.compute_content_hash(a), dv.compute_content_hash(b))

    # ── 4-6 compute_version_hash ─────────────────────────────────────────

    def test_version_hash_same_metadata_same_hash(self):
        d = {"dataset_id": "ds", "name": "n", "schema": {}, "n_cases": 2}
        h1 = dv.compute_version_hash(d, "content")
        h2 = dv.compute_version_hash(d, "content")
        self.assertEqual(h1, h2)
        self.assertEqual(len(h1), 64)

    def test_version_hash_name_change_different(self):
        d1 = {"dataset_id": "ds", "name": "n"}
        d2 = {"dataset_id": "ds", "name": "n2"}
        self.assertNotEqual(
            dv.compute_version_hash(d1, "content"), dv.compute_version_hash(d2, "content")
        )

    def test_version_hash_description_change_different(self):
        d1 = {"dataset_id": "ds", "name": "n", "description": ""}
        d2 = {"dataset_id": "ds", "name": "n", "description": "新描述"}
        self.assertNotEqual(
            dv.compute_version_hash(d1, "content"), dv.compute_version_hash(d2, "content")
        )

    def test_version_hash_missing_required_raises(self):
        with self.assertRaises(ValueError):
            dv.compute_version_hash({"name": "n"}, "content")
        with self.assertRaises(ValueError):
            dv.compute_version_hash({"dataset_id": "ds"}, "content")

    # ── 7-9 create_dataset 的 case_id ─────────────────────────────────────

    def test_create_dataset_auto_assign_case_id(self):
        cases = [
            {"input": "a", "expected_output": "A"},
            {"input": "b", "expected_output": "B"},
            {"input": "c", "expected_output": "C"},
        ]
        self._create(cases, "ds")
        cur = dv.get_current("ds", base_dir=self.base_dir)
        self.assertEqual(sorted(c["case_id"] for c in cur["cases"]), [1, 2, 3])

    def test_create_dataset_preserve_existing_case_id(self):
        cases = [
            {"case_id": 5, "input": "a"},
            {"case_id": 7, "input": "b"},
        ]
        self._create(cases, "ds")
        cur = dv.get_current("ds", base_dir=self.base_dir)
        self.assertEqual(sorted(c["case_id"] for c in cur["cases"]), [5, 7])

    def test_create_dataset_duplicate_case_id_rejected(self):
        cases = [
            {"case_id": 1, "input": "a"},
            {"case_id": 1, "input": "b"},
        ]
        with self.assertRaises(ValueError):
            self._create(cases, "ds")

    # ── 10-12 create_version ─────────────────────────────────────────────

    def test_create_version_writes_file(self):
        r = self._create(_cases_ab(), "ds")
        vf = self.base_dir / "ds" / ".versions" / f'{r["version_hash"]}.json'
        self.assertTrue(vf.exists())
        data = json.loads(vf.read_text(encoding="utf-8"))
        self.assertEqual(data["dataset_id"], "ds")
        self.assertEqual(data["version_hash"], r["version_hash"])
        self.assertEqual(data["n_cases"], 2)
        self.assertEqual(data["content_hash"], r["content_hash"])
        cf = self.base_dir / "ds" / ".versions" / ".content" / f'{r["content_hash"]}.json'
        self.assertTrue(cf.exists())

    def test_create_version_duplicate_no_overwrite(self):
        r = self._create(_cases_ab(), "ds")
        vf = self.base_dir / "ds" / ".versions" / f'{r["version_hash"]}.json'
        original = vf.read_text(encoding="utf-8")
        r2 = dv.create_version("ds", base_dir=self.base_dir)
        self.assertFalse(r2["is_new"])
        self.assertEqual(r2["version_hash"], r["version_hash"])
        self.assertEqual(vf.read_text(encoding="utf-8"), original)
        versions_dir = self.base_dir / "ds" / ".versions"
        self.assertEqual(len(list(versions_dir.glob("*.json"))), 1)

    def test_create_version_content_not_rewritten(self):
        r1 = self._create(_cases_ab(), "ds")
        content_dir = self.base_dir / "ds" / ".versions" / ".content"
        # 只改 metadata（name），内容不变 → 新 version_hash、相同 content_hash
        ds_dir = self.base_dir / "ds"
        dataset_def = json.loads((ds_dir / "dataset.json").read_text(encoding="utf-8"))
        dataset_def["name"] = "新名字"
        (ds_dir / "dataset.json").write_text(
            json.dumps(dataset_def, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        r2 = dv.create_version("ds", base_dir=self.base_dir)
        self.assertTrue(r2["is_new"])
        self.assertNotEqual(r1["version_hash"], r2["version_hash"])
        v2 = dv.read_version("ds", r2["version_hash"], base_dir=self.base_dir)
        self.assertEqual(r1["content_hash"], v2["content_hash"])
        self.assertEqual(len(list(content_dir.glob("*.json"))), 1)

    # ── 13-14 read_version ───────────────────────────────────────────────

    def test_read_version_existing(self):
        r = self._create(_cases_ab(), "ds")
        data = dv.read_version("ds", r["version_hash"], base_dir=self.base_dir)
        self.assertIsNotNone(data)
        self.assertEqual(data["version_hash"], r["version_hash"])
        self.assertEqual(data["content_hash"], r["content_hash"])

    def test_read_version_missing(self):
        self.assertIsNone(dv.read_version("ds", "0" * 64, base_dir=self.base_dir))

    # ── 15 list_versions ─────────────────────────────────────────────────

    def test_list_versions_sorted_desc(self):
        versions_dir = self.base_dir / "ds" / ".versions"
        versions_dir.mkdir(parents=True)
        rows = [
            ("a" * 64, "2026-01-01T00:00:00+00:00", "旧版本"),
            ("b" * 64, "2026-02-01T00:00:00+00:00", "新版本"),
            ("c" * 64, "2026-03-01T00:00:00+00:00", "最新版本"),
        ]
        for vh, ts, name in rows:
            (versions_dir / f"{vh}.json").write_text(
                json.dumps(
                    {"dataset_id": "ds", "version_hash": vh, "created_at": ts, "name": name},
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
        items = dv.list_versions("ds", base_dir=self.base_dir)
        self.assertEqual([x["version_hash"] for x in items], ["c" * 64, "b" * 64, "a" * 64])
        self.assertEqual([x["name"] for x in items], ["最新版本", "新版本", "旧版本"])

    def test_list_versions_empty(self):
        self.assertEqual(dv.list_versions("nonexistent", base_dir=self.base_dir), [])

    # ── 16-25 diff_versions ──────────────────────────────────────────────

    def test_diff_versions_added_cases(self):
        v_a = self._create(_cases_ab(), "ds")
        cases_b = _cases_ab() + [
            {"case_id": 3, "input": "新增", "expected_output": "result_c"}
        ]
        v_b = self._write_cases("ds", cases_b)
        diff = dv.diff_versions("ds", v_a["version_hash"], v_b["version_hash"], base_dir=self.base_dir)
        self.assertEqual([c["case_id"] for c in diff["added_cases"]], [3])
        self.assertEqual(diff["removed_cases"], [])
        self.assertEqual(diff["modified_cases"], [])
        self.assertEqual(diff["summary"]["added"], 1)

    def test_diff_versions_removed_cases(self):
        cases_a = _cases_ab() + [
            {"case_id": 3, "input": "删除", "expected_output": "result_c"}
        ]
        v_a = self._create(cases_a, "ds")
        v_b = self._write_cases("ds", _cases_ab())
        diff = dv.diff_versions("ds", v_a["version_hash"], v_b["version_hash"], base_dir=self.base_dir)
        self.assertEqual([c["case_id"] for c in diff["removed_cases"]], [3])
        self.assertEqual(diff["added_cases"], [])
        self.assertEqual(diff["summary"]["removed"], 1)

    def test_diff_versions_modified_value_change(self):
        v_a = self._create(_cases_ab(), "ds")
        cases_b = _cases_ab()
        cases_b[1]["expected_output"] = "CHANGED"
        v_b = self._write_cases("ds", cases_b)
        diff = dv.diff_versions("ds", v_a["version_hash"], v_b["version_hash"], base_dir=self.base_dir)
        self.assertEqual(len(diff["modified_cases"]), 1)
        mc = diff["modified_cases"][0]
        self.assertEqual(mc["case_id"], 2)
        self.assertEqual(
            mc["changes"],
            [{"field": "expected_output", "type": "modified", "before": "result_b", "after": "CHANGED"}],
        )

    def test_diff_versions_modified_field_added(self):
        v_a = self._create([{"case_id": 1, "input": "x"}], "ds")
        v_b = self._write_cases("ds", [{"case_id": 1, "input": "x", "expected_output": "A"}])
        diff = dv.diff_versions("ds", v_a["version_hash"], v_b["version_hash"], base_dir=self.base_dir)
        mc = diff["modified_cases"][0]
        self.assertEqual(mc["changes"], [{"field": "expected_output", "type": "added", "after": "A"}])

    def test_diff_versions_modified_field_removed(self):
        v_a = self._create([{"case_id": 1, "input": "x", "expected_output": "A"}], "ds")
        v_b = self._write_cases("ds", [{"case_id": 1, "input": "x"}])
        diff = dv.diff_versions("ds", v_a["version_hash"], v_b["version_hash"], base_dir=self.base_dir)
        mc = diff["modified_cases"][0]
        self.assertEqual(mc["changes"], [{"field": "expected_output", "type": "removed", "before": "A"}])

    def test_diff_versions_schema_change_added_field(self):
        v_a = self._create([{"case_id": 1, "input": "x"}, {"case_id": 2, "input": "y"}], "ds")
        v_b = self._write_cases(
            "ds",
            [
                {"case_id": 1, "input": "x", "expected_output": "A"},
                {"case_id": 2, "input": "y", "expected_output": "B"},
            ],
        )
        diff = dv.diff_versions("ds", v_a["version_hash"], v_b["version_hash"], base_dir=self.base_dir)
        self.assertEqual(
            diff["schema_changes"],
            [{"field": "expected_output", "type": "added", "affected_cases": 2}],
        )

    def test_diff_versions_schema_change_removed_field(self):
        v_a = self._create(
            [
                {"case_id": 1, "input": "x", "expected_output": "A"},
                {"case_id": 2, "input": "y", "expected_output": "B"},
            ],
            "ds",
        )
        v_b = self._write_cases("ds", [{"case_id": 1, "input": "x"}, {"case_id": 2, "input": "y"}])
        diff = dv.diff_versions("ds", v_a["version_hash"], v_b["version_hash"], base_dir=self.base_dir)
        self.assertEqual(
            diff["schema_changes"],
            [{"field": "expected_output", "type": "removed", "affected_cases": 2}],
        )

    def test_diff_versions_no_schema_change_partial(self):
        v_a = self._create([{"case_id": 1, "input": "x"}, {"case_id": 2, "input": "y"}], "ds")
        v_b = self._write_cases(
            "ds",
            [{"case_id": 1, "input": "x", "expected_output": "A"}, {"case_id": 2, "input": "y"}],
        )
        diff = dv.diff_versions("ds", v_a["version_hash"], v_b["version_hash"], base_dir=self.base_dir)
        self.assertEqual(diff["schema_changes"], [])
        self.assertEqual(len(diff["modified_cases"]), 1)

    def test_diff_versions_no_change(self):
        v_a = self._create(_cases_ab(), "ds")
        ds_dir = self.base_dir / "ds"
        dataset_def = json.loads((ds_dir / "dataset.json").read_text(encoding="utf-8"))
        dataset_def["name"] = "改名但内容不变"
        (ds_dir / "dataset.json").write_text(
            json.dumps(dataset_def, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        v_b = dv.create_version("ds", base_dir=self.base_dir)
        self.assertNotEqual(v_a["version_hash"], v_b["version_hash"])
        diff = dv.diff_versions("ds", v_a["version_hash"], v_b["version_hash"], base_dir=self.base_dir)
        self.assertEqual(diff["summary"]["matched"], 2)
        self.assertEqual(diff["summary"]["modified"], 0)
        self.assertEqual(diff["summary"]["added"], 0)
        self.assertEqual(diff["summary"]["removed"], 0)
        self.assertEqual(diff["schema_changes"], [])
        self.assertEqual(diff["modified_cases"], [])
        self.assertEqual(diff["added_cases"], [])
        self.assertEqual(diff["removed_cases"], [])

    def test_diff_versions_field_filter(self):
        v_a = self._create(_cases_ab(), "ds")
        cases_b = _cases_ab()
        cases_b[1]["input"] = "如何修改登录密码"
        cases_b[1]["expected_output"] = "CHANGED"
        v_b = self._write_cases("ds", cases_b)

        diff_all = dv.diff_versions("ds", v_a["version_hash"], v_b["version_hash"], base_dir=self.base_dir)
        diff_input = dv.diff_versions(
            "ds", v_a["version_hash"], v_b["version_hash"], fields=["input"], base_dir=self.base_dir
        )
        self.assertEqual(len(diff_all["modified_cases"][0]["changes"]), 2)
        self.assertEqual(len(diff_input["modified_cases"]), 1)
        mc = diff_input["modified_cases"][0]
        self.assertEqual(mc["case_id"], 2)
        self.assertTrue(all(ch["field"] == "input" for ch in mc["changes"]))

    # ── 26 infer_schema ──────────────────────────────────────────────────

    def test_infer_schema_auto(self):
        cases = [
            {
                "case_id": 1,
                "input": "x",
                "expected_output": "A",
                "actual_output": None,
                "context": {"a": 1},
                "tags": ["a", "b"],
                "score": 0.5,
                "flag": True,
                "count": 3,
            }
        ]
        schema = dv.infer_schema(cases)
        props = schema["properties"]
        self.assertEqual(props["case_id"]["type"], "integer")
        self.assertEqual(props["input"]["type"], "string")
        self.assertEqual(props["expected_output"]["type"], "string")
        self.assertEqual(props["actual_output"]["type"], "null")
        self.assertEqual(props["context"]["type"], "object")
        self.assertEqual(props["tags"]["type"], "array")
        self.assertEqual(props["score"]["type"], "number")
        self.assertEqual(props["flag"]["type"], "boolean")
        self.assertEqual(props["count"]["type"], "integer")
        self.assertEqual(
            schema["required"],
            ["case_id", "context", "count", "expected_output", "flag", "input", "score", "tags"],
        )

    def test_infer_schema_empty(self):
        self.assertEqual(dv.infer_schema([]), {"type": "object"})

    # ── 27-28 validate_dataset ───────────────────────────────────────────

    def test_validate_dataset_valid(self):
        schema = {
            "type": "object",
            "required": ["case_id", "input"],
            "properties": {"case_id": {"type": "integer"}, "input": {"type": "string"}},
        }
        cases = [{"case_id": 1, "input": "x"}, {"case_id": 2, "input": "y"}]
        self.assertEqual(dv.validate_dataset(cases, schema), [])

    def test_validate_dataset_invalid(self):
        schema = {
            "type": "object",
            "required": ["case_id", "input"],
            "properties": {"case_id": {"type": "integer"}, "input": {"type": "string"}},
        }
        cases = [{"case_id": 1, "input": "x"}, {"case_id": 2, "input": 123}]
        errors = dv.validate_dataset(cases, schema)
        self.assertTrue(errors)
        self.assertTrue(any(e.startswith("case_id=2:") for e in errors))

    # ── 29 migrate_from_file ─────────────────────────────────────────────

    def test_migrate_from_file(self):
        source = Path(self._tmp.name) / "source_cases.json"
        original = [
            {"input": "a", "expected_output": "A"},
            {"input": "b", "expected_output": "B"},
        ]
        source.write_text(json.dumps(original, ensure_ascii=False), encoding="utf-8")
        result = dv.migrate_from_file(str(source), "ds", "迁移集", description="d", base_dir=self.base_dir)
        self.assertEqual(result["dataset_id"], "ds")
        cur = dv.get_current("ds", base_dir=self.base_dir)
        self.assertEqual(sorted(c["case_id"] for c in cur["cases"]), [1, 2])
        self.assertTrue((self.base_dir / "ds" / "dataset.json").exists())
        # 原文件不动
        self.assertEqual(json.loads(source.read_text(encoding="utf-8")), original)

    # ── 审计新增用例 ─────────────────────────────────────────────────────

    def test_content_hash_empty_array(self):
        h = dv.compute_content_hash([])
        self.assertEqual(h, hashlib.sha256("[]".encode("utf-8")).hexdigest())
        self.assertEqual(len(h), 64)

    def test_create_dataset_non_int_case_id(self):
        cases = [{"case_id": "3", "input": "x"}]
        self._create(cases, "ds")
        cur = dv.get_current("ds", base_dir=self.base_dir)
        self.assertIsInstance(cur["cases"][0]["case_id"], int)
        self.assertEqual(cur["cases"][0]["case_id"], 3)

    def test_create_dataset_invalid_case_id_raises(self):
        with self.assertRaises(ValueError):
            self._create([{"case_id": "abc", "input": "x"}], "ds")

    def test_create_dataset_schema_validation_raises(self):
        schema = {
            "type": "object",
            "required": ["input"],
            "properties": {"input": {"type": "string"}},
        }
        with self.assertRaises(ValueError):
            dv.create_dataset("ds", "n", [{"input": 123}], schema=schema, base_dir=self.base_dir)

    def test_infer_schema_multi_type_union(self):
        cases = [{"case_id": 1, "value": "text"}, {"case_id": 2, "value": 42}]
        schema = dv.infer_schema(cases)
        self.assertEqual(schema["properties"]["value"]["type"], ["integer", "string"])

    def test_detect_schema_changes_denominator(self):
        matched_changes = [{"case_id": i, "changes": []} for i in range(1, 11)]
        matched_changes[0]["changes"] = [{"field": "x", "type": "added", "after": 1}]
        # 10 个 matched 中只有 1 个出现字段 → 不应判 schema 变化（分母是 n_matched）
        self.assertEqual(dv.detect_schema_changes(matched_changes, 10), [])
        for entry in matched_changes:
            entry["changes"] = [{"field": "x", "type": "added", "after": 1}]
        self.assertEqual(
            dv.detect_schema_changes(matched_changes, 10),
            [{"field": "x", "type": "added", "affected_cases": 10}],
        )
        # 防除零
        self.assertEqual(dv.detect_schema_changes([], 0), [])

    def test_diff_case_ignores_case_id(self):
        a = {"case_id": 1, "input": "x"}
        b = {"case_id": 2, "input": "x"}
        self.assertEqual(dv.diff_case(a, b), [])

    def test_get_current_contract(self):
        r = self._create(_cases_ab(), "ds")
        cur = dv.get_current("ds", base_dir=self.base_dir)
        self.assertIsNotNone(cur)
        self.assertEqual(cur["dataset_id"], "ds")
        self.assertEqual(cur["name"], "测试集")
        self.assertEqual(cur["n_cases"], 2)
        self.assertEqual(cur["content_hash"], r["content_hash"])
        self.assertEqual([c["case_id"] for c in cur["cases"]], [1, 2])
        self.assertEqual(cur["cases"], sorted(_cases_ab(), key=lambda c: c["case_id"]))
        self.assertIsNone(dv.get_current("nope", base_dir=self.base_dir))

    def test_atomic_write_order_rewrites_missing_content(self):
        r = self._create(_cases_ab(), "ds")
        content_file = self.base_dir / "ds" / ".versions" / ".content" / f'{r["content_hash"]}.json'
        self.assertTrue(content_file.exists())
        content_file.unlink()
        r2 = dv.create_version("ds", base_dir=self.base_dir)
        self.assertFalse(r2["is_new"])  # version record 已存在
        self.assertTrue(content_file.exists())  # content 在版本检查前被补写
        versions_dir = self.base_dir / "ds" / ".versions"
        self.assertEqual(list(versions_dir.rglob("*.tmp")), [])

    def test_type_change_schema_detection(self):
        v_a = self._create(
            [{"case_id": 1, "actual_output": None}, {"case_id": 2, "actual_output": None}],
            "ds",
        )
        v_b = self._write_cases(
            "ds",
            [
                {"case_id": 1, "actual_output": "result_a"},
                {"case_id": 2, "actual_output": "result_b"},
            ],
        )
        diff = dv.diff_versions("ds", v_a["version_hash"], v_b["version_hash"], base_dir=self.base_dir)
        self.assertEqual(len(diff["modified_cases"]), 2)
        for mc in diff["modified_cases"]:
            for ch in mc["changes"]:
                self.assertEqual(ch["type"], "modified")
                self.assertEqual(ch["field"], "actual_output")
                self.assertIsNone(ch["before"])
        self.assertEqual(
            diff["schema_changes"],
            [{"field": "actual_output", "type": "type_changed", "affected_cases": 2}],
        )


class MiniJsonSchemaTestCase(unittest.TestCase):
    def test_type_string(self):
        self.assertEqual(mjs.validate("abc", {"type": "string"}), [])
        self.assertTrue(mjs.validate(123, {"type": "string"}))

    def test_type_union(self):
        schema = {"type": ["string", "null"]}
        self.assertEqual(mjs.validate(None, schema), [])
        self.assertEqual(mjs.validate("x", schema), [])
        self.assertTrue(mjs.validate(1, schema))

    def test_enum(self):
        self.assertEqual(mjs.validate("agent", {"enum": ["agent", "ui"]}), [])
        self.assertTrue(mjs.validate("other", {"enum": ["agent", "ui"]}))

    def test_const(self):
        self.assertEqual(mjs.validate("1.0", {"const": "1.0"}), [])
        self.assertTrue(mjs.validate("2.0", {"const": "1.0"}))

    def test_pattern(self):
        self.assertEqual(mjs.validate("a1b2c3", {"pattern": "^[0-9a-f]{6}$"}), [])
        self.assertTrue(mjs.validate("xyz", {"pattern": "^[0-9a-f]{6}$"}))

    def test_min_length(self):
        self.assertEqual(mjs.validate("ab", {"minLength": 1}), [])
        self.assertTrue(mjs.validate("", {"minLength": 1}))

    def test_minimum(self):
        self.assertEqual(mjs.validate(5, {"minimum": 3}), [])
        self.assertTrue(mjs.validate(2, {"minimum": 3}))

    def test_min_items(self):
        self.assertEqual(mjs.validate([1, 2], {"minItems": 1}), [])
        self.assertTrue(mjs.validate([], {"minItems": 1}))

    def test_additional_properties_false(self):
        schema = {
            "type": "object",
            "properties": {"a": {"type": "string"}},
            "additionalProperties": False,
        }
        self.assertEqual(mjs.validate({"a": "x"}, schema), [])
        self.assertTrue(mjs.validate({"a": "x", "b": 1}, schema))

    def test_one_of(self):
        schema = {"oneOf": [{"type": "null"}, {"type": "object"}]}
        self.assertEqual(mjs.validate(None, schema), [])
        self.assertEqual(mjs.validate({"a": 1}, schema), [])
        self.assertTrue(mjs.validate("str", schema))

    def test_any_of(self):
        schema = {"anyOf": [{"type": "string"}, {"type": "integer"}]}
        self.assertEqual(mjs.validate("x", schema), [])
        self.assertEqual(mjs.validate(1, schema), [])
        self.assertTrue(mjs.validate([], schema))

    def test_unsupported_keyword_raises(self):
        with self.assertRaises(mjs.UnsupportedKeywordError):
            mjs.validate("x", {"maxLength": 5})

    def test_null_schema_passes(self):
        self.assertEqual(mjs.validate({"anything": 1}, None), [])
        self.assertEqual(mjs.validate({"anything": 1}, {}), [])

    def test_manifest_schema_smoke(self):
        schema = {
            "$schema": "https://json-schema.org/draft-07/schema",
            "type": "object",
            "required": ["manifest_version", "dataset", "metrics"],
            "properties": {
                "manifest_version": {"type": "string", "const": "1.0"},
                "manifest_hash": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
                "triggered_by": {"type": "string", "enum": ["agent", "ui"]},
                "dataset": {
                    "type": "object",
                    "required": ["dataset_id", "n_cases"],
                    "properties": {
                        "dataset_id": {"type": "string", "minLength": 1},
                        "n_cases": {"type": "integer", "minimum": 0},
                    },
                },
                "metrics": {"type": "array", "minItems": 1, "items": {"type": "object"}},
                "judge_model": {"oneOf": [{"type": "null"}, {"type": "object"}]},
            },
        }
        valid = {
            "manifest_version": "1.0",
            "triggered_by": "agent",
            "dataset": {"dataset_id": "ds", "n_cases": 5},
            "metrics": [{"name": "mrr"}],
            "judge_model": None,
        }
        self.assertEqual(mjs.validate(valid, schema), [])
        bad = dict(valid)
        bad["dataset"] = {"dataset_id": "ds", "n_cases": -1}
        self.assertTrue(mjs.validate(bad, schema))


if __name__ == "__main__":
    unittest.main()
