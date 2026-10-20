"""Export complete illustrated content as offline HTML, EPUB 3 and navigable PDF."""

import argparse
import base64
import contextlib
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import html
import importlib.util
import io
import json
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import uuid
from zipfile import ZIP_DEFLATED, ZIP_STORED, ZipFile

from lxml import etree
from lxml import html as html_parser
from pypdf import PdfReader
from PIL import Image

from task_paths import content_paths, validate_task_name
from task_state import digest, gates, load


ROOT = Path(__file__).resolve().parent.parent
XHTML = "http://www.w3.org/1999/xhtml"
EPUB = "http://www.idpf.org/2007/ops"
OPF = "http://www.idpf.org/2007/opf"
DC = "http://purl.org/dc/elements/1.1/"
EPUB_CSS = """
body{font-family:sans-serif;line-height:1.75;color:#333;letter-spacing:0}
h1,h2,h3,h4,h5,h6{page-break-after:avoid}
img{display:block;width:85%;max-width:100%;height:auto;margin:20px auto 8px}
figure{margin:20px 0 24px;page-break-inside:avoid}
table{width:100%;table-layout:fixed;border-collapse:collapse}
pre{white-space:pre-wrap;overflow-wrap:anywhere}p{orphans:3;widows:3}
nav ol{list-style:none;padding-left:20px}
@media(max-width:600px){img{width:100%!important}}
"""


def compact(text):
    return re.sub(r"\s+", "", text)


def verify_prepared_source(source, prepared, proof):
    record = json.loads(Path(proof).read_text(encoding="utf-8-sig"))
    if record.get("source_sha256") != digest(source) or record.get("reviewed") is not True:
        raise ValueError("Prepared source requires a current reviewed transformation record")
    expected = Path(source).read_text(encoding="utf-8-sig")
    for change in record["replacements"]:
        before, after, count = change["before"], change["after"], change["count"]
        if not before or expected.count(before) != count:
            raise ValueError("Prepared-source replacement count differs")
        expected = expected.replace(before, after)
    if expected != Path(prepared).read_text(encoding="utf-8-sig"):
        raise ValueError("Prepared source contains changes outside reviewed replacements")


def toc_list(headings):
    root = etree.Element("ol")
    stack = [(0, root)]
    for depth, anchor, text in headings:
        while len(stack) > 1 and depth < stack[-1][0]:
            stack.pop()
        if depth > stack[-1][0] and len(stack[-1][1]):
            nested = etree.SubElement(stack[-1][1][-1], "ol")
            stack.append((depth, nested))
        elif stack[-1][0] == 0:
            stack[-1] = (depth, root)
        item = etree.SubElement(stack[-1][1], "li")
        link = etree.SubElement(item, "a", href="#" + anchor)
        link.text = text
    return root


def xhtml_document(title, body_nodes):
    root = etree.Element("{" + XHTML + "}html", nsmap={None: XHTML, "epub": EPUB})
    root.set("{http://www.w3.org/XML/1998/namespace}lang", "zh-CN")
    head = etree.SubElement(root, "head")
    etree.SubElement(head, "title").text = title
    etree.SubElement(head, "link", rel="stylesheet", href="styles.css", type="text/css")
    body = etree.SubElement(root, "body")
    for node in body_nodes:
        copied = deepcopy(node)
        for element in copied.iter():
            if isinstance(element.tag, str):
                element.tag = "{" + XHTML + "}" + etree.QName(element).localname
        body.append(copied)
    for element in root.iter():
        if isinstance(element.tag, str) and not element.tag.startswith("{"):
            element.tag = "{" + XHTML + "}" + element.tag
    return etree.tostring(root, encoding="utf-8", xml_declaration=True)


def epub_image(original):
    original = Path(original)
    if original.suffix.lower() != ".webp":
        return original.suffix.lower(), original.read_bytes()
    with Image.open(original) as image:
        pixels = image.convert("RGBA")
        stream = io.BytesIO()
        pixels.save(stream, format="PNG")
        data = stream.getvalue()
        with Image.open(io.BytesIO(data)) as converted:
            if converted.size != pixels.size or converted.convert("RGBA").tobytes() != pixels.tobytes():
                raise ValueError("WebP to PNG conversion changed pixels")
    return ".png", data


