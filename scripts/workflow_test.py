import itertools
import json
from pathlib import Path
import tempfile
import unittest

from task_paths import create_task
from task_state import gates, load, update
from validate_parameters import validate
from task_parameters import render
from workflow_switches import resolve, table_rows


ROOT = Path(__file__).resolve().parent.parent
TEMPLATE = render(config_path=ROOT / "config/extend.example.md")


def parameter_document(start=4, overrides=None):
    answers = {
        "课程输入材料": "已读取本地测试.md", "任务名称": "本地测试", "专业领域": "2",
        "本次任务起点": str(start), "预设 `preset`": "1", "图片类型 `type`": "8",
        "图片密度 `density`": "1", "图片风格 `style`": "24", "配色 `palette`": "6",
        "图中文字语言 `language`": "1", "图片比例 `aspect_ratio`": "5",
        "参考图 `references`": "1", "水印开关 `watermark.enabled`": "2",
        "模型 `model`": "1", "清晰度 `resolution`": "1", "质量 `quality`": "3",
        "背景 `background`": "1", "输出格式 `output_format`": "2",
        "每图变体数 `variants_per_image`": "1", "批量大小 `generation_batch_size`": "1",
        "图片信息展示 `show_info`": "2", "数量或预算约束 `limit`": "1",
        "图片保存方式 `output_dir`": "1", "讲义处理 `article_action`": "1",
    }
    answers.update(overrides or {})
    result = []
    for line in TEMPLATE.splitlines():
        if line.startswith("|"):
            cells = line.split("|")
            if cells[1].strip() in answers:
                cells[4] = " " + answers[cells[1].strip()] + " "
            line = "|".join(cells)
        result.append(line)
    return "\n".join(result)


def historical_document(start=4, choice="1", overrides=None):
    """Fixture for saved versioned tasks, not a new user-facing parameter."""
    text = parameter_document(start, overrides).replace("parameter_schema_version: 3",
                                                       "parameter_schema_version: 2")
    text = text.replace("longform_schema_version: 2", "")
    text = text.replace("# 技能输入参数设置", "# 历史任务参数")
    return text + (
        "\n| 长平台篇幅组合 | 用户可选 | 1.三档全部输出（流程默认） | "
        + choice + " | 历史任务篇幅组合 |\n")


def historical_paths(state):
    from task_paths import LONGFORM_VARIANTS, PLATFORMS
    for key in ("zhihu", "wechat", "csdn"):
        label, extension = PLATFORMS[key]
        state["paths"]["publish"][key] = {
            variant: f"publish/{label}/{variant}/{state['task_name']}_{label}_publish.{extension}"
            for variant in LONGFORM_VARIANTS}
    state.pop("longform_schema_version", None)
    return state


