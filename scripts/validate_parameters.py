"""Validate one five-column parameter document without generating content."""

import argparse
import json
import re
from pathlib import Path

from task_paths import validate_task_name
from workflow_switches import resolve, table_rows
from parameter_catalog import CATALOG, REFERENCES, IMAGE_GEN_FIELDS, choices, key_for


TEMPLATE = CATALOG
FLOW_NAMES = {"任务名称", "专业领域", "本次任务起点", "长平台篇幅组合",
              "是否需要配图方案审核", "是否需要图片审核"}
CUSTOM = {
    "preset": {27}, "palette": {7}, "references": {2, 3},
    "watermark.content": {2}, "output_compression": {4},
    "variants_per_image": {3}, "generation_batch_size": {4},
    "limit": {2, 3}, "output_dir": {4}, "article_action": {2},
}
DEPENDENT_FIELDS = frozenset((
    "reference_usage", "watermark.content", "watermark.position",
    "output_compression", "existing_images",
))


def definition_optional(row):
    return row[2].strip() in ("用户选填", "用户可选", "条件选填")


def identity_answers(text, rows):
    """Resolve the page header and table without silently overriding a conflict."""
    errors, result = [], {}
    for name in ("任务名称", "专业领域"):
        header = re.findall(r"^" + name + r"[ \t]*[：:][ \t]*([^\r\n]*)$", text, re.M)
        if len(header) > 1:
            errors.append(name + "：页首重复")
        top = header[0].strip() if header else ""
        row = rows.get(name)
        answer = row[4].strip() if row else ""
        if name == "专业领域":
            options = choices(row) if row else {}
            def normalize(value):
                if not value or value.isdecimal():
                    return value
                matched = []
                for n, label in options.items():
                    token = re.search(r"`([^`]+)`", label)
                    display = re.search(r"[（(]([^）)]+)[）)]", label)
                    if value in (token[1] if token else "", display[1] if display else ""):
                        matched.append(str(n))
                return matched[0] if len(matched) == 1 else value
            top, answer = normalize(top), normalize(answer)
        if top and answer and top != answer:
            errors.append(name + "：页首与表内答案不一致")
        result[name] = answer or top
    return result, errors