def write_epub(output, title, article, toc, images):
    chapter = deepcopy(article)
    assets, names = {}, {}
    for image, original in zip(chapter.xpath(".//img"), images):
        original = Path(original)
        key = digest(original)
        if key not in names:
            extension, data = epub_image(original)
            names[key] = f"images/image-{len(names) + 1:03d}{extension}"
            assets[names[key]] = data
        image.set("src", names[key])
    navigation = etree.Element("nav", id="toc")
    navigation.set("{" + EPUB + "}type", "toc")
    heading = etree.SubElement(navigation, "h1")
    heading.text = "目录"
    navigation.append(deepcopy(toc))
    for link in navigation.xpath(".//a"):
        link.set("href", "content.xhtml" + link.get("href"))

    package = etree.Element("{" + OPF + "}package", nsmap={None: OPF, "dc": DC},
                            version="3.0", attrib={"unique-identifier": "book-id"})
    metadata = etree.SubElement(package, "{" + OPF + "}metadata")
    etree.SubElement(metadata, "{" + DC + "}identifier", id="book-id").text = "urn:uuid:" + str(uuid.uuid4())
    etree.SubElement(metadata, "{" + DC + "}title").text = title
    etree.SubElement(metadata, "{" + DC + "}language").text = "zh-CN"
    etree.SubElement(metadata, "{" + OPF + "}meta", property="dcterms:modified").text = (
        datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
    manifest = etree.SubElement(package, "{" + OPF + "}manifest")
    for identifier, href, mime, props in (
        ("content", "content.xhtml", "application/xhtml+xml", ""),
        ("nav", "nav.xhtml", "application/xhtml+xml", "nav"),
        ("css", "styles.css", "text/css", ""),
    ):
        item = etree.SubElement(manifest, "{" + OPF + "}item",
                                id=identifier, href=href, attrib={"media-type": mime})
        if props:
            item.set("properties", props)
    for index, (href, _) in enumerate(assets.items()):
        mime = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg"}[Path(href).suffix]
        etree.SubElement(manifest, "{" + OPF + "}item", id=f"image-{index}",
                         href=href, attrib={"media-type": mime})
    spine = etree.SubElement(package, "{" + OPF + "}spine")
    etree.SubElement(spine, "{" + OPF + "}itemref", idref="nav")
    etree.SubElement(spine, "{" + OPF + "}itemref", idref="content")
    container = etree.Element("container", nsmap={None: "urn:oasis:names:tc:opendocument:xmlns:container"},
                              version="1.0")
    rootfiles = etree.SubElement(container, "rootfiles")
    etree.SubElement(rootfiles, "rootfile", attrib={
        "full-path": "EPUB/package.opf", "media-type": "application/oebps-package+xml"})
    with ZipFile(output, "w", compression=ZIP_DEFLATED) as archive:
        archive.writestr("mimetype", b"application/epub+zip", compress_type=ZIP_STORED)
        archive.writestr("META-INF/container.xml", etree.tostring(container, xml_declaration=True, encoding="utf-8"))
        archive.writestr("EPUB/package.opf", etree.tostring(package, xml_declaration=True, encoding="utf-8"))
        archive.writestr("EPUB/nav.xhtml", xhtml_document(title, [navigation]))
        archive.writestr("EPUB/content.xhtml", xhtml_document(title, [chapter]))
        archive.writestr("EPUB/styles.css", EPUB_CSS.encode("utf-8"))
        for href, data in assets.items():
            archive.writestr("EPUB/" + href, data)


def verify_bundle(outputs, record):
    """Check current export bytes, source identity, navigation and embedded content."""
    source = Path(record["source"])
    if digest(source) != record["source_sha256"]:
        raise ValueError("Content source changed after export")
    if record.get("render_source"):
        for key in ("render_source", "transformation_record"):
            if digest(record[key]) != record[key + "_sha256"]:
                raise ValueError("Prepared content source/proof changed")
        verify_prepared_source(source, record["render_source"], record["transformation_record"])
    for extension, path in outputs.items():
        if digest(path) != record["output_sha256"][extension]:
            raise ValueError("Content output changed: " + extension)
    originals = [Path(p).read_bytes() for p in record["images"]]
    if [hashlib.sha256(data).hexdigest() for data in originals] != record["image_sha256"]:
        raise ValueError("Content source image changed")
    page = html_parser.fromstring(Path(outputs["html"]).read_bytes())
    article = page.get_element_by_id("article")
    expected = compact("".join(article.itertext()))
    if hashlib.sha256(expected.encode("utf-8")).hexdigest() != record["body_text_sha256"]:
        raise ValueError("Content body text changed")
    embedded = [base64.b64decode(image.get("src").split(",", 1)[1], validate=True)
                for image in article.xpath(".//img")]
    if embedded != originals:
        raise ValueError("HTML image order/bytes differ")
    targets = set(article.xpath(".//*[@id]/@id"))
    links = page.get_element_by_id("toc").xpath(".//a/@href")
    if links != ["#" + heading["id"] for heading in record["headings"]] or any(
            link[1:] not in targets for link in links):
        raise ValueError("HTML table of contents is broken")
    with ZipFile(outputs["epub"]) as archive:
        first = archive.infolist()[0]
        if first.filename != "mimetype" or first.compress_type != ZIP_STORED or (
                archive.read("mimetype") != b"application/epub+zip") or archive.testzip():
            raise ValueError("Invalid EPUB ZIP container")
        container = etree.fromstring(archive.read("META-INF/container.xml"))
        if container.xpath("//*[local-name()='rootfile']/@full-path") != ["EPUB/package.opf"]:
            raise ValueError("EPUB rootfile differs")
        package = etree.fromstring(archive.read("EPUB/package.opf"))
        manifest = {item.get("id"): item for item in package.findall("{" + OPF + "}manifest/{" + OPF + "}item")}
        if manifest["nav"].get("properties") != "nav" or package.xpath(
                "//*[local-name()='spine']/*/@idref") != ["nav", "content"]:
            raise ValueError("EPUB navigation/spine invalid")
        for item in manifest.values():
            if "EPUB/" + item.get("href") not in archive.namelist():
                raise ValueError("Missing EPUB resource")
        content = etree.fromstring(archive.read("EPUB/content.xhtml"))
        epub_article = content.find(".//{" + XHTML + "}main")
        if compact("".join(epub_article.itertext())) != expected:
            raise ValueError("EPUB body text differs")
        epub_images = [archive.read("EPUB/" + image.get("src"))
                       for image in content.findall(".//{" + XHTML + "}img")]
        if epub_images != [epub_image(p)[1] for p in record["images"]]:
            raise ValueError("EPUB image order/verified pixels differ")
        nav = etree.fromstring(archive.read("EPUB/nav.xhtml"))
        epub_links = nav.xpath("//*[local-name()='a']/@href")
        if epub_links != ["content.xhtml" + link for link in links]:
            raise ValueError("EPUB table of contents differs")
    reader = PdfReader(outputs["pdf"])
    if not reader.pages or not reader.outline:
        raise ValueError("PDF pages/bookmarks missing")
    def outline_titles(items):
        result = []
        for item in items:
            result.extend(outline_titles(item)) if isinstance(item, list) else result.append(item.title)
        return result
    if outline_titles(reader.outline) != [heading["text"] for heading in record["headings"]]:
        raise ValueError("PDF chapter bookmarks differ")
    page_texts = []
    for index, pdf_page in enumerate(reader.pages, 1):
        text = pdf_page.extract_text()
        footer = rf"(?m)^\s*{index}\s*/\s*{len(reader.pages)}\s*$"
        page_texts.append(re.sub(footer, "", text))
    if expected not in compact("".join(page_texts)):
        raise ValueError("PDF body text differs or font extraction failed")
    if not any(a.get_object().get("/Dest") or a.get_object().get("/A", {}).get("/S") == "/GoTo"
               for p in reader.pages for a in p.get("/Annots", [])):
        raise ValueError("PDF clickable navigation missing")
    return {"text_verified": True, "html_verified": True, "epub_verified": True,
            "pdf_verified": True, "pdf_pages": len(reader.pages),
            "limits": "PDF image encoding is renderer-dependent; page rendering must also be reviewed."}


def export(args):
    root = Path(args.task_root).resolve(strict=True)
    state = load(root / "_work/task.json")
    parameters = state.get("parameters", {})
    if not parameters.get("valid") or parameters.get("scope") not in ("full", "publish"):
        raise ValueError("Content export requires validated full/publish parameters")
    if parameters["route"]["outputs"].get("content", {}).get("value", 0) != 1:
        report = {"platform": "content", "skipped": True, "reason": "content输出开关关闭"}
        print(json.dumps(report, ensure_ascii=False))
        return report
    name = validate_task_name(args.task_name)
    if name != state["task_name"]:
        raise ValueError("Task name differs from task state")
    source = Path(args.source).resolve(strict=True)
    if source != (root / state["paths"]["illustrated"]).resolve():
        raise ValueError("Content must export this task's illustrated Markdown")
    render_source = source
    prepared = getattr(args, "render_source", None)
    transformation_record = getattr(args, "transformation_record", None)
    if bool(prepared) != bool(transformation_record):
        raise ValueError("Prepared source and transformation record must be supplied together")
    if prepared:
        render_source = Path(prepared).resolve(strict=True)
        transformation_record = Path(transformation_record).resolve(strict=True)
        if not all(p.is_relative_to(root / "_work") for p in (render_source, transformation_record)):
            raise ValueError("Prepared content files must stay inside this task's _work")
        verify_prepared_source(source, render_source, transformation_record)
    relative = content_paths(name)
    if state["paths"]["publish"].get("content", relative) != relative:
        raise ValueError("Content output paths differ from fixed task paths")
    outputs = {extension: root / value for extension, value in relative.items()}
    if any(path.exists() for path in outputs.values()) and not args.replace:
        raise FileExistsError("Content output exists; replacement requires --replace")
    original_source = digest(source)
    with tempfile.TemporaryDirectory(prefix="sanbao-content-") as temporary:
        temp = Path(temporary)
        spec = importlib.util.spec_from_file_location("publishing_renderer", ROOT / "scripts/export-publishing-documents.py")
        renderer = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(renderer)
        with contextlib.redirect_stdout(io.StringIO()) as stream:
            renderer.export(argparse.Namespace(
                source=str(render_source), task_name=name, platform="csdn", summary="internal",
                tags=None, node=args.node, marked=args.marked, output_dir=str(temp / "publish/CSDN"),
                task_root=str(temp), variant=None, replace=False, number_sections=True))
        rendered = json.loads(stream.getvalue())
        image_paths = rendered["images"]
        plan = (root / state["paths"]["review"]).resolve()
        gate = gates(state, plan_files=[plan] if plan.is_file() else [], image_files=image_paths)
        if not gate["can_assemble"]:
            raise ValueError("Content image gate failed: " + "; ".join(gate["reasons"]))
        if any(Path(p).suffix.lower() not in (".png", ".jpg", ".jpeg", ".webp") for p in image_paths):
            raise ValueError("Content images must be PNG, JPEG or WebP")
        tree = html_parser.fromstring(Path(rendered["html"]).read_bytes())
        title = tree.get_element_by_id("title").text_content() or name
        article = tree.get_element_by_id("article")
        article.tag = "main"
        heading = etree.Element("h1")
        heading.text = title
        article.insert(0, heading)
        headings = []
        for index, element in enumerate(article.xpath(".//*[self::h1 or self::h2 or self::h3 or self::h4 or self::h5 or self::h6]"), 1):
            anchor = f"section-{index:03d}"
            element.set("id", anchor)
            headings.append((int(element.tag[1]), anchor, "".join(element.itertext())))
        for paragraph in list(article.xpath(".//p[img]")):
            if len(paragraph) != 1 or (paragraph.text or "").strip() or (paragraph[0].tail or "").strip():
                continue
            parent, caption = paragraph.getparent(), paragraph.getnext()
            figure = etree.Element("figure")
            parent.insert(parent.index(paragraph), figure)
            figure.append(paragraph)
            paragraph.set("style", "margin:0;")
            if caption is not None and caption.tag == "p" and "text-align:center" in caption.get("style", ""):
                figure.append(caption)
        toc = toc_list(headings)
        body = "".join(etree.tostring(child, encoding="unicode", method="html") for child in article)
        template = (ROOT / "assets/content-reader.html").read_text(encoding="utf-8")
        values = {"TITLE": html.escape(title), "TOC": etree.tostring(toc, encoding="unicode", method="html"), "BODY": body}
        page = re.sub(r"\{\{([A-Z_]+)\}\}", lambda match: values[match[1]], template)
        staging = {extension: temp / (name + "." + extension) for extension in outputs}
        staging["html"].write_text(page, encoding="utf-8")
        write_epub(staging["epub"], title, article, toc, image_paths)
        subprocess.run([args.node, str(ROOT / "scripts/render-content-pdf.mjs"),
                        str(staging["html"]), str(staging["pdf"]), args.playwright,
                        args.browser or ""], check=True, capture_output=True, text=True, encoding="utf-8")
        if digest(source) != original_source:
            raise ValueError("Source changed during export")
        record = {
            "platform": "content", "source": str(source), "source_sha256": original_source,
            "outputs": {ext: str(path) for ext, path in outputs.items()},
            "output_sha256": {ext: digest(path) for ext, path in staging.items()},
            "images": image_paths, "image_sha256": [digest(p) for p in image_paths],
            "image_occurrences": len(image_paths),
            "epub_conversions": [{"source": p, "format": "PNG", "pixels_verified": True}
                                 for p in image_paths if Path(p).suffix.lower() == ".webp"],
            "body_text_sha256": hashlib.sha256(compact("".join(article.itertext())).encode("utf-8")).hexdigest(),
            "headings": [{"level": depth, "id": anchor, "text": text} for depth, anchor, text in headings],
            "original_text_verified": rendered["text_verified"],
            "layout_changes": rendered.get("layout_changes", []),
            "checked_at": datetime.now(timezone.utc).isoformat(),
        }
        if prepared:
            record.update({
                "render_source": str(render_source), "render_source_sha256": digest(render_source),
                "transformation_record": str(transformation_record),
                "transformation_record_sha256": digest(transformation_record),
            })
        record.update(verify_bundle(staging, record))
        outputs["html"].parent.mkdir(parents=True, exist_ok=True)
        for extension, target in outputs.items():
            shutil.copy2(staging[extension], target)
        report_path = root / "_work/export/content.json"
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(record, ensure_ascii=False))
    return record


if __name__ == "__main__":
    from local_config import runtime_value
    from markdown_contract import runtime_paths
    default_node, default_marked = runtime_paths()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True)
    parser.add_argument("--render-source", help="Reviewed internal formatting copy; original source stays unchanged")
    parser.add_argument("--transformation-record", help="Exact reviewed replacement trace for --render-source")
    parser.add_argument("--task-name", required=True)
    parser.add_argument("--task-root", required=True)
    parser.add_argument("--node", default=default_node)
    parser.add_argument("--marked", default=default_marked)
    parser.add_argument("--playwright", default=runtime_value("SANBAO_PLAYWRIGHT", str(
        Path.home() / ".cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright/index.mjs")),
        help="Path to Playwright's index.mjs")
    parser.add_argument("--browser", default=runtime_value("SANBAO_BROWSER"),
                        help="Installed Chromium/Edge executable; omit for Playwright Chromium")
    parser.add_argument("--replace", action="store_true")
    export(parser.parse_args())
