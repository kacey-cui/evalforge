"""run_manifest — Report 的 provenance Manifest（自包含、不可变、可验证）。

职责：把一次 Run 的「输入」（dataset / metric / skill / model / judge_model /
environment）固化为一个 manifest.json 快照，并给出可验证的 manifest_hash。

- 只依赖 metric_versioning / dataset_versioning / mini_json_schema（均为纯标准库）。
- 不修改 GUI、不引入数据库、不产生循环依赖。
- ``build_manifest`` 绝不崩溃：任何子项解析失败都降级（warn + 跳过 / 置 None）。

用法：
    from run_manifest import build_manifest, validate_manifest, compute_manifest_hash
"""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import platform
import sys
from copy import deepcopy
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import metric_versioning as mv
import dataset_versioning as dv
from mini_json_schema import validate as _js_validate, UnsupportedKeywordError

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DATA_DIR = REPO_ROOT / "data"
DEFAULT_DATASET_BASE_DIR = DEFAULT_DATA_DIR / "datasets"
DEFAULT_METRIC_BASE_DIR = DEFAULT_DATA_DIR / "metrics"
METRIC_CATEGORIES = ("llm", "non_llm")
DEPENDENCY_PACKAGES = ("deepeval", "openai", "requests")


# ── 数据模型（设计 §10.1）────────────────────────────────────────────────────

@dataclass
class DatasetRef:
    dataset_id: str
    version_hash: str
    content_hash: str
    n_cases: int
    source_path: Optional[str] = None


@dataclass
class MetricInstance:
    label: Optional[str] = None
    params: dict = field(default_factory=dict)
    weight: float = 0.0
    strictness: float = 1.0
    zone: str = "score"


@dataclass
class MetricRef:
    metric_id: str
    version_hash: str
    instance: MetricInstance = field(default_factory=MetricInstance)


@dataclass
class SkillRef:
    name: str
    content_hash: str
    source_path: Optional[str] = None


@dataclass
class ModelRef:
    model_id: str
    base_url: Optional[str] = None
    extra_config: dict = field(default_factory=dict)


@dataclass
class EnvironmentInfo:
    python_version: str
    platform: str
    dependencies: dict = field(default_factory=dict)


@dataclass
class Manifest:
    manifest_version: str = "1.0"
    manifest_hash: str = ""
    run_id: str = ""
    created_at: str = ""
    triggered_by: str = "agent"
    dataset: Optional[DatasetRef] = None
    metrics: list[MetricRef] = field(default_factory=list)
    skill: Optional[SkillRef] = None
    model: Optional[ModelRef] = None
    judge_model: Optional[ModelRef] = None
    environment: Optional[EnvironmentInfo] = None
    extra: dict = field(default_factory=dict)


# ── Schema（设计 §8.1）───────────────────────────────────────────────────────

