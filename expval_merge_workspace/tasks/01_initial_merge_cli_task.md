# External Agent Task: Experimental Value to LNPDB-Like Merge CLI

## Purpose

Build or operate a CLI that merges image-extracted experimental values into LNPDB-like tables.

## Default Inputs

Extracted values:

- `F:\내 드라이브\LNPDB_update_1\Supplementrays\expvals`

LNPDB-like tables:

- `F:\내 드라이브\LNPDB_update_1\Supplementrays`
- `F:\내 드라이브\LNPDB_update_1\Source_head_tail_separated_f`
- `F:\내 드라이브\LNPDB_update_1\Source_DOI_added_f`

## Expected Outputs

Write to a separate output root:

- `input_inventory.csv`
- `normalized_expvals.csv`
- `normalized_lnpdb_rows.csv`
- `merge_candidates.csv`
- `merge_conflicts.csv`
- `merge_unmatched_expvals.csv`
- `merge_unmatched_lnpdb_rows.csv`
- `merged_lnpdb_like.csv`
- `merge_review_flags.csv`
- `merge_qc_report.json`

## Required Rules

1. Do not modify original files.
2. Normalize image-derived barplot and heatmap tables to a canonical long format.
3. Preserve every original LNPDB-like column.
4. Match by DOI/paper, figure/item/panel, formulation/group/condition, and metric context.
5. Never match by value alone.
6. Fill only the `experimental_value` column.
7. Fill only rows where `experimental_value` is blank.
8. Never overwrite non-empty `experimental_value`.
9. Use all other target columns flexibly as matching context, even when their names do not match the canonical schema.
10. Write conflicts and unmatched rows for review.
11. Record provenance for every inserted value.
12. Validate that every extracted-value row is accounted for.
