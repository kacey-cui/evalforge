"""Demo audit regressions for frontend/backend JSON contracts."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))


def test_git_bridge_lists_filesystem_projects():
    from git_bridge import app

    client = app.test_client()
    response = client.get("/api/projects")

    assert response.status_code == 200
    projects = {item["id"] for item in response.get_json()}
    assert {"rag_research", "customer_support", "tool_agent"}.issubset(projects)


def test_git_bridge_exposes_global_metric_library_including_recall_at_k():
    from git_bridge import app

    client = app.test_client()
    response = client.get("/api/metrics")

    assert response.status_code == 200
    metrics = {item["id"] for item in response.get_json()}
    assert "recall_at_k" in metrics


def test_git_bridge_exposes_project_dataset_summary_and_cases():
    from git_bridge import app

    client = app.test_client()
    response = client.get("/api/projects/rag_research/dataset")

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["dataset"]["dataset_id"] == "rag_research_v2"
    assert payload["dataset"]["n_cases"] == 80
    assert len(payload["cases"]) == 80
    assert {"case_id", "input", "expected_output"}.issubset(payload["cases"][0])


def test_eval_diff_explains_dataset_family_version_case_changes():
    from eval_diff import eval_diff

    result = eval_diff("rag_eval_004", "rag_eval_005")

    assert result["ok"] is True
    dataset = result["data"]["dataset"]
    assert dataset["status"] == "modified"
    assert isinstance(dataset["detail"], dict)
    assert dataset["detail"]["summary"]["modified"] > 0
    assert dataset["detail"]["modified_cases"][0]["changes"]


def test_frontend_contains_demo_contract_fixes():
    html = Path("index.html").read_text(encoding="utf-8")

    assert "completed: '✅'" in html
    assert "loadProjectsFromFileSystem" in html
    assert "normalizeCanvasPayload" in html
    assert "describeMetricDiffField" in html
    assert "renderDatasetSummary" in html
    assert "xMode = allX.every" in html
