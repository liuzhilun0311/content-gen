"""Verify selected deliverables and current evidence; never generate or charge."""

import argparse
import base64
from datetime import datetime, timezone
from html.parser import HTMLParser
import json
import io
from pathlib import Path
import re
import subprocess
import time
import zipfile
import xml.etree.ElementTree as ET

from task_paths import PLATFORMS, content_paths
from task_state import digest, gates, load, save, stage_dependencies, _field_value

IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}


def required_stages(state):
    scope, start = state["scope"], state["starting_point"]
    needed = []
    if scope == "content" or (scope in ("full", "plan", "images") and start <= 2):
        needed.append("content")
    if scope in ("full", "plan", "images") and start < 5:
        needed.append("plan")
    if scope in ("full", "images", "publish"):
        needed.append("image_checks")
    if scope in ("full", "publish"):
        needed.append("illustrated")
        route = state["parameters"]["route"]
        if route["selected_platforms"] or route["outputs"].get("content", {}).get("value") == 1:
            needed.append("publish")
    return needed


def short_copy_errors(text):
    headers = list(re.finditer(r"^#{1,6}\s+(.+)$", text, re.M))
    errors = []
    if len(headers) != 3 or [m[1] for m in headers][-2:] != ["文案", "标签"]:
        errors.append("Short platform must contain title/content/tags only")
    if len(headers) == 3:
        for left, right in ((headers[1].end(), headers[2].start()), (headers[2].end(), len(text))):
            if not text[left:right].strip():
                errors.append("Short platform content/tags cannot be empty")
    if re.search(r"!\[|<\s*(?:img|video|audio|svg)\b", text, re.I):
        errors.append("Short platform cannot embed media")
    if re.search(r"(?:\]\(|https?://|(?:imgs|illustrations|publish)[\\/]|[A-Za-z]:[\\/]|"
                 r"\b\S+\.(?:png|jpe?g|webp)\b)", text, re.I):
        errors.append("Short platform cannot contain asset links or paths")
    if re.search(r"^\s*(?:图\s*\d+|分镜|口播|素材清单|素材|图片路径)\s*[：:]?", text, re.M):
        errors.append("Short platform cannot contain production markers")
    return errors


def current_export_text(path):
    if path.suffix == ".html":
        from lxml import html
        tree = html.fromstring(path.read_text(encoding="utf-8-sig"))
        return (tree.get_element_by_id("title").text_content()
                + tree.get_element_by_id("article").text_content()), tree
    with zipfile.ZipFile(path) as archive:
        doc = ET.fromstring(archive.read("word/document.xml"))
        tag = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}t"
        return "".join(node.text or "" for node in doc.iter(tag)), None

def inside(root, relative):
    path = (root / relative).resolve()
    if not path.is_relative_to(root):
        raise ValueError("Output path escaped task directory")
    return path


def expected_files(state):
    route, scope = state["parameters"]["route"], state["scope"]
    paths = state["paths"]
    expected = [paths["parameters"]]
    if scope in ("full", "content", "plan", "images"):
        expected.append(paths["content"])
    if scope in ("full", "plan", "images") and state["starting_point"] < 5:
        expected.append(paths["review"])
    if scope in ("full", "publish"):
        expected.append(paths["illustrated"])
        for key, (label, _) in PLATFORMS.items():
            if label not in route["selected_platforms"]:
                continue
            variants = route["longform"].get("by_platform", {}).get(
                label, route["longform"]["variants"])
            output = paths["publish"][key]
            if isinstance(output, dict):
                if not variants or any(v not in output for v in variants):
                    raise ValueError("Historical version paths require an explicit preserved route or migration")
                expected.extend(output[v] for v in variants)
            else:
                if key in ("zhihu", "wechat", "csdn") and variants != [None]:
                    raise ValueError("Single-article paths cannot use a historical versioned route")
                expected.append(output)
        if route["outputs"].get("content", {}).get("value") == 1:
            expected.extend(paths["publish"].get("content", content_paths(state["task_name"])).values())
    return expected


