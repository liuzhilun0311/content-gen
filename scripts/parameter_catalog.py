"""Map non-secret semantic defaults to the existing numbered task catalogue."""

import re
import json
from pathlib import Path

from workflow_switches import table_rows


ROOT = Path(__file__).resolve().parent.parent
CATALOG = ROOT / "config/extend.example.md"
REFERENCES = ROOT / "references"
IDENTITIES = frozenset(("任务名称", "专业领域"))
SWITCHES = frozenset((
    "use_image_gen", "是否需要配图方案审核", "是否需要图片审核",
    "是否输出知乎", "是否输出微信公众号", "是否输出CSDN",
    "是否输出抖音", "是否输出小红书", "是否输出content",
))
LANGUAGES = {1: "zh", 2: "en", 3: "bilingual", 4: "source"}
POSITIONS = {1: "bottom-right", 2: "bottom-left", 3: "bottom-center", 4: "top-right"}
IMAGE_GEN_FIELDS = frozenset((
    "model", "resolution", "quality", "background", "output_format",
    "output_compression", "moderation", "show_info",
))


def key_for(name):
    if name == "是否使用 image-gen":
        return "use_image_gen"
    match = re.search(r"`([^`]+)`", name)
    return match[1] if match else name


def choices(row):
    return {int(m[1]): m[2].strip() for m in re.finditer(
        r"(?:^|<br\s*/?>)\s*(\d+)\.\s*(.*?)(?=<br\s*/?>|$)", row[5])}


def parameter_rows(text):
    return {name: row for name, row in table_rows(text).items()
            if name not in ("参数名称", "---")}


def starting_point_number(value):
    if type(value) is int and value in range(1, 6):
        return value
    if isinstance(value, str):
        row = parameter_rows(CATALOG.read_text(encoding="utf-8-sig"))["本次任务起点"]
        for number, label in choices(row).items():
            if value.strip().rstrip("。") in (label.rstrip("。"), label.split("：", 1)[0]):
                return number
    raise ValueError("Starting point default must be 1 to 5 or a catalogue label")


def semantic_value(name, number, label):
    key = key_for(name)
    if key in SWITCHES:
        return bool(number)
    if key in ("watermark.enabled", "show_info"):
        return number == 1
    if key == "本次任务起点":
        return number
    if key == "language":
        return LANGUAGES[number]
    if key == "watermark.position":
        return POSITIONS[number]
    if key == "variants_per_image" and number in (1, 2):
        return number
    if key == "generation_batch_size" and number in (1, 2, 3):
        return {1: 1, 2: 2, 3: 4}[number]
    if key == "output_compression" and number in (1, 2, 3):
        return {1: None, 2: 70, 3: 90}[number]
    if (key in ("moderation", "output_format") and number == 1):
        return None
    if key == "aspect_ratio" and number == 1:
        return "per-image"
    if (key, number) in (("type", 8), ("style", 24), ("palette", 6)):
        return "preset"
    if key == "palette" and number == 5:
        return "style-default"
    if key == "preset" and number == 27:
        return "none"
    token = re.search(r"`([^`]+)`", label)
    return token[1] if token else label


def default_number(name, row, value):
    for number, label in choices(row).items():
        candidate = semantic_value(name, number, label)
        if type(candidate) is type(value) and candidate == value:
            return number
    custom = {"palette": 7, "watermark.content": 2, "variants_per_image": 3,
              "generation_batch_size": 4, "output_compression": 4}
    return custom.get(key_for(name))


def check_catalog(text):
    rows = parameter_rows(text)
    expected = parameter_rows(CATALOG.read_text(encoding="utf-8-sig"))
    if list(rows) != list(expected):
        raise ValueError("Configuration must contain the complete parameter catalogue in order")
    for name, row in rows.items():
        if row[4].strip() or row[3].strip():
            raise ValueError("Configuration catalogue has no task answers or defaults; edit JSON defaults")
        requirements = {expected[name][2].strip()}
        if key_for(name) in IMAGE_GEN_FIELDS:
            requirements.add("用户选填")
        if choices(row) != choices(expected[name]) or row[2].strip() not in requirements:
            raise ValueError("Keep catalogue option numbers and requirements unchanged: " + name)
    return rows


def apply_defaults(text, defaults):
    rows = parameter_rows(text)
    supplements = {}
    lines = []
    for name, row in rows.items():
        key = key_for(name)
        row[3], row[4] = " ", " "
        if key in IMAGE_GEN_FIELDS:
            row[2] = " 条件选填 "
            if "use_image_gen=true" not in row[5]:
                row[5] = " 仅 use_image_gen=true 且本次需要生图时适用；留空沿用本表默认。 " + row[5].lstrip()
        if key in IDENTITIES:
            if defaults.get(key, "") != "":
                raise ValueError("Task name and field cannot have cross-task defaults")
            continue
        value = defaults.get(key, "")
        if value == "":
            continue
        if key == "本次任务起点":
            value = starting_point_number(value)
        number = default_number(name, row, value)
        if number is None:
            raise ValueError("Default cannot be mapped to a numbered option: " + key)
        label = choices(row)[number]
        row[3] = f" {number}.{label.split('：', 1)[0]} "
        if semantic_value(name, number, label) != value:
            supplements[key] = value
    for line in text.splitlines():
        if line.startswith("|"):
            name = line.split("|")[1].strip()
            lines.append("|".join(rows[name]) if name in rows else line)
    return "\n".join(lines) + "\n", supplements


def snapshot_supplements(text, rows):
    blocks = re.findall(r"<!-- content-gen-default-supplements\r?\n(.*?)\r?\n-->", text, re.S)
    if not blocks:
        return {}
    if len(blocks) != 1:
        raise ValueError("Duplicate default supplement snapshots")
    try:
        data = json.loads(blocks[0])
    except json.JSONDecodeError as error:
        raise ValueError("Invalid default supplement snapshot") from error
    allowed = {"palette", "watermark.content", "variants_per_image",
               "generation_batch_size", "output_compression"}
    if not isinstance(data, dict) or set(data) - allowed:
        raise ValueError("Unsupported default supplement snapshot")
    result = {}
    for key, item in data.items():
        if not isinstance(item, dict) or set(item) != {"default", "value"}:
            raise ValueError("Invalid default supplement entry")
        row = next((row for name, row in rows.items() if key_for(name) == key), None)
        if row and not row[4].strip() and row[3].strip() == item["default"]:
            result[key] = item["value"]
    return result