MANIFEST_SCHEMA = {
    "$schema": "https://json-schema.org/draft-07/schema",
    "type": "object",
    "required": [
        "manifest_version", "run_id", "created_at", "triggered_by",
        "dataset", "metrics", "skill", "model", "environment",
    ],
    "properties": {
        "manifest_version": {"type": "string", "const": "1.0"},
        "manifest_hash": {
            "type": "string",
            "pattern": "^[0-9a-f]{64}$",
        },
        "run_id": {"type": "string", "minLength": 1},
        "created_at": {"type": "string"},
        "triggered_by": {"type": "string", "enum": ["agent", "ui"]},
        "dataset": {
            "type": "object",
            "required": ["dataset_id", "version_hash", "content_hash", "n_cases"],
            "properties": {
                "dataset_id": {"type": "string", "minLength": 1},
                "version_hash": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
                "content_hash": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
                "n_cases": {"type": "integer", "minimum": 0},
                "source_path": {"type": "string"},
            },
        },
        "metrics": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "required": ["metric_id", "version_hash", "instance"],
                "properties": {
                    "metric_id": {"type": "string", "minLength": 1},
                    "version_hash": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
                    "instance": {
                        "type": "object",
                        "properties": {
                            "label": {"type": "string"},
                            "params": {"type": "object"},
                            "weight": {"type": "number"},
                            "strictness": {"type": "number"},
                            "zone": {"type": "string", "enum": ["gate", "score"]},
                        },
                    },
                },
            },
        },
        "skill": {
            "type": "object",
            "required": ["name", "content_hash"],
            "properties": {
                "name": {"type": "string", "minLength": 1},
                "content_hash": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
                "source_path": {"type": "string"},
            },
        },
        "model": {
            "type": "object",
            "required": ["model_id"],
            "properties": {
                "model_id": {"type": "string", "minLength": 1},
                "base_url": {"type": "string"},
                "extra_config": {"type": "object"},
            },
        },
        "judge_model": {
            "oneOf": [
                {"type": "null"},
                {
                    "type": "object",
                    "required": ["model_id"],
                    "properties": {
                        "model_id": {"type": "string", "minLength": 1},
                        "base_url": {"type": "string"},
                    },
                },
            ],
        },
        "environment": {
            "type": "object",
            "required": ["python_version", "platform", "dependencies"],
            "properties": {
                "python_version": {"type": "string"},
                "platform": {"type": "string"},
                "dependencies": {"type": "object"},
            },
        },
        "extra": {"type": "object"},
    },
}

_INSTANCE_KEYS = frozenset({"label", "params", "weight", "strictness", "zone"})


# ── serialize / deserialize（设计 §10.2）─────────────────────────────────────

def serialize(manifest: Manifest) -> str:
    """Manifest dataclass → JSON string。"""
    return json.dumps(asdict(manifest), ensure_ascii=False, indent=2)


def _filter_instance(instance_dict: Optional[dict]) -> dict:
    """只透传 MetricInstance 的已知键，过滤未知键（如 canvas 的 order）。"""
    if not isinstance(instance_dict, dict):
        return {}
    return {k: v for k, v in instance_dict.items() if k in _INSTANCE_KEYS}


def deserialize(json_str: str) -> Manifest:
    """JSON string → Manifest dataclass。instance 只透传已知键。"""
    d = json.loads(json_str)
    return Manifest(
        manifest_version=d.get("manifest_version", "1.0"),
        manifest_hash=d.get("manifest_hash", ""),
        run_id=d.get("run_id", ""),
        created_at=d.get("created_at", ""),
        triggered_by=d.get("triggered_by", "agent"),
        dataset=DatasetRef(**d["dataset"]) if d.get("dataset") else None,
        metrics=[
            MetricRef(
                metric_id=m["metric_id"],
                version_hash=m["version_hash"],
                instance=MetricInstance(**_filter_instance(m.get("instance"))),
            )
            for m in d.get("metrics", [])
        ],
        skill=SkillRef(**d["skill"]) if d.get("skill") else None,
        model=ModelRef(**d["model"]) if d.get("model") else None,
        judge_model=ModelRef(**d["judge_model"]) if d.get("judge_model") else None,
        environment=EnvironmentInfo(**d["environment"]) if d.get("environment") else None,
        extra=d.get("extra", {}),
    )


# ── manifest_hash（设计 §7.1）────────────────────────────────────────────────

