import tempfile
import unittest
from pathlib import Path
from unittest import mock

import pandas as pd

import Expval_Merge_Runner as runner


class SinglePaperPipelineTests(unittest.TestCase):
    def test_target_excel_folder_is_combined_and_progress_snapshots_accumulate(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source_dir = root / "source"
            target_dir = root / "target"
            output_dir = root / "output"
            source_dir.mkdir()
            target_dir.mkdir()

            for figure, label, value in [
                ("figure 1", "Formulation A", "10.1"),
                ("figure 2", "Formulation B", "20.2"),
            ]:
                pd.DataFrame(
                    [
                        {
                            "figure_name": figure,
                            "X_Label": label,
                            "Group": "Treated",
                            "Value": value,
                            "Type": "bar_plot",
                        }
                    ]
                ).to_csv(source_dir / f"{figure.replace(' ', '_')}.csv", index=False)

            target_frames = {}
            for index, (figure, label) in enumerate(
                [
                    ("figure 1", "Formulation A"),
                    ("figure 2", "Formulation B"),
                ],
                start=1,
            ):
                target_path = target_dir / f"target_{index}.xlsx"
                target_path.write_bytes(b"mock excel input")
                target_frames[target_path.name] = pd.DataFrame(
                    [
                        {
                            "FigureKey": figure,
                            "TreatmentName": f"{label} Treated",
                            "Readout": "bar_plot",
                            "experimental_value": "",
                        }
                    ]
                )

            original_read_table_file = runner.read_table_file

            def fake_read_table_file(path):
                if path.suffix.lower() == ".csv":
                    return original_read_table_file(path)
                return [("Sheet1", target_frames[path.name])]

            class FakeExcelFile:
                sheet_names = ["Sheet1"]

                def __init__(self, _path):
                    pass

            with mock.patch.object(runner, "read_table_file", side_effect=fake_read_table_file), mock.patch.object(
                runner.pd, "ExcelFile", FakeExcelFile
            ):
                report = runner.observe_inputs([source_dir], [target_dir], output_dir)
                self.assertEqual(report["target_input_mode"], "excel_folder_combined")
                runner.build_figure_table_key_map(output_dir, provider="heuristic")
                runner.normalize_expvals(output_dir)
                normalized = runner.normalize_lnpdb(output_dir)
                self.assertEqual(normalized["files"], 2)
                self.assertEqual(normalized["combined_rows"], 2)
                runner.build_match_candidates(output_dir, provider="heuristic")
                merged = runner.merge_values(output_dir, mode="fill_existing")

            self.assertEqual(merged["progress_steps"], 2)
            combined = pd.read_csv(output_dir / "combined_lnpdb_target.csv").fillna("")
            self.assertEqual(len(combined), 2)
            self.assertIn("__target_source_file", combined.columns)

            manifest = pd.read_csv(output_dir / "merge_progress_manifest.csv")
            self.assertEqual(manifest["partition_key"].tolist(), ["figure 1", "figure 2"])
            first = pd.read_csv(manifest.iloc[0]["snapshot_file"]).fillna("")
            second = pd.read_csv(manifest.iloc[1]["snapshot_file"]).fillna("")
            self.assertEqual((first["experimental_value"] != "").sum(), 1)
            self.assertEqual((second["experimental_value"] != "").sum(), 2)

    def test_reference_root_retries_ambiguous_codex_mapping(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            output_dir = root / "output"
            reference_dir = root / "previous_extract"
            output_dir.mkdir()
            reference_dir.mkdir()
            (reference_dir / "supplementary_notes.md").write_text(
                "Supplementary Figure 18 maps H22 to FG_2026_F40.",
                encoding="utf-8",
            )
            source_rows = [
                {
                    "partition_key": "supplementary figure 18",
                    "X_Label": "H22",
                    "Value": "12.3",
                    "Type": "bar_plot",
                }
            ]
            target_rows = [
                {
                    "partition_key": "supplementary figure 18",
                    "Formulation_ID": "FG_2026_F40",
                    "Experiment_value": "",
                    "Experiment_method": "luminescence",
                }
            ]
            ambiguous_plan = {
                "source_value_column": "Value",
                "target_value_column": "Experiment_value",
                "relations": [],
                "fixed_target_values": [],
                "confidence": "low",
                "needs_review": True,
                "reason": "missing reference evidence",
            }
            resolved_plan = {
                "source_value_column": "Value",
                "target_value_column": "Experiment_value",
                "relations": [
                    {
                        "source_columns": ["X_Label"],
                        "target_columns": ["Formulation_ID"],
                        "mode": "value_map",
                        "required": True,
                        "value_pairs": [
                            {
                                "source_values": ["H22"],
                                "target_values": ["FG_2026_F40"],
                            }
                        ],
                        "reason": "reference note resolves the missing label",
                    }
                ],
                "fixed_target_values": [],
                "confidence": "high",
                "needs_review": False,
                "reason": "resolved with reference context",
            }

            with mock.patch.object(
                runner,
                "call_codex_mapping_planner",
                side_effect=[(ambiguous_plan, "{}"), (resolved_plan, "{}")],
            ) as planner:
                plans = runner.build_partition_mapping_plans(
                    output_dir,
                    source_rows,
                    target_rows,
                    provider="codex",
                    reference_roots=[reference_dir],
                )

            plan = plans["supplementary figure 18"]
            self.assertFalse(plan["needs_review"])
            self.assertTrue(plan["reference_context_used"])
            self.assertEqual(planner.call_count, 2)
            second_prompt = planner.call_args_list[1].args[0]
            self.assertIn("reference_context", second_prompt)
            self.assertIn("documents", second_prompt["reference_context"])
            self.assertIn("Supplementary Figure 18 maps H22", second_prompt["reference_context"]["documents"][0]["content"])
            self.assertTrue((output_dir / "partition_reference_context_report.json").exists())

    def test_high_confidence_heuristic_fallback_after_codex_failure_is_accepted(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir)
            source_rows = [
                {
                    "partition_key": "supplementary figure 6",
                    "X_Label": "CHCha-10",
                    "Value": "13.2",
                }
            ]
            target_rows = [
                {
                    "partition_key": "supplementary figure 6",
                    "IL-name": "CHCha-10",
                    "Experiment_value": "",
                }
            ]

            with mock.patch.object(
                runner,
                "call_codex_mapping_planner",
                side_effect=FileNotFoundError("codex"),
            ):
                plans = runner.build_partition_mapping_plans(
                    output_dir,
                    source_rows,
                    target_rows,
                    provider="codex",
                )

            plan = plans["supplementary figure 6"]
            self.assertEqual(plan["confidence"], "high")
            self.assertFalse(plan["needs_review"])
            self.assertIn("heuristic fallback accepted", plan["reason"])

    def test_review_partition_can_accept_unambiguous_partial_matches(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            output_dir = root / "output"
            output_dir.mkdir()
            pd.DataFrame(
                [
                    {
                        "expval_id": "EV1",
                        "partition_key": "supplementary figure 47",
                        "X_Label": "A",
                        "Group": "C10",
                        "Value": "1.1",
                    },
                    {
                        "expval_id": "EV2",
                        "partition_key": "supplementary figure 47",
                        "X_Label": "MC3",
                        "Group": "C10",
                        "Value": "2.2",
                    },
                    {
                        "expval_id": "EV3",
                        "partition_key": "supplementary figure 47",
                        "X_Label": "MC3",
                        "Group": "C12",
                        "Value": "3.3",
                    },
                ]
            ).to_csv(output_dir / "normalized_expvals.csv", index=False)
            pd.DataFrame(
                [
                    {
                        "lnpdb_row_id": "LN1",
                        "partition_key": "supplementary figure 47",
                        "IL_name": "A-C10",
                        "Experiment_value": "",
                    },
                    {
                        "lnpdb_row_id": "LN2",
                        "partition_key": "supplementary figure 47",
                        "IL_name": "DLin-MC3-DMA",
                        "Experiment_value": "",
                    },
                ]
            ).to_csv(output_dir / "normalized_lnpdb_rows.csv", index=False)
            review_plan = {
                "source_value_column": "Value",
                "target_value_column": "Experiment_value",
                "relations": [
                    {
                        "source_columns": ["X_Label", "Group"],
                        "target_columns": ["IL_name"],
                        "mode": "value_map",
                        "required": True,
                        "value_pairs": [
                            {"source_values": ["A", "C10"], "target_values": ["A-C10"]},
                            {"source_values": ["MC3", "C10"], "target_values": ["DLin-MC3-DMA"]},
                            {"source_values": ["MC3", "C12"], "target_values": ["DLin-MC3-DMA"]},
                        ],
                        "reason": "partial deterministic plan with ambiguous MC3 rows",
                    }
                ],
                "fixed_target_values": {},
                "confidence": "medium",
                "needs_review": True,
                "reason": "MC3 rows are ambiguous",
            }

            with mock.patch.object(
                runner,
                "build_partition_mapping_plans",
                return_value={"supplementary figure 47": review_plan},
            ):
                result = runner.build_match_candidates(output_dir, provider="heuristic")

            self.assertEqual(result["accepted"], 1)
            candidates = pd.read_csv(output_dir / "merge_candidates.csv").fillna("")
            accepted = candidates[candidates["accepted"].astype(str).str.lower() == "true"]
            conflicts = candidates[candidates["conflict_reason"].astype(str) != ""]
            self.assertEqual(accepted["expval_id"].tolist(), ["EV1"])
            self.assertEqual(len(conflicts), 2)


if __name__ == "__main__":
    unittest.main()
