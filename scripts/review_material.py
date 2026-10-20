"""Build internal numeric review signals; never infer values or edit source text."""

import argparse
import json
from pathlib import Path
import re

from markdown_contract import measure, parse
from task_state import digest


NUMERAL = r"(?:[+-]?\d+(?:[.,]\d+)*|[零〇一二两三四五六七八九十百千万亿点几]+)"
NUMBER = NUMERAL + r"(?:\s*(?:到|至|～|~|—|-)\s*" + NUMERAL + r")?(?:个)?"
UNIT = r"(?:毫秒|微秒|分钟|小时|摄氏度|百分比|秒|伏特|安培时|安时|安培|毫安时|毫安|欧姆|千瓦时|瓦时|千瓦|公里|千米|度电|毫伏|伏|mV|mAh|mA|mWh|kWh|Wh|Ah|kHz|MHz|Hz|ms|us|min|km|s|h|mΩ|Ω|V|A|W|C|%|％|℃|°C)"
PATTERN = re.compile(r"百分之" + NUMBER + r"|" + NUMBER + r"\s*" + UNIT
                     + r"(?![A-Za-z])", re.I)


def signals(path):
    path = Path(path).resolve()
    text = path.read_text(encoding="utf-8-sig")
    return {"path": str(path), "sha256": digest(path), "signals": [
        {"raw": match[0], "line": text.count("\n", 0, match.start()) + 1,
         "start": match.start(), "end": match.end(),
         "context": text[max(0, match.start() - 60):match.end() + 60]}
        for match in PATTERN.finditer(text)]}


def review(sources, draft, variant=None, reason=None):
    source_records = [signals(path) for path in sources]
    draft_record = signals(draft)
    original = {s["raw"] for record in source_records for s in record["signals"]}
    current = {s["raw"] for s in draft_record["signals"]}
    metrics = measure(parse(draft), variant)
    return {"schema_version": 1, "sources": source_records, "draft": draft_record,
            "metrics": metrics, "length_deviation_reason": reason,
            "length_review_required": False,
            "source_only_signals": sorted(original - current),
            "draft_only_signals": sorted(current - original),
            "review_items": [{"source": record["path"], **signal,
                              "draft_locations": [item for item in draft_record["signals"]
                                                  if item["raw"] == signal["raw"]],
                              "condition_review": "pending", "resolution": None}
                             for record in source_records for signal in record["signals"]],
            "limits": "Exact raw-form differences are review prompts, not numerical errors. "
                      "Match equivalent wording, units, time bases and conditions manually."}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, action="append", type=Path)
    parser.add_argument("--draft", required=True, type=Path)
    parser.add_argument("--variant", choices=("精读版", "标准版", "深度版"))
    parser.add_argument("--length-deviation-reason")
    args = parser.parse_args()
    print(json.dumps(review(args.source, args.draft, args.variant, args.length_deviation_reason),
                     ensure_ascii=False, indent=2))
