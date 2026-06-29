# Runbook

Use this runbook when a coding agent starts in the repository.

## 1. Read Project Instructions

Read:

- `README_FOR_CODEX_OR_CLAUDE.md`
- `agent_workspace/AGENT_INSTRUCTIONS.md`
- `agent_workspace/PIPELINE_SPEC.md`
- `agent_workspace/STAGE_CONTRACTS.md`
- `agent_workspace/OUTPUT_SCHEMA.md`
- `agent_workspace/TROUBLESHOOTING.md`

`agent_workspace/legacy_context/` is optional read-only reference context for external agents. Use it only to inspect prior logic, output shapes, and naming conventions. Do not execute or import Gemini/API-dependent scripts from that folder in the active workflow. The context copy is regenerated with:

```bash
python agent_workspace/tools/build_legacy_context.py
```

## 2. Observe State

```bash
python Agent_Task_Runner.py observe --paper-folder "<PAPER_FOLDER>"
```

Also inspect:

- `agent_workspace/agent_state.json`
- `agent_workspace/task_queue.json`
- latest log in `agent_workspace/logs/`
- files under `<PAPER_FOLDER>`

## 3. Find Next Stage

```bash
python Agent_Task_Runner.py next --paper-folder "<PAPER_FOLDER>"
```

If the next stage is `02b_manual_review`, stop and ask a human to run:

```bash
streamlit run 0_mark_down_gen/02B_FT_manual_selector_gui.py -- --paper-folder "<PAPER_FOLDER>"
```

## 4. Run an Eligible Stage

Dry run first when uncertain:

```bash
python Agent_Task_Runner.py run --stage "<STAGE_NAME>" --paper-folder "<PAPER_FOLDER>" --dry-run
```

Then run:

```bash
python Agent_Task_Runner.py run --stage "<STAGE_NAME>" --paper-folder "<PAPER_FOLDER>"
```

Unified extraction:

```bash
python Agent_Task_Runner.py run --stage 06_unified_lnpdb_extraction --paper-folder "<PAPER_FOLDER>"
python Agent_Task_Runner.py validate --stage 06_unified_lnpdb_extraction --paper-folder "<PAPER_FOLDER>"
```

Current 06 behavior extracts condition + formulation rows and may populate experimental assay/readout value columns only from reliable mapped Excel/source-data blocks. Populate `metric_type`, `original_values`, `aggregated_value`, `unit`, and `replicate_type` only when the value is backed by `Exp_Excel_Blocks/`, source-data Excel, `excel_mapping.json`, `excel_mapping_rows.csv`, or a referenced `block_csv_path`.

Do not use graph image digitization, pixel/axis extraction, bar-height estimation, heatmap color estimation, caption-only inferred values, or hallucinated values. If no reliable Excel/source-data mapping exists, leave value columns blank and keep the condition/formulation row.

Condition fields in 06 must be concise LNPDB-style scalar values. Do not place caption prose, semicolon-separated mixed contexts, `or`-merged model/route/method values, or multi-method bundles into condition columns. Split rows by panel/item/block context when conditions differ.

Prefer column-specific examples extracted from existing LNPDB references over generic prompt examples. For `Experiment_method`, preserve assay+readout labels such as `flow_cytometry_CD8_T_cells` when panel identity depends on the measured population/readout.

Optional 06 reference context can be inspected without running extraction:

```bash
python Agent_Task_Runner.py inspect-reference --paper-folder "<PAPER_FOLDER>" --output-json "<OUTPUT_JSON>"
```

The 06 task generator also writes `agent_workspace/tasks/06_reference_context_<paper_name>.json`. Missing LNPDB reference files or human guide files are warnings only.

API-free active-stage sequence:

```bash
python Agent_Task_Runner.py run --stage 03_figure_mapping --paper-folder "<PAPER_FOLDER>"
python Agent_Task_Runner.py run --stage 03_split_excel_blocks_batch --paper-folder "<PAPER_FOLDER>"
python Agent_Task_Runner.py run --stage 04_figure_separate --paper-folder "<PAPER_FOLDER>"
python Agent_Task_Runner.py run --stage 04_ft_excel_matcher --paper-folder "<PAPER_FOLDER>"
python Agent_Task_Runner.py run --stage 05_smiles_structure_resolution --paper-folder "<PAPER_FOLDER>"
python Agent_Task_Runner.py run --stage 06_unified_lnpdb_extraction --paper-folder "<PAPER_FOLDER>"
python Agent_Task_Runner.py run --stage 07_finalize_unified_table --paper-folder "<PAPER_FOLDER>"
```

