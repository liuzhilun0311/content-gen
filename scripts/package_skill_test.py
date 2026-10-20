import tempfile
import unittest
from pathlib import Path
import zipfile

from package_skill import package_skill


class PackageTests(unittest.TestCase):
    def test_duplicate_generation_runtime_is_never_packaged(self):
        for name in ("gpt-image2.mjs", "request-controls.mjs", "info-summary.mjs",
                     "image-info.mjs", "gpt-image2.test.mjs"):
            (self.root / "scripts" / name).write_text("old runtime fixture", encoding="utf-8")
        package_skill(self.root, self.output)
        with zipfile.ZipFile(self.output) as archive:
            self.assertFalse(any(name.endswith(".mjs") for name in archive.namelist()))

    def test_show_me_guide_and_images_are_public_without_generation_logs(self):
        (self.root / "show-me").mkdir()
        (self.root / "show-me/show-me.html").write_text("<html>Skill guide</html>", encoding="utf-8")
        (self.root / "show-me/framework_vector-illustration_macaron.png").write_bytes(b"public image fixture")
        (self.root / "show-me/request.json").write_text("internal generation metadata", encoding="utf-8")
        package_skill(self.root, self.output)
        with zipfile.ZipFile(self.output) as archive:
            self.assertIn("skill/show-me/show-me.html", archive.namelist())
            self.assertIn("skill/show-me/framework_vector-illustration_macaron.png", archive.namelist())
            self.assertNotIn("skill/show-me/request.json", archive.namelist())

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "skill"
        (self.root / "config").mkdir(parents=True)
        (self.root / "scripts").mkdir()
        (self.root / "references").mkdir()
        (self.root / "agents").mkdir()
        (self.root / "SKILL.md").write_text("Public instructions", encoding="utf-8")
        (self.root / ".gitignore").write_text("config/.env\n", encoding="utf-8")
        (self.root / "config" / ".env.example").write_text("GPT_IMAGE2_API_KEY=\n", encoding="utf-8")
        (self.root / "config" / ".env").write_text("GPT_IMAGE2_API_KEY=private-fixture-key\n", encoding="utf-8")
        self.output = Path(self.temp.name) / "shared.zip"

    def test_only_public_files_are_archived(self):
        (self.root / "scripts" / ".env").write_text("legacy private key", encoding="utf-8")
        (self.root / "scripts" / "debug.log").write_text("private-fixture-key", encoding="utf-8")
        (self.root / "references" / "writing.md").write_text("Public guide", encoding="utf-8")
        package_skill(self.root, self.output)
        with zipfile.ZipFile(self.output) as archive:
            names = archive.namelist()
            self.assertIn("skill/config/.env.example", names)
            self.assertIn("skill/references/writing.md", names)
            self.assertNotIn("skill/config/.env", names)
            self.assertNotIn("skill/scripts/.env", names)
            self.assertNotIn("skill/scripts/debug.log", names)
            for name in names:
                self.assertNotIn(b"private-fixture-key", archive.read(name))

    def test_accidental_secret_in_public_file_blocks_packaging(self):
        (self.root / "SKILL.md").write_text("Oops: private-fixture-key", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "Private configuration"):
            package_skill(self.root, self.output)
        self.assertFalse(self.output.exists())

    def test_existing_archive_is_preserved(self):
        self.output.write_bytes(b"existing user archive")
        with self.assertRaises(FileExistsError):
            package_skill(self.root, self.output)
        self.assertEqual(self.output.read_bytes(), b"existing user archive")

    def test_user_defaults_and_task_history_are_not_shared(self):
        (self.root / "extend.md").write_text("private user preferences and task IDs", encoding="utf-8")
        (self.root / "extend.example.md").write_text("Empty preference template", encoding="utf-8")
        (self.root / "config/extend.md").write_text("private canonical preferences and task IDs", encoding="utf-8")
        (self.root / "config/extend.example.md").write_text("Empty preference template", encoding="utf-8")
        package_skill(self.root, self.output)
        with zipfile.ZipFile(self.output) as archive:
            self.assertIn("skill/config/extend.example.md", archive.namelist())
            self.assertNotIn("skill/extend.example.md", archive.namelist())
            self.assertNotIn("skill/extend.md", archive.namelist())
            self.assertNotIn("skill/config/extend.md", archive.namelist())
            self.assertFalse(any(b"private user preferences" in archive.read(name) for name in archive.namelist()))
            self.assertFalse(any(b"private canonical preferences" in archive.read(name) for name in archive.namelist()))

    def test_archive_cannot_be_written_inside_skill(self):
        with self.assertRaisesRegex(ValueError, "outside"):
            package_skill(self.root, self.root / "shared.zip")

    def test_workflow_export_and_copy_template_are_included(self):
        (self.root / "assets").mkdir()
        filenames = ("task_paths.py", "task_state.py", "workflow_switches.py",
                     "validate_parameters.py", "workflow_test.py",
                     "export-publishing-documents.py", "export_publishing_test.py",
                     "export-content-documents.py", "render-content-pdf.mjs", "export_content_test.py")
        for name in filenames:
            (self.root / "scripts" / name).write_text("# Public runtime", encoding="utf-8")
        (self.root / "assets/wechat-copy.html").write_text("<html></html>", encoding="utf-8")
        package_skill(self.root, self.output)
        with zipfile.ZipFile(self.output) as archive:
            for name in filenames:
                self.assertIn("skill/scripts/" + name, archive.namelist())
            self.assertIn("skill/assets/wechat-copy.html", archive.namelist())

    def test_secret_detection_handles_utf8_bom(self):
        (self.root / "config" / ".env").write_text("GPT_IMAGE2_API_KEY=private-fixture-key\n", encoding="utf-8-sig")
        (self.root / "SKILL.md").write_text("private-fixture-key", encoding="utf-8")
        with self.assertRaises(ValueError):
            package_skill(self.root, self.output)


if __name__ == "__main__":
    unittest.main()
