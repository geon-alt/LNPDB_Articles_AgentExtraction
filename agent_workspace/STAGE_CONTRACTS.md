# Stage Contracts

Contracts define what an external CLI agent must check before and after running a stage. Use `<PAPER_FOLDER>` for the target paper folder or root folder being processed.

`agent_workspace/legacy_context/` is a read-only copy/index for external-agent reference. It may be used to inspect prior helper logic, output shapes, and naming conventions, but it is not an active runtime path. Active stage contracts, `AGENT_INSTRUCTIONS.md`, and `OUTPUT_SCHEMA.md` override legacy behavior. Do not execute or import Gemini/API-dependent legacy scripts from this folder unless the operator explicitly requests legacy mode.

## 00_marker

Inputs:
- required: PDF files under `<PAPER_FOLDER>`
- optional: existing markdown files for comparison

Command:
```bash
python Agent_Task_Runner.py run --stage 00_marker --paper-folder "<PAPER_FOLDER>"
```

Direct legacy script caution:
```bash
python 0_mark_down_gen/00_Marker.py
```
The legacy script currently uses a hard-coded path in its `__main__` block. Prefer the task runner or edit only the execution wrapper if direct execution is needed.

Outputs:
- `.md` files

Validation:
- Find at least one non-empty `.md` file.
- Log generated markdown paths.

Failure handling:
- Check PDF readability, Marker install, and hard-coded paths.

## 01_make_ft_csv

Inputs:
- required: `.md` or `.pdf` files
- optional: API credential files expected by existing code

Command:
```bash
python Agent_Task_Runner.py run --stage 01_make_ft_csv --paper-folder "<PAPER_FOLDER>"
```

Outputs:
- `fig_table_inventory.csv`

Validation:
- CSV exists and has rows.
- CSV has an item identifier column.

Failure handling:
- Check markdown presence, token/API errors, and CSV parse problems.

## 02_ft_selector

Inputs:
- required: `fig_table_inventory.csv`, source markdown/PDF
- optional: API credential files expected by existing code

Command:
```bash
python Agent_Task_Runner.py run --stage 02_ft_selector --paper-folder "<PAPER_FOLDER>"
```

Outputs:
- `fig_table_lnpdb_classified.csv`
- optional `fig_table_lnpdb_usage.csv`

Validation:
- Classified CSV exists and has rows.
- Item IDs from inventory are preserved or traceable.

Failure handling:
- Check missing inventory, API errors, malformed LLM output, and item count mismatch.

## 02b_manual_review

Inputs:
- required: `fig_table_lnpdb_classified.csv`
- optional: source PDF/images for human inspection

Command:
```bash
streamlit run 0_mark_down_gen/02B_FT_manual_selector_gui.py -- --paper-folder "<PAPER_FOLDER>"
```

Outputs:
- `.manual_select_review_done`
- `fig_table_lnpdb_classified_manual_reviewed.csv` or updated `fig_table_lnpdb_classified.csv`

Validation:
- Marker file exists.
- `manual_select` column exists or reviewed copy exists.

Failure handling:
- Stop automation and request human review.

## 03_figure_mapping

Inputs:
- required: `.manual_select_review_done`, reviewed/classified CSV, source image/table assets
- optional: `fig_table_lnpdb_classified_manual_reviewed.csv`

Command:
```bash
python Agent_Task_Runner.py run --stage 03_figure_mapping --paper-folder "<PAPER_FOLDER>"
```

Outputs:
- `total_figure_mapping.json`
- optional debug CSVs such as `figure_mapping_excel_covered_excluded.csv`

Validation:
- Mapping JSON exists.
- JSON parses successfully.
- It contains at least one non-empty mapping when selected rows exist.

Failure handling:
- Check selected rows, source folders, image paths, API credentials, and whether the script scanned the intended root.

## 03_split_excel_blocks

Inputs:
- required: Excel workbook/sheet files, usually under `Exp_Excel`
- optional: `fig_table_inventory.csv`

