import copy
import argparse
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile
import base64
import http.server
import os
import shutil
import subprocess
import threading

from effective_image_config import build
from markdown_contract import measure, parse, runtime_paths
from package_skill import package_skill
from review_material import signals
from runtime_preflight import inspect_runtime
from task_state import digest, file_evidence, gates, load, save, update
from validate_image_plan import validate as validate_plan
from validate_parameters import validate
from verify_task import verify
import verify_task_test
from workflow_test import historical_document, historical_paths, parameter_document


class OptimizationTests(unittest.TestCase):
    def test_task_snapshot_handoff_to_external_image_gen(self):
        backend = Path(__file__).resolve().parents[2] / "image-gen" / "scripts"
        node = shutil.which("node")
        if not node or not (backend / "gpt-image2.mjs").is_file():
            self.skipTest("Separate image-gen checkout and Node are needed for integration testing")
        requests = []
        png = base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAIAAAACCAIAAAD91JpzAAAAEklEQVR4nGOUm1bBwMDAxAAGAA3gATBe/P02AAAAAElFTkSuQmCC")

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_POST(self):
                requests.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
                payload = json.dumps({"data": [{"b64_json": base64.b64encode(png).decode()}]}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(payload)

            def log_message(self, *args):
                pass

        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with tempfile.TemporaryDirectory() as folder:
                root = Path(folder)
                runtime = root / "external-skill"
                runtime.mkdir()
                for name in ("gpt-image2.mjs", "request-controls.mjs", "info-summary.mjs", "image-info.mjs",
                             "model-capabilities.mjs", "gpt-image.mjs", "banana-image.mjs"):
                    shutil.copyfile(backend / name, runtime / name)
                snapshot = root / "execution.json"
                settings = validate(parameter_document(4))
                self.assertTrue(settings["valid"], settings["errors"])
                snapshot.write_text(json.dumps(build(settings)), encoding="utf-8")
                env = {k: v for k, v in os.environ.items() if not k.startswith("GPT_IMAGE2_")}
                env.update(GPT_IMAGE2_BASE_URL=f"http://127.0.0.1:{server.server_port}",
                           GPT_IMAGE2_API_KEY="isolated-handoff-key", GPT_IMAGE2_MODEL="invalid-default",
                           GPT_IMAGE2_BACKGROUND="transparent", GPT_IMAGE2_SHOW_INFO="true")
                completed = subprocess.run(
                    [node, str(runtime / "gpt-image2.mjs"), "--execution-config", str(snapshot),
                     "--prompt", "CONTENT isolated integration fixture", "--out-dir", str(root / "imgs")],
                    cwd=root, env=env, capture_output=True, text=True, encoding="utf-8", timeout=20)
                self.assertEqual(completed.returncode, 0, completed.stderr)
                result = json.loads(next(line[9:] for line in completed.stdout.splitlines()
                                         if line.startswith("result = ")))
                self.assertEqual(result["status"], "success")
                self.assertEqual(Path(result["images"][0]["path"]).read_bytes(), png)
                self.assertEqual(len(requests), 1)
                self.assertEqual(requests[0]["model"], settings["effective_parameters"]["model"])
                self.assertEqual(requests[0]["quality"], settings["effective_parameters"]["quality"])
                self.assertNotIn("background", requests[0])
                self.assertNotIn("info_summary", result)
                self.assertNotIn("isolated-handoff-key", completed.stdout + completed.stderr)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    def test_chinese_numbers_retain_source_offsets_and_conditions(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "input.txt"
            text = "静置一秒、十秒、三十秒、六十秒。\n百分之八十，三十摄氏度；电压3.2V，采样100ms。"
            source.write_text(text, encoding="utf-8")
            result = signals(source)
            self.assertEqual([s["raw"] for s in result["signals"]],
                             ["一秒", "十秒", "三十秒", "六十秒", "百分之八十", "三十摄氏度", "3.2V", "100ms"])
            for signal in result["signals"]:
                self.assertEqual(text[signal["start"]:signal["end"]], signal["raw"])
            self.assertEqual(result["signals"][-1]["line"], 2)
            self.assertIn("静置", result["signals"][0]["context"])

    def test_ast_count_excludes_captions_code_formula_and_references(self):
        with tempfile.TemporaryDirectory() as folder:
            draft = Path(folder) / "draft.md"
            draft.write_text("# Heading\n\n变量 x=1 表示状态。\n\n![图](x.png)\n\n"
                             "图1 示意\n\n`y = x + 1`\n\n```python\nx = 1\n```\n\n"
                             "## 参考文献\n\n不计此内容\n", encoding="utf-8")
            result = measure(parse(draft), "精读版")
            self.assertEqual(result["body_characters"], len("变量x=1表示状态。"))
            self.assertEqual(result["code_characters"], len("x=1"))
            self.assertGreater(result["formula_characters"], 0)
            self.assertTrue(result["within_target"])
            self.assertIsNone(result["target"])

    def test_execution_snapshot_clears_service_defaults_and_preserves_choices(self):
        result = validate(parameter_document(1), scope="full")
        self.assertTrue(result["valid"], result["errors"])
        snapshot = build(result)
        self.assertEqual(snapshot["request_defaults"]["GPT_IMAGE2_BACKGROUND"], "")
        self.assertEqual(snapshot["request_defaults"]["GPT_IMAGE2_N"], 1)
        self.assertEqual(snapshot["scheduling"]["batch_size"], 1)
        self.assertNotIn("GPT_IMAGE2_API_KEY", snapshot["request_defaults"])
        with self.assertRaises(ValueError):
            build({"valid": False})

    def test_moderation_description_does_not_become_api_value(self):
        name = "内容审核模式 `moderation`"
        for choice, expected in (("1", ""), ("2", "auto"), ("3", "low")):
            with self.subTest(choice=choice):
                result = validate(parameter_document(1, {name: choice}))
                self.assertTrue(result["valid"], result["errors"])
                self.assertEqual(
                    build(result)["request_defaults"]["GPT_IMAGE2_MODERATION"], expected)

    def test_per_image_ratio_requires_plan_and_cannot_override_fixed_ratio(self):
        result = validate(parameter_document(1, {"图片比例 `aspect_ratio`": "1"}))
        self.assertTrue(result["valid"], result["errors"])
        with self.assertRaisesRegex(ValueError, "approved plan"):
            build(result)
        self.assertEqual(build(result, "4:3")["request_defaults"]["GPT_IMAGE2_ASPECT_RATIO"], "4:3")
        fixed = validate(parameter_document(1))
        ratio = fixed["effective_parameters"]["aspect_ratio"]
        different = "9:16" if ratio != "9:16" else "4:3"
        with self.assertRaisesRegex(ValueError, "contradicts"):
            build(fixed, different)

    def test_v2_graph_binds_sources_prompts_and_rejects_wrong_direction(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "_work").mkdir()
            prompt = root / "prompt.md"
            prompt.write_text("SOC", encoding="utf-8")
            binding = {}
            for key in ("content", "review", "parameters"):
                source = root / (key + ".md")
                source.write_text(key, encoding="utf-8")
                binding[key] = {"path": source.name, "sha256": digest(source)}
            edge = {"from": "电流", "to": "SOC", "relation": "积分输入", "condition": "统一时间单位"}
            data = {"schema_version": 2, "binding": binding, "short_image_ids": ["00"],
                    "images": [{"image_id": "00", "prompt_path": prompt.name, "prompt_sha256": digest(prompt),
                                "allowed_labels": ["电流", "SOC"], "semantic_contract": {
                                    "nodes": ["电流", "SOC"], "edges": [edge],
                                    "forbidden_edges": [{"from": "SOC", "to": "电流",
                                                        "relation": "反向推导", "condition": ""}],
                                    "forbidden_symbols": ["接地"]}}]}
            plan = root / "_work/image-plan.json"

            def check(value):
                plan.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
                return validate_plan(plan)

            self.assertTrue(check(data)["valid"])
            bad = copy.deepcopy(data)
            bad["images"][0]["semantic_contract"]["edges"][0]["from"] = "不存在"
            self.assertFalse(check(bad)["valid"])
            bad = copy.deepcopy(data)
            bad["images"][0]["semantic_contract"]["edges"] = bad["images"][0]["semantic_contract"]["forbidden_edges"]
            self.assertFalse(check(bad)["valid"])
            (root / "content.md").write_text("changed", encoding="utf-8")
            self.assertFalse(check(data)["valid"])
            data["images"] = [None]
            self.assertFalse(check(data)["valid"])

    def test_content_refresh_invalidates_downstream_even_with_fresh_hash(self):
        with tempfile.TemporaryDirectory() as folder:
            path, root = verify_task_test.CompletionTests().short_fixture(folder)
            state = load(path)
            content = root / state["paths"]["content"]
            content.write_text("New actual content", encoding="utf-8")
            update(path, "stage", {"stage": "content", "status": "passed",
                                   "evidence": file_evidence([content])})
            state = load(path)
            self.assertEqual(state["stages"]["plan"]["status"], "pending")
            self.assertEqual(state["image_checks"], {})
            self.assertFalse(verify(path)["passed"])

    def test_current_html_text_rechecked_even_after_output_and_record_hash_refresh(self):
        with tempfile.TemporaryDirectory() as folder:
            path, root = verify_task_test.CompletionTests().short_fixture(folder)
            original = path.read_bytes()
            state = historical_paths(load(path))
            save(path, state, original)
            parameters = root / state["paths"]["parameters"]
            parameters.write_text(historical_document(1, "5", {
                "是否输出知乎": "0", "是否输出CSDN": "0", "是否输出微信公众号": "1",
                "是否输出content": "0",
                "是否需要配图方案审核": "0", "是否需要图片审核": "0"}), encoding="utf-8")
            update(path, "parameters", validate(parameters.read_text(encoding="utf-8"),
                                                {"longform_variants": ["标准版", "深度版"]}))
            state = load(path)
            variant = "标准版"
            draft = root / "_work/drafts/微信公众号" / variant / (state["task_name"] + "_微信公众号_draft.md")
            draft.parent.mkdir(parents=True)
            draft.write_text("# Old title\n\n![cover](../../../../imgs/00-cover-main.png)\n\n"
                             "## Principle\n\nActual verified current text.\n", encoding="utf-8")
            spec = importlib.util.spec_from_file_location(
                "drift_exporter", Path(__file__).with_name("export-publishing-documents.py"))
            exporter = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(exporter)
            node, marked = runtime_paths()
            output = root / state["paths"]["publish"]["wechat"][variant]
            args = argparse.Namespace(source=str(draft), task_name=state["task_name"], platform="wechat",
                                      node=node, marked=marked, variant=variant, task_root=str(root),
                                      output_dir=str(output.parent), summary="Summary", tags="#Tag", replace=False)
            with contextlib.redirect_stdout(io.StringIO()):
                exporter.export(args)
            record_path = root / "_work/export/wechat" / (variant + ".json")
            evidence = dict(state["stages"]["publish"]["evidence"])
            evidence.update(file_evidence([draft, record_path, output]))
            other_draft = root / "_work/drafts/微信公众号/深度版" / draft.name
            other_draft.parent.mkdir(parents=True)
            other_draft.write_bytes(draft.read_bytes())
            args.source, args.variant = str(other_draft), "深度版"
            other_output = root / state["paths"]["publish"]["wechat"]["深度版"]
            args.output_dir = str(other_output.parent)
            with contextlib.redirect_stdout(io.StringIO()):
                exporter.export(args)
            evidence.update(file_evidence([other_draft, other_output,
                                           root / "_work/export/wechat/深度版.json"]))
            update(path, "stage", {"stage": "publish", "status": "passed", "evidence": evidence})
            self.assertTrue(verify(path)["passed"], verify(path)["errors"])
            text = output.read_text(encoding="utf-8")
            output.write_text(text.replace("Actual verified current text.", "Silently changed conclusion."), encoding="utf-8")
            record = json.loads(record_path.read_text(encoding="utf-8"))
            record["output_sha256"] = digest(output)
            record_path.write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")
            evidence.update(file_evidence([record_path, output]))
            update(path, "stage", {"stage": "publish", "status": "passed", "evidence": evidence})
            report = verify(path)
            self.assertFalse(report["passed"])
            self.assertTrue(any("Current exported text differs" in e for e in report["errors"]), report["errors"])

    def test_preflight_reports_missing_node_without_network(self):
        with patch.dict("os.environ", {"SANBAO_NODE": "missing-sentinel-node",
                                      "SANBAO_MARKED": "missing-sentinel-marked"}), \
                patch("markdown_contract.shutil.which", return_value=None):
            report = inspect_runtime("plan")
            self.assertFalse(report["ready"])
            self.assertFalse(next(c for c in report["checks"] if c["name"] == "node/marked")["ready"])

    def test_legacy_plan_reuses_reviewed_images_but_cannot_authorize_new_generation(self):
        with tempfile.TemporaryDirectory() as folder:
            path, root = verify_task_test.CompletionTests().short_fixture(folder)
            state = load(path)
            (root / "_work/image-plan.json").write_text(
                '{"images":[{"id":"00","prompt_path":"old-format"}]}', encoding="utf-8")
            images = sorted((root / "imgs").glob("*.png"))
            result = gates(state, [root / state["paths"]["review"]], images)
            self.assertTrue(result["can_assemble"])
            self.assertFalse(result["can_generate"])
            self.assertTrue(result["generation_reasons"])
            self.assertTrue(verify(path)["passed"], verify(path)["errors"])

    def test_malformed_plan_is_rejected_without_crashing(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "plan.json"
            for value in ("[]", "{bad json", '{"schema_version":2,"images":[null]}'):
                path.write_text(value, encoding="utf-8")
                self.assertFalse(validate_plan(path)["valid"])

    def test_current_field_rules_are_bound_to_content_review(self):
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder) / "fake-skill"
            (directory / "scripts").mkdir(parents=True)
            rules = directory / "references/fields/field_battery"
            rules.mkdir(parents=True)
            for name in ("expert-teaching.md", "writing-examples.md", "illustration-guidance.md"):
                (rules / name).write_text("Original field rules", encoding="utf-8")
            with patch("task_state.__file__", str(directory / "scripts/task_state.py")):
                path, root, _ = verify_task_test.CompletionTests().fixture(folder, overrides={"专业领域": "1"})
                self.assertTrue(verify(path)["passed"])
                (rules / "expert-teaching.md").write_text("Changed field rules", encoding="utf-8")
                self.assertFalse(verify(path)["passed"])
                (rules / "expert-teaching.md").unlink()
                content = root / load(path)["paths"]["content"]
                with self.assertRaisesRegex(ValueError, "three current rule files"):
                    update(path, "stage", {"stage": "content", "status": "passed",
                                           "evidence": file_evidence([content])})

    def test_custom_scope_and_visual_supplements_invalidate_upstream_reviews(self):
        with tempfile.TemporaryDirectory() as folder:
            path, root = verify_task_test.CompletionTests().short_fixture(folder)
            parameters = copy.deepcopy(load(path)["parameters"])
            parameters["supplements"] = {"palette": "new custom palette"}
            update(path, "parameters", parameters)
            self.assertEqual(load(path)["stages"]["content"]["status"], "passed")
            self.assertEqual(load(path)["stages"]["plan"]["status"], "pending")
            parameters["supplements"]["field"] = {"main": "field_battery", "scope": "new domain scope"}
            update(path, "parameters", parameters)
            self.assertEqual(load(path)["stages"]["content"]["status"], "pending")

    def test_release_manifest_matches_every_public_file(self):
        root = Path(__file__).resolve().parent.parent
        with tempfile.TemporaryDirectory() as folder:
            output, _ = package_skill(root, Path(folder) / "skill.zip")
            with zipfile.ZipFile(output) as archive:
                manifest = json.loads(archive.read(root.name + "/release-manifest.json"))
                import hashlib
                self.assertEqual(manifest["version"],
                                 json.loads((root / "version.json").read_text(encoding="utf-8"))["version"])
                for name, expected in manifest["files"].items():
                    self.assertEqual(hashlib.sha256(archive.read(name)).hexdigest(), expected)


if __name__ == "__main__":
    unittest.main()
