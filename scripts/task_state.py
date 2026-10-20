"""Persist task evidence and bind human confirmation to actual file hashes."""

import argparse
import hashlib
import json
import os
import tempfile
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load(path):
    state = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    if state.get("state_schema_version") != 1 or not state.get("task_id"):
        raise ValueError("Historical task state requires explicit migration before updating")
    return state


@contextmanager
def _state_lock(path):
    """Serialize the complete read/transform/write transaction."""
    lock_path = Path(path).with_name(Path(path).name + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    handle = lock_path.open("a+b")
    try:
        if os.name == "nt":
            import msvcrt
            handle.seek(0)
            handle.write(b"0")
            handle.flush()
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
        else:
            import fcntl
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        yield
    finally:
        if os.name == "nt":
            import msvcrt
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        handle.close()


def _write(path, state, original):
    path = Path(path)
    if path.read_bytes() != original:
        raise ValueError("Task state changed; reload before updating")
    state["state_revision"] = int(state.get("state_revision", 0)) + 1
    with tempfile.NamedTemporaryFile(dir=path.parent, suffix=".tmp", delete=False) as stream:
        temporary = Path(stream.name)
        stream.write(json.dumps(state, ensure_ascii=False, indent=2).encode("utf-8"))
        stream.flush()
        os.fsync(stream.fileno())
    try:
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def save(path, state, original):
    with _state_lock(path):
        _write(path, state, original)


DEPENDENT_STAGES = ("content", "plan", "images", "image_checks", "illustrated", "publish")


def _invalidate(state, stages, reason):
    changed = []
    for stage in stages:
        prior = state.setdefault("stages", {}).get(stage)
        if prior and prior.get("status") != "pending":
            state["stages"][stage] = {
                "status": "pending",
                "invalidated_at": datetime.now(timezone.utc).isoformat(),
                "reason": reason,
            }
            changed.append(stage)
    if "plan" in stages:
        state.setdefault("confirmations", {}).pop("plan", None)
    if "images" in stages or "image_checks" in stages:
        state.setdefault("confirmations", {}).pop("images", None)
    if "image_checks" in stages:
        state["image_checks"] = {}
    if changed:
        state.setdefault("history", []).append({
            "event": "invalidate",
            "stages": changed,
            "reason": reason,
            "recorded_at": datetime.now(timezone.utc).isoformat(),
        })


def _field_value(result):
    effective = result.get("effective_parameters", {})
    value = effective.get("field", effective.get("专业领域"))
    if isinstance(value, dict):
        value = value.get("value")
    scope = result.get("supplements", {}).get("field")
    if scope:
        return {"selection": value, "scope": scope}
    return value


def file_evidence(paths):
    if not paths:
        raise ValueError("Actual files are required for an evidence record")
    return {str(Path(p).resolve(strict=True)): digest(p) for p in paths}


def stage_dependencies(state, stage):
    root = Path(state["task_directory"])
    dependencies = dict(state.get("input_snapshot", {})) if stage == "content" else {}
    if stage == "content":
        field = _field_value(state.get("parameters", {}))
        if isinstance(field, dict):
            field = field.get("selection")
        if isinstance(field, str) and field.startswith("field_") and Path(field).name == field:
            directory = Path(__file__).resolve().parent.parent / "references/fields" / field
            sources = [directory / name for name in
                       ("expert-teaching.md", "writing-examples.md", "illustration-guidance.md")]
            if not all(source.is_file() for source in sources):
                raise ValueError("Selected field requires all three current rule files: " + str(directory))
            dependencies.update(file_evidence(sources))
    upstream = {
        "plan": ("content",), "images": ("content", "review"),
        "image_checks": ("content", "review"),
        "illustrated": ("content", "review"),
        "publish": ("content", "review", "illustrated"),
    }
    for key in upstream.get(stage, ()):
        source = root / state["paths"][key]
        if source.is_file():
            dependencies.update(file_evidence([source]))
    if stage in ("illustrated", "publish"):
        dependencies.update({p: check["sha256"] for p, check in state["image_checks"].items()
                             if check.get("passed")})
    return dependencies


def update(path, event, payload):
    path = Path(path)
    with _state_lock(path):
        original = path.read_bytes()
        state = load(path)
        now = datetime.now(timezone.utc).isoformat()
        state.pop("completion", None)
        state["status"] = "in_progress"
        if event == "parameters":
            if not payload.get("valid") or payload.get("errors"):
                raise ValueError("Only a passing parameter-validation result may be recorded")
            prior = state.get("parameters", {})
            state["parameters"] = payload
            state["starting_point"] = payload["route"]["starting_point"]
            state["scope"] = payload["scope"]
            parameter_file = path.parent.parent / state["paths"]["parameters"]
            if parameter_file.is_file():
                state["parameter_snapshot"] = file_evidence([parameter_file])
            from verify_task import expected_files
            state["deliverable_manifest"] = expected_files(state)

            def visual_values(result):
                values = result.get("effective_parameters", {})
                # Ignore the retired field when comparing saved legacy validations.
                excluded = {"任务名称", "本次任务起点", "长平台篇幅组合", "自动学习偏好",
                            "是否需要配图方案审核", "是否需要图片审核"}
                selected = {k: v for k, v in values.items()
                            if k not in excluded and not k.startswith("是否输出")}
                extra_keys = {"palette", "references", "watermark.content", "author_name",
                              "output_compression", "variants_per_image", "generation_batch_size",
                              "limit", "output_dir", "article_action"}
                selected["_supplements"] = {
                    k: v for k, v in result.get("supplements", {}).items() if k in extra_keys}
                return selected

            if prior:
                field_changed = _field_value(prior) != _field_value(payload)
                visual_changed = visual_values(prior) != visual_values(payload)
                if field_changed:
                    _invalidate(state, DEPENDENT_STAGES, "专业领域或领域范围已变化")
                elif visual_changed:
                    _invalidate(state, ("plan", "images", "image_checks", "illustrated", "publish"),
                                "视觉或专业作图参数已变化")
        elif event == "inputs":
            new_snapshot = file_evidence(payload.get("files"))
            if state.get("input_snapshot") and state["input_snapshot"] != new_snapshot:
                _invalidate(state, DEPENDENT_STAGES, "输入材料SHA256已变化")
            state["input_snapshot"] = new_snapshot
        elif event == "stage":
            stage, status = payload.get("stage"), payload.get("status")
            if stage not in DEPENDENT_STAGES:
                raise ValueError("Unknown stage")
            if status not in ("pending", "running", "waiting", "passed", "failed"):
                raise ValueError("Unknown stage status")
            if status == "passed" and not payload.get("evidence"):
                raise ValueError("Passed stages require actual validation evidence")
            if status == "passed":
                evidence = payload["evidence"]
                if not isinstance(evidence, dict) or any(
                        not Path(p).is_file() or digest(p) != sha for p, sha in evidence.items()):
                    raise ValueError("Passed-stage evidence must match current actual files")
            state["status"] = {"waiting": "waiting", "failed": "failed"}.get(status, "in_progress")
            prior = state["stages"].get(stage, {})
            dependencies = stage_dependencies(state, stage) if status == "passed" else {}
            if prior and (prior.get("evidence") != payload.get("evidence")
                          or prior.get("status") != status
                          or prior.get("dependencies", {}) != dependencies):
                following = DEPENDENT_STAGES[DEPENDENT_STAGES.index(stage) + 1:]
                _invalidate(state, following, "上游阶段或文件证据已变化：" + stage)
            state["stages"][stage] = {
                **payload, "recorded_at": now, "stage_schema_version": 2,
                "dependencies": dependencies, "field": _field_value(state["parameters"]),
            }
        elif event == "image-check":
            files = file_evidence(payload.get("files"))
            checklist = payload.get("checks", {})
            needed = {"text", "professional", "composition", "content_mapping"}
            if set(checklist) != needed or any(type(v) is not bool for v in checklist.values()):
                raise ValueError("All four actual image-check outcomes must be recorded as booleans")
            for image, sha in files.items():
                state["image_checks"][image] = {
                    "sha256": sha, "checks": checklist, "passed": all(checklist.values()),
                    "notes": payload.get("notes", ""), "recorded_at": now,
                }
        elif event in ("plan-confirm", "image-confirm"):
            if payload.get("explicit_user_confirmation") is not True or not payload.get("source"):
                raise ValueError("Confirmation requires explicit user approval and its source")
            evidence = file_evidence(payload.get("files"))
            if event == "image-confirm":
                for image, sha in evidence.items():
                    check = state["image_checks"].get(image, {})
                    if not check.get("passed") or check.get("sha256") != sha:
                        raise ValueError("Human approval cannot substitute for a passing current image check")
            state["confirmations"]["plan" if event == "plan-confirm" else "images"] = {
                "files": evidence, "source": payload["source"], "confirmed_at": now,
            }
        else:
            raise ValueError("Unknown event")
        state["history"].append({"event": event, "recorded_at": now})
        _write(path, state, original)
        return state


def gates(state, plan_files=(), image_files=()):
    parameters = state.get("parameters", {})
    if not parameters.get("valid"):
        return {"can_generate": False, "can_assemble": False, "reasons": ["参数尚未校验通过"]}
    route = parameters["route"]
    generate = bool(route.get("stages", {}).get("generate_images")) and parameters["scope"] in ("full", "images")
    reasons = []

    def current_confirm(key, paths):
        return bool(paths) and state.get("confirmations", {}).get(key, {}).get("files") == file_evidence(paths)

    plan_ok = not generate or route["review"]["value"] != 1 or current_confirm("plan", plan_files)
    machine_plan = Path(state["task_directory"]) / "_work/image-plan.json"
    generation_plan_ok, generation_reasons = True, []
    if generate:
        from validate_image_plan import validate
        validation = validate(machine_plan)
        if not validation["valid"] or validation.get("schema_version") != 2:
            generation_plan_ok = False
            generation_reasons.append("新生图需先通过当前v2来源／提示词／图关系校验；历史合格图可复用")
    if not plan_ok:
        reasons.append("当前方案尚未取得用户确认")
    checks_ok = bool(image_files) and all(
        state.get("image_checks", {}).get(str(Path(p).resolve()), {}).get("passed") and
        state["image_checks"][str(Path(p).resolve())]["sha256"] == digest(p)
        for p in image_files)
    images_ok = route["image_review"]["value"] != 1 or current_confirm("images", image_files)
    if not checks_ok:
        reasons.append("当前图组尚未充分自检通过")
    if not images_ok:
        reasons.append("当前图组尚未取得用户确认")
    return {"can_generate": generate and plan_ok and generation_plan_ok,
            "can_assemble": parameters["scope"] in ("full", "publish") and checks_ok and images_ok and plan_ok,
            "reasons": reasons, "generation_reasons": generation_reasons}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state", required=True, type=Path)
    parser.add_argument("--event", choices=("parameters", "inputs", "stage", "image-check", "plan-confirm", "image-confirm"))
    parser.add_argument("--payload", type=Path)
    parser.add_argument("--check-gates", action="store_true")
    parser.add_argument("--plan-file", action="append", default=[])
    parser.add_argument("--image-file", action="append", default=[])
    args = parser.parse_args()
    if args.event:
        if not args.payload:
            parser.error("--event requires --payload")
        result = update(args.state, args.event, json.loads(args.payload.read_text(encoding="utf-8-sig")))
    elif args.check_gates:
        result = gates(load(args.state), args.plan_file, args.image_file)
    else:
        result = load(args.state)
    print(json.dumps(result, ensure_ascii=False, indent=2))
