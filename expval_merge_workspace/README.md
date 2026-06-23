# Experimental Value Merge Workspace

This workspace defines the rules for a future CLI that merges figure/image-extracted experimental values into LNPDB-like tables.

It is separate from `agent_workspace` because this is not the article extraction pipeline itself. It is a downstream curation/merge workflow.

## Default Input Roots

Extracted image value files:

- `F:\내 드라이브\LNPDB_update_1\Supplementrays\expvals`

LNPDB-like table search roots:

- `F:\내 드라이브\LNPDB_update_1\Supplementrays`
- `F:\내 드라이브\LNPDB_update_1\Source_head_tail_separated_f`
- `F:\내 드라이브\LNPDB_update_1\Source_DOI_added_f`

## Documents

- `AGENT_INSTRUCTIONS.md`: global rules for agents and the CLI.
- `MERGE_CLI_SPEC.md`: intended CLI stages and commands.
- `INPUT_SCHEMA.md`: accepted extracted-value and LNPDB-like input shapes.
- `MATCHING_RULES.md`: deterministic matching and conflict rules.
- `OUTPUT_SCHEMA.md`: required output files and columns.
- `RUNBOOK.md`: operator workflow.
- `TROUBLESHOOTING.md`: common failures and fixes.
- `merge_manifest.json`: machine-readable stage manifest.

## Core Principle

Never overwrite source spreadsheets. The CLI must create a merged copy, normalized intermediate tables, and review reports so every inserted value can be audited back to its extracted image table row.
