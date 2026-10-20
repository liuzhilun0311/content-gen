"""Check local execution dependencies once; no installation or network requests."""

import argparse
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

from markdown_contract import runtime_paths
from local_config import runtime_value


def inspect_runtime(profile="full", workspace=None):
    checks = []

    def record(name, ready, detail, required=True):
        checks.append({"name": name, "ready": bool(ready), "required": required, "detail": detail})

    record("python", True, sys.executable)
    publishing = profile in ("full", "publish")
    for module in ("docx", "lxml", "PIL", "pypdf"):
        spec = importlib.util.find_spec(module)
        record(module, spec is not None, spec.origin if spec else "not installed", publishing)
    rasterizers = {name: bool(importlib.util.find_spec(name))
                   for name in ("fitz", "pymupdf", "pypdfium2")}
    record("pdf_rasterizer", any(rasterizers.values()), rasterizers, publishing)
    node, marked = runtime_paths()
    try:
        completed = subprocess.run(
            [node, "--input-type=module", "--eval",
             "import {marked} from " + json.dumps(Path(marked).resolve().as_uri())
             + "; if (!marked.lexer('# preflight').length) process.exit(1);"],
            capture_output=True, timeout=20)
        record("node/marked", completed.returncode == 0, {"node": node, "marked": marked},
               profile != "content")
    except (OSError, subprocess.SubprocessError) as exc:
        record("node/marked", False, str(exc), profile != "content")
    runtime = Path.home() / ".cache/codex-runtimes/codex-primary-runtime/dependencies/node"
    playwright = runtime_value("SANBAO_PLAYWRIGHT") or str(runtime / "node_modules/playwright/index.mjs")
    browser = runtime_value("SANBAO_BROWSER") or (
        "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe" if os.name == "nt"
        else shutil.which("chromium") or "")
    if publishing:
        try:
            script = ("import {chromium} from " + json.dumps(Path(playwright).resolve().as_uri())
                      + "; const b=await chromium.launch({headless:true,executablePath:"
                      + json.dumps(browser) + "}); const p=await b.newPage();"
                      "await p.setContent('<p>preflight</p>');"
                      "if(await p.locator('p').innerText()!=='preflight') process.exitCode=1;"
                      "await b.close();")
            completed = subprocess.run([node, "--input-type=module", "--eval", script],
                                       capture_output=True, timeout=30)
            record("browser/playwright", completed.returncode == 0,
                   {"browser": browser, "playwright": playwright})
        except (OSError, subprocess.SubprocessError) as exc:
            record("browser/playwright", False, str(exc))
    word = False
    if os.name == "nt":
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, "Word.Application"):
                word = True
        except OSError:
            pass
    libreoffice = shutil.which("soffice")
    record("docx_renderer_available", bool(word or libreoffice),
           {"word_registered": word, "libreoffice": libreoffice,
            "limits": "Availability only; actual document rendering QA is required."}, publishing)
    target = Path(workspace or tempfile.gettempdir()).resolve()
    try:
        with tempfile.TemporaryFile(dir=target) as stream:
            stream.write(b"preflight")
            stream.flush()
        record("workspace_writable", True, str(target))
    except OSError as exc:
        record("workspace_writable", False, str(exc))
    return {"profile": profile, "ready": all(c["ready"] for c in checks if c["required"]),
            "checks": checks, "limits": "No remote service, API key, visual correctness or editor paste verified."}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", choices=("content", "plan", "images", "publish", "full"), default="full")
    parser.add_argument("--workspace", type=Path)
    args = parser.parse_args()
    result = inspect_runtime(args.profile, args.workspace)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(0 if result["ready"] else 1)
