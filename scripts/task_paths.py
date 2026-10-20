"""Create a named task directory and record its fixed output paths."""

import argparse
import json
import re
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


PLATFORMS = {"zhihu": ("知乎", "docx"), "wechat": ("微信公众号", "html"),
             "csdn": ("CSDN", "html"), "douyin": ("抖音", "md"),
             "xiaohongshu": ("小红书", "md")}
LONGFORM_VARIANTS = ("精读版", "标准版", "深度版")
CONTENT_FORMATS = ("html", "epub", "pdf")


def content_paths(name):
    validate_task_name(name)
    return {extension: f"publish/content/{name}/{name}.{extension}"
            for extension in CONTENT_FORMATS}


def validate_task_name(name):
    if not name or name != name.strip() or name.endswith("."):
        raise ValueError("Task name must be nonempty without leading/trailing spaces or a trailing dot")
    if re.search(r'[<>:"/\\|?*\x00-\x1f]', name) or name in (".", ".."):
        raise ValueError("Task name contains a forbidden filename character")
    device = name.split(".", 1)[0].upper()
    if device in {"CON", "PRN", "AUX", "NUL"} or re.fullmatch(r"(COM|LPT)[1-9¹²³]", device):
        raise ValueError("Task name is a reserved Windows device name")
    return name


def create_task(name, output_root, timezone_name):
    validate_task_name(name)
    try:
        local_zone = ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError:
        if timezone_name != "Asia/Shanghai":
            raise
        local_zone = timezone(timedelta(hours=8))
    created = datetime.now(local_zone)
    root = Path(output_root).resolve() / (name + "_" + created.strftime("%Y%m%d%H%M%S"))
    root.mkdir(parents=True, exist_ok=False)
    work = root / "_work"
    work.mkdir()
    record = {
        "state_schema_version": 1, "state_revision": 0,
        "parameter_schema_version": 4, "longform_schema_version": 2,
        "starting_point_schema_version": 2, "task_id": str(uuid.uuid4()),
        "task_name": name, "created_at": created.isoformat(),
        "timezone": timezone_name, "task_directory": str(root),
        "scope": None, "starting_point": None, "parameters": {},
        "status": "awaiting_parameters", "input_snapshot": {},
        "stages": {}, "confirmations": {}, "image_checks": {},
        "artifacts": {}, "history": [],
        "paths": {
            "parameters": name + "_参数.md", "content": name + "_内容.md",
            "review": name + "_内容_配图审核稿.md", "illustrated": name + "_内容_配图.md",
            "images": "imgs", "work": "_work",
            "publish": {key: f"publish/{label}/{name}_{label}_publish.{extension}"
                        for key, (label, extension) in PLATFORMS.items()},
        },
    }
    version_file = Path(__file__).resolve().parent.parent / "version.json"
    if version_file.is_file():
        record["skill_version"] = json.loads(version_file.read_text(encoding="utf-8"))["version"]
    record["paths"]["publish"]["content"] = content_paths(name)
    (work / "task.json").write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    return record


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task-name", required=True)
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--timezone", required=True)
    args = parser.parse_args()
    print(json.dumps(create_task(args.task_name, args.output_root, args.timezone), ensure_ascii=False))
