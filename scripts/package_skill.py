"""Build a shareable skill archive from an explicit public-file allowlist."""

import argparse
import hashlib
import json
from pathlib import Path
import zipfile


RUNTIME_FILES = (
    "package_skill.py",
    "package_skill_test.py", "preferences.py", "preferences_test.py",
    "task_paths.py", "task_state.py", "workflow_switches.py",
    "image_plan_boundary_test.py",
    "validate_parameters.py", "workflow_test.py", "export-publishing-documents.py",
    "export_publishing_test.py", "validate_image_plan.py",
    "reliability_regression_test.py", "verify_task.py", "verify_task_test.py",
    "export-content-documents.py", "render-content-pdf.mjs", "export_content_test.py",
    "document_layout.py", "document_layout_test.py",
    "markdown_contract.py", "review_material.py", "runtime_preflight.py",
    "effective_image_config.py", "optimization_test.py", "single_longform_test.py",
    "task_parameters.py", "task_parameters_test.py",
    "local_config.py", "local_config_test.py",
    "parameter_catalog.py",
)


def private_values(root):
    config = root / "config" / ".env"
    if not config.exists():
        return []
    values = []
    for raw in config.read_text(encoding="utf-8-sig").splitlines():
        key, separator, value = raw.strip().partition("=")
        if not separator or key.startswith("#"):
            continue
        if any(part in key.upper() for part in ("KEY", "SECRET", "TOKEN", "PASSWORD")):
            value = value.strip().strip("\"'")
            if value:
                values.append(value.encode("utf-8"))
    return values


def public_payload(root):
    root = root.resolve()
    selected = [root / "SKILL.md", root / ".gitignore"]
    for template in ("config/.env.example", "config/extend.example.md"):
        if (root / template).is_file():
            selected.append(root / template)
    if (root / "version.json").exists():
        selected.append(root / "version.json")
    selected += sorted((root / "references").rglob("*.md"))
    selected += sorted((root / "agents").glob("*.yaml"))
    selected += sorted((root / "assets").glob("*.html"))
    selected += sorted((root / "show-me").glob("*.html"))
    selected += sorted((root / "show-me").glob("*.png"))
    selected += [root / "scripts" / name for name in RUNTIME_FILES if (root / "scripts" / name).exists()]
    secrets = private_values(root)
    payload = []
    for source in selected:
        relative = source.relative_to(root)
        if source.is_symlink() or any(parent.is_symlink() for parent in source.parents if parent != root):
            raise ValueError("Public package cannot contain symbolic links")
        if not source.resolve().is_relative_to(root):
            raise ValueError("Public file escaped the skill directory")
        data = source.read_bytes()
        if any(secret in data for secret in secrets):
            raise ValueError(f"Private configuration value found in public file: {relative}")
        payload.append((f"{root.name}/{relative.as_posix()}", data))
    return payload


def release_manifest(root, payload):
    version_file = Path(root) / "version.json"
    version = json.loads(version_file.read_text(encoding="utf-8")) if version_file.exists() else {}
    return {"version": version.get("version", "unversioned"),
            "files": {name: hashlib.sha256(data).hexdigest() for name, data in payload},
            "private_files_excluded": True}


def package_skill(root, output):
    root = Path(root).resolve()
    output = Path(output).resolve()
    if output.is_relative_to(root):
        raise ValueError("Save shared archives outside the skill directory")
    payload = public_payload(root)
    manifest = release_manifest(root, payload)
    payload.append((root.name + "/release-manifest.json",
                    json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8")))
    output.parent.mkdir(parents=True, exist_ok=True)
    created = False
    try:
        with zipfile.ZipFile(output, "x", compression=zipfile.ZIP_DEFLATED) as archive:
            created = True
            for name, data in payload:
                archive.writestr(name, data)
        with zipfile.ZipFile(output) as archive:
            if archive.testzip() is not None:
                raise ValueError("Archive verification failed")
            if [(name, archive.read(name)) for name in archive.namelist()] != payload:
                raise ValueError("Archive content does not match public files")
    except Exception:
        if created:
            output.unlink(missing_ok=True)
        raise
    return output, len(payload)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    location, count = package_skill(Path(__file__).resolve().parent.parent, args.out)
    print(f"Public skill package verified: {location} ({count} files; private configuration excluded)")
