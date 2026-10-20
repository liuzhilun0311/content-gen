"""Shared Markdown parsing, permitted layout changes and text accounting."""

import json
import os
from pathlib import Path
import re
import shutil
import subprocess

from document_layout import caption_after, normalize_layout, text_of
from local_config import runtime_value


def runtime_paths():
    runtime = Path.home() / ".cache/codex-runtimes/codex-primary-runtime/dependencies/node"
    node = runtime_value("SANBAO_NODE") or str(runtime / "bin" / (
        "node.exe" if os.name == "nt" else "node"))
    if not Path(node).is_file():
        node = shutil.which(node) or shutil.which("node") or node
    marked = runtime_value("SANBAO_MARKED") or str(runtime / "node_modules/marked/lib/marked.esm.js")
    return node, marked


def parse(path, node=None, marked=None):
    default_node, default_marked = runtime_paths()
    node, marked = node or default_node, marked or default_marked
    module = Path(marked).resolve(strict=True).as_uri()
    script = ("import fs from 'node:fs';"
              f"import {{marked}} from {json.dumps(module)};"
              "console.log(JSON.stringify(marked.lexer(fs.readFileSync(process.argv[1],'utf8'))));")
    return json.loads(subprocess.check_output(
        [node, "--input-type=module", "--eval", script, str(Path(path).resolve())],
        encoding="utf-8", timeout=30))


def compact(text):
    return "".join(text.split())


def exported_ast_text(ast):
    """Match the existing exporter's list labels and nested-block order."""
    pieces = []
    for block in ast:
        kind = block["type"]
        if kind in ("space", "hr"):
            continue
        if kind == "code":
            pieces.append(block["text"])
        elif kind == "table":
            pieces.extend(text_of(cell["tokens"]) for row in [block["header"], *block["rows"]]
                          for cell in row)
        elif kind == "list":
            for index, item in enumerate(block["items"]):
                label = str(block.get("start", 1) + index) + "." if block["ordered"] else "\u2022"
                pieces.append(label + " ")
                simple = [b for b in item["tokens"] if b["type"] in ("text", "paragraph")]
                nested = [b for b in item["tokens"] if b["type"] not in ("text", "paragraph")]
                pieces.append(exported_ast_text(simple))
                pieces.append(exported_ast_text(nested))
        elif kind == "blockquote":
            pieces.append(exported_ast_text(block["tokens"]))
        elif kind in ("heading", "paragraph", "text"):
            pieces.append(text_of(block.get("tokens", [])) if "tokens" in block else block.get("text", ""))
        else:
            raise ValueError("Unsupported Markdown block: " + kind)
    return "".join(pieces)


def expected_text(draft, task_name, record):
    ast = parse(draft)
    # Historical exports without this field used the original draft title/captions.
    if "layout_changes" in record:
        ast, _ = normalize_layout(ast, task_name, record.get("number_sections", False))
    return compact(exported_ast_text(ast))


def measure(ast, variant=None):
    captions, formulas, code, body = set(), [], [], []
    for index, block in enumerate(ast):
        tokens = block.get("tokens", [])
        if block["type"] in ("paragraph", "text") and any(t["type"] == "image" for t in tokens):
            following = caption_after(ast, index)
            if following is not None:
                captions.add(following)
    references = False

    def visit(blocks):
        for block in blocks:
            kind = block["type"]
            if kind == "code":
                code.append(block["text"])
            elif kind in ("paragraph", "text"):
                text = text_of(block.get("tokens", []))
                tokens = [t for t in block.get("tokens", []) if t.get("text", "").strip()]
                standalone_code = len(tokens) == 1 and tokens[0]["type"] == "codespan"
                plain_equation = not re.search(r"[\u4e00-\u9fff。！？]", text)
                if (standalone_code or plain_equation) and re.search(r"=|∫|Σ|≈|≤|≥", text):
                    formulas.append(text)
                else:
                    body.append(text)
            elif kind in ("list", "blockquote"):
                for item in block["items"] if kind == "list" else [{"tokens": block["tokens"]}]:
                    visit(item["tokens"])
            elif kind == "table":
                body.extend(text_of(cell["tokens"]) for row in [block["header"], *block["rows"]]
                            for cell in row)
    for index, block in enumerate(ast):
        if block["type"] == "heading":
            if re.search(r"(?:^|\s)(?:参考资料|参考文献|References)\s*$", text_of(block["tokens"]), re.I):
                references = True
            continue
        if index not in captions and not references:
            visit([block])
    count = len(compact("".join(body)))
    return {"body_characters": count, "formula_characters": len(compact("".join(formulas))),
            "code_characters": len(compact("".join(code))), "target": None,
            "within_target": True, "length_policy": "content_driven",
            "method": "Markdown AST; headings/captions/reference sections/code/standalone equations excluded"}
