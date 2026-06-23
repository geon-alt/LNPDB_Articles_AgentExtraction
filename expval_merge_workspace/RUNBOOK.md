# Runbook

Use this runbook for the future merge CLI.

## 1. Read Rules

Read:

- `expval_merge_workspace/AGENT_INSTRUCTIONS.md`
- `expval_merge_workspace/MERGE_CLI_SPEC.md`
- `expval_merge_workspace/INPUT_SCHEMA.md`
- `expval_merge_workspace/MATCHING_RULES.md`
- `expval_merge_workspace/OUTPUT_SCHEMA.md`
- `expval_merge_workspace/TROUBLESHOOTING.md`

## 2. Observe Inputs

Default paths:

```bash
python Expval_Merge_Runner.py observe ^
  --expval-root "F:\내 드라이브\LNPDB_update_1\Supplementrays\expvals" ^
  --lnpdb-root "F:\내 드라이브\LNPDB_update_1\Supplementrays" ^
  --lnpdb-root "F:\내 드라이브\LNPDB_update_1\Source_head_tail_separated_f" ^
  --lnpdb-root "F:\내 드라이브\LNPDB_update_1\Source_DOI_added_f" ^
  --output-root "F:\내 드라이브\LNPDB_update_1\expval_merge_outputs"
```

Expected output:

- `input_inventory.csv`
- `observe_report.json`

## 3. Build Figure/Table Key Map

Heuristic only:

```bash
python Expval_Merge_Runner.py build-key-map --config expval_merge_workspace/merge_manifest.json
```

With OpenAI:

```bash
python Expval_Merge_Runner.py build-key-map --config expval_merge_workspace/merge_manifest.json --llm-provider openai --llm-model gpt-4.1-mini
```

Check:

- `figure_table_key_map.csv`
- `figure_table_key_map_review_flags.csv`

## 4. Normalize

```bash
python Expval_Merge_Runner.py normalize-expvals --config expval_merge_workspace/merge_manifest.json
python Expval_Merge_Runner.py normalize-lnpdb --config expval_merge_workspace/merge_manifest.json
```

Check:

- `normalized_expvals.csv`
- `normalized_lnpdb_rows.csv`
- warnings files

## 5. Build Match Candidates

```bash
python Expval_Merge_Runner.py build-candidates --config expval_merge_workspace/merge_manifest.json
```

Review:

- `partition_inventory.csv`
- `partitioned/expvals/...`
- `partitioned/lnpdb_like/...`
- `merge_candidates.csv`
- `merge_conflicts.csv`
- `merge_unmatched_expvals.csv`
- `merge_unmatched_lnpdb_rows.csv`

Do not proceed if high-severity conflicts are unexpected.

## 6. Merge

Conservative default:

```bash
python Expval_Merge_Runner.py merge --config expval_merge_workspace/merge_manifest.json --mode fill_existing
```

Allow row expansion only when the target LNPDB-like table is figure-level and extracted values are group-level:

```bash
python Expval_Merge_Runner.py merge --config expval_merge_workspace/merge_manifest.json --mode long_expand
```

## 7. Validate

```bash
python Expval_Merge_Runner.py validate --config expval_merge_workspace/merge_manifest.json
```

Expected:

- `merge_qc_report.json`
- `merge_review_flags.csv`
- merged output file parses

## 8. Human Review

Open:

- `figure_table_key_map_review_flags.csv`
- `merge_conflicts.csv`
- `merge_review_flags.csv`
- `merge_unmatched_expvals.csv`

Resolve conflicts in a separate manual review file. Do not edit original extracted-value or LNPDB-like source files directly.