class WorkflowTests(unittest.TestCase):
    def test_image_gen_choice_defaults_and_rejects_nonbinary_answers(self):
        for answer, expected in (("", 1), ("1", 1), ("0", 0)):
            text = parameter_document(overrides={"是否使用 image-gen": answer})
            result = validate(text)
            self.assertTrue(result["valid"], result["errors"])
            self.assertEqual(result["route"]["use_image_gen"]["value"], expected)
            self.assertEqual(result["route"]["stages"]["call_image_gen"], bool(expected))
            self.assertTrue(result["route"]["stages"]["inspect_and_correct_images"])
        historical = "\n".join(line for line in parameter_document().splitlines()
                               if not line.startswith("| 是否使用 image-gen |"))
        self.assertTrue(validate(historical)["valid"])
        self.assertEqual(validate(historical)["route"]["use_image_gen"]["value"], 1)
        for answer in ("2", "false", "-1"):
            self.assertFalse(validate(parameter_document(overrides={
                "是否使用 image-gen": answer}))["valid"])

    def test_opt_out_preserves_design_checks_without_provider_requirements(self):
        from effective_image_config import build
        from validate_parameters import IMAGE_GEN_FIELDS, key_for
        text = parameter_document(overrides={"是否使用 image-gen": "0",
            "是否需要配图方案审核": "1", "是否需要图片审核": "1"})
        text = "\n".join(line for line in text.splitlines()
                         if not line.startswith("|") or key_for(line.split("|")[1].strip())
                         not in IMAGE_GEN_FIELDS)
        result = validate(text)
        self.assertTrue(result["valid"], result["errors"])
        self.assertNotIn("model", result["effective_parameters"])
        self.assertEqual(result["effective_parameters"]["style"], "blueprint")
        for key in ("generate_images", "inspect_and_correct_images",
                    "user_plan_review_required", "user_image_review_required"):
            self.assertTrue(result["route"]["stages"][key])
        self.assertFalse(result["route"]["stages"]["call_image_gen"])
        with self.assertRaisesRegex(ValueError, "disabled"):
            build(result)
        bad = text.replace("| 图片风格 `style` | 用户选填 |", "| 图片风格 `style` | 用户必填 |")
        bad = bad.replace("| 24 |", "| 999 |")
        self.assertFalse(validate(bad)["valid"])

    def test_opt_out_does_not_impose_image_gen_reference_limits(self):
        with tempfile.TemporaryDirectory() as folder:
            image = Path(folder) / "reference.png"
            image.write_bytes(b"reference fixture")
            overrides = {"是否使用 image-gen": "0", "参考图 `references`": "2",
                         "参考图用途 `reference_usage`": "2", "每图变体数 `variants_per_image`": "2"}
            supplements = {"references": [str(image)] * 17}
            result = validate(parameter_document(overrides=overrides), supplements)
            self.assertTrue(result["valid"], result["errors"])
            overrides["是否使用 image-gen"] = "1"
            self.assertFalse(validate(parameter_document(overrides=overrides), supplements)["valid"])

    def test_opt_out_ignores_provider_only_supplement_constraints(self):
        for compression in (101, "external-codec-setting"):
            result = validate(parameter_document(overrides={"是否使用 image-gen": "0"}),
                              {"output_compression": compression})
            self.assertTrue(result["valid"], result["errors"])
            self.assertNotIn("output_compression", result["effective_parameters"])
            enabled = validate(parameter_document(), {"output_compression": compression})
            self.assertFalse(enabled["valid"])

    def test_existing_images_and_non_generation_scopes_never_call_image_gen(self):
        for scope, point in (("content", 1), ("plan", 1), ("publish", 5), ("full", 5)):
            result = validate(parameter_document(point), scope=scope)
            self.assertTrue(result["valid"], result["errors"])
            self.assertFalse(result["route"]["stages"]["call_image_gen"])

    def test_optional_start_uses_one_without_explicit_default_acceptance(self):
        text = parameter_document(overrides={"本次任务起点": ""})
        self.assertEqual(resolve(text)["starting_point"], 1)
        result = validate(text)
        self.assertTrue(result["valid"], result["errors"])
        self.assertEqual(result["parameters"]["本次任务起点"]["number"], 1)
        self.assertEqual(result["sources"]["本次任务起点"], "任务默认快照")

    def test_blank_legacy_start_without_snapshot_uses_one(self):
        text = parameter_document(overrides={"本次任务起点": ""}).replace(
            "| 本次任务起点 | 用户选填 | 1.原始内容 |",
            "| 本次任务起点 | 用户必填 | |")
        result = validate(text)
        self.assertTrue(result["valid"], result["errors"])
        self.assertEqual(result["route"]["starting_point"], 1)
        self.assertEqual(result["parameters"]["本次任务起点"]["number"], 1)

    def test_optional_start_preserves_snapshot_and_explicit_choice(self):
        text = parameter_document(overrides={"本次任务起点": ""}).replace(
            "1.原始内容 |", "4.生图（任务默认） |")
        self.assertEqual(resolve(text)["starting_point"], 4)
        self.assertEqual(validate(text)["parameters"]["本次任务起点"]["number"], 4)
        self.assertEqual(resolve(parameter_document(5))["starting_point"], 5)
        for invalid in ("0", "6", "abc"):
            self.assertFalse(validate(parameter_document(overrides={"本次任务起点": invalid}))["valid"])

    def test_blank_historical_schema_still_requires_migration(self):
        text = parameter_document(overrides={"本次任务起点": ""}).replace(
            "5. 正文插图+发布内容生成", "5. 通用续接")
        with self.assertRaisesRegex(ValueError, "schema"):
            resolve(text)

    def test_all_routes_and_independent_review_gates(self):
        for start, plan, image, bits in itertools.product(range(1, 6), (0, 1), (0, 1),
                                                         itertools.product((0, 1), repeat=5)):
            overrides = {"是否需要配图方案审核": str(plan), "是否需要图片审核": str(image)}
            overrides.update({"是否输出" + p: str(b) for p, b in zip(
                ("CSDN", "抖音", "微信公众号", "小红书", "知乎"), bits)})
            route = resolve(parameter_document(start, overrides))
            self.assertEqual(route["stages"]["generate_images"], start < 5)
            self.assertTrue(route["stages"]["inspect_and_correct_images"])
            self.assertEqual(route["stages"]["user_plan_review_required"], start < 5 and plan == 1)
            self.assertEqual(route["stages"]["user_image_review_required"], image == 1)
            self.assertEqual(len(route["selected_platforms"]), sum(bits))

    def test_task_snapshot_is_preserved_but_explicit_change_wins(self):
        text = parameter_document().replace(
            "| 是否需要图片审核 | 用户选填 | 0.不需要", "| 是否需要图片审核 | 用户选填 | 1.需要")
        self.assertEqual(resolve(text)["image_review"]["value"], 1)
        text = text.replace("| 1.需要 | |", "| 1.需要 | 0 |")
        self.assertEqual(resolve(text)["image_review"]["value"], 0)

    def test_legacy_semantics_are_not_reinterpreted_as_new_point_five(self):
        text = parameter_document(5).replace("5. 正文插图+发布内容生成", "5. 通用续接")
        with self.assertRaisesRegex(ValueError, "schema"):
            resolve(text)

    def test_full_valid_parameters_and_preset_expansion(self):
        result = validate(parameter_document())
        self.assertTrue(result["valid"], result["errors"])
        self.assertEqual(result["effective_parameters"]["style"], "blueprint")
        self.assertEqual(result["route"]["longform"]["variants"], [None])

    def test_errors_are_aggregated_and_do_not_pass_invalid_inputs(self):
        result = validate(parameter_document(overrides={
            "质量 `quality`": "999", "参考图 `references`": "2",
            "任务名称": "CON", "背景 `background`": "4", "输出格式 `output_format`": "3",
        }))
        self.assertFalse(result["valid"])
        self.assertGreaterEqual(len(result["errors"]), 5)

    def test_optional_defaults_do_not_count_as_explicit_answers(self):
        text = parameter_document(overrides={"质量 `quality`": ""})
        result = validate(text)
        self.assertTrue(result["valid"], result["errors"])
        self.assertEqual(result["parameters"]["quality"]["number"], 3)
        self.assertEqual(result["sources"]["quality"], "任务默认快照")
        row = table_rows(text)["质量 `quality`"]
        original = "|".join(row)
        row[3] = " "
        missing = text.replace(original, "|".join(row))
        self.assertFalse(validate(missing)["valid"])

    def test_stage_five_skips_missing_image_generation_choices(self):
        text = parameter_document(5, {name: "" for name in table_rows(TEMPLATE) if "`" in name})
        self.assertTrue(validate(text, scope="publish")["valid"])
        self.assertFalse(validate(text)["route"]["stages"]["generate_images"])

    def test_legacy_single_article_does_not_expand_to_three(self):
        text = "\n".join(line for line in parameter_document().splitlines()
                         if not line.startswith("| 长平台篇幅组合 |"))
        self.assertEqual(resolve(text)["longform"]["variants"], [None])

    def test_content_output_has_independent_switch_and_legacy_scope(self):
        text = parameter_document(5)
        result = validate(text, scope="publish")
        self.assertTrue(result["route"]["outputs"]["content"]["value"])
        self.assertIn("content", result["route"]["selected_outputs"])
        off = validate(parameter_document(5, {"是否输出content": "0"}), scope="publish")
        self.assertEqual(off["route"]["selected_platforms"], result["route"]["selected_platforms"])
        self.assertNotIn("content", off["route"]["selected_outputs"])
        legacy = "\n".join(line for line in text.splitlines()
                           if not line.startswith("| 是否输出content |"))
        old = validate(legacy, scope="publish")
        self.assertTrue(old["valid"], old["errors"])
        self.assertEqual(old["route"]["outputs"]["content"]["value"], 0)

    def test_scope_stops_before_unrequested_work(self):
        for scope in ("content", "plan", "images", "publish"):
            result = validate(parameter_document(5 if scope == "publish" else 1), scope=scope)
            self.assertTrue(result["valid"], result["errors"])
            self.assertEqual(result["route"]["stages"]["generate_images"], scope == "images")
            self.assertEqual(result["route"]["stages"]["assemble_final_content"], scope == "publish")
            if scope != "publish":
                self.assertFalse(result["route"]["selected_platforms"])

    def test_custom_variants_resolve_to_actual_version_lists(self):
        result = validate(historical_document(choice="5"), {
            "longform_variants": ["精读版", "深度版"],
            "longform_by_platform": {"知乎": ["深度版"]}})
        self.assertTrue(result["valid"], result["errors"])
        self.assertEqual(result["route"]["longform"]["variants"], ["精读版", "深度版"])
        self.assertEqual(result["route"]["longform"]["by_platform"]["知乎"], ["深度版"])

    def test_task_identity_and_confirmation_are_bound_to_current_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            task = create_task("测试", tmp, "Asia/Shanghai")
            state_path = Path(task["task_directory"]) / "_work/task.json"
            self.assertTrue(task["task_id"])
            self.assertIsInstance(task["paths"]["publish"]["zhihu"], str)
            parameters = validate(parameter_document(5, {"是否需要图片审核": "1"}), scope="publish")
            update(state_path, "parameters", parameters)
            image = Path(task["task_directory"]) / "image.png"
            image.write_bytes(b"fixture-original")
            self.assertFalse(gates(load(state_path), image_files=[image])["can_assemble"])
            update(state_path, "image-check", {
                "files": [str(image)], "checks": dict.fromkeys(
                    ("text", "professional", "composition", "content_mapping"), True),
                "notes": "Only local state logic test; no visual claim",
            })
            self.assertFalse(gates(load(state_path), image_files=[image])["can_assemble"])
            update(state_path, "image-confirm", {"files": [str(image)],
                   "explicit_user_confirmation": True, "source": "isolated test fixture"})
            self.assertTrue(gates(load(state_path), image_files=[image])["can_assemble"])
            revised = validate(parameter_document(5, {
                "是否需要图片审核": "1", "长平台篇幅组合": "2",
                "是否输出知乎": "0"}), scope="publish")
            self.assertTrue(revised["valid"], revised["errors"])
            update(state_path, "parameters", revised)
            self.assertTrue(gates(load(state_path), image_files=[image])["can_assemble"])
            image.write_bytes(b"fixture-changed")
            self.assertFalse(gates(load(state_path), image_files=[image])["can_assemble"])

    def test_user_confirmation_cannot_override_failed_self_check(self):
        with tempfile.TemporaryDirectory() as tmp:
            task = create_task("测试", tmp, "Asia/Shanghai")
            state_path = Path(task["task_directory"]) / "_work/task.json"
            image = Path(task["task_directory"]) / "image.png"
            image.write_bytes(b"fixture")
            with self.assertRaisesRegex(ValueError, "passing current"):
                update(state_path, "image-confirm", {"files": [str(image)],
                       "explicit_user_confirmation": True, "source": "test"})


if __name__ == "__main__":
    unittest.main()