Command:
```bash
python Agent_Task_Runner.py validate --stage 03_split_excel_blocks --paper-folder "<PAPER_FOLDER>"
```

Outputs:
- No primary artifact from this file alone in the current repository.

Validation:
- Import of `0_mark_down_gen/03_split_excel_blocks.py` succeeds.
- Excel files are discoverable.

Failure handling:
- Treat as utility-stage failure and run/fix `03_split_excel_blocks_batch` only after import and input checks pass.

## 03_split_excel_blocks_batch

Inputs:
- required: `.manual_select_review_done`, `Exp_Excel/`, source markdown/PDF, `fig_table_inventory.csv`
- optional: existing `_batch_jobs/` records

Command:
```bash
python Agent_Task_Runner.py run --stage 03_split_excel_blocks_batch --paper-folder "<PAPER_FOLDER>"
```

Outputs:
- `excel_block_inventory.csv`
- `three_core_result_all.json`
- `Exp_Excel_Blocks/`
- optional `excel_block_usage_inventory.csv`

Validation:
- Inventory CSV exists.
- Every non-empty `block_csv_path` points to an existing file under `<PAPER_FOLDER>`.
- `Exp_Excel_Blocks/` exists when inventory has rows.

Failure handling:
- Check `Exp_Excel`, openpyxl/pandas dependencies, Vertex/GCS batch logs, and partial `_batch_jobs/` output.

## 04_figure_separate

Inputs:
- required: `.manual_select_review_done`, `total_figure_mapping.json`, source images or source PDF/page metadata
- optional: reviewed classified CSV

Command:
```bash
python Agent_Task_Runner.py run --stage 04_figure_separate --paper-folder "<PAPER_FOLDER>"
```

Legacy script path:
```bash
python 0_mark_down_gen/04_figure_saperate_gemini.py
```

Outputs:
- `separated_panels_gemini/`
- optional `pdf_page_renders/` with rendered fallback PDF pages
- updated `total_figure_mapping.json`
  - optional `fallback_render`
  - optional `selected_source_for_paneling`
  - optional `source_quality="pdf_page_render_fallback"`
  - optional `manual_required=true`

Validation:
- JSON parses.
- Panel paths recorded in JSON exist when present.
- `fallback_render` and `selected_source_for_paneling` paths exist when present.
- Output folders contain readable image files for processed mappings.

Failure handling:
- Check filename typo, mapping keys, source image readability, PyMuPDF availability for fallback render, OpenCV, and Gemini/Vertex batch output.
- Treat Marker image crops as primary candidates only; if a crop is suspect, render the PDF page and set `manual_required=true` when boundaries remain unclear.

## 04_ft_excel_matcher

Inputs:
- required: `.manual_select_review_done`, `fig_table_lnpdb_classified.csv`, `fig_table_inventory.csv`, `excel_block_inventory.csv`
- optional: source PDFs and `_batch_jobs/`

Command:
```bash
python Agent_Task_Runner.py run --stage 04_ft_excel_matcher --paper-folder "<PAPER_FOLDER>"
```

Outputs:
- `excel_mapping.json`
- `excel_mapping_rows.csv`
- updated `fig_table_lnpdb_classified.csv`
- optional `04_excel_match_batch_usage.csv`

Validation:
- `excel_mapping.json` parses.
- `excel_mapping_rows.csv` exists.
- Non-empty matched block paths exist under `<PAPER_FOLDER>`.

Failure handling:
- Check block inventory, selected FT rows, batch result parse errors, and normalized FT IDs.

## 05_smiles_structure_resolution

Inputs:
- required: `.manual_select_review_done`, markdown/PDF sources
- optional: `total_figure_mapping.json`, local LNPDB reference files, text/IUPAC extraction outputs, manually curated/manual-verified SMILES files

