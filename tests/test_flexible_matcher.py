import json
import unittest

from expval_merge_workspace.flexible_matcher import (
    evaluate_pair,
    heuristic_mapping_plan,
    validate_mapping_plan,
)


def wrapped(raw, **helpers):
    return {"raw_columns_json": json.dumps(raw), **helpers}


class FlexibleMatcherTests(unittest.TestCase):
    def test_heuristic_builds_many_source_to_one_target_mapping(self):
        source = [
            wrapped(
                {
                    "figure_name": "figure 2b",
                    "X_Label": "G0-SS-AA-C12",
                    "Group": "Treated",
                    "Value": "123.4",
                    "Type": "bar_plot",
                }
            )
        ]
        target = [
            wrapped(
                {
                    "FigureKey": "figure 2b",
                    "TreatmentName": "G0-SS-AA-C12 Treated",
                    "Readout": "bar_plot",
                    "experimental_value": "",
                }
            )
        ]

        plan = heuristic_mapping_plan("figure 2b", source, target)

        self.assertEqual(plan["source_value_column"], "Value")
        self.assertEqual(plan["target_value_column"], "experimental_value")
        self.assertTrue(
            any(
                relation["source_columns"] == ["X_Label", "Group"]
                and relation["target_columns"] == ["TreatmentName"]
                for relation in plan["relations"]
            )
        )
        self.assertTrue(evaluate_pair(source[0], target[0], plan)["matched"])

    def test_explicit_mapping_supports_one_source_to_multiple_target_columns(self):
        source = [wrapped({"Condition": "mouse liver IV", "Value": "8.2"})]
        target = [
            wrapped(
                {
                    "Model_type": "mouse",
                    "Model_target": "liver",
                    "Route": "IV",
                    "experimental_value": "",
                }
            )
        ]
        raw_plan = {
            "source_value_column": "Value",
            "target_value_column": "experimental_value",
            "relations": [
                {
                    "source_columns": ["Condition"],
                    "target_columns": ["Model_type", "Model_target", "Route"],
                    "mode": "value_map",
                    "required": True,
                    "value_pairs": [
                        {
                            "source_values": ["mouse liver IV"],
                            "target_values": ["mouse", "liver", "IV"],
                        }
                    ],
                    "reason": "source condition encodes three target fields",
                }
            ],
            "fixed_target_values": {},
            "confidence": "high",
            "needs_review": False,
            "reason": "test",
        }

        plan = validate_mapping_plan(raw_plan, "figure 1a", source, target)

        self.assertFalse(plan["needs_review"])
        self.assertTrue(evaluate_pair(source[0], target[0], plan)["matched"])


if __name__ == "__main__":
    unittest.main()
