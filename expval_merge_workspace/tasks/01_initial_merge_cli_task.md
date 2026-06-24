# External Agent Task: Experimental Value to LNPDB-Like Merge CLI

## Purpose

Build or operate a CLI that merges image-extracted experimental values into LNPDB-like tables.

## Default Inputs

Extracted values:

- `F:\내 드라이브\LNPDB_update_1\Supplementrays\expvals`

LNPDB-like target:

- one CSV/Excel file, or one folder containing target Excel files for the same paper

## Expected Outputs

Write to a separate output root:

- `input_inventory.csv`
- `combined_lnpdb_target.csv`
- `normalized_expvals.csv`
- `normalized_lnpdb_rows.csv`
- `merge_candidates.csv`
- `merge_conflicts.csv`
- `merge_unmatched_expvals.csv`
- `merge_unmatched_lnpdb_rows.csv`
- `merged_lnpdb_like.csv`
- `merge_progress_manifest.csv`
- `merge_review_flags.csv`
- `merge_qc_report.json`

## Required Rules

1. Do not modify original files.
2. Normalize image-derived barplot and heatmap tables to a canonical long format.
3. Combine one target folder's Excel files into one logical target table and preserve every original LNPDB-like column.
4. Match by DOI/paper, figure/item/panel, formulation/group/condition, and metric context.
5. Never match by value alone.
6. Select one target value column per figure/table partition and fill only that column.
7. Fill only rows where the selected target value column is blank.
8. Never overwrite non-empty `experimental_value`.
9. Use all other target columns flexibly as matching context, even when their names do not match the canonical schema.
10. Write conflicts and unmatched rows for review.
11. Record provenance for every inserted value.
12. Save cumulative per-figure/table merge snapshots.
13. Validate that every extracted-value row is accounted for.
