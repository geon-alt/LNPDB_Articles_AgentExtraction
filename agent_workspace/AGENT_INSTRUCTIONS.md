# Agent Instructions

This repository is an agent workspace for the LNPDB article extraction pipeline. It is not a Python-internal agent framework and it does not introduce a new LLM backend abstraction. Codex CLI, Claude Code, or another coding agent CLI should read these files, inspect the current paper folder, execute the existing scripts, validate outputs, fix or retry when appropriate, and record state.

The default workflow is API-free external CLI agent workflow. Legacy Gemini/API scripts remain available only as compatibility mode and must not be treated as the default path for active judgment stages.

`agent_workspace/legacy_context/` is a read-only legacy-code reference area for external agents. Agents may inspect it to understand prior output shapes, naming conventions, deterministic helper logic, and edge cases, but must not execute or import Gemini/API-dependent legacy scripts in the active workflow. Original legacy folders remain in place for compatibility, and the context copy may be regenerated from those source folders.

## Project Purpose

Process LNPDB article extraction work one paper folder at a time:

- convert source PDFs to markdown
- inventory figures and tables
- classify LNPDB-relevant figure/table candidates
- require human review before active agent automation
- map selected figure/table items to source figures/images/tables
- split Excel sheets into table blocks
- classify/refine Excel blocks
- separate figure panels or important regions
- match selected figure/table items to Excel blocks
- resolve compound names/SMILES without API judgment
- build one unified extraction table for conditions, formulation composition, values, and provenance
- finalize unified outputs with QC

## Agent Role

The coding agent is responsible for this loop:

1. Observe the paper folder and project state.
2. Plan the next stage using `PIPELINE_SPEC.md`, `STAGE_CONTRACTS.md`, and `task_queue.json`.
3. Execute the existing script for that stage.
4. Validate expected outputs.
5. Diagnose failures from logs, files, exceptions, and missing artifacts.
6. Fix code or retry only when the cause is understood.
7. Update `agent_state.json`, `task_queue.json`, and a run log under `agent_workspace/logs/`.
8. Move to the next eligible stage.

For API-free active stages, the agent should read task markdown files under `agent_workspace/tasks/` and produce the expected JSON/CSV outputs directly. In `external_agent` mode, `Agent_Task_Runner.py` creates the task file and records `external_agent_required`; Codex CLI, Claude Code, or another external coding agent then completes the task by reading files, inspecting assets, running API-free helper code, and writing outputs.

`run-agent-active` is the orchestration mode for this API-free workflow. It creates stage task files, invokes an external CLI agent such as Codex or Claude as a subprocess, validates outputs, appends validation feedback to the task file on failure, retries when configured, and then advances to the next active stage. The same no-Gemini/no-API/no-legacy-import rules apply inside the external CLI agent run.

Use `--stream-agent-output` when operators need to watch the external CLI agent's stdout/stderr live during long-running stages.

## Safety Rules

- Do not delete original PDF or Excel files.
- Do not overwrite existing outputs without creating a backup or receiving explicit confirmation.
- Do not hard-code API keys, service account JSON contents, or secrets into code.
- Do not add Gemini/API judgment to new code.
- Do not require `find_api.py`, `LLM_API.py`, `LLM_Batch.py`, Vertex credentials, or Gemini credentials in API-free `external_agent` or `heuristic` mode.
- If judgment is needed in API-free workflow, create or complete a task file so the external CLI agent performs the judgment directly.
- Do not proceed automatically to stage `03_figure_mapping` or later unless the paper folder contains `.manual_select_review_done`.
- Do not treat a successful process exit as sufficient. Validate required output files and basic row/key counts.
- Do not silently skip validation failures. Log them and either fix, retry, or mark the task as blocked for human review.

## Stage Boundary

`00_marker`, `01_make_ft_csv`, `02_ft_selector`, and `02b_manual_review` are pre-agent stages. They prepare source text, inventory, classification, and human confirmation.

`03_figure_mapping`, `03_split_excel_blocks`, `03_split_excel_blocks_batch`, `04_figure_separate`, `04_ft_excel_matcher`, `05_smiles_structure_resolution`, `06_unified_lnpdb_extraction`, and `07_finalize_unified_table` are active agent stages. The coding agent may run these after manual review is complete.

Stage `06_unified_lnpdb_extraction` extracts experimental conditions and formulation composition together, and now may populate `metric_type`, `original_values`, `aggregated_value`, `unit`, and `replicate_type` only from reliable mapped Excel/source-data blocks. Graph image digitization, pixel/axis extraction, heatmap color estimation, caption-only numeric inference, and hallucinated values remain disabled. Populated value rows require Excel/source-data provenance in `evidence_excel`, `block_csv_path`, or related Excel fields.

