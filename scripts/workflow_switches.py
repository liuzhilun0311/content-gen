"""Resolve fixed five-column task-table review and platform switches."""

import argparse
import json
import re
from pathlib import Path


PLATFORMS = ("CSDN", "抖音", "微信公众号", "小红书", "知乎")
LEGACY = {"CSDN": "CSDN 文章", "抖音": "抖音文案", "微信公众号": "微信公众号文章",
          "小红书": "小红书文案", "知乎": "知乎文章"}


def binary(value, default, legacy=False):
    value = value.strip()
    if value == "":
        return default, "流程默认"
    if legacy and value == "2":
        return 0, "旧表迁移"
    if value not in ("0", "1"):
        raise ValueError("Expected 0 or 1, got: " + value)
    return int(value), "明确填写"


def table_rows(text):
    rows = {}
    for line in text.splitlines():
        if not line.startswith("|"):
            continue
        cells = re.split(r"(?<!\\)\|", line)
        if len(cells) != 7:
            raise ValueError("Task-table rows must contain exactly five columns")
        name = cells[1].strip()
        if name in rows:
            raise ValueError("Duplicate parameter: " + name)
        rows[name] = cells
    return rows


def row_choice(row, default, allowed, legacy=False):
    answer = row[4].strip()
    if answer:
        if legacy and answer == "2":
            return 0, "旧表迁移"
        if answer not in allowed:
            raise ValueError("Invalid parameter answer: " + row[1].strip())
        return int(answer), "明确填写"
    snapshot = row[3].strip()
    if snapshot:
        match = re.match(r"^(\d+)\s*[.．]", snapshot)
        if not match or match[1] not in allowed:
            if legacy and match and match[1] == "2":
                return 0, "任务默认快照（旧表迁移）"
            raise ValueError("Invalid task default snapshot: " + row[1].strip())
        return int(match[1]), "任务默认快照"
    return default, "流程默认"


def point_from_row(row, text):
    if row is None:
        return None
    point, _ = row_choice(row, 1, ("1", "2", "3", "4", "5"))
    description = row[5]
    marker = "起点规则版本：五起点" in text or "starting_point_schema_version: 2" in text
    current_options = all(token in description for token in (
        "4. 生图", "5. 正文插图+发布内容生成"))
    legacy_options = any(token in description for token in (
        "通用续接", "自动判断", "从生成最终内容和所发布内容开始"))
    if legacy_options or not (marker or current_options):
        raise ValueError("Starting-point schema is missing or historical; record a verified five-point migration")
    return point


def resolve(text):
    rows = table_rows(text)
    review_names = [name for name in ("是否需要配图方案审核", "是否需要配图审核")
                    if name in rows]
    if len(review_names) > 1:
        raise ValueError("Both new and legacy plan-review switches exist")
    if not review_names:
        raise ValueError("Review mode missing in a historical table; preserve its prior review agreement")
    review_row = rows[review_names[0]]
    review = None if review_row[2].strip() == "不适用" else row_choice(review_row, 0, ("0", "1"))
    image_review_row = rows.get("是否需要图片审核")
    if image_review_row is None:
        image_review = (0, "历史表未设置，保留原审核约定")
    elif image_review_row[2].strip() == "不适用":
        image_review = None
    else:
        image_review = row_choice(image_review_row, 0, ("0", "1"))
    start_row = rows.get("本次任务起点")
    start = point_from_row(start_row, text)
    provider_row = rows.get("是否使用 image-gen")
    provider = row_choice(provider_row, 1, ("0", "1")) if provider_row else (
        1, "历史表未设置，默认使用 image-gen")
    length_row = rows.get("长平台篇幅组合")
    current_template = text.startswith("# 技能输入参数设置")
    if length_row and (current_template or re.search(r"^longform_schema_version:\s*2\s*$", text, re.M)):
        raise ValueError("New single-article tables cannot contain a historical length selector")
    length = row_choice(length_row, 1, ("1", "2", "3", "4", "5")) if length_row else (
        0, "单篇输出，篇幅由内容决定")
    variants = {0: [None], 1: ["精读版", "标准版", "深度版"], 2: ["标准版"],
                3: ["精读版"], 4: ["深度版"], 5: None}[length[0]]
    outputs = {}
    for platform in PLATFORMS:
        name, legacy_name = "是否输出" + platform, LEGACY[platform]
        if name in rows and legacy_name in rows:
            raise ValueError("Both new and legacy output switches exist for " + platform)
        if name in rows:
            value, source = row_choice(rows[name], 1, ("0", "1"))
        elif legacy_name in rows:
            value, source = row_choice(rows[legacy_name], 1, ("0", "1"), legacy=True)
        else:
            raise ValueError("Output switch missing: " + name)
        outputs[platform] = {"value": value, "source": source}
    content_row = rows.get("是否输出content")
    content = row_choice(content_row, 1, ("0", "1")) if content_row else (
        0, "历史表未设置，保留原输出范围")
    outputs["content"] = {"value": content[0], "source": content[1]}
    return {
        "use_image_gen": {"value": provider[0], "source": provider[1]},
        "review": {"value": review[0], "source": review[1]} if review else {
            "value": None, "source": "不适用"},
        "image_review": {"value": image_review[0], "source": image_review[1]} if image_review else {
            "value": None, "source": "不适用"},
        "outputs": outputs,
        "selected_platforms": [p for p in PLATFORMS if outputs[p]["value"] == 1],
        "selected_outputs": [p for p in (*PLATFORMS, "content") if outputs[p]["value"] == 1],
        "all_outputs_disabled": all(item["value"] == 0 for item in outputs.values()),
        "starting_point": start,
        "longform": {"value": length[0], "source": length[1], "variants": variants},
        "route_only": True,
        "parameter_validation_required": True,
        "stages": {
            "convert_content": start == 1,
            "plan_illustrations": start in (1, 2),
            "review_existing_plan": start == 3,
            "check_plan_before_generation": start in (1, 2, 3, 4),
            "generate_images": start in (1, 2, 3, 4),
            "call_image_gen": start in (1, 2, 3, 4) and provider[0] == 1,
            "inspect_and_correct_images": start in (1, 2, 3, 4, 5),
            "user_plan_review_required": start in (1, 2, 3, 4) and review is not None and review[0] == 1,
            "user_image_review_required": image_review is not None and image_review[0] == 1,
            "assemble_final_content": start in (1, 2, 3, 4, 5),
        } if start is not None else None,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--parameters", required=True)
    args = parser.parse_args()
    print(json.dumps(resolve(Path(args.parameters).read_text(encoding="utf-8-sig")),
                     ensure_ascii=False, indent=2))
