"""Validate the handoff contract for an image plan without generating images."""

import argparse
import hashlib
import json
from pathlib import Path


REQUIRED = {"image_id", "prompt_path", "allowed_labels", "semantic_contract"}


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _validate(plan_path):
    plan_path = Path(plan_path).resolve()
    data = json.loads(plan_path.read_text(encoding="utf-8-sig"))
    if not isinstance(data, dict):
        return {"valid": False, "errors": ["plan must be an object"]}
    errors = []
    version = data.get("schema_version")
    strict = type(version) is int and version == 2
    if version is not None and (type(version) is not int or version not in (1, 2)):
        errors.append("unsupported schema_version")
    task_root = plan_path.parent.parent
    items = data.get("images", data.get("items", []))
    if not isinstance(items, list) or not items:
        errors.append("plan must contain a non-empty images list")
        return {"valid": False, "errors": errors}
    ids = [str(item.get("image_id", "")) for item in items if isinstance(item, dict)]
    if len(ids) != len(set(ids)):
        errors.append("image_id values must be unique")
    if "00" not in ids and "00-cover" not in ids:
        errors.append("plan must contain the shared 00 cover")
    if strict and (not ids or ids[0] not in ("00", "00-cover")):
        errors.append("shared cover must be first")
    for index, item in enumerate(items):
        prefix = f"images[{index}]"
        if not isinstance(item, dict):
            errors.append(prefix + " must be an object")
            continue
        missing = REQUIRED - set(item)
        errors.extend(prefix + " missing " + key for key in sorted(missing))
        if strict and (not isinstance(item.get("image_id"), str) or not item["image_id"].strip()):
            errors.append(prefix + " image_id must be a non-empty string")
        prompt = item.get("prompt_path")
        if strict and (not isinstance(prompt, str) or not prompt.strip()):
            errors.append(prefix + " prompt_path must be a non-empty string")
        if isinstance(prompt, str) and prompt.strip():
            prompt_path = (task_root / prompt).resolve()
            if not prompt_path.is_relative_to(task_root):
                errors.append(prefix + " prompt_path escapes task root")
            elif not prompt_path.is_file():
                errors.append(prefix + " prompt_path does not exist")
            elif strict and item.get("prompt_sha256") != sha256(prompt_path):
                errors.append(prefix + " prompt_sha256 differs from current prompt")
        labels = item.get("allowed_labels")
        if not isinstance(labels, list) or any(not isinstance(label, str) for label in labels):
            errors.append(prefix + " allowed_labels must be a string list")
        contract = item.get("semantic_contract")
        if not isinstance(contract, dict):
            errors.append(prefix + " semantic_contract must be an object")
            continue
        for key in ("nodes", "edges", "forbidden_edges", "forbidden_symbols"):
            if (strict and key not in contract) or not isinstance(contract.get(key, []), list):
                errors.append(prefix + f" semantic_contract.{key} must be a list")
        if any(not isinstance(contract.get(key, []), list)
               for key in ("nodes", "edges", "forbidden_edges", "forbidden_symbols")):
            continue
        nodes = contract.get("nodes", [])
        if strict and (not nodes or any(not isinstance(n, str) or not n.strip() for n in nodes)
                       or len(nodes) != len(set(n for n in nodes if isinstance(n, str)))):
            errors.append(prefix + " nodes must be unique non-empty strings")
        for edge in contract.get("edges", []) + contract.get("forbidden_edges", []):
            if not isinstance(edge, dict) or not edge.get("from") or not edge.get("to"):
                errors.append(prefix + " edges require from and to")
            elif strict:
                if edge["from"] not in nodes or edge["to"] not in nodes:
                    errors.append(prefix + " edge endpoint is outside nodes")
                if (not isinstance(edge.get("condition"), str)
                        or not isinstance(edge.get("relation"), str) or not edge["relation"].strip()):
                    errors.append(prefix + " edges require relation and condition (empty means unconditional)")
        if strict:
            allowed = {(e.get("from"), e.get("to")) for e in contract.get("edges", [])
                       if isinstance(e, dict) and isinstance(e.get("from"), str)
                       and isinstance(e.get("to"), str)}
            forbidden = {(e.get("from"), e.get("to")) for e in contract.get("forbidden_edges", [])
                         if isinstance(e, dict) and isinstance(e.get("from"), str)
                         and isinstance(e.get("to"), str)}
            if allowed & forbidden:
                errors.append(prefix + " edge is both allowed and forbidden")
            if any(not isinstance(symbol, str) for symbol in contract.get("forbidden_symbols", [])):
                errors.append(prefix + " forbidden_symbols must contain strings")
        if "relation_graph" in item and item.get("relation_graph") != contract:
            errors.append(prefix + " relation_graph does not match semantic_contract")
    binding = data.get("binding", {})
    if not isinstance(binding, dict):
        errors.append("binding must be an object")
        binding = {}
    if strict:
        for key in ("content", "review", "parameters"):
            item = binding.get(key, {})
            if not isinstance(item, dict) or not isinstance(item.get("path"), str):
                errors.append("binding." + key + " requires path and sha256")
                continue
            source = (task_root / item["path"]).resolve()
            if not source.is_relative_to(task_root) or not source.is_file():
                errors.append("binding." + key + " is outside task or missing")
            elif item.get("sha256") != sha256(source):
                errors.append("binding." + key + " differs from current source")
        short_ids = data.get("short_image_ids", [])
        if (not isinstance(short_ids, list) or
                any(not isinstance(i, str) for i in short_ids) or
                (short_ids and (short_ids[0] not in ("00", "00-cover")
                               or any(i not in ids for i in short_ids)
                               or len(short_ids) != len(set(short_ids))))):
            errors.append("short_image_ids must be an ordered unique subset with cover first")
    for key in ("content_sha256", "review_sha256", "parameters_sha256"):
        if key in binding and not isinstance(binding[key], str):
            errors.append("binding." + key + " must be a SHA256 string")
    return {"valid": not errors, "errors": errors,
            "warnings": [] if strict else ["Legacy plan: missing v2 source/prompt/graph bindings; review before generation"],
            "schema_version": 2 if strict else 1, "image_count": len(items),
            "plan_sha256": sha256(plan_path)}


def validate(plan_path):
    try:
        return _validate(plan_path)
    except (OSError, ValueError, TypeError, KeyError) as exc:
        return {"valid": False, "errors": ["Invalid image plan: " + str(exc)],
                "schema_version": None}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", required=True, type=Path)
    args = parser.parse_args()
    result = validate(args.plan)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(0 if result["valid"] else 1)