Stage 06 may include optional LNPDB reference context from existing DB/reference files and human-curated column/value guide files. Use that context only to normalize concise scalar condition/formulation fields; do not treat existing values as a closed vocabulary. Prefer column-specific existing LNPDB examples over generic examples; for `Experiment_method`, preserve readout-specific labels such as `flow_cytometry_CD8_T_cells` when that is the established style. Missing reference context is not a blocker. Reference context never permits prose condition fields: split rows when conditions differ, and keep source prose in `evidence_text`.

The current active workflow completely excludes molecule-structure-image-based SMILES extraction. Do not run or use DECIMER, MolScribe, `worker_mol.py`, structure-recognition `pipeline.py`, `recognition.py`, `segmentation.py`, molecule image crops, or image-derived SMILES outputs. Stage 05 may still produce compound inventory / SMILES QC artifacts, but Stage 06 and 07 must not project any SMILES into `unified_extraction.csv`, `unified_extraction_final.csv`, or `unified_extraction_lnpdb_like.csv`. Preserve component names and molar ratios, force `IL_SMILES`, `HL_SMILES`, `CHL_SMILES`, `PEG_SMILES`, and `Fifth_component_SMILES` blank, and do not treat blank output SMILES as a manual-review issue.

Stage 07 finalization writes the LNPDB-like value table separately from source evidence. It also builds `markdown_sentence_index/` from source markdown files, excluding markdown table regions, and uses numbered global sentence IDs such as `QS_2026:S000145` as the primary text-evidence anchor. Use `unified_extraction_source_evidence.csv` for unique evidence/source objects with `evidence_summary` and `evidence_sentence_ids`, and `unified_extraction_figure_evidence_map.csv` for grouped figure/item evidence mappings from each evidence source object to supported LNPDB scientific condition/formulation columns. Do not require noisy per-cell mappings for administrative/provenance columns.

Treat one selected `paper_folder` as one paper-level document package. Multiple markdown/PDF sources under that folder, including main article and supplementary information, share the same `Paper_ID` unless explicitly marked otherwise. Stage 07 may use global methods/protocol evidence from any source document in the same paper package to support condition/formulation rows from another source document, but only for broadly applicable context such as LNP preparation, formulation composition rules, dosing protocols, or assay methods. Source provenance must still record the sentence IDs/source document that supplied the evidence.

For the API-free workflow, use `03_figure_mapping`, `03_split_excel_blocks_batch`, `04_figure_separate`, `04_ft_excel_matcher`, `05_smiles_structure_resolution`, and `06_unified_lnpdb_extraction` in `external_agent` mode where judgment is needed; `07_finalize_unified_table` defaults to `heuristic`. These modes must not import the legacy Gemini scripts:

- `0_mark_down_gen/03_figure_mapping.py`
- `0_mark_down_gen/03_split_excel_blocks_batch.py`
- `0_mark_down_gen/04_figure_saperate_gemini.py`
- `0_mark_down_gen/04_FT-Excel_matcher.py`
- scripts under `1_Extract_Exp_Figs/`
- scripts under `2_Extract_SMILES/`
- scripts under `3_Extract_Formula_by_Figs/`
- scripts under `4_Extract_Exp_Vals/`

Legacy mode is a compatibility mode for running the old Gemini/API scripts and may require the old credential files and helper modules.

When external-agent task markdown lists `## Legacy context files`, those paths are informational only. Read them as context; `AGENT_INSTRUCTIONS.md`, `PIPELINE_SPEC.md`, `STAGE_CONTRACTS.md`, and `OUTPUT_SCHEMA.md` override legacy behavior.

## Required Human Intervention

Stop and request human review when any of the following is true:

- `.manual_select_review_done` is missing.
- The selected figure/table rows are ambiguous or empty but source content clearly contains relevant data.
- Output validation fails repeatedly after a retry.
- Source figure/table content and extracted/mapped result clearly disagree.
- The code needs credentials or cloud resources that are not configured locally.
- A stage would overwrite important prior output and no backup exists.

## Default Behavior Loop

Use this loop for every task:

```text
observe -> plan -> act -> validate -> log -> next
```

Before acting, read the current state:

- `agent_workspace/agent_state.json`
- `agent_workspace/pipeline_manifest.json`
- `agent_workspace/task_queue.json`
- latest file under `agent_workspace/logs/`

Then inspect the target paper folder directly. Prefer concrete evidence from files over assumptions.

## Logging Expectations

Every meaningful action should be reflected in machine-readable state and human-readable logs:

- stage started
- command or callable used
- important inputs found or missing
- outputs created
- validation result
- failure reason
- retry count
- next recommended action

Use `Agent_Task_Runner.py` when possible because it writes JSON logs and state automatically. If you execute scripts manually, update the same state files yourself.

For automated active-stage execution, prefer:

```bash
python Agent_Task_Runner.py run-agent-active --paper-folder "<PAPER_FOLDER>" --agent codex
```
