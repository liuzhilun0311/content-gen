"""Read manual defaults and explicitly initialize or migrate their configuration."""

import argparse
import json
from pathlib import Path
import tempfile

from parameter_catalog import (
    CATALOG, IDENTITIES, SWITCHES, apply_defaults, check_catalog, starting_point_number,
)


FIELDS = frozenset((
    "preset", "type", "density", "style", "palette", "language", "aspect_ratio",
    "references", "reference_usage", "watermark.enabled", "watermark.content",
    "watermark.position", "model", "resolution", "quality", "background",
    "output_format", "output_compression", "moderation", "variants_per_image",
    "generation_batch_size", "show_info", "limit", "output_dir",
    "article_action", "existing_images",
))
ENUMS = {
    "density": {"rich", "balanced", "minimal", "per-section"},
    "model": {"gpt-image-2.5-flare", "gpt-image-2.5-sunburst", "gpt-image-2"},
    "resolution": {"1k", "2k", "4k"},
    "quality": {"auto", "low", "medium", "high", "xhigh", "max"},
    "background": {"design", "auto", "opaque", "transparent"},
    "output_format": {"png", "jpeg", "webp"},
    "moderation": {"auto", "low"},
    "references": {"none", "attachments", "provide"},
    "reference_usage": {"direct", "style", "palette"},
    "limit": {"teaching", "image-count", "budget"},
    "output_dir": {"imgs", "same-directory", "illustrations", "custom"},
    "article_action": {"new-copy", "custom-copy"},
    "existing_images": {"reuse", "new-version", "skip"},
}
BOOLEAN_FIELDS = {"show_info", "watermark.enabled"}
NULLABLE_FIELDS = {"background", "output_format", "output_compression", "moderation"}
INTEGER_FIELDS = {
    "generation_batch_size": (1, 8),
    "variants_per_image": (1, None),
    "output_compression": (0, 100),
}
MARKER = "```json\n"


def default_preferences_path(root=None):
    root = Path(root) if root is not None else Path(__file__).resolve().parent.parent
    canonical = root / "config" / "extend.md"
    legacy = root / "extend.md"
    return canonical if canonical.exists() or not legacy.exists() else legacy


def validate_choices(choices):
    if not isinstance(choices, dict) or set(choices) - FIELDS:
        raise ValueError("Defaults must contain only supported preference fields")
    for key, value in choices.items():
        if value is None and key in NULLABLE_FIELDS:
            continue
        if key in BOOLEAN_FIELDS:
            valid = type(value) is bool
        elif key in INTEGER_FIELDS:
            low, high = INTEGER_FIELDS[key]
            valid = type(value) is int and value >= low and (high is None or value <= high)
        elif key in ENUMS:
            valid = isinstance(value, str) and value in ENUMS[key]
        else:
            valid = isinstance(value, str) and 0 < len(value) <= 300
        if not valid:
            raise ValueError(f"Invalid default value: {key}")


def validate(data):
    if not isinstance(data, dict) or type(data.get("version")) is not int:
        raise ValueError("Unsupported configuration structure or version")
    version = data["version"]
    required = {"version", "defaults"}
    # Old metadata is accepted only for reading legacy files, never acted upon.
    legacy_keys = {"learning", "tracked_defaults", "history", "recorded_tasks"}
    allowed = required | legacy_keys if version in (1, 2) else required
    if version not in (1, 2, 3) or not required <= set(data) or set(data) - allowed:
        raise ValueError("Unsupported configuration structure or version")
    defaults = data["defaults"]
    if version == 1:
        validate_choices(defaults)
        return
    allowed_defaults = FIELDS | SWITCHES | IDENTITIES | {"本次任务起点"}
    if not isinstance(defaults, dict) or set(defaults) - allowed_defaults:
        raise ValueError("Defaults contain unsupported or sensitive fields")
    for key, value in defaults.items():
        if key in IDENTITIES:
            if value != "":
                raise ValueError("Task name and field cannot have cross-task defaults")
        elif key in SWITCHES:
            if type(value) is not bool:
                raise ValueError("Workflow defaults must be true/false: " + key)
        elif key == "本次任务起点":
            starting_point_number(value)
        elif value != "":
            validate_choices({key: value})


def read_document(path):
    path = Path(path)
    if path.is_symlink():
        raise ValueError("Configuration must not be a symbolic link")
    if not path.exists():
        return None, "# Default settings\n\n", "\n", {"version": 1, "defaults": {}}
    original = path.read_bytes()
    text = original.decode("utf-8-sig").replace("\r\n", "\n")
    if text.count(MARKER) != 1:
        raise ValueError("extend.md must contain exactly one JSON block")
    before, block = text.split(MARKER, 1)
    content, separator, after = block.partition("\n```")
    if not separator:
        raise ValueError("Unclosed configuration JSON block")
    try:
        data = json.loads(content)
    except json.JSONDecodeError as error:
        raise ValueError("Invalid configuration JSON; file left unchanged") from error
    validate(data)
    data = {"version": data["version"], "defaults": data["defaults"]}
    if data["version"] == 2:
        # A retired parameter in an old catalogue has no effect on new tasks.
        before = "\n".join(line for line in before.split("\n")
                           if not line.startswith("| 自动学习偏好 |"))
        after = "\n".join(line for line in after.split("\n")
                          if not line.startswith("| 自动学习偏好 |"))
    if data["version"] in (2, 3):
        check_catalog(before + after)
        apply_defaults(before + after, data["defaults"])
    return original, before, after, data


def load_preferences(path):
    return read_document(Path(path))[3]


def migrate_preferences(path):
    """Explicitly initialize current defaults or migrate a legacy document."""
    path = Path(path)
    original, _, _, existing = read_document(path)
    if original is not None and existing["version"] == 3:
        return {"migrated": False, "path": str(path)}
    _, before, after, data = read_document(CATALOG)
    data["defaults"].update(existing["defaults"])
    validate(data)
    apply_defaults(before + after, data["defaults"])
    document = before + MARKER + json.dumps(
        data, ensure_ascii=False, indent=2, allow_nan=False) + "\n```" + after
    if (path.read_bytes() if path.exists() else None) != original:
        raise ValueError("Configuration changed during migration")
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, suffix=".tmp", delete=False) as stream:
        temporary = Path(stream.name)
        stream.write(document.encode("utf-8"))
    try:
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)
    return {"migrated": True, "path": str(path)}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--file", type=Path, default=default_preferences_path())
    parser.add_argument("--migrate", action="store_true",
                        help="Explicitly initialize or migrate manual defaults to version 3")
    args = parser.parse_args()
    try:
        output = migrate_preferences(args.file) if args.migrate else load_preferences(args.file)
        print(json.dumps(output, ensure_ascii=False, indent=2))
    except (ValueError, OSError) as error:
        parser.exit(1, f"{error}\n")
