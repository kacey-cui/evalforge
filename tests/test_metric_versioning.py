"""Metric Versioning 模块测试（标准库 unittest）。

覆盖设计文档第 7.2 节全部 19 条用例 + 审计新增 3 条。
所有 fixture 均使用 tempfile.TemporaryDirectory()，绝不读写真实 data/metrics/。
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import metric_versioning as mv


THRESHOLD_PARAM = {
    "key": "threshold",
    "label": "阈值",
    "type": "number",
    "default": 0.7,
    "min": 0,
    "max": 1,
    "step": 0.1,
}
K_PARAM = {
    "key": "k",
    "label": "K 值",
    "type": "number",
    "default": 5,
    "min": 1,
    "max": 100,
    "step": 1,
}


def _sample_metric(**overrides):
    m = {
        "id": "sample",
        "name": "样例指标",
        "category": "llm",
        "description": "测试用指标",
        "params": [dict(THRESHOLD_PARAM), dict(K_PARAM)],
        "criteria": "评估回答是否准确",
        "requires": ["actual_output", "expected_output"],
        "code_template": "GEval(...)",
    }
    m.update(overrides)
    return m


class MetricVersioningTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.base_dir = Path(self._tmp.name) / "metrics"
        self.base_dir.mkdir(parents=True)

    def tearDown(self):
        self._tmp.cleanup()

    def _write_metric(self, metric, category=None, filename="sample.json"):
        cat = category or metric.get("category") or "llm"
        cat_dir = self.base_dir / cat
        cat_dir.mkdir(parents=True, exist_ok=True)
        path = cat_dir / filename
        path.write_text(json.dumps(metric, ensure_ascii=False), encoding="utf-8")
        return path

    def _write_version(self, category, metric_id, version_hash, record):
        versions_dir = self.base_dir / category / ".versions" / metric_id
        versions_dir.mkdir(parents=True, exist_ok=True)
        f = versions_dir / f"{version_hash}.json"
        f.write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")
        return f

    def _full_record(self, metric, version_hash, created_at="2026-01-01T00:00:00+00:00"):
        return {
            "metric_id": metric.get("id") or metric.get("metric_id"),
            "version_hash": version_hash,
            "created_at": created_at,
            "name": metric.get("name"),
            "description": metric.get("description"),
            "category": metric.get("category"),
            "params": metric.get("params"),
            "criteria": metric.get("criteria"),
            "requires": metric.get("requires"),
            "code_template": metric.get("code_template"),
        }

    # ── 1-6 compute_version_hash ──────────────────────────────────────

    def test_compute_version_hash_same_content_same_hash(self):
        m = _sample_metric()
        h1 = mv.compute_version_hash(m)
        h2 = mv.compute_version_hash(m)
        self.assertEqual(h1, h2)
        self.assertEqual(len(h1), 64)

    def test_compute_version_hash_criteria_change_different(self):
        h1 = mv.compute_version_hash(_sample_metric())
        h2 = mv.compute_version_hash(_sample_metric(criteria="完全不同的标准"))
        self.assertNotEqual(h1, h2)

    def test_compute_version_hash_name_change_same(self):
        h1 = mv.compute_version_hash(_sample_metric())
        h2 = mv.compute_version_hash(_sample_metric(name="另一个名字"))
        self.assertEqual(h1, h2)

    def test_compute_version_hash_description_change_same(self):
        h1 = mv.compute_version_hash(_sample_metric())
        h2 = mv.compute_version_hash(_sample_metric(description="另一段描述"))
        self.assertEqual(h1, h2)

    def test_compute_version_hash_params_order_independent(self):
        m1 = _sample_metric()
        m2 = _sample_metric(params=[dict(K_PARAM), dict(THRESHOLD_PARAM)])
        self.assertEqual(mv.compute_version_hash(m1), mv.compute_version_hash(m2))

    def test_compute_version_hash_requires_order_independent(self):
        h1 = mv.compute_version_hash(_sample_metric(requires=["actual_output", "expected_output"]))
        h2 = mv.compute_version_hash(_sample_metric(requires=["expected_output", "actual_output"]))
        self.assertEqual(h1, h2)

    # ── 7-9 create_version ────────────────────────────────────────────

    def test_create_version_writes_file(self):
        m = _sample_metric()
        path = self._write_metric(m)
        result = mv.create_version(str(path))
        self.assertTrue(result["is_new"])
        self.assertIsNotNone(result["created_at"])
        vf = self.base_dir / "llm" / ".versions" / "sample" / f'{result["version_hash"]}.json'
        self.assertTrue(vf.exists())
        data = json.loads(vf.read_text(encoding="utf-8"))
        self.assertEqual(data["metric_id"], "sample")
        self.assertEqual(data["version_hash"], result["version_hash"])
        self.assertEqual(data["category"], "llm")
        self.assertEqual(data["params"], m["params"])

    def test_create_version_duplicate_no_overwrite(self):
        path = self._write_metric(_sample_metric())
        r1 = mv.create_version(str(path))
        r2 = mv.create_version(str(path))
        self.assertTrue(r1["is_new"])
        self.assertFalse(r2["is_new"])
        self.assertEqual(r1["version_hash"], r2["version_hash"])
        self.assertEqual(r1["created_at"], r2["created_at"])
        versions_dir = self.base_dir / "llm" / ".versions" / "sample"
        self.assertEqual(len(list(versions_dir.glob("*.json"))), 1)

    def test_create_version_immutable(self):
        path = self._write_metric(_sample_metric())
        r1 = mv.create_version(str(path))
        vf = self.base_dir / "llm" / ".versions" / "sample" / f'{r1["version_hash"]}.json'
        original = vf.read_text(encoding="utf-8")

        # 修改源文件 → 产生新版本
        path.write_text(
            json.dumps(_sample_metric(criteria="完全不同的标准"), ensure_ascii=False),
            encoding="utf-8",
        )
        r2 = mv.create_version(str(path))
        self.assertNotEqual(r1["version_hash"], r2["version_hash"])

        # 旧版本文件内容保持不可变
        self.assertEqual(vf.read_text(encoding="utf-8"), original)

    # ── 10-11 read_version ────────────────────────────────────────────

    def test_read_version_existing(self):
        path = self._write_metric(_sample_metric())
        r = mv.create_version(str(path))
        data = mv.read_version("sample", r["version_hash"], base_dir=self.base_dir)
        self.assertIsNotNone(data)
        self.assertEqual(data["metric_id"], "sample")
        self.assertEqual(data["version_hash"], r["version_hash"])

    def test_read_version_missing(self):
        self.assertIsNone(mv.read_version("sample", "0" * 64, base_dir=self.base_dir))

    # ── 12-13 list_versions ───────────────────────────────────────────

    def test_list_versions_sorted_desc(self):
        rows = [
            ("a" * 64, "2026-01-01T00:00:00+00:00", "旧版本"),
            ("b" * 64, "2026-02-01T00:00:00+00:00", "新版本"),
            ("c" * 64, "2026-03-01T00:00:00+00:00", "最新版本"),
        ]
        for vh, ts, name in rows:
            self._write_version("llm", "sample", vh, {
                "metric_id": "sample", "version_hash": vh, "created_at": ts, "name": name,
            })
        items = mv.list_versions("sample", base_dir=self.base_dir)
        self.assertEqual([x["version_hash"] for x in items], ["c" * 64, "b" * 64, "a" * 64])
        self.assertEqual([x["name"] for x in items], ["最新版本", "新版本", "旧版本"])

    def test_list_versions_empty(self):
        self.assertEqual(mv.list_versions("nonexistent", base_dir=self.base_dir), [])

    # ── 14-17 diff_versions ───────────────────────────────────────────

    def test_diff_versions_added(self):
        ma = _sample_metric(params=[dict(THRESHOLD_PARAM)], requires=["actual_output"])
        mb = _sample_metric()
        ha, hb = "1" * 64, "2" * 64
        self._write_version("llm", "sample", ha, self._full_record(ma, ha))
        self._write_version("llm", "sample", hb, self._full_record(mb, hb))
        diff = mv.diff_versions("sample", ha, hb, base_dir=self.base_dir)
        self.assertIn("params[1]", diff["added_fields"])
        self.assertIn("requires[1]", diff["added_fields"])

    def test_diff_versions_removed(self):
        ma = _sample_metric()
        mb = _sample_metric(params=[dict(THRESHOLD_PARAM)], requires=["actual_output"])
        ha, hb = "1" * 64, "2" * 64
        self._write_version("llm", "sample", ha, self._full_record(ma, ha))
        self._write_version("llm", "sample", hb, self._full_record(mb, hb))
        diff = mv.diff_versions("sample", ha, hb, base_dir=self.base_dir)
        self.assertIn("params[1]", diff["removed_fields"])
        self.assertIn("requires[1]", diff["removed_fields"])

    def test_diff_versions_modified(self):
        ma = _sample_metric(criteria="标准A", params=[dict(THRESHOLD_PARAM)])
        mb = _sample_metric(criteria="标准B", params=[{**THRESHOLD_PARAM, "default": 0.8}])
        ha, hb = "1" * 64, "2" * 64
        self._write_version("llm", "sample", ha, self._full_record(ma, ha))
        self._write_version("llm", "sample", hb, self._full_record(mb, hb))
        diff = mv.diff_versions("sample", ha, hb, base_dir=self.base_dir)
        self.assertIn("criteria", diff["modified_fields"])
        self.assertIn("params[0].default", diff["modified_fields"])

    def test_diff_versions_no_change(self):
        m = _sample_metric()
        ha, hb = "1" * 64, "2" * 64
        self._write_version("llm", "sample", ha, self._full_record(m, ha))
        self._write_version("llm", "sample", hb, self._full_record(m, hb))
        diff = mv.diff_versions("sample", ha, hb, base_dir=self.base_dir)
        self.assertEqual(diff["changes"], [])
        self.assertEqual(diff["added_fields"], [])
        self.assertEqual(diff["removed_fields"], [])
        self.assertEqual(diff["modified_fields"], [])

    # ── 18-19 migrate_existing ────────────────────────────────────────

    def test_migrate_existing_creates_all(self):
        self._write_metric(_sample_metric(id="m_ok1"), category="llm", filename="m_ok1.json")
        self._write_metric(_sample_metric(id="m_ok2", category="non_llm"), category="non_llm", filename="m_ok2.json")
        self._write_metric({"category": "llm", "name": "no id"}, category="llm", filename="no_id.json")
        self._write_metric({"id": "no_cat", "name": "no cat", "params": []}, category="llm", filename="no_cat.json")

        hashes = mv.migrate_existing(base_dir=self.base_dir)
        self.assertEqual(len(hashes), 2)
        self.assertTrue((self.base_dir / "llm" / ".versions" / "m_ok1").is_dir())
        self.assertTrue((self.base_dir / "non_llm" / ".versions" / "m_ok2").is_dir())
        self.assertFalse((self.base_dir / "llm" / ".versions" / "no_id").exists())
        self.assertFalse((self.base_dir / "llm" / ".versions" / "no_cat").exists())

    def test_migrate_existing_idempotent(self):
        self._write_metric(_sample_metric(), category="llm", filename="sample.json")
        h1 = mv.migrate_existing(base_dir=self.base_dir)
        self.assertEqual(len(h1), 1)
        h2 = mv.migrate_existing(base_dir=self.base_dir)
        self.assertEqual(h2, [])

    # ── 审计新增 3 条 ─────────────────────────────────────────────────

    def test_hash_matches_version_filename(self):
        path = self._write_metric(_sample_metric())
        r = mv.create_version(str(path))
        data = mv.read_version("sample", r["version_hash"], base_dir=self.base_dir)
        self.assertEqual(mv.compute_version_hash(data), r["version_hash"])

    def test_create_version_missing_category_raises(self):
        metric = {"id": "no_cat", "name": "无分类", "params": []}
        path = self._write_metric(metric, category="llm", filename="no_cat.json")
        with self.assertRaises(ValueError) as ctx:
            mv.create_version(str(path))
        self.assertIn("category", str(ctx.exception))

    def test_label_change_does_not_change_hash(self):
        h1 = mv.compute_version_hash(_sample_metric(params=[{**THRESHOLD_PARAM, "label": "标签A"}]))
        h2 = mv.compute_version_hash(_sample_metric(params=[{**THRESHOLD_PARAM, "label": "标签B"}]))
        self.assertEqual(h1, h2)


if __name__ == "__main__":
    unittest.main()
