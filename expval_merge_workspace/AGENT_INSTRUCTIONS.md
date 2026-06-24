# Agent Instructions

This workspace is for building and operating a local CLI with optional LLM-based figure/table key classification that merges two kinds of local files:

1. Figure/image-extracted experimental value tables.
2. User-curated LNPDB-like tables.

The purpose is to insert extracted experimental values into one paper-level LNPDB-like target table using both target table metadata and extracted image table metadata.

One run has one logical target: a single CSV/Excel file or a folder of target Excel files that must be combined. Experimental-value sources are multiple figure/table CSV files and should remain separate until partition matching.

## Agent Role

Use this loop:

```text
observe -> normalize -> match -> merge -> validate -> report
```

Before implementing or running the merge CLI, read:

- `MERGE_CLI_SPEC.md`
- `INPUT_SCHEMA.md`
- `MATCHING_RULES.md`
- `OUTPUT_SCHEMA.md`
- `RUNBOOK.md`
- `TROUBLESHOOTING.md`

## Safety Rules

- Do not modify original extracted-value files.
- Do not modify original LNPDB-like files.
- Treat each run as one paper with one logical target table.
- If the target input is a folder, combine its Excel files into `combined_lnpdb_target.csv`.
- Always write outputs to a separate output directory.
- Always keep provenance columns for every inserted value.
- Do not match rows using numeric values alone.
- Do not overwrite an existing non-empty LNPDB-like value unless the old and new values are equivalent after numeric normalization.
- Select one source value column and one target value column per figure/table partition before row matching.
- Map source and target columns using column meaning and observed values, including many-to-one and one-to-many column relationships.
- If a row has multiple plausible matches, do not choose silently; write it to conflict/review output.
- If a value cannot be traced to `source_file`, `source_sheet`, and source row, do not insert it.
- Preserve all original LNPDB-like columns in output.
- Save cumulative merge snapshots after each source figure/table partition.
- Tolerate extra columns in both input file types.
- Prefer deterministic matching. Fuzzy matching is allowed only as a last step and must be logged with confidence and reason.
- Do not use Gemini, Vertex, OpenAI API, web APIs, or credential-based services for this merge workflow.

## Required Evidence For Inserted Values

Every inserted value must record:

- source extracted-value file
- source sheet when applicable
- source row number
- source value column used
- figure/item identifier or inferred figure/item identifier
- label/group/condition evidence used for matching
- match confidence
- match reason

## Human Review Gates

Stop or flag for review when:

- LNPDB-like target rows have no stable identifier such as DOI, paper ID, figure ID, item ID, metric, condition, or formulation.
- More than one extracted-value row matches a single target row.
- More than one target row matches a single extracted-value row and row expansion is disabled.
- Existing LNPDB-like value conflicts with the extracted value.
- Image table lacks enough label/group/context columns to map safely.
- Unit or metric interpretation is unclear.