Command:
```bash
python Agent_Task_Runner.py run --stage 05_smiles_structure_resolution --paper-folder "<PAPER_FOLDER>"
```

Outputs:
- `compound_inventory_standardized.csv`
- `smiles_resolved.csv`
- `smiles_resolution_qc.csv`

Validation:
- `smiles_resolved.csv` parses.
- It includes `Name` or `compound_id`.
- It includes `SMILES` or `resolved_smiles`.
- Non-empty SMILES must not come from DECIMER, MolScribe, `worker_mol.py`, structure image crops, image recognition, `recognition.py`, or `segmentation.py` unless explicitly manual verified.
- Novel pIL SMILES remain blank unless exact text/reference/manual-curated mapping exists.
- Stage 05 artifacts may exist for compound inventory/QC, but current Stage 06/07 unified outputs force all formulation/component SMILES columns blank.

Failure handling:
- Check deterministic text/name/IUPAC tools or references such as OPSIN, PubChem, CIR, existing LNPDB references, and manual-curated files.
- Mark unresolved or ambiguous compounds with `manual_required=true`.
- Do not call Gemini/API helpers or image-based structure-recognition helpers.

## 06_unified_lnpdb_extraction

Inputs:
- required: `.manual_select_review_done`, `fig_table_lnpdb_classified.csv`, `total_figure_mapping.json`, `excel_mapping.json`, `excel_block_inventory.csv`, `Exp_Excel_Blocks/`, markdown files
- optional: `separated_panels_gemini/`, `compound_inventory_standardized.csv`, `text_extracted_iupac.csv`, `smiles_resolved.csv`. `smiles_resolved.csv` is optional QC context only and must not populate unified output SMILES columns. Do not use image-based structure-recognition outputs from `2_Extract_SMILES/FromImage/`.
- optional reference context: existing LNPDB DB/reference files and human-curated column/value guides discovered from the paper folder, `agent_workspace/reference/`, guide folders, or `LNPDB_REFERENCE_ROOT` / `LNPDB_COLUMN_GUIDE_ROOT` / `LNPDB_SCHEMA_GUIDE_ROOT` / `LNPDB_VALUE_GUIDE_ROOT`

Purpose:
- Extract experimental conditions and formulation composition together into one unified long table.
- Experimental numeric assay/readout values may be populated only from reliable mapped Excel/source-data blocks.
- Excel blocks may be used for sheet/block identity, labels, headers, formulation names, group labels, condition context, provenance, and source-data assay/readout values.
- Figure-image graph digitization, pixel/axis extraction, heatmap color estimation, caption-only inferred numeric values, and hallucinated values are disallowed.
- `IL_SMILES`, `HL_SMILES`, `CHL_SMILES`, `PEG_SMILES`, and `Fifth_component_SMILES` must remain blank. Blank output SMILES are expected and are not a manual-review issue by themselves.
- Optional reference context may guide concise scalar LNPDB-style normalization. Human-curated definitions outrank existing-value frequency examples, and column-specific existing LNPDB examples outrank generic examples. Absence of reference context must not block execution.
- `Experiment_method` may be a readout-specific scalar such as `flow_cytometry_CD8_T_cells` when that matches existing LNPDB style; do not collapse readout-specific panels to generic `flow_cytometry`.
- Reference context does not permit prose fields. Condition fields must be scalar values; split rows when one caption/panel group contains multiple models, routes, doses, or methods.

Command:
```bash
python Agent_Task_Runner.py run --stage 06_unified_lnpdb_extraction --paper-folder "<PAPER_FOLDER>"
```

Outputs:
- `unified_extraction.csv`
- `unified_extraction.json`
- `unified_extraction_review_flags.csv`
- `agent_workspace/tasks/06_reference_context_<paper_name>.json` when the 06 external-agent task is generated

