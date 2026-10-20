import argparse
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from zipfile import ZipFile

from lxml import etree
from PIL import Image
from pypdf import PdfReader

from task_paths import content_paths, create_task
from task_state import file_evidence, load, update
from validate_parameters import validate
from verify_task import expected_files, verify
from workflow_test import parameter_document


spec = importlib.util.spec_from_file_location(
    "content_documents", Path(__file__).with_name("export-content-documents.py"))
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class ContentExportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        state = create_task("本地测试", self.temp.name, "Asia/Shanghai")
        self.root = Path(state["task_directory"])
        self.state_path = self.root / "_work/task.json"
        self.parameters = self.root / state["paths"]["parameters"]
        self.set_parameters()
        self.images = self.root / "imgs"
        self.images.mkdir()
        Image.new("RGB", (640, 480), "#448899").save(self.images / "01-structure.png")
        Image.new("RGBA", (400, 300), (200, 120, 80, 170)).save(self.images / "02-detail.webp", lossless=True)
        self.source = self.root / state["paths"]["illustrated"]
        self.source.write_text(
            "# 完整配图正文\n\n## 原理\n\n"
            "保持完整正文，能量 E=mc<sup>2</sup>，水 H<sub>2</sub>O。\n\n"
            "![结构](imgs/01-structure.png)\n\n图1 内部结构与连接关系\n\n"
            "### 判断方法\n\n先观察，再记录。[参考](https://example.com)\n\n"
            "1. 一级步骤\n   - 二级说明\n2. 核对结论\n\n"
            "| 条件 | 结果 |\n| --- | --- |\n| 正常 | 继续 |\n\n"
            "```python\nvalue = 2\n```\n\n"
            "> 保留适用条件与边界。\n\n"
            "## 原理\n\n![细节](imgs/02-detail.webp)\n\n图2 局部细节\n\n"
            "### 补充\n\n![重复引用](imgs/01-structure.png)\n\n图3 对照结构\n\n"
            + "\n\n".join(f"第{index}项说明："
                          + "完整保留知识、条件、案例与解释边界，避免为了篇幅缩写原文。" * 5
                          for index in range(1, 21)) + "\n",
            encoding="utf-8")
        update(self.state_path, "inputs", {"files": [str(self.source)]})
        update(self.state_path, "image-check", {
            "files": [str(p) for p in self.images.iterdir()],
            "checks": dict.fromkeys(("text", "professional", "composition", "content_mapping"), True),
            "notes": "Synthetic export fixture; no professional image review claim"})
        self.args = argparse.Namespace(
            source=str(self.source), task_name="本地测试", task_root=str(self.root),
            node=os.environ.get("SANBAO_NODE", "node"),
            marked=os.environ.get("SANBAO_MARKED", ""),
            playwright=os.environ.get("SANBAO_PLAYWRIGHT", ""),
            browser=os.environ.get("SANBAO_BROWSER"), replace=False)

    def set_parameters(self, content="1"):
        overrides = {name: "0" for name in (
            "是否输出知乎", "是否输出微信公众号", "是否输出CSDN", "是否输出抖音", "是否输出小红书")}
        overrides["是否输出content"] = content
        self.parameters.write_text(parameter_document(5, overrides), encoding="utf-8")
        result = validate(self.parameters.read_text(encoding="utf-8"), scope="publish")
        self.assertTrue(result["valid"], result["errors"])
        update(self.state_path, "parameters", result)

    def run_export(self):
        with contextlib.redirect_stdout(io.StringIO()):
            return module.export(self.args)

    def test_disabled_export_creates_no_folder_and_preserves_existing(self):
        self.set_parameters("0")
        self.assertTrue(self.run_export()["skipped"])
        self.assertFalse((self.root / "publish").exists())
        existing = self.root / "publish/content/本地测试/old.html"
        existing.parent.mkdir(parents=True)
        existing.write_text("existing output", encoding="utf-8")
        self.run_export()
        self.assertEqual(existing.read_text(encoding="utf-8"), "existing output")

    def test_content_manifest_independent_of_platform_versions(self):
        state = load(self.state_path)
        expected = expected_files(state)
        self.assertEqual(set(expected), {
            state["paths"]["parameters"], state["paths"]["illustrated"],
            *content_paths("本地测试").values()})
        self.assertFalse(state["parameters"]["route"]["all_outputs_disabled"])
        self.assertEqual(state["parameters"]["route"]["selected_platforms"], [])
        self.set_parameters("0")
        self.assertEqual(len(expected_files(load(self.state_path))), 2)

    def test_source_path_must_match_illustrated_document(self):
        self.args.source = str(self.parameters)
        with self.assertRaisesRegex(ValueError, "illustrated Markdown"):
            self.run_export()
        self.assertFalse((self.root / "publish").exists())

    def test_missing_content_blocks_task_completion(self):
        report = verify(self.state_path)
        self.assertFalse(report["passed"])
        for extension in ("html", "epub", "pdf"):
            self.assertTrue(any("本地测试." + extension in error for error in report["errors"]))

    def test_prepared_copy_requires_exact_reviewed_transformations(self):
        prepared = self.root / "_work/prepared.md"
        proof = self.root / "_work/transformations.json"
        original = self.source.read_text(encoding="utf-8")
        before, after = "E=mc<sup>2</sup>", "E = mc<sup>2</sup>"
        prepared.write_text(original.replace(before, after), encoding="utf-8")
        proof.write_text(json.dumps({
            "source_sha256": module.digest(self.source), "reviewed": True,
            "replacements": [{"before": before, "after": after, "count": 1}],
        }), encoding="utf-8")
        module.verify_prepared_source(self.source, prepared, proof)
        prepared.write_text(prepared.read_text(encoding="utf-8") + "unreviewed prose", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "outside reviewed"):
            module.verify_prepared_source(self.source, prepared, proof)

    def test_three_formats_navigation_images_and_completion(self):
        if not Path(self.args.marked).is_file() or not Path(self.args.playwright).is_file():
            self.skipTest("Set SANBAO_MARKED and SANBAO_PLAYWRIGHT for real three-format export")
        before = file_evidence([self.source, *self.images.iterdir()])
        record = self.run_export()
        outputs = {extension: Path(path) for extension, path in record["outputs"].items()}
        self.assertTrue(record["text_verified"])
        self.assertEqual(set(outputs), {"html", "epub", "pdf"})
        self.assertTrue(all(path.name == f"本地测试.{extension}" for extension, path in outputs.items()))
        self.assertEqual(record["headings"][0]["text"], "本地测试")
        self.assertIn("1.1 判断方法", [heading["text"] for heading in record["headings"]])
        self.assertIn("2.1 补充", [heading["text"] for heading in record["headings"]])
        self.assertEqual(before, file_evidence([self.source, *self.images.iterdir()]))
        self.assertEqual(len({h["id"] for h in record["headings"]}), len(record["headings"]))
        self.assertEqual([h["text"] for h in record["headings"] if h["text"].endswith("原理")],
                         ["1 原理", "2 原理"])
        self.assertEqual(record["image_occurrences"], 3)
        self.assertTrue(record["epub_conversions"][0]["pixels_verified"])
        with ZipFile(outputs["epub"]) as archive:
            content = etree.fromstring(archive.read("EPUB/content.xhtml"))
            self.assertTrue(content.xpath("//*[local-name()='sup']"))
            self.assertTrue(content.xpath("//*[local-name()='sub']"))
            self.assertEqual(len([name for name in archive.namelist() if name.startswith("EPUB/images/")]), 2)
        self.assertTrue(PdfReader(outputs["pdf"]).outline)
        with self.assertRaises(FileExistsError):
            self.run_export()
        qa = self.root / "_work/qa/content-check.json"
        qa.parent.mkdir()
        qa.write_text(json.dumps({"synthetic_fixture": True, "structural_checks": True}), encoding="utf-8")
        for stage, files in (
            ("image_checks", [qa]), ("illustrated", [self.source]),
            ("publish", [*outputs.values(), self.root / "_work/export/content.json", self.source, qa]),
        ):
            update(self.state_path, "stage", {"stage": stage, "status": "passed", "evidence": file_evidence(files)})
        report = verify(self.state_path)
        self.assertTrue(report["passed"], report["errors"])
        saved = os.environ.get("SANBAO_CONTENT_QA_DIR")
        if saved:
            shutil.copytree(self.root, Path(saved), dirs_exist_ok=False)
        outputs["html"].write_text("tampered", encoding="utf-8")
        self.assertFalse(verify(self.state_path)["passed"])


if __name__ == "__main__":
    unittest.main()
