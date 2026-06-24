# Output Schema

The merge CLI must write all outputs under the configured output root.

## `input_inventory.csv`

Columns:

```text
file_role
source_file
extension
file_size_bytes
sheet_count
readable
error
```

`file_role` values:

- `expval`
- `lnpdb_like`

For `lnpdb_like`, a valid one-paper run has either one target file row or multiple Excel file rows from one target folder.

## `combined_lnpdb_target.csv`

The logical target table for the paper.

Behavior:

- written for both single-file and Excel-folder target inputs
- preserves all original target columns
- adds target provenance helper columns:

```text
__target_source_file
__target_source_sheet
__target_source_row
__target_combined_row_id
```

## `target_combine_report.json`

Summary of target files and combined row count.

## `normalized_expvals.csv`

Required columns are listed in `INPUT_SCHEMA.md` under canonical extracted-value columns.

Validation:

- CSV parses.
- `expval_id`, `source_file`, `source_row`, `source_table_type`, and `value_text` exist.
- Rows with insertable values have non-empty `value` or `value_text`.

## `figure_table_key_map.csv`

One row per input file/sheet block.

Columns:

```text
role
source_file
source_sheet
row_count
inferred_key
confidence
method
evidence
raw_llm_response
prompt_json
needs_review
review_reason
```

`method` is `heuristic`, `codex:<model>`, `openai:<model>`, or `heuristic_after_llm_failed`.

## `figure_table_key_map_review_flags.csv`

Rows requiring manual review before trusting the partition.

## `normalized_lnpdb_rows.csv`

Required columns are listed in `INPUT_SCHEMA.md` under canonical LNPDB row columns.

Validation:

- CSV parses.
- `lnpdb_row_id`, `source_file`, and `source_row` exist.
- Original row payload is preserved in `raw_columns_json`.

## `partition_inventory.csv`

Rows are split and saved before matching.

Columns:

```text
role
partition_key
paper_key
figure_key
row_count
id_column
partition_file
```

Partition CSVs are written under:

```text
partitioned/expvals/<figure_or_table_key>.csv
partitioned/lnpdb_like/<figure_or_table_key>.csv
```

Partition CSVs include the original input columns plus canonical provenance/helper columns.

## `partition_mapping_rules.json`

One reusable schema/value mapping plan per figure/table partition:

```text
source_value_column
target_value_column
relations
fixed_target_values
confidence
needs_review
reason
method
```

Each relation can connect one or more source columns to one or more target columns and can contain explicit source/target value tuples.

## `partition_mapping_rules.csv`

Human-readable mapping-plan summary with the complete plan in `mapping_plan_json`.

## `merge_candidates.csv`

Columns:

```text
candidate_id
lnpdb_row_id
expval_id
match_tier
lnpdb_partition_key
expval_partition_key
source_value_column
target_value_column
match_score
match_confidence
matched_fields
match_reason
accepted
manual_required
conflict_reason
```

Validation:

- Accepted candidates have exactly one `lnpdb_row_id` and one `expval_id`.
- `matched_fields` and `match_reason` are non-empty.

## `merged_lnpdb_like.csv`

Required behavior:

- Preserve all original LNPDB-like columns.
- Add the provenance columns from `MATCHING_RULES.md`.
- Insert values only into the partition plan's selected `target_value_column`.
- Fill only rows where that selected target value column is blank.
- Do not fill `original_values`, `aggregated_value`, `Value`, `value`, or other value-like columns.
- Preserve original row identity through `lnpdb_row_id`.

Required added columns:

```text
lnpdb_row_id
experimental_value
merged_experimental_value
expval_source_file
expval_source_sheet
expval_source_row
expval_source_table_type
expval_value_column
expval_value_text
expval_x_pixel
expval_y_pixel
expval_x_center
expval_y_center
expval_match_score
expval_match_confidence
expval_match_reason
expval_manual_required
```

If an existing value column is filled, `merged_experimental_value` may mirror that value for audit.

## `merge_progress_manifest.csv`

One row per source figure/table partition in merge order.

Columns:

```text
step
partition_key
source_files
accepted_candidates
inserted_this_step
cumulative_inserted
snapshot_file
```

## `merge_progress/<step>_<figure_or_table_key>.csv`

Cumulative intermediate target table after applying one figure/table source partition.

Example:

```text
merge_progress/001_figure_1.csv
merge_progress/002_figure_2.csv
merge_progress/003_figure_3.csv
```

These files are intended to verify that experimental values are progressively filled figure by figure.

## `merge_conflicts.csv`

Columns:

```text
conflict_id
lnpdb_row_id
expval_id
conflict_type
conflict_reason
candidate_ids
existing_value_text
extracted_value_text
existing_unit
extracted_unit
review_action
```

## `merge_unmatched_expvals.csv`

Columns:

```text
expval_id
source_file
source_sheet
source_row
figure_name
item_id
label_summary
value_text
reason
```

## `merge_unmatched_lnpdb_rows.csv`

Columns:

```text
lnpdb_row_id
source_file
source_sheet
source_row
item_id
figure_name
label_summary
existing_value_text
reason
```

## `merge_review_flags.csv`

Columns:

```text
flag_id
severity
lnpdb_row_id
expval_id
field
issue
reason
recommended_action
```

## `merge_qc_report.json`

Expected keys:

```json
{
  "schema_version": 1,
  "merge_mode": "fill_existing",
  "expval_files_seen": 0,
  "lnpdb_files_seen": 0,
  "normalized_expval_rows": 0,
  "normalized_lnpdb_rows": 0,
  "accepted_matches": 0,
  "merged_rows": 0,
  "conflict_rows": 0,
  "unmatched_expval_rows": 0,
  "unmatched_lnpdb_rows": 0,
  "manual_required_rows": 0,
  "output_files": [],
  "warnings": []
}
```
