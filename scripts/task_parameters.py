"""Prepare a fillable task table and retain a validated filled document."""

import argparse
import json
from pathlib import Path
import re

from task_paths import create_task
from task_state import file_evidence, load, update
from validate_parameters import TEMPLATE, choices, validate
from workflow_switches import table_rows
from parameter_catalog import CATALOG, REFERENCES, apply_defaults, key_for
from preferences import default_preferences_path, read_document


def available_fields():
    fields = {}
    for directory in sorted((REFERENCES / "fields").glob("field_*")):
        if not re.fullmatch(r"field_[a-z0-9]+(?:-[a-z0-9]+)*", directory.name):
            continue
        files = [directory / name for name in
                 ("expert-teaching.md", "illustration-guidance.md", "writing-examples.md")]
        if not all(path.is_file() for path in files):
            continue
        text = files[0].read_text(encoding="utf-8-sig")
        metadata = re.match(r"^---\s*\n(.*?)\n---", text, re.S)
        if not metadata:
            continue
        def value(key):
            match = re.search(r"^" + key + r":\s*([^\r\n]+)", metadata[1], re.M)
            return match[1].strip().strip("\"'") if match else None
        if value("field_id") == directory.name and value("status") == "ready":
            fields[directory.name] = value("display_name") or directory.name
    return fields


def render(task_name=None, field=None, config_path=None):
    path = Path(config_path) if config_path is not None else default_preferences_path()
    baseline = read_document(CATALOG)
    document = read_document(path) if path.exists() else baseline
    data = document[3]
    defaults = {**baseline[3]["defaults"], **data["defaults"]} if data["version"] == 1 else data["defaults"]
    source = (document[1] + document[2]) if data["version"] in (2, 3) else (baseline[1] + baseline[2])
    table, default_supplements = apply_defaults(source, defaults)
    text = "# 技能输入参数设置\n\n技能：`content-gen`\n\n版本：1.2.0\n\n任务名称：\n\n专业领域：\n\n" + table
    rows = table_rows(text)
    field_row = rows["专业领域"]
    fields = available_fields()
    existing, numbers = choices(field_row), {}
    for n, label in existing.items():
        token = re.search(r"`([^`]+)`", label)
        if token and token[1] in fields:
            numbers[token[1]] = n
    next_number = max(existing, default=0) + 1
    for identifier in fields:
        if identifier not in numbers:
            numbers[identifier] = next_number
            next_number += 1
    options = []
    for identifier, number in sorted(numbers.items(), key=lambda item: item[1]):
        label = existing.get(number, f"`{identifier}`（{fields[identifier]}）")
        options.append(str(number) + ". " + label)
    if field is not None and field not in numbers:
        raise ValueError("Selected field must be an available field ID")
    field_row[5] = " " + field_row[5].split("<br>", 1)[0] + (
        "<br>" + "<br>".join(options) if options else "") + " "
    if task_name:
        from task_paths import validate_task_name
        validate_task_name(task_name)
        rows["任务名称"][4] = " " + task_name + " "
    if field:
        field_row[4] = " " + str(numbers[field]) + " "
    lines = []
    for line in text.splitlines():
        if line.startswith("|"):
            name = line.split("|")[1].strip()
            line = "|".join(rows[name])
        elif line.startswith("任务名称：") and task_name:
            line = "任务名称：" + task_name
        elif line.startswith("专业领域：") and field:
            line = "专业领域：" + fields[field]
        lines.append(line)
    result = "\n".join(lines) + "\n"
    if default_supplements:
        snapshot = {key: {"default": next(row[3].strip() for name, row in rows.items()
                                          if key_for(name) == key), "value": value}
                    for key, value in default_supplements.items()}
        result += "\n<!-- content-gen-default-supplements\n" + json.dumps(
            snapshot, ensure_ascii=False).replace("--", "\\u002d\\u002d") + "\n-->\n"
    return result


def retain(filled, output_root=None, timezone_name="Asia/Shanghai", state_path=None,
           inputs=None, supplements=None, scope="full"):
    filled = Path(filled).resolve(strict=True)
    original = filled.read_bytes()
    result = validate(original.decode("utf-8-sig"), supplements, scope)
    if not result["valid"]:
        raise ValueError("Parameters invalid: " + "; ".join(result["errors"]))
    state_path = Path(state_path).resolve(strict=True) if state_path else None
    state = load(state_path) if state_path else None
    source_files = inputs or (list(state.get("input_snapshot", {})) if state else [])
    source_evidence = file_evidence(source_files)
    if any(Path(p).stat().st_size == 0 for p in source_evidence):
        raise ValueError("Input material cannot be empty")
    task_name = result["effective_parameters"]["任务名称"]
    if state:
        if task_name != state["task_name"]:
            raise ValueError("Filled task name differs from the task directory")
    else:
        if output_root is None:
            raise ValueError("New tasks require an output root")
        state = create_task(task_name, output_root, timezone_name)
        state_path = Path(state["task_directory"]) / "_work/task.json"
    root = Path(state["task_directory"]).resolve()
    destination = root / state["paths"]["parameters"]
    if not destination.resolve().is_relative_to(root):
        raise ValueError("Parameter path escaped task directory")
    if destination.exists() and destination.read_bytes() != original:
        raise FileExistsError("Existing task parameters differ; preserve and explicitly revise them")
    if filled.read_bytes() != original or file_evidence(source_files) != source_evidence:
        raise ValueError("Parameters or input material changed during retention")
    if not destination.exists():
        with destination.open("xb") as stream:
            stream.write(original)
    update(state_path, "inputs", {"files": list(source_evidence)})
    update(state_path, "parameters", result)
    return {"parameter_file": str(destination), "state": str(state_path),
            "task_directory": str(root), "byte_identical": destination.read_bytes() == original,
            "status": "parameters_validated", "content_generation_started": False}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, help="New fillable Markdown file; never overwrites")
    parser.add_argument("--task-name")
    parser.add_argument("--field", help="Available field ID")
    parser.add_argument("--config", type=Path, help="Configuration for a new table; existing tasks keep their snapshots")
    parser.add_argument("--filled", type=Path, help="Filled user document to retain")
    parser.add_argument("--state", type=Path, help="Existing task state")
    parser.add_argument("--output-root", type=Path)
    parser.add_argument("--timezone", default="Asia/Shanghai")
    parser.add_argument("--input", action="append", type=Path)
    parser.add_argument("--supplements", type=Path)
    parser.add_argument("--scope", choices=("full", "content", "plan", "images", "publish"), default="full")
    args = parser.parse_args()
    if bool(args.out) == bool(args.filled):
        parser.error("Choose exactly one of --out or --filled")
    if args.out:
        text = render(args.task_name, args.field, args.config)
        args.out.parent.mkdir(parents=True, exist_ok=True)
        with args.out.open("x", encoding="utf-8") as stream:
            stream.write(text)
        print(json.dumps({"fillable_parameters": str(args.out.resolve())}, ensure_ascii=False))
    else:
        extra = json.loads(args.supplements.read_text(encoding="utf-8-sig")) if args.supplements else None
        print(json.dumps(retain(args.filled, args.output_root, args.timezone, args.state,
                                args.input, extra, args.scope), ensure_ascii=False, indent=2))
