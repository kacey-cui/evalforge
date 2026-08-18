"""DatasetStore — Agent-native Dataset API.

Wraps dataset_versioning with structured error handling and a unified class interface.
Agent should not need to write files or open GUI to manage datasets.
"""

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_BASE_DIR = REPO_ROOT / "data" / "datasets"

# Add parent dir to path for imports
sys.path.insert(0, str(Path(__file__).resolve().parent))
import dataset_versioning as dv
from mini_json_schema import validate as js_validate


def _ok(data):
    return {"ok": True, "data": data}


def _err(code, message, details=None):
    d = {"ok": False, "error": {"code": code, "message": message}}
    if details:
        d["error"]["details"] = details
    return d


DATASET_SCHEMA = {
    "type": "object",
    "required": ["dataset_id", "name"],
    "properties": {
        "dataset_id": {"type": "string", "minLength": 1, "maxLength": 128},
        "name": {"type": "string", "minLength": 1, "maxLength": 256},
        "description": {"type": "string", "maxLength": 1024},
        "dataset_id_alias": {"type": "string"},
    },
}


class DatasetStore:
    """Agent-native wrapper around dataset_versioning with structured error handling.

    Every public method returns ``{"ok": True, "data": ...}`` on success or
    ``{"ok": False, "error": {"code": ..., "message": ...}}`` on failure.
    """

    def __init__(self, base_dir=None):
        self.base_dir = Path(base_dir) if base_dir else DEFAULT_BASE_DIR

    # ── Create ────────────────────────────────────────────────────────────────

    def create(self, dataset_id, name, cases, description="", schema=None):
        """Create a new dataset. *cases* is a list of dicts.

        Returns:
            ``{"ok": True, "data": {dataset_id, version_hash, content_hash,
            n_cases, is_new}}`` on success, or an error dict.
        """
        # 0. Validate dataset_id, name, n_cases with DATASET_SCHEMA
        ds_meta = {"dataset_id": dataset_id, "name": name}
        if description:
            ds_meta["description"] = description
        ds_errors = js_validate(ds_meta, DATASET_SCHEMA)
        if ds_errors:
            return _err("VALIDATION_ERROR", "dataset 元数据验证失败", ds_errors)

        # 1. Check duplicate
        ds_dir = self.base_dir / dataset_id
        if ds_dir.exists():
            return _err("DUPLICATE_ID", f"Dataset '{dataset_id}' already exists")

        # 2. Validate cases
        if not isinstance(cases, list):
            return _err("INVALID_CASES", "cases must be a list")
        if not cases:
            return _err("INVALID_CASES", "cases must not be empty")

        # 3. Validate each case is a dict
        for i, case in enumerate(cases):
            if not isinstance(case, dict):
                return _err("INVALID_CASES", f"Case at index {i} is not a dict")

        # 4. Assign case_id where missing (0-based index for agent convenience;
        #    dv._assign_case_ids will keep these as-is since they are already set).
        for i, case in enumerate(cases):
            if "case_id" not in case:
                case["case_id"] = i

        # 5. Infer/validate schema
        if schema is None:
            schema = dv.infer_schema(cases)
        else:
            errors = dv.validate_dataset(cases, schema)
            if errors:
                return _err("VALIDATION_ERROR", "Schema validation failed", errors)

        # 6. Create dataset via dv (raises ValueError on failure)
        try:
            result = dv.create_dataset(
                dataset_id=dataset_id,
                name=name,
                cases=cases,
                description=description,
                schema=schema,
                base_dir=self.base_dir,
            )
        except ValueError as exc:
            return _err("VALIDATION_ERROR", str(exc))
        except Exception as exc:
            return _err("INTERNAL_ERROR", str(exc))

        return _ok({
            "dataset_id": dataset_id,
            "version_hash": result.get("version_hash", ""),
            "content_hash": result.get("content_hash", ""),
            "n_cases": result.get("n_cases", len(cases)),
            "is_new": True,
        })

    # ── List ──────────────────────────────────────────────────────────────────

    def list_datasets(self):
        """List all datasets.

        Returns:
            ``{"ok": True, "data": [{dataset_id, name, n_cases, version_hash}, ...]}``.
        """
        if not self.base_dir.exists():
            return _ok([])

        items = []
        for ds_dir in sorted(self.base_dir.iterdir()):
            if not ds_dir.is_dir():
                continue
            ds_file = ds_dir / "dataset.json"
            if not ds_file.exists():
                continue
            try:
                ds = json.loads(ds_file.read_text("utf-8"))
                items.append({
                    "dataset_id": ds.get("dataset_id", ds_dir.name),
                    "name": ds.get("name", ""),
                    "n_cases": ds.get("n_cases", 0),
                    "version_hash": ds.get("version_hash", ""),
                })
            except Exception:
                continue
        return _ok(items)

    # ── Get current ───────────────────────────────────────────────────────────

    def get(self, dataset_id):
        """Get current dataset definition and cases.

        Returns:
            ``{"ok": True, "data": {"dataset": {...}, "cases": [...]}}``.
        """
        try:
            result = dv.get_current(dataset_id, base_dir=self.base_dir)
        except Exception as exc:
            return _err("NOT_FOUND", str(exc))

        if result is None:
            return _err("NOT_FOUND", f"Dataset '{dataset_id}' not found")

        # get_current returns a dict with "cases" key merged in
        cases = result.pop("cases", [])
        return _ok({"dataset": result, "cases": cases})

    # ── Create version ────────────────────────────────────────────────────────

    def create_version(self, dataset_id, new_cases):
        """Create a new version from *new_cases* (list of dicts).

        Idempotent: if the content hash matches the current version, returns
        ``is_new=False`` without writing anything.

        Returns:
            ``{"ok": True, "data": {dataset_id, version_hash, content_hash,
            n_cases, is_new}}`` on success, or an error dict.
        """
        # 1. Check dataset exists
        ds_file = self.base_dir / dataset_id / "dataset.json"
        if not ds_file.exists():
            return _err("NOT_FOUND", f"Dataset '{dataset_id}' not found")

        # 2. Load current dataset definition
        try:
            ds_def = json.loads(ds_file.read_text("utf-8"))
        except Exception as exc:
            return _err("INTERNAL_ERROR", f"Failed to read dataset.json: {exc}")

        # 3. Validate new_cases
        if not isinstance(new_cases, list):
            return _err("INVALID_CASES", "new_cases must be a list")
        if not new_cases:
            return _err("INVALID_CASES", "new_cases must not be empty")

        # 4. Validate each case is a dict
        for i, case in enumerate(new_cases):
            if not isinstance(case, dict):
                return _err("INVALID_CASES", f"Case at index {i} is not a dict")

        # 5. Assign case_id where missing (0-based index)
        for i, case in enumerate(new_cases):
            if "case_id" not in case:
                case["case_id"] = i

        # 6. Get schema from current dataset (or infer)
        schema = ds_def.get("schema") or dv.infer_schema(new_cases)

        # 7. Validate against schema
        errors = dv.validate_dataset(new_cases, schema)
        if errors:
            return _err("VALIDATION_ERROR", "Schema validation failed", errors)

        # 8. Compute new content hash
        new_content_hash = dv.compute_content_hash(new_cases)

        # 9. Check if content changed (idempotent)
        current_content_hash = ds_def.get("content_hash", "")
        if new_content_hash == current_content_hash:
            return _ok({
                "dataset_id": dataset_id,
                "version_hash": ds_def.get("version_hash", ""),
                "content_hash": new_content_hash,
                "n_cases": len(new_cases),
                "is_new": False,
            })

        # 10. Write new test_cases.json (sorted for consistency with dv)
        cases_file = self.base_dir / dataset_id / "test_cases.json"
        cases_sorted = sorted(new_cases, key=lambda c: c["case_id"])
        try:
            cases_file.write_text(
                json.dumps(cases_sorted, ensure_ascii=False, indent=2), "utf-8"
            )
        except Exception as exc:
            return _err("INTERNAL_ERROR", f"Failed to write test_cases.json: {exc}")

        # 11. Update dataset.json
        ds_def["n_cases"] = len(new_cases)
        ds_def["content_hash"] = new_content_hash
        try:
            ds_def["version_hash"] = dv.compute_version_hash(ds_def, new_content_hash)
        except ValueError as exc:
            return _err("INTERNAL_ERROR", f"Failed to compute version hash: {exc}")
        try:
            ds_file.write_text(
                json.dumps(ds_def, ensure_ascii=False, indent=2), "utf-8"
            )
        except Exception as exc:
            return _err("INTERNAL_ERROR", f"Failed to write dataset.json: {exc}")

        # 12. Create version snapshot
        try:
            result = dv.create_version(dataset_id, base_dir=self.base_dir)
        except ValueError as exc:
            return _err("INTERNAL_ERROR", str(exc))
        except Exception as exc:
            return _err("INTERNAL_ERROR", str(exc))

        return _ok({
            "dataset_id": dataset_id,
            "version_hash": result.get("version_hash", ds_def["version_hash"]),
            "content_hash": new_content_hash,
            "n_cases": len(new_cases),
            "is_new": result.get("is_new", True),
        })

    # ── Get version ───────────────────────────────────────────────────────────

    def get_version(self, dataset_id, version_hash):
        """Get a specific version.

        Returns:
            ``{"ok": True, "data": {...}}`` or error.
        """
        try:
            data = dv.read_version(dataset_id, version_hash, base_dir=self.base_dir)
        except Exception as exc:
            return _err("NOT_FOUND", str(exc))

        if data is None:
            return _err("NOT_FOUND", f"Version '{version_hash}' not found")
        return _ok(data)

    # ── List versions ─────────────────────────────────────────────────────────

    def list_versions(self, dataset_id):
        """List all versions of a dataset.

        Returns:
            ``{"ok": True, "data": [{dataset_id, version_hash, created_at, name}, ...]}``.
        """
        try:
            items = dv.list_versions(dataset_id, base_dir=self.base_dir)
        except Exception as exc:
            return _err("NOT_FOUND", str(exc))
        return _ok(items)

    # ── Diff versions ─────────────────────────────────────────────────────────

    def diff_versions(self, dataset_id, hash_a, hash_b, fields=None):
        """Diff two versions.

        Returns:
            ``{"ok": True, "data": {dataset_id, version_a, version_b, summary,
            schema_changes, added_cases, removed_cases, modified_cases}}``
            or error.
        """
        try:
            result = dv.diff_versions(
                dataset_id, hash_a, hash_b, fields=fields, base_dir=self.base_dir
            )
        except ValueError as exc:
            return _err("NOT_FOUND", str(exc))
        except Exception as exc:
            return _err("INTERNAL_ERROR", str(exc))
        return _ok(result)


