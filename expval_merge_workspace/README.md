# Experimental Value Merge Workspace

This workspace defines a CLI that merges figure/image-extracted experimental values into LNPDB-like tables.

It is separate from `agent_workspace` because this is not the article extraction pipeline itself. It is a downstream curation/merge workflow.

## Default Input Roots

Extracted image value files. These are figure/table-specific CSV/Excel source files and are not combined into one source table:

- `F:\내 드라이브\LNPDB_update_1\Supplementrays\expvals`

LNPDB-like target. A run is for one paper and therefore uses one logical target table:

- one CSV/Excel file, or
- one folder containing Excel files to be combined into one target table

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

Never overwrite source spreadsheets. The CLI creates a combined target copy, figure/table partitions, a reusable source-target schema/value mapping plan for each partition, deterministic row matches, per-figure cumulative merge snapshots, a final merged copy, and review reports.
