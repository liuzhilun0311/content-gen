from pathlib import Path
import base64
import json
import tempfile
import unittest

from task_paths import create_task
from task_state import file_evidence, load, update
from validate_parameters import validate
from verify_task import commit, expected_files, inside, verify
from workflow_test import parameter_document


class CompletionTests(unittest.TestCase):
    def fixture(self, folder, scope="content", overrides=None):
        state = create_task("本地测试", folder, "Asia/Shanghai")
        root = Path(state["task_directory"])
        path = root / "_work/task.json"
        parameters = root / state["paths"]["parameters"]
        parameters.write_text(parameter_document(1, overrides), encoding="utf-8")
        source = Path(folder) / "input.txt"
        source.write_text("Actual input", encoding="utf-8")
        update(path, "inputs", {"files": [str(source)]})
        result = validate(parameters.read_text(encoding="utf-8"), scope=scope)
        self.assertTrue(result["valid"], result["errors"])
        update(path, "parameters", result)
        content = root / state["paths"]["content"]
        content.write_text("# Actual content\n", encoding="utf-8")
        update(path, "stage", {"stage": "content", "status": "passed",
                               "evidence": file_evidence([content])})
        return path, root, source

    def test_content_only_completes_without_fabricated_images_or_platforms(self):
        with tempfile.TemporaryDirectory() as folder:
            path, root, _ = self.fixture(folder)
            report = verify(path)
            self.assertTrue(report["passed"], report["errors"])
            self.assertEqual(len(report["expected"]), 2)
            commit(path, report)
            self.assertEqual(load(path)["status"], "complete")
            self.assertFalse((root / "imgs").exists())

    def test_missing_file_prevents_completion(self):
        with tempfile.TemporaryDirectory() as folder:
            path, root, _ = self.fixture(folder)
            (root / load(path)["paths"]["content"]).unlink()
            report = verify(path)
            self.assertFalse(report["passed"])
            with self.assertRaises(ValueError):
                commit(path, report)

    def test_changed_input_and_parameters_are_detected(self):
        with tempfile.TemporaryDirectory() as folder:
            path, root, source = self.fixture(folder)
            source.write_text("Changed input", encoding="utf-8")
            parameters = root / load(path)["paths"]["parameters"]
            parameters.write_text("Changed choices", encoding="utf-8")
            report = verify(path)
            self.assertFalse(report["passed"])
            self.assertTrue(any("Input: changed" in e for e in report["errors"]))
            self.assertTrue(any("Parameters: changed" in e for e in report["errors"]))

    def test_stale_passed_evidence_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            path, root, _ = self.fixture(folder)
            content = root / load(path)["paths"]["content"]
            old = file_evidence([content])
            content.write_text("# Changed\n", encoding="utf-8")
            self.assertFalse(verify(path)["passed"])
            with self.assertRaisesRegex(ValueError, "current actual"):
                update(path, "stage", {"stage": "content", "status": "passed", "evidence": old})

    def test_single_articles_and_five_platforms_are_all_required(self):
        with tempfile.TemporaryDirectory() as folder:
            path, _, _ = self.fixture(folder, "full")
            expected = expected_files(load(path))
            self.assertEqual(sum(p.endswith("_publish.docx") for p in expected), 1)
            self.assertEqual(sum(p.endswith("_publish.html") for p in expected), 2)
            self.assertEqual(sum(p.endswith("_publish.md") for p in expected), 2)
            self.assertFalse(verify(path)["passed"])

    def test_closed_platform_and_selected_length_are_respected(self):
        with tempfile.TemporaryDirectory() as folder:
            path, _, _ = self.fixture(folder, "full", {
                "是否输出CSDN": "0", "是否输出微信公众号": "0",
                "是否输出抖音": "0", "是否输出小红书": "0"})
            expected = expected_files(load(path))
            self.assertEqual(sum("_publish." in p for p in expected), 1)
            self.assertTrue(any("publish/知乎/本地测试_知乎_publish.docx" == p for p in expected))

    def test_verified_file_change_prevents_commit(self):
        with tempfile.TemporaryDirectory() as folder:
            path, root, _ = self.fixture(folder)
            report = verify(path)
            (root / load(path)["paths"]["content"]).write_text("Changed", encoding="utf-8")
            with self.assertRaises(ValueError):
                commit(path, report)

    def test_state_update_invalidates_complete_status(self):
        with tempfile.TemporaryDirectory() as folder:
            path, _, _ = self.fixture(folder)
            commit(path, verify(path))
            update(path, "stage", {"stage": "content", "status": "running"})
            self.assertNotEqual(load(path)["status"], "complete")
            self.assertNotIn("completion", load(path))

    def test_output_path_cannot_escape_task_root(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(ValueError):
                inside(Path(folder).resolve(), "../other/result.docx")

    def short_fixture(self, folder):
        path, root, _ = self.fixture(folder, "full", {
            "是否输出CSDN": "0", "是否输出微信公众号": "0", "是否输出知乎": "0",
            "是否输出content": "0",
            "是否需要配图方案审核": "0", "是否需要图片审核": "0"})
        state = load(path)
        plan = root / state["paths"]["review"]
        plan.write_text("# Plan\n", encoding="utf-8")
        update(path, "stage", {"stage": "plan", "status": "passed", "evidence": file_evidence([plan])})
        image_dir = root / state["paths"]["images"]
        image_dir.mkdir()
        png = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aHlcAAAAASUVORK5CYII=")
        images = [image_dir / name for name in ("00-cover-main.png", "01-first.png", "03-second.png", "05-third.png")]
        for image in images:
            image.write_bytes(png)
        update(path, "image-check", {"files": [str(p) for p in images], "checks": {
            "text": True, "professional": True, "composition": True, "content_mapping": True}})
        qa = root / "_work/qa/actual-test-review.json"
        qa.parent.mkdir()
        qa.write_text(json.dumps({"fixture": True}), encoding="utf-8")
        update(path, "stage", {"stage": "image_checks", "status": "passed", "evidence": file_evidence([qa])})
        illustrated = root / state["paths"]["illustrated"]
        illustrated.write_text("# Body\n![image](imgs/00-cover-main.png)\n", encoding="utf-8")
        update(path, "stage", {"stage": "illustrated", "status": "passed", "evidence": file_evidence([illustrated])})
        outputs = []
        for key in ("douyin", "xiaohongshu"):
            output = root / state["paths"]["publish"][key]
            output.parent.mkdir(parents=True)
            output.write_text("# Title\n\n## 文案\nText\n\n## 标签\n#Tag\n", encoding="utf-8")
            outputs.append(output)
            for image in images:
                (output.parent / image.name).write_bytes(image.read_bytes())
        update(path, "stage", {"stage": "publish", "status": "passed", "evidence": file_evidence(outputs + [qa])})
        self.assertTrue(verify(path)["passed"], verify(path)["errors"])
        return path, root

    def test_one_missing_platform_is_not_complete(self):
        with tempfile.TemporaryDirectory() as folder:
            path, root = self.short_fixture(folder)
            (root / load(path)["paths"]["publish"]["douyin"]).unlink()
            self.assertFalse(verify(path)["passed"])

    def test_changed_reviewed_image_invalidates_completion(self):
        with tempfile.TemporaryDirectory() as folder:
            path, root = self.short_fixture(folder)
            (root / "imgs/01-first.png").write_bytes(b"changed")
            self.assertFalse(verify(path)["passed"])

    def test_two_short_platforms_must_share_exact_group(self):
        with tempfile.TemporaryDirectory() as folder:
            path, root = self.short_fixture(folder)
            output = root / load(path)["paths"]["publish"]["douyin"]
            (output.parent / "03-second.png").unlink()
            report = verify(path)
            self.assertFalse(report["passed"])
            self.assertIn("Two short platforms use different images", report["errors"])

    def test_content_stage_must_bind_its_actual_document(self):
        with tempfile.TemporaryDirectory() as folder:
            path, root, _ = self.fixture(folder)
            qa = root / "_work/unrelated.json"
            qa.write_text('{"fixture":true}', encoding="utf-8")
            update(path, "stage", {"stage": "content", "status": "passed",
                                   "evidence": file_evidence([qa])})
            self.assertFalse(verify(path)["passed"])

    def test_full_raw_input_requires_content_stage(self):
        with tempfile.TemporaryDirectory() as folder:
            path, root = self.short_fixture(folder)
            state = load(path)
            del state["stages"]["content"]
            path.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
            self.assertFalse(verify(path)["passed"])

    def test_short_copy_rejects_images_paths_and_production_markers(self):
        for extra in ("\n![unexpected](missing.png)", "\n素材：imgs/01.png",
                      "\n口播：按此分镜执行", "\n<img src='missing.png'>",
                      "\n[下载图片](https://example.com/a.png)"):
            with self.subTest(extra=extra), tempfile.TemporaryDirectory() as folder:
                path, root = self.short_fixture(folder)
                state = load(path)
                output = root / state["paths"]["publish"]["douyin"]
                output.write_text(output.read_text(encoding="utf-8") + extra, encoding="utf-8")
                proof = {**state["stages"]["publish"]["evidence"], **file_evidence([output])}
                update(path, "stage", {"stage": "publish", "status": "passed", "evidence": proof})
                self.assertFalse(verify(path)["passed"])

    def test_content_scope_ignores_failed_old_publishing(self):
        with tempfile.TemporaryDirectory() as folder:
            path, root = self.short_fixture(folder)
            update(path, "stage", {"stage": "publish", "status": "failed"})
            parameters = root / load(path)["paths"]["parameters"]
            result = validate(parameters.read_text(encoding="utf-8"), scope="content")
            update(path, "parameters", result)
            self.assertTrue(verify(path)["passed"], verify(path)["errors"])


if __name__ == "__main__":
    unittest.main()