def validate(text, supplements=None, scope="full", allow_defaults=False):
    supplements = supplements or {}
    errors, warnings, values, sources = [], [], {}, {}
    try:
        rows = table_rows(text)
        route = resolve(text)
        from parameter_catalog import snapshot_supplements
        supplements = {**snapshot_supplements(text, rows), **supplements}
    except ValueError as exc:
        return {"valid": False, "errors": [str(exc)], "warnings": [], "parameters": {}}
    identities, identity_errors = identity_answers(text, rows)
    errors.extend(identity_errors)
    start = route["starting_point"]
    if start is None:
        errors.append("本次任务起点：必须填写1至5")
    if scope not in ("full", "content", "plan", "images", "publish"):
        errors.append("处理范围无效")
    if scope == "content" and start not in (1, 2):
        errors.append("仅内容范围只适用于起点1或2")
    if scope == "publish" and start != 5:
        errors.append("仅平台生成应从起点5接续，不重新生图")
    generate = start in (1, 2, 3, 4) and scope not in ("content", "publish")
    use_image_gen = route["use_image_gen"]["value"] == 1
    planned_images = scope != "content"
    definitions = table_rows(TEMPLATE.read_text(encoding="utf-8-sig"))
    for name, definition in definitions.items():
        if name in ("参数名称", "---"):
            continue
        key = key_for(name)
        applicable = True
        if key == "use_image_gen":
            applicable = generate
        elif key in IMAGE_GEN_FIELDS and not use_image_gen:
            applicable = False
        elif name.startswith("是否输出"):
            applicable = scope in ("full", "publish")
        elif name == "长平台篇幅组合":
            applicable = scope in ("full", "publish") and any(
                route["outputs"][p]["value"] for p in ("知乎", "微信公众号", "CSDN"))
        elif name == "是否需要配图方案审核":
            applicable = generate
        elif name == "是否需要图片审核":
            applicable = planned_images and scope not in ("plan",)
        elif key not in FLOW_NAMES and name != "课程输入材料" and not name.startswith("是否输出"):
            applicable = generate
        if not applicable:
            continue
        row = rows.get(name)
        if row is None:
            if key == "use_image_gen":
                values[key] = {"number": 1, "value": "使用"}
                sources[key] = route["use_image_gen"]["source"]
                warnings.append("历史表未设置是否使用 image-gen，默认使用；不迁移旧凭据")
                continue
            if name == "是否输出content":
                warnings.append("历史表未设置content开关，保留原输出范围（不输出）")
                continue
            errors.append(name + "：缺少参数行，请迁移旧表")
            continue
        # Dependent fields are checked after their controlling choices resolve.
        if key in DEPENDENT_FIELDS:
            continue
        if row[2].strip() == "不适用":
            errors.append(name + "：本阶段适用，不能标为不适用")
            continue
        if name == "课程输入材料":
            if row[4].strip() in ("", "自动识别", "未识别"):
                errors.append("输入材料：需记录已实际读取的文件或材料")
            continue
        answer, source = identities.get(name, row[4].strip()), "明确填写"
        if answer and name in identities and not row[4].strip():
            source = "页首明确填写"
        required = ("用户必填" in row[2] or "用户必填" in definition[2]
                    or name in ("任务名称", "专业领域"))
        if not answer:
            if name == "本次任务起点":
                answer = str(start)
                source = "任务默认快照" if row[3].strip() else "流程默认"
            elif required and not allow_defaults:
                errors.append(name + "：必填项未回答")
                continue
            match = re.match(r"^(\d+)\s*[.．]", row[3].strip())
            if name == "本次任务起点":
                pass
            elif match:
                answer, source = match[1], "明确沿用任务默认" if required else "任务默认快照"
            elif key == "moderation":
                values[key], sources[key] = {"number": 1, "value": None}, "服务默认"
                continue
            else:
                errors.append(name + "：没有答案或可用默认值")
                continue
        if name == "任务名称":
            try:
                validate_task_name(answer)
            except ValueError as exc:
                errors.append("任务名称：" + str(exc))
            values[key], sources[key] = answer, source
            continue
        options = choices(row) if name == "专业领域" else choices(definition)
        if not answer.isdecimal() or int(answer) not in options:
            errors.append(name + "：无效选项编号 " + answer)
            continue
        number = int(answer)
        label = options[number]
        token = re.search(r"`([^`]+)`", label)
        values[key] = {"number": number, "value": token[1] if token else label}
        if key == "moderation":
            values[key]["value"] = {1: None, 2: "auto", 3: "low"}.get(number)
        sources[key] = source
        if number in CUSTOM.get(key, set()) and key != "preset":
            if key not in supplements:
                errors.append(name + "：请在补充参数中提供 " + key)
        if name == "专业领域":
            if token and re.fullmatch(r"field_[a-z0-9]+(?:-[a-z0-9]+)*", token[1]):
                field_dir = REFERENCES / "fields" / token[1]
                if not all((field_dir / filename).is_file() for filename in (
                        "expert-teaching.md", "illustration-guidance.md", "writing-examples.md")):
                    errors.append("专业领域：所选领域缺少完整配置")
            elif "field" not in supplements:
                errors.append("专业领域：新增或跨领域需补充 field 名称及范围")
    # Historical tables keep their explicitly selected versions; new tables omit the row.
    if route["longform"]["value"] == 5:
        allowed_variants = {"精读版", "标准版", "深度版"}
        def valid_variants(value):
            return (isinstance(value, list) and bool(value) and
                    all(isinstance(v, str) and v in allowed_variants for v in value)
                    and len(value) == len(set(value)))
        if not valid_variants(supplements.get("longform_variants")):
            errors.append("历史篇幅组合：需有效且不重复的 longform_variants")
        exceptions = supplements.get("longform_by_platform", {})
        if (not isinstance(exceptions, dict) or any(
                p not in ("知乎", "微信公众号", "CSDN") or not valid_variants(v)
                for p, v in exceptions.items())):
            errors.append("历史篇幅组合：平台例外无效")
    elif route["longform"]["value"] == 0 and any(
            key in supplements for key in ("longform_variants", "longform_by_platform")):
        errors.append("新任务每个长平台只输出一篇，请移除历史分档补充参数")

    def number(key):
        value = values.get(key)
        return value.get("number") if isinstance(value, dict) else None

    def dependent(key, active):
        name = next(n for n in definitions if key_for(n) == key)
        row = rows.get(name)
        if not active:
            return
        if not row or row[2].strip() == "不适用":
            errors.append(name + "：条件满足，必须填写")
            return
        answer = row[4].strip()
        if not answer and (allow_defaults or definition_optional(definitions[name])):
            match = re.match(r"^(\d+)\s*[.．]", row[3].strip())
            answer = match[1] if match else ""
        opts = choices(definitions[name])
        if not answer.isdecimal() or int(answer) not in opts:
            errors.append(name + "：条件满足，请填写有效编号")
            return
        n = int(answer)
        values[key] = {"number": n, "value": opts[n]}
        sources[key] = ("明确填写" if row[4].strip() else
                        "任务默认快照" if definition_optional(definitions[name]) else
                        "明确沿用任务默认")
        if n in CUSTOM.get(key, set()) and key not in supplements:
            errors.append(name + "：缺少补充值 " + key)

    if generate:
        dependent("reference_usage", number("references") in (2, 3))
        dependent("watermark.content", number("watermark.enabled") == 1)
        dependent("watermark.position", number("watermark.enabled") == 1)
        dependent("output_compression", use_image_gen and number("output_format") in (3, 4))
        dependent("existing_images", bool(supplements.get("has_existing_images")))
        if number("references") in (2, 3):
            files = supplements.get("references")
            if (not isinstance(files, list) or not files or
                    any(not isinstance(p, str) or not Path(p).is_file() or
                        Path(p).stat().st_size == 0 for p in files)):
                errors.append("参考图：需可读取且非空的本地文件")
            elif use_image_gen and (len(files) > 16 or any(
                    Path(p).stat().st_size > 10 * 1024 * 1024 for p in files)):
                errors.append("image-gen参考图：最多16个文件，每个不超过10MB")
            if use_image_gen and number("variants_per_image") != 1:
                errors.append("使用参考图时每图变体数必须为一张")
        if number("model") == 3 and number("quality") in (5, 6):
            errors.append("旧模型不支持xhigh/max")
        if number("background") == 4 and (number("model") == 3 or number("output_format") not in (2, 4)):
            errors.append("透明背景需2.5模型和明确PNG或WebP格式")
        if number("preset") == 27 and any((number("type") == 8, number("style") == 24, number("palette") == 6)):
            errors.append("手动组合不能选择沿用预设")
        for key in ("watermark.content", "palette", "output_dir", "article_action"):
            if key in supplements and (not isinstance(supplements[key], str) or not supplements[key].strip()):
                errors.append(key + "：需非空补充文字或路径")
        for key, low, high in (("generation_batch_size", 1, 8), ("variants_per_image", 1, None),
                               ("output_compression", 0, 100)):
            if key in IMAGE_GEN_FIELDS and not use_image_gen:
                continue
            value = supplements.get(key)
            if key in supplements and (type(value) is not int or value < low or (high is not None and value > high)):
                errors.append(key + "：补充数值无效")
        if number("limit") in (2, 3):
            limit = supplements.get("limit")
            if not isinstance(limit, dict):
                errors.append("数量或预算约束：补充limit对象")
            elif number("limit") == 2 and (type(limit.get("image_count")) is not int or limit["image_count"] < 1):
                errors.append("图片数量上限必须为正整数")
            elif number("limit") == 3:
                amount = limit.get("amount")
                if type(amount) not in (int, float) or not amount > 0 or not limit.get("currency"):
                    errors.append("预算必须有正数金额和币种")
                errors.append("费用上限不能由本解析器验证；需先确认可靠控制方式或改用请求/数量上限")
        if number("watermark.enabled") == 1 and number("watermark.content") == 1 and not supplements.get("author_name"):
            errors.append("水印名称：需已明确提供的author_name，不能推测身份")
    effective = {key: item["value"] if isinstance(item, dict) else item for key, item in values.items()}
    if generate and "preset" in effective and effective["preset"] != "手动组合，不使用预设":
        preset_text = (REFERENCES / "style-presets.md").read_text(encoding="utf-8-sig")
        preset_line = next((line for line in preset_text.splitlines()
                            if line.startswith("| `" + str(effective["preset"]) + "` |")), None)
        if preset_line:
            cells = preset_line.split("|")
            expanded = [re.search(r"`([^`]+)`", cells[i]) for i in (2, 3, 4)]
            for index, (key, inherited) in enumerate((("type", 8), ("style", 24), ("palette", 6))):
                if number(key) == inherited:
                    effective[key] = expanded[index][1] if expanded[index] else "style-default"
    if generate:
        if number("type") == 8 and effective.get("type") == "沿用预设中的类型":
            errors.append("所选预设无法展开类型")
        if number("style") == 24 and effective.get("style") == "沿用预设中的风格":
            errors.append("所选预设无法展开风格")
    if route["longform"]["value"] == 5 and not errors:
        route["longform"]["variants"] = supplements["longform_variants"]
        route["longform"]["by_platform"] = supplements.get("longform_by_platform", {})
    route["scope"] = scope
    stages = route.get("stages")
    if stages:
        if scope in ("content", "publish"):
            for key in ("plan_illustrations", "review_existing_plan",
                        "check_plan_before_generation", "user_plan_review_required"):
                stages[key] = False
        stages["generate_images"] = stages["generate_images"] and scope in ("full", "images")
        stages["call_image_gen"] = stages["generate_images"] and use_image_gen
        stages["inspect_and_correct_images"] = stages["inspect_and_correct_images"] and scope in ("full", "images", "publish")
        stages["user_image_review_required"] = stages["user_image_review_required"] and scope in ("full", "images", "publish")
        stages["assemble_final_content"] = stages["assemble_final_content"] and scope in ("full", "publish")
    if scope not in ("full", "publish"):
        route["selected_platforms"] = []
        route["selected_outputs"] = []
    return {"valid": not errors, "errors": list(dict.fromkeys(errors)), "warnings": warnings,
            "parameters": values, "sources": sources, "scope": scope,
            "effective_parameters": effective, "route": route, "supplements": supplements,
            "professional_checks_required": True,
            "input_evidence_required": True,
            "confirmation_records_required": True}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--parameters", required=True, type=Path)
    parser.add_argument("--supplements", type=Path)
    parser.add_argument("--scope", choices=("full", "content", "plan", "images", "publish"), default="full")
    parser.add_argument("--allow-defaults", action="store_true",
                        help="Only when the user explicitly accepts all applicable task defaults")
    args = parser.parse_args()
    extra = json.loads(args.supplements.read_text(encoding="utf-8-sig")) if args.supplements else {}
    result = validate(args.parameters.read_text(encoding="utf-8-sig"), extra, args.scope, args.allow_defaults)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(0 if result["valid"] else 1)