Validation:
- `unified_extraction.csv` parses.
- Required unified columns exist.
- `Item_ID`, `confidence`, and `manual_required` exist.
- At least one row exists when selected items exist.
- `unified_extraction_review_flags.csv` exists.
- Populated `metric_type`, `original_values`, `aggregated_value`, `unit`, and `replicate_type` rows must have Excel/source-data provenance.
- `original_values` and `aggregated_value` must be numeric-like unless a future explicitly categorical metric is enabled.
- `IL_SMILES`, `HL_SMILES`, `CHL_SMILES`, `PEG_SMILES`, and `Fifth_component_SMILES` must be empty in `unified_extraction.csv`.
- `Model` must be blank, `N/A`, `in_vitro`, `in_vivo`, or `ex_vivo`.
- `Experiment_batching` must be blank, `N/A`, `individual`, `barcoded`, `pooled`, or `grouped`.
- `Dose_ug_nucleicacid` must be blank/`N/A` or numeric-like only.
- Condition columns must not contain obvious prose or mixed-context patterns such as semicolons, panel phrases, `or`-merged contexts, or multi-method slash bundles.
- Figure 4G-M style groups must not collapse multiple spleen flow-cytometry readouts to identical `Experiment_method=flow_cytometry`.

Failure handling:
- Check selected FT rows and Excel mappings.
- Check `block_csv_path` files under `Exp_Excel_Blocks/`.
- Use Excel blocks for context/provenance and source-data values, figures/images for labels and visual context only, and markdown for methods/caption context.
- Leave uncertain fields blank with `manual_required=true`.

## 07_finalize_unified_table

Inputs:
- required: `.manual_select_review_done`, `unified_extraction.csv`, `unified_extraction_review_flags.csv`

Command:
```bash
python Agent_Task_Runner.py run --stage 07_finalize_unified_table --paper-folder "<PAPER_FOLDER>"
```

Outputs:
- `markdown_sentence_index/markdown_sentence_index_all.csv`
- `markdown_sentence_index/markdown_sentence_index_manifest.json`
- `paper_source_context.json`
- `unified_extraction_final.csv`
- `unified_extraction_lnpdb_like.csv`
- `unified_extraction_source_evidence.csv`
- `unified_extraction_figure_evidence_map.csv`
- `unified_extraction_qc_report.json`

Validation:
- Final and LNPDB-like CSVs parse.
- Final and LNPDB-like CSVs contain non-empty unique `row_id` values.
- Source evidence CSV parses, has non-empty unique `evidence_id` values, and stores unique evidence/source objects.
- Markdown sentence index CSV parses when markdown files exist, and `global_sentence_id` values are unique.
- Source evidence includes compact `evidence_summary`, `evidence_sentence_ids` when indexed text support is found, and optional `evidence_sentence_texts`.
- Figure evidence map CSV parses and connects each `Item_ID + evidence_id` pair to pipe-separated supported LNPDB scientific condition/formulation columns.
- `supported_columns` contains only allowed scientific condition/formulation/value columns, not administrative/provenance columns.
- Any non-empty `evidence_sentence_ids` in source evidence or figure evidence map rows resolve to `markdown_sentence_index_all.csv`.
- `paper_source_context.json` classifies markdown/PDF source documents under the selected paper folder as one paper package. Global methods evidence may cross source documents within that package when it supports broadly applicable LNP preparation, formulation, dosing, or method context.
- LNP rows with populated `Aqueous_buffer`, `Dialysis_buffer`, or `Mixing_method` should have sentence-backed global methods evidence. PBS/free-drug/free-mRNA/control rows are not backfilled with LNP preparation evidence unless explicitly formulated as LNPs.
- Each `Item_ID` with non-empty scientific condition/formulation columns has at least one grouped evidence map row unless it is a manual-review placeholder.
- QC report JSON parses.

Failure handling:
- Fix required columns in `unified_extraction.csv`.
- Check markdown sentence index generation if sentence IDs do not resolve.
- Check source evidence and figure evidence map referential integrity.
- Review low-confidence and manual-required rows before treating final outputs as curated.
