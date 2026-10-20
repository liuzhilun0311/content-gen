"""Check the reviewed template, identity resolution and filled-file retention."""

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import task_parameters
from task_parameters import render, retain
from task_state import load
from validate_parameters import TEMPLATE, validate
from workflow_switches import table_rows
from preferences import load_preferences, migrate_preferences


class TaskParameterTests(unittest.TestCase):
    def setUp(self):
        self.addCleanup(patch.stopall)
        patch.object(task_parameters, "default_preferences_path", return_value=TEMPLATE).start()

    def test_layout_and_defaults_follow_reviewed_template(self):
        text = render()
        self.assertTrue(text.startswith("# 技能输入参数设置"))
        rows = table_rows(text)
        self.assertEqual(rows["预设 `preset`"][3].strip(), "1.`tech-explainer`（技术解释）")
        self.assertTrue(all(not row[4].strip() for name, row in rows.items()
                            if name not in ("参数名称", "---")))
        self.assertNotIn("课程输入材料", rows)
        self.assertNotIn("偏好学习阈值", rows)
        self.assertNotIn("长平台输出策略", rows)
        names = list(rows)
        self.assertEqual(names[names.index("配色 `palette`") + 1], "图片密度 `density`")

    def test_configuration_lists_every_parameter_without_duplicate_defaults_or_private_task_history(self):
        from parameter_catalog import key_for, parameter_rows
        data = load_preferences(TEMPLATE)
        rows = parameter_rows(TEMPLATE.read_text(encoding="utf-8"))
        self.assertEqual({key_for(name) for name in rows}, set(data["defaults"]))
        self.assertTrue(all(not row[3].strip() and not row[4].strip() for row in rows.values()))
        with tempfile.TemporaryDirectory() as folder:
            path = self.config(Path(folder))
            original = path.read_bytes()
            task = render(config_path=path)
            self.assertNotIn('"history"', task)
            self.assertNotIn('"tracked_defaults"', task)
            self.assertNotIn("自动学习偏好", task)
            self.assertEqual(path.read_bytes(), original)

    def test_prefilled_header_and_table_match(self):
        text = render("企业交付", "field_enterprise-ai-fde")
        result = validate(text)
        self.assertTrue(result["valid"], result["errors"])
        self.assertEqual(result["effective_parameters"]["专业领域"], "field_enterprise-ai-fde")
        self.assertEqual(result["effective_parameters"]["任务名称"], "企业交付")
        self.assertEqual(result["route"]["starting_point"], 1)
        self.assertEqual(result["sources"]["preset"], "任务默认快照")

    def test_header_only_identity_and_conflicts(self):
        text = render().replace("任务名称：", "任务名称：动力电池")
        text = text.replace("专业领域：", "专业领域：动力电池")
        result = validate(text)
        self.assertTrue(result["valid"], result["errors"])
        self.assertEqual(result["sources"]["任务名称"], "页首明确填写")
        for name, answer in (("任务名称", "另一任务"), ("专业领域", "2")):
            rows = table_rows(text)
            old = "|".join(rows[name])
            rows[name][4] = answer
            bad = validate(text.replace(old, "|".join(rows[name])))
            self.assertFalse(bad["valid"])
            self.assertTrue(any("不一致" in error for error in bad["errors"]))

    def test_missing_identity_not_filled_by_defaults(self):
        for allow in (False, True):
            self.assertFalse(validate(render(), allow_defaults=allow)["valid"])

    def test_table_only_needs_no_usage_prose_or_header_markers(self):
        text = "\n".join(line for line in render("仅表格任务", "field_battery").splitlines()
                         if line.startswith("|"))
        for start in range(1, 6):
            rows = table_rows(text)
            old = "|".join(rows["本次任务起点"])
            rows["本次任务起点"][4] = str(start)
            current = text.replace(old, "|".join(rows["本次任务起点"]))
            for scope in ("full", "plan", "images", "content", "publish"):
                with self.subTest(start=start, scope=scope):
                    result = validate(current, scope=scope)
                    expected = not (scope == "content" and start not in (1, 2)
                                    or scope == "publish" and start != 5)
                    self.assertEqual(result["valid"], expected, result["errors"])
                    self.assertEqual(result["route"]["starting_point"], start)
                    self.assertEqual(result["route"]["longform"]["variants"], [None])
                    self.assertEqual(result["sources"]["任务名称"], "明确填写")
                    self.assertEqual(result["route"]["review"]["value"], 0)
                    self.assertEqual(result["route"]["image_review"]["value"], 0)

    def test_conditional_optional_default_is_not_an_explicit_answer(self):
        text = render("条件默认", "field_battery")
        rows = table_rows(text)
        for name, column, value in (
                ("输出格式 `output_format`", 4, "3"),
                ("输出压缩 `output_compression`", 3, "2.70")):
            old = "|".join(rows[name])
            rows[name][column] = value
            text = text.replace(old, "|".join(rows[name]))
        result = validate(text)
        self.assertTrue(result["valid"], result["errors"])
        self.assertEqual(result["sources"]["output_compression"], "任务默认快照")

    def test_table_only_retention_still_requires_real_material(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            filled = root / "仅参数.md"
            text = "\n".join(line for line in render("精简模板", "field_battery").splitlines()
                             if line.startswith("|"))
            filled.write_text(text, encoding="utf-8")
            with self.assertRaises(ValueError):
                retain(filled, root / "outputs")
            self.assertFalse((root / "outputs").exists())
            source = root / "正文.txt"
            source.write_text("实际材料，表格外没有任何操作说明。", encoding="utf-8")
            record = retain(filled, root / "outputs", inputs=[source])
            self.assertEqual(Path(record["parameter_file"]).read_bytes(), filled.read_bytes())
            state = load(record["state"])
            self.assertEqual(state["parameter_schema_version"], 4)
            self.assertEqual(state["starting_point_schema_version"], 2)
            self.assertEqual(state["longform_schema_version"], 2)
            self.assertIn(str(source.resolve()), state["input_snapshot"])
            self.assertEqual(state["stages"], {})

    def test_conditional_fields_cannot_be_silently_skipped(self):
        text = render("测试任务", "field_battery")
        rows = table_rows(text)
        old = "|".join(rows["水印开关 `watermark.enabled`"])
        rows["水印开关 `watermark.enabled`"][4] = "1"
        result = validate(text.replace(old, "|".join(rows["水印开关 `watermark.enabled`"])))
        self.assertFalse(result["valid"])
        self.assertTrue(any("条件满足" in error for error in result["errors"]))

    def test_dynamic_field_options_show_available_fields_only(self):
        with patch.object(task_parameters, "available_fields",
                          return_value={"field_battery": "动力电池", "field_new": "新维护领域"}):
            text = render()
        row = table_rows(text)["专业领域"][5]
        self.assertIn("field_battery", row)
        self.assertIn("field_new", row)
        self.assertNotIn("field_ai", row)
        self.assertNotIn("新增领域", row)

    def test_filled_file_retained_exactly_with_input_and_parameter_snapshots(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            filled = root / "用户填写.md"
            filled.write_text(render("留存测试", "field_battery"), encoding="utf-8-sig")
            original = filled.read_bytes()
            source = root / "原材料.txt"
            source.write_text("用于检查实际输入记录，不进行内容生成。", encoding="utf-8")
            record = retain(filled, root / "outputs", inputs=[source])
            self.assertTrue(record["byte_identical"])
            saved = Path(record["parameter_file"])
            self.assertEqual(saved.read_bytes(), original)
            self.assertEqual(saved.name, "留存测试_参数.md")
            state = load(record["state"])
            self.assertEqual(state["parameter_schema_version"], 4)
            self.assertIn(str(source.resolve()), state["input_snapshot"])
            self.assertIn(str(saved.resolve()), state["parameter_snapshot"])
            self.assertEqual(state["parameters"]["effective_parameters"]["专业领域"], "field_battery")
            self.assertEqual(state["stages"], {})
            retain(filled, state_path=record["state"])
            filled.write_text(filled.read_text(encoding="utf-8-sig") + "\n用户修改\n", encoding="utf-8")
            with self.assertRaises(FileExistsError):
                retain(filled, state_path=record["state"])
            self.assertEqual(saved.read_bytes(), original)

    def test_missing_input_or_invalid_parameters_create_no_task_directory(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            filled = root / "填写.md"
            filled.write_text(render("测试", "field_battery"), encoding="utf-8")
            with self.assertRaises(ValueError):
                retain(filled, root / "outputs")
            self.assertFalse((root / "outputs").exists())
            filled.write_text(render(), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "Parameters invalid"):
                retain(filled, root / "outputs")
            self.assertFalse((root / "outputs").exists())

    def config(self, root, changes=None):
        path = root / "extend.md"
        text = TEMPLATE.read_text(encoding="utf-8")
        start = text.index("```json\n") + len("```json\n")
        end = text.index("\n```", start)
        import json
        data = json.loads(text[start:end])
        data["defaults"].update(changes or {})
        path.write_text(text[:start] + json.dumps(data, ensure_ascii=False, indent=2) + text[end:],
                        encoding="utf-8")
        return path

    def test_all_workflow_defaults_apply_only_to_new_task_snapshots(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            path = self.config(root, {
                "本次任务起点": 5, "use_image_gen": False,
                "是否输出知乎": False, "是否输出微信公众号": False,
                "是否输出CSDN": False, "是否输出抖音": False, "是否输出小红书": False,
                "是否输出content": False, "是否需要配图方案审核": True,
                "是否需要图片审核": True})
            saved = render("配置快照", "field_battery", path)
            result = validate(saved)
            self.assertTrue(result["valid"], result["errors"])
            self.assertEqual(result["route"]["starting_point"], 5)
            self.assertFalse(result["route"]["use_image_gen"]["value"])
            self.assertEqual(result["route"]["selected_outputs"], [])
            self.assertEqual(result["route"]["image_review"]["value"], 1)
            self.assertNotIn("自动学习偏好", table_rows(saved))
            self.config(root, {"本次任务起点": 1, "是否需要图片审核": False})
            revised = validate(render("新任务", "field_battery", path))
            self.assertEqual(revised["route"]["starting_point"], 1)
            self.assertEqual(validate(saved)["route"], result["route"])

    def test_starting_point_text_defaults_map_to_numbered_task_snapshots(self):
        from parameter_catalog import choices
        options = choices(table_rows(TEMPLATE.read_text(encoding="utf-8"))["本次任务起点"])
        with tempfile.TemporaryDirectory() as folder:
            for number, label in options.items():
                for value in (number, label, label.rstrip("。"), label.split("：", 1)[0]):
                    with self.subTest(value=value):
                        path = self.config(Path(folder), {"本次任务起点": value})
                        original = path.read_bytes()
                        text = render("文字起点", "field_battery", path)
                        result = validate(text)
                        self.assertTrue(result["valid"], result["errors"])
                        self.assertEqual(result["route"]["starting_point"], number)
                        self.assertNotIn("content-gen-default-supplements", text)
                        self.assertEqual(path.read_bytes(), original)

    def test_image_gen_inputs_are_conditional_and_validate_only_when_applicable(self):
        from parameter_catalog import IMAGE_GEN_FIELDS, key_for
        original = render("生图条件", "field_battery")
        rows = table_rows(original)
        for name, row in rows.items():
            if key_for(name) not in IMAGE_GEN_FIELDS:
                continue
            self.assertEqual(row[2].strip(), "条件选填")
            modified = row.copy()
            modified[4] = "999"
            bad = original.replace("|".join(row), "|".join(modified))
            if key_for(name) == "output_compression":
                fmt = rows["输出格式 `output_format`"].copy()
                fmt[4] = "3"
                bad = bad.replace("|".join(rows["输出格式 `output_format`"]), "|".join(fmt))
            with self.subTest(key=key_for(name)):
                self.assertFalse(validate(bad)["valid"])
                for control, answer in (("是否使用 image-gen", "0"), ("本次任务起点", "5")):
                    control_row = rows[control].copy()
                    control_row[4] = answer
                    inactive = bad.replace("|".join(rows[control]), "|".join(control_row))
                    result = validate(inactive)
                    self.assertTrue(result["valid"], result["errors"])
                    self.assertNotIn(key_for(name), result["effective_parameters"])
                self.assertTrue(validate(bad, scope="content")["valid"])
        self.assertTrue(validate(original)["valid"])

    def test_image_gen_missing_default_requires_value_only_when_enabled(self):
        with tempfile.TemporaryDirectory() as folder:
            path = self.config(Path(folder), {"quality": ""})
            text = render("无质量默认", "field_battery", path)
            result = validate(text)
            self.assertFalse(result["valid"])
            self.assertTrue(any("quality" in error for error in result["errors"]))
            rows = table_rows(text)
            control = rows["是否使用 image-gen"]
            modified = control.copy()
            modified[4] = "0"
            self.assertTrue(validate(text.replace("|".join(control), "|".join(modified)))["valid"])

    def test_legacy_image_gen_optional_labels_are_read_without_rewriting_configuration(self):
        from parameter_catalog import IMAGE_GEN_FIELDS, key_for
        with tempfile.TemporaryDirectory() as folder:
            path = self.config(Path(folder))
            text = path.read_text(encoding="utf-8")
            for name, row in table_rows(text).items():
                if key_for(name) in IMAGE_GEN_FIELDS and key_for(name) != "output_compression":
                    old = "|".join(row)
                    row[2] = " 用户选填 "
                    text = text.replace(old, "|".join(row))
            path.write_text(text, encoding="utf-8")
            original = path.read_bytes()
            task = render("旧配置兼容", "field_battery", path)
            self.assertTrue(validate(task)["valid"])
            self.assertEqual(table_rows(task)["质量 `quality`"][2].strip(), "条件选填")
            self.assertEqual(path.read_bytes(), original)

    def test_manual_defaults_feed_new_tables_without_automatic_updates(self):
        with tempfile.TemporaryDirectory() as folder:
            path = self.config(Path(folder), {"quality": "high", "language": "bilingual"})
            text = render("偏好默认", "field_battery", path)
            result = validate(text)
            self.assertTrue(result["valid"], result["errors"])
            self.assertEqual(result["effective_parameters"]["quality"], "high")
            self.assertEqual(result["parameters"]["language"]["number"], 3)
            original = path.read_bytes()
            for index in range(4):
                task = render(f"task-{index}", "field_battery", path)
                rows = table_rows(task)
                row = rows["图片风格 `style`"]
                old = "|".join(row)
                row[4] = "2"
                self.assertTrue(validate(task.replace(old, "|".join(row)))["valid"])
            self.assertEqual(path.read_bytes(), original)
            self.config(Path(folder), {"style": "ink-notes"})
            after = validate(render("手动修改后", "field_battery", path))
            self.assertEqual(after["effective_parameters"]["style"], "ink-notes")
            self.assertEqual(validate(text)["effective_parameters"]["style"], "sketch-notes")
            self.assertEqual(load_preferences(path)["defaults"]["use_image_gen"], True)

    def test_custom_defaults_keep_values_in_task_snapshot_and_require_fresh_explicit_answers(self):
        with tempfile.TemporaryDirectory() as folder:
            path = self.config(Path(folder), {
                "variants_per_image": 3, "generation_batch_size": 5,
                "output_format": "jpeg", "output_compression": 83,
                "palette": "custom emerald and coral"})
            saved = render("自定义快照", "field_battery", path)
            result = validate(saved)
            self.assertTrue(result["valid"], result["errors"])
            self.assertEqual(result["supplements"]["variants_per_image"], 3)
            self.assertEqual(result["supplements"]["output_compression"], 83)
            self.config(Path(folder), {"variants_per_image": 2})
            self.assertEqual(validate(saved)["supplements"]["generation_batch_size"], 5)
            rows = table_rows(saved)
            row = rows["每图变体数 `variants_per_image`"]
            original = "|".join(row)
            row[4] = "3"
            self.assertFalse(validate(saved.replace(original, "|".join(row)))["valid"])
            explicit = validate(saved, {"variants_per_image": 7})
            self.assertEqual(explicit["supplements"]["variants_per_image"], 7)

    def test_version_one_defaults_render_and_migrate_without_retired_records(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "legacy.md"
            import json
            legacy = {"version": 1, "defaults": {"quality": "high", "style": "ink-notes"},
                      "learning": {"enabled": True, "threshold": 3},
                      "tracked_defaults": {}, "history": {}, "recorded_tasks": ["legacy-task"]}
            path.write_text("```json\n" + json.dumps(legacy) + "\n```\n", encoding="utf-8")
            text = render("兼容旧偏好", "field_battery", path)
            self.assertEqual(validate(text)["effective_parameters"]["quality"], "high")
            migrate_preferences(path)
            data = load_preferences(path)
            self.assertEqual(data["version"], 3)
            self.assertEqual(set(data), {"version", "defaults"})
            self.assertNotIn("legacy-task", path.read_text(encoding="utf-8"))
            self.assertEqual(data["defaults"]["style"], "ink-notes")
            self.assertEqual(validate(render("迁移后", "field_battery", path))["route"]["starting_point"], 1)
            original = path.read_bytes()
            self.assertFalse(migrate_preferences(path)["migrated"])
            self.assertEqual(path.read_bytes(), original)

    def test_retired_parameter_in_saved_task_has_no_effect(self):
        with tempfile.TemporaryDirectory() as folder:
            path = self.config(Path(folder))
            original = path.read_bytes()
            task = render("旧任务兼容", "field_battery", path)
            expected = validate(task)
            for answer in ("1", "2", ""):
                legacy = task + f"\n| 自动学习偏好 | 用户选填 | 1.开启 | {answer} | 旧参数 |\n"
                actual = validate(legacy)
                self.assertTrue(actual["valid"], actual["errors"])
                self.assertEqual(actual["effective_parameters"], expected["effective_parameters"])
                self.assertEqual(actual["route"], expected["route"])
            self.assertEqual(path.read_bytes(), original)

    def test_invalid_or_task_specific_configuration_is_not_silently_ignored(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for changes in ({"任务名称": "固定任务"}, {"专业领域": "field_battery"},
                            {"use_image_gen": 2}, {"本次任务起点": 6},
                            {"本次任务起点": "不认识的阶段"}, {"本次任务起点": True},
                            {"api_key": "private-value"}, {"quality": "unknown"}):
                path = self.config(root, changes)
                original = path.read_bytes()
                with self.subTest(changes=changes), self.assertRaises(ValueError):
                    render(config_path=path)
                self.assertEqual(path.read_bytes(), original)
            path = self.config(root)
            text = path.read_text(encoding="utf-8")
            path.write_text(text.replace("| 图片信息展示 `show_info`", "| 已移除的参数"), encoding="utf-8")
            with self.assertRaises(ValueError):
                render(config_path=path)


if __name__ == "__main__":
    unittest.main()
