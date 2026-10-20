import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import local_config
from markdown_contract import runtime_paths
from preferences import default_preferences_path, load_preferences, migrate_preferences


class LocalConfigTests(unittest.TestCase):
    def test_runtime_file_allows_only_tool_paths_and_preserves_quoted_windows_paths(self):
        with tempfile.TemporaryDirectory() as folder:
            config = Path(folder) / ".env"
            config.write_text(
                'export SANBAO_NODE="C:\\Program Files\\Node\\node.exe" # runtime\n'
                "SANBAO_MARKED='C:\\Modules\\marked.mjs'\n"
                "SANBAO_BROWSER=C:/Browser/msedge.exe # browser\n"
                "SANBAO_PLAYWRIGHT=\nGPT_IMAGE2_API_KEY=isolated-unused-key\n",
                encoding="utf-8-sig")
            values = local_config.read_runtime_config(config)
            self.assertEqual(values["SANBAO_NODE"], r"C:\Program Files\Node\node.exe")
            self.assertEqual(values["SANBAO_MARKED"], r"C:\Modules\marked.mjs")
            self.assertEqual(values["SANBAO_BROWSER"], "C:/Browser/msedge.exe")
            self.assertEqual(values["SANBAO_PLAYWRIGHT"], "")
            self.assertNotIn("GPT_IMAGE2_API_KEY", values)
            with patch.object(local_config, "CONFIG", config), patch.dict(os.environ, {}, clear=True):
                self.assertEqual(local_config.runtime_value("SANBAO_BROWSER"), values["SANBAO_BROWSER"])
                with patch.dict(os.environ, {"SANBAO_BROWSER": "environment-browser"}):
                    self.assertEqual(local_config.runtime_value("SANBAO_BROWSER"), "environment-browser")
                with patch.dict(os.environ, {"SANBAO_BROWSER": ""}):
                    self.assertEqual(local_config.runtime_value("SANBAO_BROWSER", "fallback"), "fallback")
                self.assertNotIn("SANBAO_NODE", os.environ)
                with self.assertRaises(ValueError):
                    local_config.runtime_value("GPT_IMAGE2_API_KEY")

    def test_runtime_paths_use_canonical_config_without_changing_environment(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            node = root / "custom-node"
            node.touch()
            config = root / ".env"
            config.write_text(f"SANBAO_NODE={node}\nSANBAO_MARKED={root / 'marked.mjs'}\n", encoding="utf-8")
            with patch.object(local_config, "CONFIG", config), patch.dict(os.environ, {}, clear=True), \
                    patch("markdown_contract.Path.home", return_value=root):
                self.assertEqual(runtime_paths(), (str(node), str(root / "marked.mjs")))
            self.assertEqual(local_config.read_runtime_config(root / "missing"), {})

    def test_preferences_prefer_config_and_fall_back_to_legacy_without_overwriting(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            canonical = root / "config/extend.md"
            legacy = root / "extend.md"
            self.assertEqual(default_preferences_path(root), canonical)
            legacy.write_text("legacy file", encoding="utf-8")
            self.assertEqual(default_preferences_path(root), legacy)
            canonical.parent.mkdir()
            canonical.write_text("canonical file", encoding="utf-8")
            self.assertEqual(default_preferences_path(root), canonical)
            self.assertEqual(legacy.read_text(encoding="utf-8"), "legacy file")

    def test_manual_initialization_is_written_under_config(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            target = default_preferences_path(root)
            migrate_preferences(target)
            data = load_preferences(target)
            self.assertEqual(data["defaults"]["aspect_ratio"], "4:3")
            self.assertEqual(data["defaults"]["quality"], "medium")
            self.assertEqual(set(data), {"version", "defaults"})
            self.assertFalse((root / "extend.md").exists())


if __name__ == "__main__":
    unittest.main()