Stage 05 in the active workflow is text/reference/manual-curated only for SMILES. Do not run DECIMER, MolScribe, `worker_mol.py`, structure-recognition `pipeline.py`, `recognition.py`, `segmentation.py`, or any PDF/image crop-to-SMILES workflow. Image-derived SMILES helper outputs are ignored unless explicitly manual verified. Novel pIL SMILES should remain blank when no exact text/reference/manual-curated SMILES is available.

Current unified outputs intentionally keep all formulation/component SMILES columns blank. Stage 05 artifacts may exist for compound inventory/QC, but Stage 06 and 07 do not project DB/reference/curated/PubChem/OPSIN/CIR/image-derived SMILES into `IL_SMILES`, `HL_SMILES`, `CHL_SMILES`, `PEG_SMILES`, or `Fifth_component_SMILES`. Preserve lipid/component names and molar ratios; blank SMILES are not a review issue by themselves.

Stage 07 writes a normalized three-table evidence structure:

- `unified_extraction_lnpdb_like.csv`: value table with stable `row_id`.
- `markdown_sentence_index/`: table-excluded numbered sentence indexes for source markdown files.
- `unified_extraction_source_evidence.csv`: unique evidence/source objects with stable `evidence_id`, compact `evidence_summary`, and `evidence_sentence_ids` when source markdown support is found.
- `unified_extraction_figure_evidence_map.csv`: figure/item-level links from each evidence sentence/source object to pipe-separated supported LNPDB scientific condition/formulation columns.
- `paper_source_context.json`: source-document registry for the selected paper package, classifying main article, supplementary information, source data, and reporting-summary markdown/PDF sources under the same `Paper_ID`.

This is intentionally not a per-cell evidence table. Later UI jumps can use `row_id + Item_ID + column_name -> figure_evidence_map rows whose supported_columns include column_name -> evidence_id -> source_evidence evidence_sentence_ids -> markdown_sentence_index`. Fuzzy markdown matching is a fallback only when sentence IDs are absent.

One selected paper folder is one paper package. Stage 07 can use global methods/protocol evidence from the main article to support supplementary rows, or vice versa, as long as the sentence IDs come from sources inside the same folder and the context is broadly applicable. Current backfill uses this for LNP preparation fields such as `Aqueous_buffer`, `Dialysis_buffer`, and `Mixing_method`, while excluding PBS/free-drug/free-mRNA/control rows that are not LNP formulations.

Automatic external CLI agent orchestration:

```bash
python Agent_Task_Runner.py run-agent-active --paper-folder "<PAPER_FOLDER>" --agent codex
python Agent_Task_Runner.py run-agent-active --paper-folder "<PAPER_FOLDER>" --agent codex --stream-agent-output
```

Custom command examples:

```bash
python Agent_Task_Runner.py run-agent-active --paper-folder "<PAPER_FOLDER>" --agent custom --agent-command "codex exec --cd \"{project_root}\" --dangerously-bypass-approvals-and-sandbox --add-dir \"{paper_folder}\" -"
python Agent_Task_Runner.py run-agent-active --paper-folder "<PAPER_FOLDER>" --agent custom --agent-command "cmd /c codex exec --cd \"{project_root}\" --dangerously-bypass-approvals-and-sandbox --add-dir \"{paper_folder}\" -"
```

Limit stages or retry behavior:

```bash
python Agent_Task_Runner.py run-agent-active --paper-folder "<PAPER_FOLDER>" --agent codex --stages 03_figure_mapping 04_figure_separate 06_unified_lnpdb_extraction
python Agent_Task_Runner.py run-agent-active --paper-folder "<PAPER_FOLDER>" --agent codex --max-agent-retries 2 --continue-on-error
python Agent_Task_Runner.py run-agent-active --paper-folder "<PAPER_FOLDER>" --agent codex --no-skip-valid
python Agent_Task_Runner.py run-agent-active --paper-folder "<PAPER_FOLDER>" --agent codex --stream-agent-output
```

`run-agent-active` creates task markdown for `external_agent` stages, sends the prompt to the chosen CLI agent through stdin when the command includes `-` or `{prompt_stdin}`, validates outputs, appends validation feedback to the task file on failure, retries up to `--max-agent-retries`, and proceeds stage by stage. Valid stages are skipped by default and logged as `stage_skip_valid`. Use `--stream-agent-output` to see Codex/Claude stdout and stderr in real time while still preserving log tails.

## 5. Validate

```bash
python Agent_Task_Runner.py validate --stage "<STAGE_NAME>" --paper-folder "<PAPER_FOLDER>"
```

If validation fails, read the stage log and troubleshoot before retrying.

## 6. Log and Continue

The runner updates state automatically. If you run a legacy script manually, update:

- `agent_workspace/agent_state.json`
- `agent_workspace/task_queue.json`
- `agent_workspace/logs/<paper-name>.jsonl`

Then call `next` again.
