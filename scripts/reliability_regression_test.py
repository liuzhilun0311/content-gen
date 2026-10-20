import json
import sys
import tempfile
import threading
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from task_paths import create_task
from task_state import file_evidence, load, update
from validate_image_plan import validate


class ReliabilityRegressionTests(unittest.TestCase):
    def test_input_refresh_invalidates_passed_content(self):
        with tempfile.TemporaryDirectory() as folder:
            task = create_task("失效测试", folder, "Asia/Shanghai")
            state_path = Path(task["task_directory"]) / "_work/task.json"
            source = Path(folder) / "source.txt"
            source.write_text("one", encoding="utf-8")
            update(state_path, "inputs", {"files": [str(source)]})
            content = Path(task["task_directory"]) / "content.md"
            content.write_text("content", encoding="utf-8")
            update(state_path, "stage", {"stage": "content", "status": "passed",
                                         "evidence": file_evidence([content])})
            source.write_text("two", encoding="utf-8")
            update(state_path, "inputs", {"files": [str(source)]})
            state = load(state_path)
            self.assertEqual(state["stages"]["content"]["status"], "pending")
            self.assertTrue(any(item["event"] == "invalidate" for item in state["history"]))

    def test_concurrent_stage_updates_are_not_lost(self):
        with tempfile.TemporaryDirectory() as folder:
            task = create_task("并发测试", folder, "Asia/Shanghai")
            state_path = Path(task["task_directory"]) / "_work/task.json"
            files = {}
            for stage in ("content", "plan"):
                file = Path(task["task_directory"]) / (stage + ".md")
                file.write_text(stage, encoding="utf-8")
                files[stage] = file
            barrier = threading.Barrier(2)
            errors = []

            def write_stage(stage):
                try:
                    barrier.wait()
                    update(state_path, "stage", {
                        "stage": stage, "status": "passed",
                        "evidence": file_evidence([files[stage]]),
                    })
                except Exception as exc:
                    errors.append(exc)

            threads = [threading.Thread(target=write_stage, args=(stage,))
                       for stage in ("content", "plan")]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()
            self.assertEqual(errors, [])
            state = load(state_path)
            self.assertEqual(state["stages"]["content"]["status"], "passed")
            self.assertEqual(state["stages"]["plan"]["status"], "passed")
            self.assertGreaterEqual(state["state_revision"], 2)

    def test_image_plan_requires_semantic_contract_and_shared_cover(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "_work").mkdir()
            (root / "imgs/prompts").mkdir(parents=True)
            prompt = root / "imgs/prompts/00.md"
            prompt.write_text("CONTENT", encoding="utf-8")
            plan = root / "_work/image-plan.json"
            plan.write_text(json.dumps({
                "images": [{
                    "image_id": "00",
                    "prompt_path": "imgs/prompts/00.md",
                    "allowed_labels": ["电池"],
                    "semantic_contract": {
                        "nodes": ["电池"], "edges": [],
                        "forbidden_edges": [], "forbidden_symbols": ["V"],
                    },
                }],
            }, ensure_ascii=False), encoding="utf-8")
            result = validate(plan)
            self.assertTrue(result["valid"], result["errors"])

            bad = json.loads(plan.read_text(encoding="utf-8"))
            bad["images"][0].pop("semantic_contract")
            plan.write_text(json.dumps(bad), encoding="utf-8")
            self.assertFalse(validate(plan)["valid"])


if __name__ == "__main__":
    unittest.main()