def compute_manifest_hash(manifest_dict: dict) -> str:
    """SHA256 of canonicalized manifest，排除 manifest_hash 自身。"""
    d = deepcopy(manifest_dict)
    d.pop("manifest_hash", None)
    canonical = json.dumps(
        d, sort_keys=True, ensure_ascii=False, separators=(",", ":")
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


# ── 校验（设计 §8.2，复用 mini_json_schema）─────────────────────────────────

def validate_manifest(manifest: dict) -> list[str]:
    """返回错误列表。空列表 = 通过。"""
    try:
        return _js_validate(manifest, MANIFEST_SCHEMA)
    except (UnsupportedKeywordError, ValueError) as exc:
        return [str(exc)]


# ── 内部工具 ─────────────────────────────────────────────────────────────────

def _warn(msg: str) -> None:
    print(f"[run_manifest] ⚠️  {msg}", file=sys.stderr)


def _dataset_base(base_dir) -> Path:
    return Path(base_dir) if base_dir else DEFAULT_DATASET_BASE_DIR


def _metric_base(base_dir) -> Path:
    return Path(base_dir) if base_dir else DEFAULT_METRIC_BASE_DIR


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def _find_metric_path(metric_id: str, metric_base_dir) -> Optional[Path]:
    """按 metric_id 找 metric 定义文件：先按文件名 {metric_id}.json，再按 id/metric_id 字段兜底扫描。"""
    if not metric_id:
        return None
    base = _metric_base(metric_base_dir)
    for cat in METRIC_CATEGORIES:
        f = base / cat / f"{metric_id}.json"
        if f.exists():
            return f
    for cat in METRIC_CATEGORIES:
        cat_dir = base / cat
        if not cat_dir.is_dir():
            continue
        for f in cat_dir.glob("*.json"):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
            except Exception:
                continue
            if isinstance(data, dict) and (data.get("id") == metric_id or data.get("metric_id") == metric_id):
                return f
    return None


def _find_metric_path_by_name(name: str, metric_base_dir) -> Optional[Path]:
    """按 name 字段反查 metric 定义文件（无 metricId 时的兜底）。"""
    if not name:
        return None
    base = _metric_base(metric_base_dir)
    for cat in METRIC_CATEGORIES:
        cat_dir = base / cat
        if not cat_dir.is_dir():
            continue
        for f in cat_dir.glob("*.json"):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
            except Exception:
                continue
            if isinstance(data, dict) and data.get("name") == name:
                return f
    return None


def _candidate_names(entry: dict, results: Optional[dict]) -> list:
    names = []
    for key in ("name", "label"):
        v = entry.get(key)
        if v:
            names.append(v)
    cfg = (results or {}).get("config") or {}
    if isinstance(cfg, dict):
        for m in cfg.get("metrics") or []:
            if isinstance(m, dict) and m.get("name"):
                names.append(m["name"])
    return names


# ── build_manifest（设计 §3 / 审计结论）──────────────────────────────────────

def build_manifest(run_id, triggered_by="agent", dataset_id=None, dataset_version=None, project=None,
                   skill_path=None, model_id=None, model_base_url=None,
                   judge_model_id=None, judge_model_base_url=None,
                   config_json_path=None, results=None,
                   dataset_base_dir=None, metric_base_dir=None) -> dict:
    """构建 manifest dict。任何子项解析失败都优雅降级（warn + 置 None / 跳过），绝不崩溃。"""
    created_at = datetime.now(timezone.utc).isoformat()

    # ── dataset ─────────────────────────────────────────────────────────
    dataset = None
    if dataset_id:
        cur = dv.get_current(dataset_id, dataset_base_dir)
        if cur is None:
            _warn(f"dataset_id={dataset_id!r} 未找到，dataset 溯源缺失")
        else:
            cases = cur["cases"]
            content_hash = dv.compute_content_hash(cases)
            def_for_hash = dict(cur)
            def_for_hash["n_cases"] = len(cases)
            version_hash = dataset_version or dv.compute_version_hash(def_for_hash, content_hash)
            n_cases = len(cases)
            source_path = f"data/datasets/{dataset_id}/test_cases.json"
            # 幂等落盘保证 verify 命中（写当前版本；历史版本不覆盖）。
            try:
                dv.create_version(dataset_id, base_dir=dataset_base_dir)
            except Exception as exc:
                _warn(f"dataset {dataset_id} 版本落盘失败（继续）: {exc}")

            if dataset_version:
                hist = dv.read_version(dataset_id, dataset_version, dataset_base_dir)
                if hist is None:
                    _warn(f"dataset_version={dataset_version[:8]}... 回读失败，用当前 def 兜底")
                else:
                    content_hash = hist.get("content_hash", content_hash)
                    n_cases = hist.get("n_cases", n_cases)

            dataset = {
                "dataset_id": dataset_id,
                "version_hash": version_hash,
                "content_hash": content_hash,
                "n_cases": n_cases,
                "source_path": source_path,
            }
    else:
        _warn("未提供 dataset_id，dataset 溯源缺失")

    # ── config（canvas 快照，metrics / model 的权威来源）────────────────
    config = {}
    if config_json_path:
        cfg_path = Path(config_json_path)
        if cfg_path.exists():
            try:
                config = json.loads(cfg_path.read_text(encoding="utf-8"))
            except Exception as exc:
                _warn(f"config.json 解析失败（{exc}），metrics/model 溯源将缺失")
            if not isinstance(config, dict):
                config = {}
        else:
            _warn(f"config_json_path 不存在: {config_json_path}")

    # ── metrics ─────────────────────────────────────────────────────────
    metrics = []
    for field in (config.get("fields") or []):
        if not isinstance(field, dict):
            continue
        for zone, pipeline_key in (("gate", "gatePipeline"), ("score", "scorePipeline")):
            for entry in (field.get(pipeline_key) or []):
                if not isinstance(entry, dict):
                    continue
                metric_id = entry.get("metricId") or entry.get("id")
                path = None
                if metric_id:
                    path = _find_metric_path(metric_id, metric_base_dir)
                else:
                    for name in _candidate_names(entry, results):
                        path = _find_metric_path_by_name(name, metric_base_dir)
                        if path is not None:
                            break
                if path is None:
                    _warn(f"metric {metric_id or entry.get('label') or entry.get('name') or '?'} 定义未找到，跳过")
                    continue
                try:
                    definition = json.loads(path.read_text(encoding="utf-8"))
                except Exception as exc:
                    _warn(f"metric 文件 {path} 读取失败（{exc}），跳过")
                    continue
                if not isinstance(definition, dict):
                    _warn(f"metric 文件 {path} 不是对象，跳过")
                    continue
                if not metric_id:
                    metric_id = definition.get("id") or definition.get("metric_id")
                if not metric_id:
                    _warn(f"metric 定义 {path} 缺少 id/metric_id，跳过")
                    continue
                try:
                    version_hash = mv.compute_version_hash(definition)
                except Exception as exc:
                    _warn(f"metric {metric_id} 计算 version_hash 失败（{exc}），跳过")
                    continue
                try:
                    mv.create_version(str(path))
                except Exception as exc:
                    _warn(f"metric {metric_id} 版本落盘失败（继续）: {exc}")

                instance = MetricInstance(
                    label=entry.get("label"),
                    params=entry.get("params") or {},
                    weight=entry.get("weight", 0.0),
                    strictness=entry.get("strictness", 1.0),
                    zone=zone,
                )
                instance_dict = asdict(instance)
                # label 可选：为 None 时省略，保证 schema（label 为 string）可校验通过。
                if instance_dict.get("label") is None:
                    instance_dict.pop("label", None)
                metrics.append({
                    "metric_id": metric_id,
                    "version_hash": version_hash,
                    "instance": instance_dict,
                })

    # ── skill ───────────────────────────────────────────────────────────
    skill = None
    if skill_path is None:
        skill_path = f"data/projects/{project}/eval_script.py" if project else None
    skill_source_path = str(skill_path) if skill_path else None
    content_hash = ""
    if skill_path:
        p = Path(skill_path)
        if not p.is_absolute():
            p = REPO_ROOT / p
        if p.exists():
            content_hash = _sha256_file(p)
        else:
            _warn(f"skill 文件不存在: {p}，content_hash 置空")
    else:
        _warn("未提供 skill_path 且无 project，skill 溯源缺失")
    skill = {
        "name": project,
        "content_hash": content_hash,
        "source_path": skill_source_path,
    }

    # ── model ───────────────────────────────────────────────────────────
    global_cfg = config.get("global") or {}
    if not isinstance(global_cfg, dict):
        global_cfg = {}
    resolved_model_id = model_id or global_cfg.get("modelId")
    resolved_model_base_url = model_base_url or global_cfg.get("modelBaseUrl")
    model = None
    if resolved_model_id:
        model = {
            "model_id": resolved_model_id,
            "base_url": resolved_model_base_url,
            "extra_config": {},
        }
    else:
        _warn("未提供 model_id 且 config.global.modelId 缺失，model 溯源缺失")

    # ── judge_model ─────────────────────────────────────────────────────
    judge_model = None
    if judge_model_id:
        judge_model = {
            "model_id": judge_model_id,
            "base_url": judge_model_base_url,
        }

    # ── environment ─────────────────────────────────────────────────────
    dependencies = {}
    for pkg in DEPENDENCY_PACKAGES:
        try:
            dependencies[pkg] = importlib.metadata.version(pkg)
        except importlib.metadata.PackageNotFoundError:
            dependencies[pkg] = None
    environment = {
        "python_version": sys.version.split()[0],
        "platform": platform.platform(),
        "dependencies": dependencies,
    }

    return {
        "manifest_version": "1.0",
        "manifest_hash": "",
        "run_id": run_id,
        "created_at": created_at,
        "triggered_by": triggered_by,
        "dataset": dataset,
        "metrics": metrics,
        "skill": skill,
        "model": model,
        "judge_model": judge_model,
        "environment": environment,
        "extra": {},
    }


# ── verify_manifest（设计 §9）────────────────────────────────────────────────

def verify_manifest(manifest: dict, base_dir=None) -> dict:
    """验证 manifest 引用的所有 hash 是否在版本存储中命中。

    ``base_dir`` 为 data 根目录（包含 datasets/ 与 metrics/ 两个子目录）；
    默认 ``REPO_ROOT/data``。不依赖当前文件内容，只检查 .versions/ 与 .content/。
    """
    data_root = Path(base_dir) if base_dir else DEFAULT_DATA_DIR
    dataset_base = data_root / "datasets"
    metric_base = data_root / "metrics"

    checks = []

    ds = manifest.get("dataset")
    if ds:
        rec = dv.read_version(ds["dataset_id"], ds["version_hash"], base_dir=dataset_base)
        checks.append({
            "object": f"dataset {ds['dataset_id']}",
            "status": "ok" if rec else "missing",
            "detail": (
                f"version {ds['version_hash'][:8]} found in .versions/"
                if rec else "version not found in .versions/"
            ),
        })
        content_file = (
            dataset_base / ds["dataset_id"] / ".versions" / ".content"
            / f"{ds['content_hash']}.json"
        )
        checks.append({
            "object": f"dataset content {ds['dataset_id']}",
            "status": "ok" if content_file.exists() else "missing",
            "detail": str(content_file) if content_file.exists() else "content not found in .content/",
        })
    else:
        checks.append({
            "object": "dataset",
            "status": "missing",
            "detail": "manifest 缺少 dataset",
        })

    for m in manifest.get("metrics") or []:
        rec = mv.read_version(m["metric_id"], m["version_hash"], base_dir=metric_base)
        checks.append({
            "object": f"metric {m['metric_id']}",
            "status": "ok" if rec else "missing",
            "detail": (
                f"version {m['version_hash'][:8]} found"
                if rec else f"version {m['version_hash'][:8]} not found"
            ),
        })

    return {
        "valid": all(c["status"] == "ok" for c in checks),
        "checks": checks,
    }
