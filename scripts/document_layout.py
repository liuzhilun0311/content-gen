"""Apply task-title, cover placement and caption typography to parsed Markdown."""

from copy import deepcopy
from pathlib import PurePosixPath
import re


def text_of(tokens):
    return "".join("" if token["type"] in ("image", "html") else
                   "\n" if token["type"] == "br" else
                   text_of(token["tokens"]) if token.get("tokens") else token.get("text", "")
                   for token in tokens)


def is_cover(token):
    name = PurePosixPath(token["href"].replace("\\", "/")).name.lower()
    return name.startswith("00-cover")


def caption_after(ast, index):
    index += 1
    while index < len(ast) and ast[index]["type"] == "space":
        index += 1
    if index == len(ast) or ast[index]["type"] not in ("paragraph", "text"):
        return None
    tokens = ast[index].get("tokens", [])
    if re.match(r"^图[1-9]\d*\s+\S", text_of(tokens).strip()) or (
            len(tokens) == 1 and tokens[0]["type"] == "em"):
        return index
    return None


def number_headings(ast):
    counters = [0] * 5
    changes = []
    for block in ast[1:]:
        if block["type"] != "heading":
            continue
        level = max(1, block["depth"] - 1)
        for parent in range(level - 1):
            if counters[parent] == 0:
                counters[parent] = 1
        counters[level - 1] += 1
        counters[level:] = [0] * (5 - level)
        number = ".".join(str(value) for value in counters[:level])
        tokens = block["tokens"]
        old = text_of(tokens)
        prefix = re.match(r"^\d+(?:\.\d+)*[.、)]?\s+", old)
        if prefix:
            remaining = len(prefix[0])
            while remaining and tokens and tokens[0]["type"] in ("text", "escape"):
                token = tokens[0]
                removed = min(remaining, len(token.get("text", "")))
                token["text"] = token["text"][removed:]
                remaining -= removed
                if not token["text"]:
                    tokens.pop(0)
            if remaining:
                raise ValueError("Section number must be plain text before heading formatting")
        block["tokens"] = [{"type": "text", "text": number + " "}] + tokens
        new = text_of(block["tokens"])
        block["text"] = new
        if old != new:
            changes.append({"kind": "section_number", "before": old, "after": new})
    return changes


def normalize_layout(ast, task_name, number_sections=False):
    ast = deepcopy(ast)
    changes = []
    title_index = next((i for i, block in enumerate(ast)
                        if block["type"] == "heading" and block["depth"] == 1), None)
    title = {"type": "heading", "depth": 1, "text": task_name,
             "tokens": [{"type": "text", "text": task_name}]}
    if title_index is not None:
        old = ast.pop(title_index)
        if text_of(old["tokens"]) != task_name or title_index:
            changes.append({"kind": "title", "before": text_of(old["tokens"]), "after": task_name})
    else:
        changes.append({"kind": "title", "before": None, "after": task_name})
    ast.insert(0, title)
    covers = [i for i, block in enumerate(ast) if block["type"] in ("paragraph", "text")
              and any(t["type"] == "image" and is_cover(t) for t in block.get("tokens", []))]
    if len(covers) > 1:
        raise ValueError("Only one shared cover may occur in the article")
    if covers:
        index = covers[0]
        cover = ast[index]
        if len(cover["tokens"]) != 1:
            raise ValueError("Cover must be a standalone image paragraph")
        caption_index = caption_after(ast, index)
        caption = ast.pop(caption_index) if caption_index is not None else None
        ast.pop(index)
        ast.insert(1, cover)
        if caption is not None:
            ast.insert(2, caption)
        changes.append({"kind": "cover_position", "after": "immediately_after_title"})
    number = 0
    for index, block in enumerate(ast):
        tokens = block.get("tokens", [])
        if block["type"] not in ("paragraph", "text") or len(tokens) != 1 or tokens[0]["type"] != "image":
            continue
        cover = is_cover(tokens[0])
        if not cover:
            number += 1
        caption_index = caption_after(ast, index)
        if caption_index is None:
            continue
        caption = ast[caption_index]
        old = text_of(caption["tokens"]).strip()
        meaning = re.sub(r"^图[1-9]\d*\s+", "", old).rstrip("。.")
        new = meaning if cover else f"图{number} {meaning}"
        caption["tokens"] = ([{"type": "em", "tokens": [{"type": "text", "text": new}]}]
                             if cover else [{"type": "text", "text": new}])
        caption["text"] = new
        if old != new:
            changes.append({"kind": "caption", "before": old, "after": new})
    if number_sections:
        changes.extend(number_headings(ast))
    return ast, changes
