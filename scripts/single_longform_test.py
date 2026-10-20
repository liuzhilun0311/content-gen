"""Regress new single-article workflows and saved versioned task compatibility."""

import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest

import export_publishing_test
from markdown_contract import measure
from review_material import review, signals
from task_state import file_evidence, load, save, update
from validate_parameters import validate
from verify_task import expected_files, verify
import verify_task_test
from workflow_test import historical_document, historical_paths, parameter_document


class SingleLongformTests(unittest.TestCase):
    def test_new_table_has_no_length_selector_or_legacy_supplements(self):
        text = parameter_document(5)
        self.assertNotIn("| 长平台篇幅组合 |", text)
        result = validate(text, scope="publish")
        self.assertTrue(result["valid"], result["errors"])
        self.assertEqual(result["route"]["longform"]["variants"], [None])
        bad = validate(text, {"longform_variants": ["标准版"]}, scope="publish")
        self.assertFalse(bad["valid"])
        self.assertFalse(validate(text + "\n| 长平台篇幅组合 | 用户可选 | 1.历史 | 1 | 历史 |\n",
                                  scope="publish")["valid"])

    def test_any_body_length_is_statistics_only_including_legacy_labels(self):
        for variant in (None, "精读版", "标准版", "深度版"):
            for size in (5, 15000):
                ast = [{"type": "paragraph", "tokens": [{"type": "text", "text": "文" * size}]}]
                result = measure(ast, variant)
                self.assertEqual(result["body_characters"], size)
                self.assertIsNone(result["target"])
                self.assertTrue(result["within_target"])
                self.assertEqual(result["length_policy"], "content_driven")

    def test_ranges_and_battery_units_preserve_source_offsets(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "source.txt"
            text = "一到三个小时，几十公里，三千公里，四十度电，3.2～4.2V，-20至60℃。"
            source.write_text(text, encoding="utf-8")
            result = signals(source)
            self.assertEqual([s["raw"] for s in result["signals"]],
                             ["一到三个小时", "几十公里", "三千公里", "四十度电", "3.2～4.2V", "-20至60℃"])
            for s in result["signals"]:
                self.assertEqual(text[s["start"]:s["end"]], s["raw"])
            draft = Path(folder) / "draft.md"
            draft.write_text("# 标题\n\n解释必要条件。\n", encoding="utf-8")
            report = review([source], draft, "深度版")
            self.assertFalse(report["length_review_required"])
            self.assertTrue(all(s["condition_review"] == "pending" for s in report["review_items"]))

    def test_saved_versioned_manifest_is_preserved(self):
        with tempfile.TemporaryDirectory() as folder:
            path, root, _ = verify_task_test.CompletionTests().fixture(folder, "full")
            original = path.read_bytes()
            save(path, historical_paths(load(path)), original)
            parameters = root / load(path)["paths"]["parameters"]
            parameters.write_text(historical_document(), encoding="utf-8")
            result = validate(parameters.read_text(encoding="utf-8"))
            self.assertTrue(result["valid"], result["errors"])
            update(path, "parameters", result)
            expected = expected_files(load(path))
            self.assertEqual(sum(p.endswith("_publish.docx") for p in expected), 3)
            self.assertEqual(sum(p.endswith("_publish.html") for p in expected), 6)

    def test_watt_hour_units_are_detected_and_changed_units_are_flagged(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "source.md"
            text = "3.2 V乘以100 Ah约为320 Wh，即0.32 kWh；另一示例为500 mWh。"
            source.write_text(text, encoding="utf-8")
            found = signals(source)["signals"]
            self.assertEqual([s["raw"] for s in found],
                             ["3.2 V", "100 Ah", "320 Wh", "0.32 kWh", "500 mWh"])
            for signal in found:
                self.assertEqual(text[signal["start"]:signal["end"]], signal["raw"])
            draft = Path(folder) / "draft.md"
            draft.write_text(text.replace("320 Wh", "320 kWh"), encoding="utf-8")
            result = review([source], draft)
            self.assertEqual(result["source_only_signals"], ["320 Wh"])
            self.assertEqual(result["draft_only_signals"], ["320 kWh"])

    def test_three_single_exports_have_separate_records_and_complete_verification(self):
        export_fixture = export_publishing_test.PublishingTests()
        export_fixture.setUp()
        self.addCleanup(export_fixture.doCleanups)
        with tempfile.TemporaryDirectory() as folder:
            path, root = verify_task_test.CompletionTests().short_fixture(folder)
            state = load(path)
            evidence = dict(state["stages"]["publish"]["evidence"])
            parameters = root / state["paths"]["parameters"]
            parameters.write_text(parameter_document(1, {
                "是否输出抖音": "0", "是否输出小红书": "0", "是否输出content": "0",
                "是否需要配图方案审核": "0", "是否需要图片审核": "0"}), encoding="utf-8")
            update(path, "parameters", validate(parameters.read_text(encoding="utf-8")))
            state = load(path)
            from export_publishing_test import module
            for key, label in (("zhihu", "知乎"), ("wechat", "微信公众号"), ("csdn", "CSDN")):
                draft = root / "_work/drafts" / label / (state["task_name"] + "_" + label + "_draft.md")
                draft.parent.mkdir(parents=True)
                draft.write_text("# 旧标题\n\n![封面](../../../imgs/00-cover-main.png)\n\n"
                                 "## 必要解释\n\n条件决定结论，不能省略单位和工况。\n", encoding="utf-8")
                output = root / state["paths"]["publish"][key]
                args = export_fixture.args(key)
                args.task_root, args.task_name = str(root), state["task_name"]
                args.source, args.output_dir = str(draft), str(output.parent)
                with contextlib.redirect_stdout(io.StringIO()):
                    module.export(args)
                record = root / "_work/export" / (key + ".json")
                data = json.loads(record.read_text(encoding="utf-8"))
                self.assertIsNone(data["variant"])
                self.assertIsNone(data["text_metrics"]["target"])
                self.assertIsNone(data["length_deviation_reason"])
                evidence.update(file_evidence([draft, output, record]))
            update(path, "stage", {"stage": "publish", "status": "passed", "evidence": evidence})
            report = verify(path)
            self.assertTrue(report["passed"], report["errors"])
            self.assertEqual(sum("_publish." in p for p in report["expected"]), 3)
            self.assertFalse(any((root / "publish").rglob("标准版")))
            output.write_text(output.read_text(encoding="utf-8").replace(
                "条件决定结论", "无条件确定结论"), encoding="utf-8")
            self.assertFalse(verify(path)["passed"])

    def test_single_export_rejects_wrong_task_directory(self):
        fixture = export_publishing_test.PublishingTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        args = fixture.args()
        args.output_dir = str(fixture.root / "wrong-platform")
        with self.assertRaisesRegex(ValueError, "Output directory"):
            fixture.run_export(args)
        self.assertFalse(Path(args.output_dir).exists())


if __name__ == "__main__":
    unittest.main()
