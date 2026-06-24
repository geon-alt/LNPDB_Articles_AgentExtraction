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

## `merge_candidates.csv`

Columns:

```text
candidate_id
lnpdb_row_id
expval_id
match_tier
lnpdb_partition_key
expval_partition_key
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
- Insert values only into `experimental_value`.
- Fill only rows where `experimental_value` is blank.
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
