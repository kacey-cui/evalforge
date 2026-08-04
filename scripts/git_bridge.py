"""
git_bridge.py — EvalPlatform Git REST 桥接服务
端口: 8081
"""
import json
import os
import re
import subprocess
from pathlib import Path

from flask import Flask, jsonify, request

app = Flask(__name__)
REPO_ROOT = Path(__file__).parent.parent  # scripts/ 的上级 = repo 根目录


# ─── 工具函数 ────────────────────────────────────────────────────────────────

def _git(*args):
    """运行 git 命令，返回 (stdout_str, returncode)"""
    result = subprocess.run(
        ["git"] + list(args),
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )
    return result.stdout.strip(), result.returncode


def _parse_commit_body(body: str) -> dict:
    """
    解析 git commit body，格式如下：
        project: diagnosis
        triggered_by: agent
        metrics: [accuracy, faithfulness]
        dataset: test.csv@sha256:abc123
        overall_score: 0.87
        fields: {"diagnosis": 0.91}
    """
    meta = {}
    for line in body.splitlines():
        if ":" not in line:
            continue
        key, _, val = line.partition(":")
        key = key.strip()
        val = val.strip()
        if key == "overall_score":
            try:
                meta[key] = float(val)
            except ValueError:
                meta[key] = None
        elif key == "fields":
            try:
                meta[key] = json.loads(val)
            except Exception:
                meta[key] = {}
        elif key == "metrics":
            # "[accuracy, faithfulness]" → list
            val = val.strip("[]")
            meta[key] = [m.strip() for m in val.split(",") if m.strip()]
        elif key == "triggered_by":
            meta[key] = val  # "ui" or "agent"
        elif key == "dataset":
            meta[key] = val
        elif key == "project":
            meta["project"] = val
    return meta


def _run_ids_from_log(project_filter: str = "") -> list:
    """
    遍历 git log，找出所有 run: 开头的 commit。
    返回列表，每项: {sha, run_id, project, status, timestamp, ...meta}
    """
    log, code = _git(
        "log",
        "--format=%H|%s|%ci",  # sha|subject|commit_date
        "--",
        "data/runs/",
    )
    if code != 0 or not log:
        return []

    runs = []
    for line in log.splitlines():
        parts = line.split("|", 2)
        if len(parts) < 3:
            continue
        sha, subject, timestamp = parts

        # subject 格式: "run: {project}/{run_id} [{status}]"
        m = re.match(r"run:\s+(\S+)/(\S+)\s+\[(\w+)\]", subject)
        if not m:
            continue
        project, run_id, status = m.groups()

        if project_filter and project != project_filter:
            continue

        # 跳过软删除的 run
        deleted_tag = f"deleted/{run_id}"
        tags_out, _ = _git("tag", "-l", deleted_tag)
        if tags_out.strip():
            continue

        body, _ = _git("log", "-1", "--format=%b", sha)
        meta = _parse_commit_body(body)

        runs.append(
            {
                "sha": sha,
                "run_id": run_id,
                "project": project,
                "status": status,
                "timestamp": timestamp,
                **meta,
            }
        )
    return runs


def _cors(response):
    """允许所有跨域请求（本地工具，安全无虞）"""
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, DELETE, OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type"
    return response


# ─── 端点 ────────────────────────────────────────────────────────────────────

@app.after_request
def after_request(response):
    return _cors(response)


@app.route("/api/runs", methods=["GET", "OPTIONS"])
def list_runs():
    """GET /api/runs?project=<str> — 返回 Run 列表"""
    if request.method == "OPTIONS":
        return jsonify({}), 200
    project = request.args.get("project", "")
    runs = _run_ids_from_log(project)
    return jsonify(runs)


@app.route("/api/runs/<run_id>", methods=["GET", "OPTIONS"])
def get_run(run_id):
    """GET /api/runs/<run_id> — 返回单次 Run 的详细信息"""
    if request.method == "OPTIONS":
        return jsonify({}), 200

    run_dir = REPO_ROOT / "data" / "runs" / run_id
    if not run_dir.exists():
        return jsonify({"error": f"run {run_id} not found"}), 404

    result = {"run_id": run_id}
    for fname in ["meta.json", "config.json", "dataset_ref.json", "results.json"]:
        fpath = run_dir / fname
        if fpath.exists():
            try:
                result[fname.replace(".json", "")] = json.loads(fpath.read_text("utf-8"))
            except Exception:
                result[fname.replace(".json", "")] = None
    return jsonify(result)


@app.route("/api/runs/<run_id_a>/diff/<run_id_b>", methods=["GET", "OPTIONS"])
def diff_runs(run_id_a, run_id_b):
    """GET /api/runs/<a>/diff/<b> — 对比两次 Run 的 config 和 results"""
    if request.method == "OPTIONS":
        return jsonify({}), 200

    def _load(run_id, fname):
        p = REPO_ROOT / "data" / "runs" / run_id / fname
        if not p.exists():
            return None
        try:
            return json.loads(p.read_text("utf-8"))
        except Exception:
            return None

    config_a = _load(run_id_a, "config.json") or {}
    config_b = _load(run_id_b, "config.json") or {}
    results_a = _load(run_id_a, "results.json") or {}
    results_b = _load(run_id_b, "results.json") or {}
    dataset_a = _load(run_id_a, "dataset_ref.json") or {}
    dataset_b = _load(run_id_b, "dataset_ref.json") or {}

    # 简单 diff：找出两个 dict 中值不同的 key
    def _simple_diff(d1, d2, prefix=""):
        changes = []
        all_keys = set(list(d1.keys()) + list(d2.keys()))
        for k in sorted(all_keys):
            full_key = f"{prefix}.{k}" if prefix else k
            v1 = d1.get(k)
            v2 = d2.get(k)
            if isinstance(v1, dict) and isinstance(v2, dict):
                changes.extend(_simple_diff(v1, v2, full_key))
            elif v1 != v2:
                changes.append({"key": full_key, "before": v1, "after": v2})
        return changes

    return jsonify(
        {
            "run_a": run_id_a,
            "run_b": run_id_b,
            "config_diff": _simple_diff(config_a, config_b),
            "dataset_same": (dataset_a.get("sha256") == dataset_b.get("sha256")),
            "dataset_a": dataset_a,
            "dataset_b": dataset_b,
            "score_a": results_a.get("overall_score"),
            "score_b": results_b.get("overall_score"),
            "fields_a": results_a.get("fields", {}),
            "fields_b": results_b.get("fields", {}),
        }
    )


