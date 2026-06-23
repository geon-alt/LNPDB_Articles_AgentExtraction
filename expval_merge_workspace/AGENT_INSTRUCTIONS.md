# Agent Instructions

This workspace is for building and operating a local CLI with optional LLM-based figure/table key classification that merges two kinds of local files:

1. Figure/image-extracted experimental value tables.
2. User-curated LNPDB-like tables.

The purpose is to insert extracted experimental values into the LNPDB-like rows using both table metadata and extracted image table metadata.

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
- Always write outputs to a separate output directory.
- Always keep provenance columns for every inserted value.
- Do not match rows using numeric values alone.
- Do not overwrite an existing non-empty LNPDB-like value unless the old and new values are equivalent after numeric normalization.
- Treat `experimental_value` as the only fillable target value column.
- Use all other non-empty target row cells as flexible matching context, regardless of their column names.
- If a row has multiple plausible matches, do not choose silently; write it to conflict/review output.
- If a value cannot be traced to `source_file`, `source_sheet`, and source row, do not insert it.
- Preserve all original LNPDB-like columns in output.
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
