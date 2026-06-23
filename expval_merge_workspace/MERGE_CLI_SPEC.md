# Merge CLI Specification

This document defines the intended stages for a future `expval-merge` CLI.

## CLI Purpose

Merge extracted experimental values from image-derived CSV/Excel files into LNPDB-like tables while preserving all original table metadata and recording full provenance.

## Default Command Shape

```bash
python Expval_Merge_Runner.py observe ^
  --expval-root "F:\내 드라이브\LNPDB_update_1\Supplementrays\expvals" ^
  --lnpdb-root "F:\내 드라이브\LNPDB_update_1\Supplementrays" ^
  --lnpdb-root "F:\내 드라이브\LNPDB_update_1\Source_head_tail_separated_f" ^
  --lnpdb-root "F:\내 드라이브\LNPDB_update_1\Source_DOI_added_f" ^
  --output-root "F:\내 드라이브\LNPDB_update_1\expval_merge_outputs"
```

The runner implementation is `Expval_Merge_Runner.py`. The stage contracts below should remain stable even if the implementation is later packaged as `python -m expval_merge`.

## Stages

### 00_observe_inputs

Purpose: Inventory all candidate extracted-value files and LNPDB-like files.

Inputs:

- extracted-value root
- one or more LNPDB-like search roots

Outputs:

- `input_inventory.csv`
- `observe_report.json`

Validation:

- At least one extracted-value file is found.
- At least one LNPDB-like file is found.
- Each file has readable extension: `.csv`, `.xlsx`, `.xlsm`, `.xls`.

### 01_build_figure_table_key_map

Purpose: Build one auditable figure/table key decision for each input file/sheet block.

Inputs:

- `input_inventory.csv`
- file path, file name, sheet name, columns, sample rows, and sampled unique values

Outputs:

- `figure_table_key_map.csv`
- `figure_table_key_map_review_flags.csv`

Validation:

- Every readable file/sheet has one map row.
- LLM output, prompt context, evidence, confidence, and fallback method are preserved.
- Ambiguous or missing keys are flagged for review.

### 02_normalize_expvals

Purpose: Convert extracted image tables into one canonical long table.

Inputs:

- files from `F:\내 드라이브\LNPDB_update_1\Supplementrays\expvals`

Outputs:

- `normalized_expvals.csv`
- `normalized_expvals_warnings.csv`

Validation:

- Canonical source/provenance columns exist.
- A canonical value column exists.
- Rows with no value are either dropped with warning or retained with `manual_required=true`.

### 03_normalize_lnpdb

Purpose: Read LNPDB-like tables and preserve all original columns while adding merge helper columns.

Inputs:

- LNPDB-like files under the configured roots

Outputs:

- `normalized_lnpdb_rows.csv`
- `lnpdb_file_inventory.csv`

Validation:

- Original row order and source file/sheet/row provenance are preserved.
- Original columns are not dropped.

### 04_build_match_candidates

Purpose: Generate deterministic candidate matches between LNPDB-like rows and extracted-value rows.

Inputs:

- `normalized_expvals.csv`
- `normalized_lnpdb_rows.csv`

Outputs:

- `merge_candidates.csv`
- `merge_conflicts.csv`
- `merge_unmatched_expvals.csv`
- `merge_unmatched_lnpdb_rows.csv`

Validation:

- Candidate rows include match score, matched fields, and reason.
- Conflicts are separated from accepted one-to-one matches.

### 05_merge_values

Purpose: Insert accepted extracted values into LNPDB-like output rows.

Inputs:

- `merge_candidates.csv`
- `normalized_lnpdb_rows.csv`
- `normalized_expvals.csv`

Outputs:

- `merged_lnpdb_like.csv`
- optional per-source-file merged workbooks/csv files

Validation:

- All original LNPDB-like columns are present.
- Inserted values have provenance columns.
- Existing conflicting values are not overwritten silently.

### 06_validate_merge

Purpose: Validate scientific and structural integrity.

Inputs:

- merged outputs
- candidates/conflicts/unmatched files

Outputs:

- `merge_qc_report.json`
- `merge_review_flags.csv`

Validation:

- JSON parses.
- Review flag counts are reported.
- Inserted row count equals accepted candidate count unless row expansion explains the difference.

## Merge Modes

`fill_existing`:

- Preserve row count.
- Fill value columns only when each LNPDB-like row has exactly one accepted extracted-value match.
- Default for conservative curation.

`long_expand`:

- Allow one LNPDB-like row to expand into multiple rows when multiple image values correspond to different group/condition labels.
- Required when the LNPDB-like row is a figure-level row but the image table has group-level or formulation-level rows.

The CLI must make the selected merge mode explicit in `merge_qc_report.json`.