class Page(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids, self.images = set(), []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if attrs.get("id"):
            self.ids.add(attrs["id"])
        if tag == "img":
            src = attrs.get("src", "")
            if not src.startswith("data:image/") or ";base64," not in src:
                raise ValueError("HTML image is not embedded")
            self.images.append(base64.b64decode(src.split(";base64,", 1)[1], validate=True))


def exported_images(path):
    if path.suffix == ".html":
        page = Page()
        text = path.read_text(encoding="utf-8-sig")
        if re.search(r"\{\{(?:TITLE|BODY|SUMMARY)\}\}", text):
            raise ValueError("Unresolved HTML template")
        page.feed(text)
        required = {"title", "summary", "article", "copy-title", "copy-summary", "copy-body"}
        if not required <= page.ids:
            raise ValueError("Missing copy fields or controls")
        return page.images, page.ids
    ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
          "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
          "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships"}
    with zipfile.ZipFile(path) as archive:
        if archive.testzip():
            raise ValueError("Corrupt DOCX")
        doc = ET.fromstring(archive.read("word/document.xml"))
        if not "".join(doc.itertext()).strip():
            raise ValueError("Empty DOCX body")
        rels = {r.attrib["Id"]: r.attrib for r in ET.fromstring(
            archive.read("word/_rels/document.xml.rels"))}
        images = []
        for image in doc.findall(".//a:blip", ns):
            rel = rels[image.attrib["{" + ns["r"] + "}embed"]]
            if rel.get("TargetMode") == "External":
                raise ValueError("External DOCX image")
            target = rel["Target"]
            if ".." in Path(target).parts:
                raise ValueError("Unsafe DOCX image relationship")
            images.append(archive.read("word/" + target.lstrip("/")))
        return images, set()

def embedded_images_match(embedded, originals, output, record):
    """Preserve source bytes except for explicitly verified DOCX WebP conversion."""
    if len(embedded) != len(originals):
        return False
    conversions = record.get("image_conversions", [])
    for data, source in zip(embedded, originals):
        source = Path(source)
        original = source.read_bytes()
        if data == original:
            continue
        if output.suffix.lower() != ".docx" or source.suffix.lower() != ".webp":
            return False
        conversion = next((item for item in conversions if item.get("source") == str(source)), {})
        import hashlib
        if (conversion.get("rgba_pixels_verified") is not True
                or conversion.get("embedded_format") != "png"
                or conversion.get("source_sha256") != hashlib.sha256(original).hexdigest()
                or conversion.get("embedded_sha256") != hashlib.sha256(data).hexdigest()):
            return False
        from PIL import Image
        with Image.open(io.BytesIO(original)) as expected, Image.open(io.BytesIO(data)) as actual:
            if (actual.format != "PNG" or actual.size != expected.size
                    or actual.convert("RGBA").tobytes() != expected.convert("RGBA").tobytes()):
                return False
    return True