# ── CLI ───────────────────────────────────────────────────────────────────────

def main():
    import argparse

    parser = argparse.ArgumentParser(
        prog="dataset_store", description="DatasetStore CLI"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_create = sub.add_parser("create", help="Create a new dataset")
    p_create.add_argument("--dataset-id", required=True)
    p_create.add_argument("--name", required=True)
    p_create.add_argument("--source", required=True, help="JSON file with cases list")
    p_create.add_argument("--description", default="")
    p_create.add_argument("--schema", default=None, help="Optional schema JSON file")
    p_create.add_argument("--base-dir", default=None)

    p_list = sub.add_parser("list", help="List all datasets")
    p_list.add_argument("--base-dir", default=None)

    p_get = sub.add_parser("get", help="Get current dataset with cases")
    p_get.add_argument("--dataset-id", required=True)
    p_get.add_argument("--base-dir", default=None)

    p_cv = sub.add_parser("create-version", help="Create a new version")
    p_cv.add_argument("--dataset-id", required=True)
    p_cv.add_argument("--source", required=True, help="JSON file with new cases list")
    p_cv.add_argument("--base-dir", default=None)

    p_gv = sub.add_parser("get-version", help="Get a specific version")
    p_gv.add_argument("--dataset-id", required=True)
    p_gv.add_argument("--version-hash", required=True)
    p_gv.add_argument("--base-dir", default=None)

    p_lv = sub.add_parser("list-versions", help="List versions of a dataset")
    p_lv.add_argument("--dataset-id", required=True)
    p_lv.add_argument("--base-dir", default=None)

    p_diff = sub.add_parser("diff", help="Diff two versions")
    p_diff.add_argument("--dataset-id", required=True)
    p_diff.add_argument("--version-a", required=True)
    p_diff.add_argument("--version-b", required=True)
    p_diff.add_argument("--fields", default=None, help="Comma-separated field list")
    p_diff.add_argument("--base-dir", default=None)

    args = parser.parse_args()
    store = DatasetStore(base_dir=args.base_dir)

    if args.command == "create":
        cases = json.loads(Path(args.source).read_text("utf-8"))
        schema = None
        if args.schema:
            schema = json.loads(Path(args.schema).read_text("utf-8"))
        result = store.create(
            args.dataset_id, args.name, cases,
            description=args.description, schema=schema,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif args.command == "list":
        result = store.list_datasets()
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif args.command == "get":
        result = store.get(args.dataset_id)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif args.command == "create-version":
        new_cases = json.loads(Path(args.source).read_text("utf-8"))
        result = store.create_version(args.dataset_id, new_cases)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif args.command == "get-version":
        result = store.get_version(args.dataset_id, args.version_hash)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif args.command == "list-versions":
        result = store.list_versions(args.dataset_id)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif args.command == "diff":
        fields = args.fields.split(",") if args.fields else None
        result = store.diff_versions(
            args.dataset_id, args.version_a, args.version_b, fields=fields
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()