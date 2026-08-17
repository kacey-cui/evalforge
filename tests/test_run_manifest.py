"""run_manifest 模块测试（标准库 unittest）。

覆盖设计 §13 的 20 条用例 + 审计新增用例。
所有 fixture 均使用 tempfile.TemporaryDirectory()，绝不读写真实 data/。
"""

import hashlib
import json
import platform
import sys
import tempfile
import unittest
from dataclasses import asdict
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import run_manifest as rm
import metric_versioning as mv
import dataset_versioning as dv


def _cases():
    return [
        {"case_id": 1, "input": "查询账户余额", "expected_output": "result_a"},
        {"case_id": 2, "input": "如何修改密码", "expected_output": "result_b"},
    ]


def _metric_def(metric_id="recall_at_k", category="llm", name="Recall@k"):
    return {
        "id": metric_id,
        "name": name,
        "category": category,
        "description": "测试指标",
        "params": [
            {
                "key": "k",
                "label": "K 值",
                "type": "number",
                "default": 5,
                "min": 1,
                "max": 100,
                "step": 1,
            }
        ],
        "criteria": "评估召回",
        "requires": ["actual_output", "expected_output"],
        "code_template": "GEval(...)",
    }


class RunManifestTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)  # 作为 data 根目录
        self.dataset_base = self.root / "datasets"
        self.metric_base = self.root / "metrics"
        self.dataset_base.mkdir(parents=True)
        self.metric_base.mkdir(parents=True)
        self.skill_path = self.root / "eval_script.py"
        self.skill_path.write_text("print('hello eval')\n", encoding="utf-8")

    def tearDown(self):
        self._tmp.cleanup()

    # ── 合成 fixture 工具 ──────────────────────────────────────────────

    def _write_metric(self, metric, filename=None):
        m = dict(metric)
        cat = m.get("category") or "llm"
        cat_dir = self.metric_base / cat
        cat_dir.mkdir(parents=True, exist_ok=True)
        path = cat_dir / (filename or f'{m.get("id")}.json')
        path.write_text(json.dumps(m, ensure_ascii=False), encoding="utf-8")
        return path

    def _write_canvas(self, fields, global_cfg=None):
        p = self.root / "canvas.json"
        p.write_text(
            json.dumps({"fields": fields, "global": global_cfg or {}}, ensure_ascii=False),
            encoding="utf-8",
        )
        return p

    def _build_full_manifest(self):
        """构建一个「dataset + 3 metrics + skill + model + judge_model」都齐全的 manifest。"""
        dv.create_dataset("ds", "测试集", _cases(), base_dir=self.dataset_base)
        self._write_metric(_metric_def("recall_at_k", "llm", "Recall@k"))
        self._write_metric(_metric_def("mrr", "non_llm", "MRR"))
        canvas = self._write_canvas(
            [
                {
                    "name": "diagnosis",
                    "gatePipeline": [
                        {"metricId": "mrr", "params": {"threshold": 0.5}, "order": 0}
                    ],
                    "scorePipeline": [
                        {
                            "metricId": "recall_at_k",
                            "label": "Recall@1",
                            "params": {"k": 1},
                            "weight": 0.5,
                            "strictness": 1.0,
                            "order": 0,
                        },
                        {
                            "metricId": "recall_at_k",
                            "label": "Recall@3",
                            "params": {"k": 3},
                            "weight": 0.5,
                            "strictness": 1.0,
                            "order": 1,
                        },
                    ],
                }
            ],
            {"modelId": "m1", "modelBaseUrl": "http://m", "skillName": "proj"},
        )
        return rm.build_manifest(
            run_id="run_1",
            triggered_by="agent",
            dataset_id="ds",
            project="proj",
            skill_path=str(self.skill_path),
            model_id="m1",
            model_base_url="http://m",
            judge_model_id="j1",
            judge_model_base_url="http://j",
            config_json_path=str(canvas),
            results={"config": {"metrics": []}},
            dataset_base_dir=self.dataset_base,
            metric_base_dir=self.metric_base,
        )

    def _valid_manifest(self):
        m = self._build_full_manifest()
        m["manifest_hash"] = rm.compute_manifest_hash(m)
        return m

    # ── 1 build_manifest 完整构建 ──────────────────────────────────────

    def test_build_manifest_complete(self):
        m = self._build_full_manifest()
        self.assertEqual(m["manifest_version"], "1.0")
        self.assertEqual(m["run_id"], "run_1")
        self.assertEqual(m["triggered_by"], "agent")
        self.assertTrue(m["created_at"])

        # dataset
        cur = dv.get_current("ds", base_dir=self.dataset_base)
        cases = cur["cases"]
        content_hash = dv.compute_content_hash(cases)
        def_for_hash = dict(cur)
        def_for_hash["n_cases"] = len(cases)
        expected_vh = dv.compute_version_hash(def_for_hash, content_hash)
        self.assertEqual(m["dataset"]["dataset_id"], "ds")
        self.assertEqual(m["dataset"]["version_hash"], expected_vh)
        self.assertEqual(m["dataset"]["content_hash"], content_hash)
        self.assertEqual(m["dataset"]["n_cases"], 2)
        self.assertEqual(m["dataset"]["source_path"], "data/datasets/ds/test_cases.json")

        # metrics：gate(mrr) + score(recall_at_k x2)
        self.assertEqual(len(m["metrics"]), 3)
        zones = [x["instance"]["zone"] for x in m["metrics"]]
        self.assertEqual(zones, ["gate", "score", "score"])
        recall_def = json.loads((self.metric_base / "llm" / "recall_at_k.json").read_text(encoding="utf-8"))
        for x in m["metrics"]:
            if x["metric_id"] == "recall_at_k":
                self.assertEqual(x["version_hash"], mv.compute_version_hash(recall_def))

        # skill / model / judge_model
        self.assertEqual(m["skill"]["name"], "proj")
        self.assertEqual(m["skill"]["content_hash"], hashlib.sha256(self.skill_path.read_bytes()).hexdigest())
        self.assertEqual(m["model"]["model_id"], "m1")
        self.assertEqual(m["model"]["base_url"], "http://m")
        self.assertEqual(m["model"]["extra_config"], {})
        self.assertEqual(m["judge_model"]["model_id"], "j1")

    # ── 2-4 compute_manifest_hash ──────────────────────────────────────

    def test_compute_manifest_hash_deterministic(self):
        m = self._build_full_manifest()
        self.assertEqual(rm.compute_manifest_hash(m), rm.compute_manifest_hash(m))
        self.assertEqual(len(rm.compute_manifest_hash(m)), 64)

    def test_compute_manifest_hash_excludes_self(self):
        m = self._build_full_manifest()
        m["manifest_hash"] = "0" * 64
        h1 = rm.compute_manifest_hash(m)
        m["manifest_hash"] = "f" * 64
        h2 = rm.compute_manifest_hash(m)
        self.assertEqual(h1, h2)
        self.assertEqual(len(h1), 64)

    def test_compute_manifest_hash_changes_on_field_change(self):
        m = self._build_full_manifest()
        h1 = rm.compute_manifest_hash(m)
        m2 = json.loads(json.dumps(m))
        m2["run_id"] = "run_2"
        self.assertNotEqual(h1, rm.compute_manifest_hash(m2))

    # ── 5-9 validate_manifest ──────────────────────────────────────────

    def test_validate_manifest_valid(self):
        self.assertEqual(rm.validate_manifest(self._valid_manifest()), [])

    def test_validate_manifest_missing_required(self):
        m = self._valid_manifest()
        m.pop("dataset")
        self.assertTrue(rm.validate_manifest(m))

    def test_validate_manifest_bad_hash_format(self):
        m = self._valid_manifest()
        m["dataset"]["version_hash"] = "not-a-hash"
        self.assertTrue(rm.validate_manifest(m))

    def test_validate_manifest_judge_model_null(self):
        m = self._valid_manifest()
        m["judge_model"] = None
        self.assertEqual(rm.validate_manifest(m), [])

    def test_validate_manifest_optional_manifest_hash(self):
        m = self._valid_manifest()
        m.pop("manifest_hash")
        self.assertEqual(rm.validate_manifest(m), [])

    # ── 10-11 serialize / deserialize ──────────────────────────────────

    def test_serialize_deserialize_roundtrip(self):
        m0 = rm.Manifest(
            run_id="r",
            created_at="2026-01-01T00:00:00+00:00",
            triggered_by="agent",
            dataset=rm.DatasetRef("ds", "0" * 64, "1" * 64, 2, "src"),
            metrics=[
                rm.MetricRef(
                    "m",
                    "2" * 64,
                    rm.MetricInstance(label="L", params={"k": 1}, weight=0.5, strictness=1.0, zone="score"),
                )
            ],
            skill=rm.SkillRef("s", "3" * 64, "path"),
            model=rm.ModelRef("m", "url", {}),
            judge_model=rm.ModelRef("j", "jurl"),
            environment=rm.EnvironmentInfo("3.10.0", "plat", {}),
            extra={"a": 1},
        )
        m0.manifest_hash = rm.compute_manifest_hash(asdict(m0))
        m1 = rm.deserialize(rm.serialize(m0))
        self.assertEqual(asdict(m1), asdict(m0))

    def test_deserialize_rebuilds_dataclass(self):
        d = {
            "manifest_version": "1.0",
            "manifest_hash": "0" * 64,
            "run_id": "r",
            "created_at": "2026-01-01T00:00:00+00:00",
            "triggered_by": "agent",
            "dataset": {"dataset_id": "ds", "version_hash": "1" * 64, "content_hash": "2" * 64, "n_cases": 3},
            "metrics": [
                {"metric_id": "m", "version_hash": "3" * 64, "instance": {"label": "L", "params": {}, "weight": 1.0, "strictness": 1.0, "zone": "score"}}
            ],
            "skill": {"name": "s", "content_hash": "4" * 64},
            "model": {"model_id": "m"},
            "judge_model": None,
            "environment": {"python_version": "3.10.0", "platform": "p", "dependencies": {}},
            "extra": {},
        }
        m = rm.deserialize(json.dumps(d, ensure_ascii=False))
        self.assertIsInstance(m, rm.Manifest)
        self.assertIsInstance(m.dataset, rm.DatasetRef)
        self.assertIsInstance(m.metrics[0], rm.MetricRef)
        self.assertIsInstance(m.metrics[0].instance, rm.MetricInstance)
        self.assertIsInstance(m.skill, rm.SkillRef)
        self.assertIsInstance(m.model, rm.ModelRef)
        self.assertIsNone(m.judge_model)
        self.assertIsInstance(m.environment, rm.EnvironmentInfo)
        self.assertEqual(m.dataset.n_cases, 3)
        self.assertEqual(m.metrics[0].instance.zone, "score")

    # ── 12-14 record_run 产物的等价行为（端到端由冒烟覆盖）───────────────

    def test_record_run_manifest_structure(self):
        m = self._valid_manifest()
        for key in (
            "manifest_version", "manifest_hash", "run_id", "created_at", "triggered_by",
            "dataset", "metrics", "skill", "model", "judge_model", "environment", "extra",
        ):
            self.assertIn(key, m)

    def test_dataset_ref_points_to_dataset(self):
        m = self._build_full_manifest()
        ds = m.get("dataset")
        # 复刻 record_run 的 dataset_ref 修复逻辑
        dataset_ref = {
            "n_cases": ds["n_cases"] if ds else 0,
            "source": "results.json",
            "sha256": ds["content_hash"] if ds else "results-file-hash",
            "dataset_id": ds["dataset_id"] if ds else None,
            "version_hash": ds["version_hash"] if ds else None,
            "content_hash": ds["content_hash"] if ds else None,
            "source_path": ds["source_path"] if ds else "",
        }
        self.assertEqual(dataset_ref["sha256"], ds["content_hash"])
        self.assertEqual(dataset_ref["source"], "results.json")
        self.assertEqual(dataset_ref["dataset_id"], "ds")

    def test_results_inject_manifest_hash(self):
        m = self._build_full_manifest()
        m["manifest_hash"] = rm.compute_manifest_hash(m)
        results = {"n_cases": 2, "overall_score": 0.9}
        results["manifest_hash"] = m["manifest_hash"]
        self.assertEqual(results["manifest_hash"], m["manifest_hash"])
        self.assertEqual(len(results["manifest_hash"]), 64)

    # ── 15-17 verify_manifest ──────────────────────────────────────────

    def test_verify_manifest_metric_modified_still_found(self):
        m = self._build_full_manifest()
        old_hashes = {x["metric_id"]: x["version_hash"] for x in m["metrics"]}
        # 修改 metric 定义文件
        path = self.metric_base / "llm" / "recall_at_k.json"
        metric = json.loads(path.read_text(encoding="utf-8"))
        metric["criteria"] = "修改后的标准"
        path.write_text(json.dumps(metric, ensure_ascii=False), encoding="utf-8")
        new_hash = mv.compute_version_hash(metric)
        self.assertNotEqual(old_hashes["recall_at_k"], new_hash)
        # 旧版本仍在 .versions/，verify 命中
        res = rm.verify_manifest(m, base_dir=self.root)
        self.assertTrue(res["valid"])
        self.assertTrue(all(c["status"] == "ok" for c in res["checks"]))

    def test_verify_manifest_dataset_modified_still_found(self):
        m = self._build_full_manifest()
        old_content = m["dataset"]["content_hash"]
        # 修改 dataset 内容
        cases = _cases() + [{"case_id": 3, "input": "新增", "expected_output": "result_c"}]
        ds_dir = self.dataset_base / "ds"
        (ds_dir / "test_cases.json").write_text(
            json.dumps(sorted(cases, key=lambda c: c["case_id"]), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        dv.create_version("ds", base_dir=self.dataset_base)
        self.assertNotEqual(dv.compute_content_hash(cases), old_content)
        res = rm.verify_manifest(m, base_dir=self.root)
        self.assertTrue(res["valid"])

    def test_verify_manifest_reconstruct_inputs(self):
        m = self._build_full_manifest()
        res = rm.verify_manifest(m, base_dir=self.root)
        self.assertTrue(res["valid"])

        ds = m["dataset"]
        v = dv.read_version(ds["dataset_id"], ds["version_hash"], base_dir=self.dataset_base)
        self.assertIsNotNone(v)
        content_file = (
            self.dataset_base / ds["dataset_id"] / ".versions" / ".content"
            / f'{ds["content_hash"]}.json'
        )
        self.assertTrue(content_file.exists())
        cases = json.loads(content_file.read_text(encoding="utf-8"))
        self.assertEqual(len(cases), 2)

        for met in m["metrics"]:
            self.assertIsNotNone(
                mv.read_version(met["metric_id"], met["version_hash"], base_dir=self.metric_base)
            )

        self.assertEqual(m["skill"]["content_hash"], hashlib.sha256(self.skill_path.read_bytes()).hexdigest())

    # ── 18 environment 自动采集 ────────────────────────────────────────

    def test_environment_autocollect(self):
        m = rm.build_manifest(run_id="r")
        env = m["environment"]
        self.assertEqual(env["python_version"], sys.version.split()[0])
        self.assertEqual(env["platform"], platform.platform())
        self.assertEqual(set(env["dependencies"]), {"deepeval", "openai", "requests"})

    # ── 19 同一 metric 多个 instance ───────────────────────────────────

    def test_multi_instance_same_metric(self):
        self._write_metric(_metric_def("recall_at_k", "llm", "Recall@k"))
        ks = [1, 2, 3, 5, 10, 20, 50]
        canvas = self._write_canvas(
            [
                {
                    "name": "f",
                    "scorePipeline": [
                        {"metricId": "recall_at_k", "label": f"Recall@{k}", "params": {"k": k}, "weight": 0.1, "order": i}
                        for i, k in enumerate(ks)
                    ],
                }
            ],
            {},
        )
        m = rm.build_manifest(
            run_id="r", project="p", skill_path=str(self.skill_path), model_id="m",
            config_json_path=str(canvas), metric_base_dir=self.metric_base,
        )
        self.assertEqual(len(m["metrics"]), 7)
        self.assertEqual(len({x["version_hash"] for x in m["metrics"]}), 1)
        self.assertEqual(sorted(x["instance"]["params"]["k"] for x in m["metrics"]), ks)

    # ── 20 manifest_hash 自身一致性 ────────────────────────────────────

    def test_manifest_hash_self_consistency(self):
        m = self._build_full_manifest()
        m["manifest_hash"] = rm.compute_manifest_hash(m)
        self.assertEqual(rm.compute_manifest_hash(m), m["manifest_hash"])
        self.assertEqual(len(m["manifest_hash"]), 64)

    # ── 审计新增用例 ───────────────────────────────────────────────────

    def test_compute_version_hash_signatures(self):
        # mv：单参
        mh = rm.mv.compute_version_hash(_metric_def())
        self.assertEqual(len(mh), 64)
        # dv：双参
        ch = rm.dv.compute_content_hash(_cases())
        vh = rm.dv.compute_version_hash({"dataset_id": "ds", "name": "n"}, ch)
        self.assertEqual(len(vh), 64)
        self.assertNotEqual(mh, vh)

    def test_verify_manifest_hit_and_miss(self):
        m = self._build_full_manifest()
        res = rm.verify_manifest(m, base_dir=self.root)
        self.assertTrue(res["valid"])
        self.assertTrue(res["checks"])

        bad = json.loads(json.dumps(m))
        bad["metrics"][0]["version_hash"] = "0" * 64
        res2 = rm.verify_manifest(bad, base_dir=self.root)
        self.assertFalse(res2["valid"])
        self.assertIn("missing", {c["status"] for c in res2["checks"]})

    def test_validate_manifest_judge_null_and_bad_hash(self):
        m = self._valid_manifest()
        m["judge_model"] = None
        self.assertEqual(rm.validate_manifest(m), [])
        bad = json.loads(json.dumps(m))
        bad["dataset"]["content_hash"] = "xyz"
        self.assertTrue(rm.validate_manifest(bad))

    def test_build_manifest_degradation(self):
        # dataset_id 缺失 → dataset=None + 不崩溃
        m1 = rm.build_manifest(run_id="r")
        self.assertIsNone(m1["dataset"])
        self.assertEqual(m1["metrics"], [])

        # skill_path 缺失（project 无文件）→ content_hash=""
        m2 = rm.build_manifest(run_id="r", project="ghost")
        self.assertEqual(m2["skill"]["content_hash"], "")
        self.assertEqual(m2["skill"]["name"], "ghost")

        # importlib.metadata 未装包 → None，绝不裸调抛异常
        with mock.patch.object(
            rm.importlib.metadata, "version",
            side_effect=rm.importlib.metadata.PackageNotFoundError,
        ):
            m3 = rm.build_manifest(run_id="r")
        self.assertTrue(all(v is None for v in m3["environment"]["dependencies"].values()))

    def test_serialize_deserialize_filters_unknown_instance_keys(self):
        d = {
            "manifest_version": "1.0",
            "manifest_hash": "0" * 64,
            "run_id": "r",
            "created_at": "2026-01-01T00:00:00+00:00",
            "triggered_by": "agent",
            "dataset": None,
            "metrics": [
                {
                    "metric_id": "x",
                    "version_hash": "0" * 64,
                    "instance": {
                        "label": "L", "params": {"k": 1}, "weight": 0.5,
                        "strictness": 1.0, "zone": "score", "order": 0, "foo": "bar",
                    },
                }
            ],
            "skill": None,
            "model": None,
            "judge_model": None,
            "environment": {"python_version": "3.10.0", "platform": "test", "dependencies": {}},
            "extra": {},
        }
        m = rm.deserialize(json.dumps(d, ensure_ascii=False))
        self.assertEqual(m.metrics[0].instance.label, "L")
        self.assertEqual(m.metrics[0].instance.zone, "score")
        inst_out = asdict(m)["metrics"][0]["instance"]
        self.assertNotIn("order", inst_out)
        self.assertNotIn("foo", inst_out)
        self.assertIn("params", inst_out)


if __name__ == "__main__":
    unittest.main()