@app.route("/api/groups", methods=["GET", "OPTIONS"])
def list_groups():
    """GET /api/groups — 列出所有对比组（git tag compare/*）"""
    if request.method == "OPTIONS":
        return jsonify({}), 200

    tags_out, _ = _git("tag", "-l", "compare/*")
    groups = {}
    for tag in tags_out.splitlines():
        if not tag.strip():
            continue
        # tag 格式: compare/{group_name}  或  compare/{group_name}/{run_id}
        parts = tag[len("compare/"):].split("/", 1)
        group_name = parts[0]
        if group_name not in groups:
            groups[group_name] = []
        if len(parts) == 2:
            groups[group_name].append(parts[1])

    return jsonify(
        [{"name": name, "runs": runs} for name, runs in groups.items()]
    )


@app.route("/api/groups", methods=["POST"])
def create_group():
    """POST /api/groups — 创建对比组，body: {name: str, run_ids: [str]}"""
    body = request.get_json(force=True, silent=True) or {}
    name = body.get("name", "").strip()
    run_ids = body.get("run_ids", [])

    if not name:
        return jsonify({"error": "name is required"}), 400
    if not run_ids:
        return jsonify({"error": "run_ids is required"}), 400

    # 创建 group-level tag
    group_tag = f"compare/{name}"
    _git("tag", group_tag)

    # 为每个 run 创建子 tag
    created = []
    for run_id in run_ids:
        tag = f"compare/{name}/{run_id}"
        _, code = _git("tag", tag)
        if code == 0:
            created.append(tag)

    return jsonify({"ok": True, "tag": group_tag, "run_tags": created})


@app.route("/api/runs/<run_id>", methods=["DELETE", "OPTIONS"])
def delete_run(run_id):
    """DELETE /api/runs/<run_id> — 软删除（打 deleted/{run_id} tag）"""
    if request.method == "OPTIONS":
        return jsonify({}), 200

    tag = f"deleted/{run_id}"
    _, code = _git("tag", tag)
    if code != 0:
        return jsonify({"error": "failed to create deleted tag"}), 500
    return jsonify({"ok": True, "tag": tag})


# ─── 项目级端点 ──────────────────────────────────────────────────────────────

@app.route("/api/projects/<project>/metrics", methods=["GET", "OPTIONS"])
def project_metrics(project):
    """GET /api/projects/<project>/metrics — 列出项目下所有 metric JSON"""
    if request.method == "OPTIONS":
        return jsonify({}), 200

    metrics = []
    for subdir in ["non_llm", "llm", ""]:
        search_dir = REPO_ROOT / "data" / "projects" / project / "metrics"
        if subdir:
            search_dir = search_dir / subdir
        if not search_dir.exists():
            continue
        for f in sorted(search_dir.glob("*.json")):
            try:
                data = json.loads(f.read_text("utf-8"))
                if "id" in data:
                    metrics.append(data)
            except Exception:
                pass

    return jsonify(metrics)


@app.route("/api/projects/<project>/canvas", methods=["GET", "OPTIONS"])
def project_canvas_get(project):
    """GET /api/projects/<project>/canvas — 读取 canvas.json"""
    if request.method == "OPTIONS":
        return jsonify({}), 200

    canvas_path = REPO_ROOT / "data" / "projects" / project / "canvas.json"
    if not canvas_path.exists():
        return jsonify({"error": "canvas.json not found"}), 404

    try:
        return jsonify(json.loads(canvas_path.read_text("utf-8")))
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/projects/<project>/canvas", methods=["POST"])
def project_canvas_post(project):
    """POST /api/projects/<project>/canvas — 写入 canvas.json"""
    canvas_path = REPO_ROOT / "data" / "projects" / project / "canvas.json"
    canvas_path.parent.mkdir(parents=True, exist_ok=True)

    body = request.get_json(force=True, silent=True)
    if not body:
        return jsonify({"error": "empty body"}), 400

    canvas_path.write_text(json.dumps(body, ensure_ascii=False, indent=4), "utf-8")
    return jsonify({"ok": True, "path": str(canvas_path.relative_to(REPO_ROOT))})


@app.route("/api/projects/<project>/report", methods=["GET", "OPTIONS"])
def project_latest_report(project):
    """GET /api/projects/<project>/report — 返回该项目最近一次 Run 的 results.json"""
    if request.method == "OPTIONS":
        return jsonify({}), 200

    runs = _run_ids_from_log(project_filter=project)
    if not runs:
        return jsonify({"error": "no runs found"}), 404

    latest_run_id = runs[0]["run_id"]
    results_path = REPO_ROOT / "data" / "runs" / latest_run_id / "results.json"
    if not results_path.exists():
        return jsonify({"error": f"results.json not found for {latest_run_id}"}), 404

    try:
        return jsonify(json.loads(results_path.read_text("utf-8")))
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ─── 启动 ────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("EvalPlatform git_bridge running on http://localhost:8081")
    app.run(host="127.0.0.1", port=8081, debug=False)