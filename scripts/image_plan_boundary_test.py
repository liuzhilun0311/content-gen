"""Adversarial plan and execution-gate tests; no generation requests."""

import copy
import json
from pathlib import Path
import tempfile
import unittest

from task_state import digest, gates
from validate_image_plan import validate
import verify_task_test


class ImagePlanBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "_work").mkdir()
        self.path = self.root / "_work/image-plan.json"
        binding = {}
        for key in ("content", "review", "parameters", "prompt"):
            source = self.root / (key + ".md")
            source.write_text(key, encoding="utf-8")
            binding[key] = {"path": source.name, "sha256": digest(source)}
        self.plan = {
            "schema_version": 2,
            "binding": {key: binding[key] for key in ("content", "review", "parameters")},
            "short_image_ids": ["00"],
            "images": [{
                "image_id": "00", "prompt_path": "prompt.md",
                "prompt_sha256": binding["prompt"]["sha256"],
                "allowed_labels": ["Query", "Evidence"],
                "semantic_contract": {
                    "nodes": ["Query", "Evidence"],
                    "edges": [{"from": "Query", "to": "Evidence",
                               "relation": "retrieve", "condition": ""}],
                    "forbidden_edges": [], "forbidden_symbols": ["unverified claim"],
                },
            }],
        }

    def check(self, plan):
        self.path.write_text(json.dumps(plan), encoding="utf-8")
        return validate(self.path)

    def test_valid_v2_plan_is_accepted(self):
        self.assertTrue(self.check(self.plan)["valid"])

    def test_empty_prompt_path_is_rejected(self):
        self.plan["images"][0]["prompt_path"] = ""
        self.assertFalse(self.check(self.plan)["valid"])

    def test_blank_and_non_string_image_ids_are_rejected(self):
        for identifier in (" ", 1, None):
            with self.subTest(identifier=identifier):
                plan = copy.deepcopy(self.plan)
                plan["images"].append({**plan["images"][0], "image_id": identifier})
                self.assertFalse(self.check(plan)["valid"])

    def test_omitted_semantic_lists_are_not_silently_empty(self):
        for key in ("edges", "forbidden_edges", "forbidden_symbols"):
            with self.subTest(key=key):
                plan = copy.deepcopy(self.plan)
                del plan["images"][0]["semantic_contract"][key]
                self.assertFalse(self.check(plan)["valid"])

    def test_empty_string_short_selection_is_not_an_empty_list(self):
        self.plan["short_image_ids"] = ""
        self.assertFalse(self.check(self.plan)["valid"])

    def test_non_string_prompt_path_reports_validation_errors(self):
        self.plan["images"][0]["prompt_path"] = ["prompt.md"]
        self.assertFalse(self.check(self.plan)["valid"])

    def test_false_schema_version_is_not_legacy_version_one(self):
        for value in (True, False, 2.0):
            with self.subTest(value=value):
                self.plan["schema_version"] = value
                self.assertFalse(self.check(self.plan)["valid"])

    def test_missing_machine_plan_cannot_authorize_generation(self):
        with tempfile.TemporaryDirectory() as folder:
            state_path, root = verify_task_test.CompletionTests().short_fixture(folder)
            from task_state import load
            state = load(state_path)
            result = gates(state, [root / state["paths"]["review"]],
                           sorted((root / "imgs").glob("*.png")))
            self.assertFalse(result["can_generate"])
            self.assertTrue(result["generation_reasons"])
            self.assertTrue(result["can_assemble"], "Reviewed historical images remain reusable")

    def test_boolean_starting_point_does_not_activate_generation_route(self):
        from workflow_test import parameter_document
        from validate_parameters import validate
        text = parameter_document(4)
        lines = text.splitlines()
        for index, line in enumerate(lines):
            if line.startswith("| 本次任务起点 |"):
                cells = line.split("|")
                cells[4] = " true "
                lines[index] = "|".join(cells)
                break
        text = "\n".join(lines)
        result = validate(text)
        self.assertFalse(result["valid"])


if __name__ == "__main__":
    unittest.main()