def verify(state_path):
    started = time.perf_counter()
    state = load(state_path)
    root = Path(state["task_directory"]).resolve()
    errors, evidence, expected = [], {}, []
    hashes = {}

    def current_digest(path):
        path = Path(path).resolve()
        stat = path.stat()
        stamp = (stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns)
        prior = hashes.get(path)
        if prior and prior[0] == stamp:
            return prior[1]
        value = digest(path)
        after = path.stat()
        if stamp != (after.st_size, after.st_mtime_ns, after.st_ctime_ns):
            raise ValueError("File changed during verification: " + str(path))
        hashes[path] = (stamp, value)
        return value

    def check(condition, message):
        if not condition:
            errors.append(message)

    def snapshot(files, label):
        check(bool(files), label + ": missing snapshot")
        for p, sha in files.items():
            check(Path(p).is_file() and current_digest(p) == sha, label + ": changed/missing " + p)
            if Path(p).is_file():
                evidence[str(Path(p).resolve())] = current_digest(p)

    if not state.get("parameters", {}).get("valid"):
        return {"passed": False, "errors": ["Parameters not validated"], "expected": [], "files": {}}
    try:
        snapshot(state.get("input_snapshot", {}), "Input")
        snapshot(state.get("parameter_snapshot", {}), "Parameters")
        expected = expected_files(state)
        check(state.get("deliverable_manifest") == expected, "Delivery manifest missing or differs from current route")
        for relative in expected:
            path = inside(root, relative)
            check(path.is_file() and path.stat().st_size > 0, "Missing/empty: " + relative)
            if path.is_file() and path.stat().st_size:
                evidence[str(path)] = current_digest(path)
        route, scope = state["parameters"]["route"], state["scope"]
        needed = required_stages(state)
        machine_plan = root / "_work/image-plan.json"
        if ("plan" in needed and machine_plan.is_file()
                and json.loads(machine_plan.read_text(encoding="utf-8-sig")).get("schema_version") == 2):
            from validate_image_plan import validate
            plan_result = validate(machine_plan)
            check(plan_result["valid"] and plan_result.get("schema_version") == 2,
                  "Current v2 machine plan invalid: " + "; ".join(plan_result["errors"]))
            check(state["stages"].get("plan", {}).get("evidence", {}).get(str(machine_plan))
                  == current_digest(machine_plan), "Plan stage does not bind machine plan")
        for name in needed:
            stage = state["stages"].get(name, {})
            check(stage.get("status") == "passed", "Missing passed stage: " + name)
            if stage.get("status") == "passed":
                snapshot(stage.get("evidence", {}), "Stage " + name)
                if stage.get("stage_schema_version") == 2:
                    check(stage.get("dependencies") == stage_dependencies(state, name),
                          "Stage dependencies differ from current upstream: " + name)
                    check(stage.get("field") == _field_value(state["parameters"]),
                          "Stage field differs from current parameters: " + name)
                if stage.get("dependencies"):
                    snapshot(stage["dependencies"], "Dependencies " + name)
                artifact = {"content": "content", "plan": "review", "illustrated": "illustrated"}.get(name)
                if artifact:
                    actual = inside(root, state["paths"][artifact])
                    check(actual.is_file() and stage.get("evidence", {}).get(str(actual)) == current_digest(actual),
                          "Stage " + name + " does not bind current artifact: " + str(actual))
        images = sorted(p for p in inside(root, state["paths"]["images"]).glob("*")
                        if p.suffix.lower() in IMAGE_SUFFIXES)
        if scope in ("full", "images", "publish"):
            check(bool(images), "Missing actual image group")
            plan = inside(root, state["paths"]["review"])
            result = gates(state, [plan] if plan.is_file() else [], images)
            check(result["can_assemble"] if scope != "images" else
                  not result["reasons"] and all(state["image_checks"].get(str(p.resolve()), {}).get("passed") and
                      state["image_checks"][str(p.resolve())]["sha256"] == current_digest(p) for p in images),
                  "Current image/confirmation gate failed: " + "; ".join(result["reasons"]))
            for p in images:
                evidence[str(p)] = current_digest(p)
        illustrated = inside(root, state["paths"]["illustrated"])
        if scope in ("full", "publish") and illustrated.is_file():
            for url in re.findall(r"!\[[^\]]*\]\(([^)]+)\)", illustrated.read_text(encoding="utf-8-sig")):
                referenced = inside(root, url.strip("<>"))
                check(referenced.is_file(), "Broken illustrated image: " + url)
                check(referenced in images, "Illustrated reference outside reviewed image group: " + url)
        short_groups = []
        for key, (label, extension) in PLATFORMS.items():
            if scope not in ("full", "publish") or label not in route["selected_platforms"]:
                continue
            outputs = state["paths"]["publish"][key]
            variants = route["longform"].get("by_platform", {}).get(label, route["longform"]["variants"])
            for variant in variants if isinstance(outputs, dict) else [None]:
                path = inside(root, outputs[variant] if variant else outputs)
                if not path.is_file():
                    continue
                publish_evidence = state["stages"].get("publish", {}).get("evidence", {})
                check(publish_evidence.get(str(path)) == current_digest(path),
                      "Publish stage does not bind current output: " + str(path))
                local = sorted(p for p in path.parent.iterdir() if p.suffix.lower() in IMAGE_SUFFIXES)
                for p in local:
                    original = inside(root, state["paths"]["images"]) / p.name
                    check(original in images and current_digest(original) == current_digest(p), "Wrong image copy: " + str(p))
                    evidence[str(p)] = current_digest(p)
                check(any(p.name.startswith("00-cover-main.") for p in local), "Missing shared cover: " + str(path))
                if extension == "md":
                    short_groups.append({p.name: current_digest(p) for p in local})
                    errors.extend(error + ": " + str(path) for error in
                                  short_copy_errors(path.read_text(encoding="utf-8-sig")))
                    continue
                record_path = (root / "_work" / "export" / key / (variant + ".json")
                               if variant else root / "_work" / "export" / (key + ".json"))
                draft_dir = root / "_work" / "drafts" / label
                if variant:
                    draft_dir /= variant
                draft_path = draft_dir / (
                    state["task_name"] + "_" + label + "_draft.md")
                for proof in (record_path, draft_path):
                    check(proof.is_file() and publish_evidence.get(str(proof)) == current_digest(proof),
                          "Publish stage does not bind export/draft: " + str(proof))
                record = json.loads(record_path.read_text(encoding="utf-8-sig"))
                check(record.get("platform") == key and record.get("variant") == variant,
                      "Export record belongs to a different platform/version: " + str(path))
                check(record.get("text_verified") is True, "Export text not verified: " + str(path))
                for hash_key, proof in (("source_sha256", draft_path), ("output_sha256", path)):
                    if hash_key in record:
                        check(record[hash_key] == current_digest(proof),
                              "Export record hash differs: " + hash_key + ": " + str(path))
                from markdown_contract import compact, expected_text
                actual_text, tree = current_export_text(path)
                check(compact(actual_text) == expected_text(draft_path, state["task_name"], record),
                      "Current exported text differs from draft: " + str(path))
                if tree is not None:
                    check(tree.get_element_by_id("summary").text_content() == record.get("summary"),
                          "Current summary differs from export record: " + str(path))
                    if key == "wechat":
                        check(tree.get_element_by_id("tags").text_content() == record.get("tags"),
                              "Current tags differ from export record: " + str(path))
                embedded, ids = exported_images(path)
                check(all(Path(p).resolve() in images for p in record["images"]),
                      "Export uses unreviewed source images: " + str(path))
                check(embedded_images_match(embedded, record["images"], path, record),
                      "Embedded image order/bytes differ: " + str(path))
                check(len(embedded) == record["image_occurrences"], "Image count differs: " + str(path))
                check({Path(p).name for p in record["images"]} == {p.name for p in local},
                      "Published copies differ from embedded group: " + str(path))
                if key == "wechat":
                    check({"tags", "copy-tags"} <= ids, "Missing WeChat tags: " + str(path))
                if key == "csdn":
                    check(not ({"tags", "copy-tags"} & ids), "Unexpected CSDN tags: " + str(path))
        if len(short_groups) == 2:
            check(short_groups[0] == short_groups[1], "Two short platforms use different images")
        content_enabled = scope in ("full", "publish") and route["outputs"].get("content", {}).get("value") == 1
        if content_enabled:
            from importlib.util import spec_from_file_location, module_from_spec
            content_spec = spec_from_file_location("content_export", Path(__file__).with_name("export-content-documents.py"))
            content_module = module_from_spec(content_spec)
            content_spec.loader.exec_module(content_module)
            relative = state["paths"]["publish"].get("content", content_paths(state["task_name"]))
            check(relative == content_paths(state["task_name"]), "Content paths differ from fixed task paths")
            outputs = {ext: inside(root, p) for ext, p in relative.items()}
            record_path = root / "_work/export/content.json"
            proof = state["stages"].get("publish", {}).get("evidence", {})
            for path in [*outputs.values(), record_path, illustrated]:
                check(path.is_file() and proof.get(str(path)) == current_digest(path),
                      "Publish stage does not bind content: " + str(path))
            if record_path.is_file() and all(p.is_file() for p in outputs.values()):
                record = json.loads(record_path.read_text(encoding="utf-8-sig"))
                check(record.get("platform") == "content" and Path(record["source"]).resolve() == illustrated,
                      "Content export record belongs to a different task/source")
                check(record.get("outputs") == {ext: str(p) for ext, p in outputs.items()},
                      "Content record output paths differ")
                check(all(Path(p).resolve() in images for p in record["images"]), "Content uses unreviewed images")
                check(record.get("original_text_verified") is True, "Content source text not verified")
                for key in ("render_source", "transformation_record"):
                    if record.get(key):
                        prepared = Path(record[key]).resolve()
                        check(prepared.is_relative_to(root / "_work") and prepared.is_file()
                              and proof.get(str(prepared)) == current_digest(prepared),
                              "Publish stage does not bind prepared content: " + str(prepared))
                content_module.verify_bundle(outputs, record)
                evidence[str(record_path)] = current_digest(record_path)
        if scope in ("full", "publish") and (route["selected_platforms"] or content_enabled):
            qa_evidence = state["stages"].get("publish", {}).get("evidence", {})
            check(any(Path(p).is_relative_to(root / "_work" / "qa") for p in qa_evidence),
                  "Missing actual publish QA evidence")
        for path, (stamp, _) in hashes.items():
            stat = path.stat()
            check(stamp == (stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns),
                  "File changed during verification: " + str(path))
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError,
            zipfile.BadZipFile, ET.ParseError) as exc:
        errors.append("Verification failed: " + str(exc))
    return {"task_id": state["task_id"], "checked_at": datetime.now(timezone.utc).isoformat(),
            "passed": not errors, "errors": errors, "expected": expected, "files": evidence,
            "elapsed_seconds": round(time.perf_counter() - started, 3),
            "limits": "File/evidence checks do not replace actual professional or visual review; target editor paste is separate."}


def commit(state_path, report):
    if not report["passed"]:
        raise ValueError("Incomplete task cannot be marked complete")
    original = Path(state_path).read_bytes()
    state = load(state_path)
    fresh = verify(state_path)
    if not fresh["passed"] or fresh["files"] != report["files"] or fresh["task_id"] != report["task_id"]:
        raise ValueError("Task changed after verification")
    state["status"] = "complete"
    state["completion"] = fresh
    save(state_path, state, original)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state", required=True, type=Path)
    parser.add_argument("--complete", action="store_true")
    args = parser.parse_args()
    result = verify(args.state)
    if args.complete and result["passed"]:
        commit(args.state, result)
    report_path = args.state.parent / "qa" / "completion.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(0 if result["passed"] else 1)
