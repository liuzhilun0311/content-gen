import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import preferences
from parameter_catalog import CATALOG
from preferences import load_preferences, migrate_preferences, read_document
from task_parameters import render
from validate_parameters import validate


class ManualDefaultTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "extend.md"

    def legacy(self, version=1):
        text = CATALOG.read_text(encoding="utf-8")
        start = text.index("```json\n") + len("```json\n")
        end = text.index("\n```", start)
        defaults = {"style": "ink-notes", "quality": "high"}
        if version == 2:
            defaults = {**load_preferences(CATALOG)["defaults"], **defaults}
        data = {"version": version, "defaults": defaults,
                "learning": {"enabled": True, "threshold": 3},
                "tracked_defaults": {"style": "sketch-notes"},
                "history": {"style": [{"task": "old-task", "value": "ink-notes"}]},
                "recorded_tasks": ["old-task"]}
        if version == 1:
            text = "Legacy notes\n\n```json\n" + json.dumps(data) + "\n```\n"
        else:
            text = text[:start] + json.dumps(data) + text[end:]
            text += "\n| 自动学习偏好 | 用户选填 | | | 1. 开启<br>2. 关闭 |\n"
        self.path.write_text(text, encoding="utf-8")
        return defaults

    def test_reading_missing_defaults_does_not_create_or_initialize_a_file(self):
        data = load_preferences(self.path)
        self.assertEqual(data["defaults"], {})
        self.assertFalse(self.path.exists())
        self.assertFalse(hasattr(preferences, "record_choices"))

    def test_explicit_initialization_only_contains_manual_defaults(self):
        self.assertTrue(migrate_preferences(self.path)["migrated"])
        data = load_preferences(self.path)
        self.assertEqual(data["version"], 3)
        self.assertEqual(set(data), {"version", "defaults"})
        original = self.path.read_bytes()
        self.assertFalse(migrate_preferences(self.path)["migrated"])
        self.assertEqual(self.path.read_bytes(), original)

    def test_legacy_read_is_nonmutating_and_explicit_migration_drops_retired_metadata(self):
        for version in (1, 2):
            with self.subTest(version=version):
                defaults = self.legacy(version)
                original = self.path.read_bytes()
                data = load_preferences(self.path)
                self.assertEqual(data["defaults"], defaults)
                self.assertEqual(set(data), {"version", "defaults"})
                task = render("Legacy defaults", "field_battery", self.path)
                result = validate(task)
                self.assertTrue(result["valid"], result["errors"])
                self.assertEqual(result["effective_parameters"]["quality"], "high")
                self.assertNotIn("自动学习偏好", task)
                self.assertEqual(self.path.read_bytes(), original)
                migrate_preferences(self.path)
                current = load_preferences(self.path)
                self.assertEqual(current["defaults"]["style"], "ink-notes")
                for token in ('"learning"', '"tracked_defaults"', '"history"',
                              '"recorded_tasks"', "old-task", "自动学习偏好"):
                    self.assertNotIn(token, self.path.read_text(encoding="utf-8"))

    def test_cli_read_is_read_only_and_retired_submission_options_are_rejected(self):
        migrate_preferences(self.path)
        original = self.path.read_bytes()
        command = [sys.executable, "-X", "utf8", str(Path(preferences.__file__)), "--file", str(self.path)]
        completed = subprocess.run(command, capture_output=True, check=True)
        self.assertEqual(set(json.loads(completed.stdout)), {"version", "defaults"})
        for args in (["--task", "some-task"], ["--answers", "answers.json"],
                     ["--task", "some-task", "--answers", "answers.json"]):
            result = subprocess.run(command + args, capture_output=True)
            self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.path.read_bytes(), original)

    def test_invalid_configuration_is_preserved(self):
        for text in ("```json\nnot json\n```\n",
                     '```json\n{"version": 3, "defaults": {}, "learning": {}}\n```\n',
                     '```json\n{"version": 3, "defaults": {"api_key": "secret"}}\n```\n'):
            self.path.write_text(text, encoding="utf-8")
            original = self.path.read_bytes()
            with self.assertRaises(ValueError):
                migrate_preferences(self.path)
            self.assertEqual(self.path.read_bytes(), original)

    def test_repeated_task_choices_never_fill_missing_or_replace_existing_defaults(self):
        migrate_preferences(self.path)
        original = self.path.read_bytes()
        for index in range(4):
            task = render(f"Task {index}", "field_battery", self.path)
            from workflow_switches import table_rows
            rows = table_rows(task)
            row = rows["图片风格 `style`"]
            old = "|".join(row)
            row[4] = "2"
            task = task.replace(old, "|".join(row))
            row = table_rows(task)["已有图片 `existing_images`"]
            old = "|".join(row)
            row[4] = "1"
            result = validate(task.replace(old, "|".join(row)), {"has_existing_images": True})
            self.assertTrue(result["valid"], result["errors"])
        data = read_document(self.path)[3]
        self.assertEqual(data["defaults"]["style"], "sketch-notes")
        self.assertEqual(data["defaults"]["existing_images"], "")
        self.assertEqual(self.path.read_bytes(), original)


if __name__ == "__main__":
    unittest.main()
