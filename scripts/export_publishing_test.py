import argparse
import contextlib
import importlib.util
import io
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from zipfile import ZipFile

from PIL import Image
from lxml import etree, html


spec = importlib.util.spec_from_file_location(
    "publishing_export", Path(__file__).with_name("export-publishing-documents.py"))
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class PublishingTests(unittest.TestCase):
    def setUp(self):
        runtime = Path.home() / ".cache/codex-runtimes/codex-primary-runtime/dependencies/node"
        self.node = os.environ.get("SANBAO_NODE", str(runtime / "bin/node.exe"))
        self.marked = os.environ.get(
            "SANBAO_MARKED", str(runtime / "node_modules/marked/lib/marked.esm.js"))
        if not Path(self.node).exists() or not Path(self.marked).exists():
            self.skipTest("Set SANBAO_NODE and SANBAO_MARKED to test export")
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        for name, color in (("00-cover.png", "red"), ("02-detail.png", "blue")):
            Image.new("RGB", (320, 240), color).save(self.root / name)
        self.source = self.root / "article.md"
        self.source.write_text(
            "# 测试标题\n\n![主题](00-cover.png)\n\n"
            "能量 E=mc<sup>**2**</sup>，水 H<sub>2</sub>O。\n\n"
            "1. 一级要点\n   - 二级解释\n   - 第二项\n2. 一级结论\n\n"
            "> 条件必须说明。\n\n"
            "| 项目 | 意义 |\n| --- | --- |\n| 变量 | 正确解释 |\n\n"
            "```python\nvalue = 2\n```\n\n![细节](02-detail.png)\n",
            encoding="utf-8")

    def args(self, platform="wechat", variant=None):
        destination = self.root / "publish" / module.PLATFORMS[platform][0]
        if variant:
            destination /= variant
        return argparse.Namespace(
            source=str(self.source), task_name="测试任务", platform=platform,
            node=self.node, marked=self.marked, summary="说明问题、方法及适用条件。",
            tags="#测试 #知识", replace=False, variant=variant,
            task_root=str(self.root), output_dir=str(destination))

    def run_export(self, args):
        with contextlib.redirect_stdout(io.StringIO()) as stream:
            module.export(args)
        return json.loads(stream.getvalue())

    def test_nine_outputs_and_reports_do_not_collide(self):
        paths = []
        for platform in ("zhihu", "wechat", "csdn"):
            for variant in module.LONGFORM_VARIANTS:
                args = self.args(platform, variant)
                report = self.run_export(args)
                paths.append(report["docx"] or report["html"])
                self.assertTrue(report["text_verified"])
                self.assertEqual(report["image_occurrences"], 2)
                self.assertFalse(report["target_editor_verified"])
                self.assertTrue((self.root / "_work/export" / platform /
                                 (variant + ".json")).exists())
                qa_dir = os.environ.get("SANBAO_QA_DIR")
                if qa_dir and variant == "标准版":
                    saved = Path(qa_dir) / (platform + Path(paths[-1]).suffix)
                    saved.parent.mkdir(parents=True, exist_ok=True)
                    if saved.exists():
                        raise FileExistsError("QA fixture destination must be fresh")
                    shutil.copy2(paths[-1], saved)
        self.assertEqual(len(set(paths)), 9)
        self.assertTrue(all(Path(path).exists() for path in paths))

    def test_nested_lists_scripts_and_html_copy_regions(self):
        report = self.run_export(self.args())
        tree = html.fromstring(Path(report["html"]).read_text(encoding="utf-8"))
        article = tree.get_element_by_id("article")
        text = "".join(article.itertext())
        self.assertIn("二级解释", text)
        self.assertTrue(article.xpath(".//sup/strong"))
        self.assertTrue(article.xpath(".//sub"))
        self.assertEqual(len(tree.xpath("//button[starts-with(@id,'copy-')]")), 4)
        self.assertFalse(article.xpath(".//*[@id='summary' or @id='tags']"))
        report = self.run_export(self.args("csdn"))
        tree = html.fromstring(Path(report["html"]).read_text(encoding="utf-8"))
        self.assertEqual(len(tree.xpath("//button[starts-with(@id,'copy-')]")), 3)
        self.assertFalse(tree.xpath("//*[@id='tags' or @id='copy-tags']"))

    def test_docx_scripts_and_image_order(self):
        report = self.run_export(self.args("zhihu"))
        with ZipFile(report["docx"]) as archive:
            xml = etree.fromstring(archive.read("word/document.xml"))
            ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
            self.assertEqual(xml.xpath(
                "//w:r[w:rPr/w:vertAlign[@w:val='superscript']]/w:t/text()",
                namespaces=ns), ["2"])
            self.assertEqual(xml.xpath(
                "//w:r[w:rPr/w:vertAlign[@w:val='subscript']]/w:t/text()",
                namespaces=ns), ["2"])
        with self.assertRaises(AssertionError):
            texts = xml.xpath("//w:t/text()", namespaces=ns)
            module.verify_docx(
                Path(report["docx"]),
                [self.root / "02-detail.png", self.root / "00-cover.png"], texts)

    def test_centered_captions_preserve_text_and_body_emphasis(self):
        self.source.write_text(
            "# 标题\n\n![封面](00-cover.png)\n\n*封面说明*\n\n"
            "*正文强调仍为斜体*\n\n![细节](02-detail.png)\n\n"
            "图1 内部结构与连接关系\n", encoding="utf-8")
        for platform in ("wechat", "csdn"):
            report = self.run_export(self.args(platform))
            tree = html.fromstring(Path(report["html"]).read_text(encoding="utf-8"))
            article = tree.get_element_by_id("article")
            self.assertTrue(report["text_verified"])
            for image in article.xpath(".//img"):
                self.assertIn("width:85%", image.get("style"))
            for image in article.xpath(".//p[img]"):
                caption = image.getnext()
                self.assertIn("text-align:center", caption.get("style"))
                self.assertIn("font-size:14px", caption.get("style"))
                self.assertFalse(caption.xpath(".//em"))
            self.assertEqual(article.xpath(".//em/text()"), ["正文强调仍为斜体"])
            self.assertIn("@media(max-width:600px){#article img{width:100%!important}}",
                          Path(report["html"]).read_text(encoding="utf-8"))
            qa_dir = os.environ.get("SANBAO_QA_DIR")
            if qa_dir:
                saved = Path(qa_dir) / (platform + "-captions.html")
                saved.parent.mkdir(parents=True, exist_ok=True)
                if saved.exists():
                    raise FileExistsError("QA fixture destination must be fresh")
                shutil.copy2(report["html"], saved)

    def test_docx_images_fit_content_width_and_keep_captions(self):
        self.source.write_text(
            "# 标题\n\n![细节](02-detail.png)\n\n图1 内部结构与连接关系\n",
            encoding="utf-8")
        report = self.run_export(self.args("zhihu"))
        doc = module.Document(report["docx"])
        section = doc.sections[0]
        content_width = section.page_width - section.left_margin - section.right_margin
        self.assertAlmostEqual(doc.inline_shapes[0].width / content_width, 0.85, places=4)
        self.assertAlmostEqual(doc.inline_shapes[0].width / doc.inline_shapes[0].height, 4 / 3, places=4)
        image = next(p for p in doc.paragraphs if p._p.xpath(".//wp:inline"))
        self.assertEqual(image.alignment, module.WD_ALIGN_PARAGRAPH.CENTER)
        self.assertTrue(image.paragraph_format.keep_with_next)
        caption = next(p for p in doc.paragraphs if p.text.startswith("图1 "))
        self.assertEqual(caption.alignment, module.WD_ALIGN_PARAGRAPH.CENTER)
        self.assertFalse(caption.runs[0].italic)
        self.assertEqual(caption.runs[0].font.size.pt, 10)

    def test_unsupported_formula_fails_before_export(self):
        self.source.write_text("# 数学\n\n$$E=mc^2$$\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "LaTeX"):
            self.run_export(self.args())
        self.assertFalse((self.root / "publish").exists())

    def test_layout_html_fails_before_export(self):
        self.source.write_text("# 标题\n\n<div>布局</div>\n", encoding="utf-8")
        with self.assertRaises(ValueError):
            self.run_export(self.args())
        self.assertFalse((self.root / "publish").exists())

    def test_html_embeds_webp_without_docx_picture_conversion(self):
        Image.new("RGB", (320, 240), "green").save(self.root / "detail.webp")
        self.source.write_text("# 主题\n\n![图](detail.webp)\n", encoding="utf-8")
        report = self.run_export(self.args())
        self.assertIn("data:image/webp;base64,", Path(report["html"]).read_text(encoding="utf-8"))

    def test_docx_accepts_webp_with_verified_lossless_png_embedding(self):
        import hashlib
        import io
        original = self.root / "detail.webp"
        Image.new("RGBA", (320, 240), (20, 130, 90, 150)).save(original, lossless=True)
        source_bytes = original.read_bytes()
        self.source.write_text("# 主题\n\n![图](detail.webp)\n", encoding="utf-8")
        report = self.run_export(self.args("zhihu"))
        self.assertTrue(report["text_verified"])
        self.assertEqual(original.read_bytes(), source_bytes)
        self.assertEqual(report["image_conversions"][0]["source_sha256"],
                         hashlib.sha256(source_bytes).hexdigest())
        self.assertTrue(report["image_conversions"][0]["rgba_pixels_verified"])
        with ZipFile(report["docx"]) as archive:
            media = [n for n in archive.namelist() if n.startswith("word/media/")]
            self.assertEqual(len(media), 1)
            self.assertTrue(media[0].endswith(".png"))
            embedded = archive.read(media[0])
            with Image.open(io.BytesIO(archive.read(media[0]))) as actual, Image.open(original) as expected:
                self.assertEqual(actual.size, expected.size)
                self.assertEqual(actual.convert("RGBA").tobytes(), expected.convert("RGBA").tobytes())
        from verify_task import embedded_images_match
        self.assertTrue(embedded_images_match([embedded], [original], Path(report["docx"]), report))
        modified = Image.new("RGBA", (320, 240), (21, 130, 90, 150))
        stream = io.BytesIO()
        modified.save(stream, format="PNG")
        changed = stream.getvalue()
        report["image_conversions"][0]["embedded_sha256"] = hashlib.sha256(changed).hexdigest()
        self.assertFalse(embedded_images_match([changed], [original], Path(report["docx"]), report))

    def test_variant_directory_validation(self):
        args = self.args()
        args.output_dir = str(self.root / "incorrect")
        with self.assertRaisesRegex(ValueError, "directory"):
            self.run_export(args)
        self.assertFalse(Path(args.output_dir).exists())

    def test_existing_export_requires_explicit_replace(self):
        args = self.args()
        report = self.run_export(args)
        with self.assertRaises(FileExistsError):
            self.run_export(args)
        args.replace = True
        again = self.run_export(args)
        self.assertEqual(report["html"], again["html"])


if __name__ == "__main__":
    unittest.main()
