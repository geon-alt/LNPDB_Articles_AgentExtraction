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


if __name__ == "__main__":
    unittest.main()
