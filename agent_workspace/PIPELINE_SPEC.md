# Pipeline Specification

This document defines the pipeline stages that external coding agents should follow. Existing code stays in `0_mark_down_gen/`; do not move it.

Legacy Gemini/API-assisted scripts under `1_Extract_Exp_Figs/`, `2_Extract_SMILES/`, `3_Extract_Formula_by_Figs/`, and `4_Extract_Exp_Vals/` are preserved for manual legacy mode only. The default API-free workflow uses external CLI agent task files or deterministic heuristics and must not require `find_api.py`, `LLM_API.py`, `LLM_Batch.py`, Vertex/Gemini credentials, or hard-coded API keys.

`agent_workspace/legacy_context/` is a read-only context copy/index for external agents. It may be inspected to understand old implementation logic, expected output shapes, and naming conventions, but active stages must not execute or import Gemini/API-dependent legacy scripts unless the operator explicitly requests legacy mode. The original legacy folders remain in place, and `agent_workspace/tools/build_legacy_context.py` can regenerate the context copy.

## PRE_AGENT_STAGES

### 00_marker

- Purpose: Convert source PDFs to markdown.
- Script: `0_mark_down_gen/00_Marker.py`
- Required input files: one or more `.pdf` files in the target root or paper folder.
- Expected output files: one or more `.md` files generated beside or under the processed PDF folder.
- Success criteria:
  - At least one markdown file exists.
  - Markdown files are non-empty.
- If failed, check:
  - PDF files exist and are readable.
  - Marker dependencies are installed.
  - Script still contains a hard-coded test path and may need a wrapper or code edit before use.
- Retry: Yes, after fixing path/dependency issues.

### 01_make_ft_csv

- Purpose: Build a figure/table inventory from PDF/markdown content.
- Script: `0_mark_down_gen/01_make_FT_csv.py`
- Required input files: `.md` or `.pdf` files.
- Expected output files: `fig_table_inventory.csv` or equivalent inventory CSV.
- Success criteria:
  - Inventory CSV exists.
  - It has at least one row for papers with visible figures/tables.
  - It has an item identifier column such as `item_id`, `pdf_item_id`, or `item`.
- If failed, check:
  - Markdown from stage 00 exists.
  - Existing Gemini/Vertex credentials are available.
  - Token limit errors or malformed LLM responses.
- Retry: Yes, after fixing API/config/input issues.

### 02_ft_selector

- Purpose: Classify figure/table inventory rows as LNPDB-relevant candidates.
- Script: `0_mark_down_gen/02_FT_selector.py`
- Required input files: `fig_table_inventory.csv`, markdown or PDF source text.
- Expected output files: `fig_table_lnpdb_classified.csv`.
- Success criteria:
  - Classified CSV exists.
  - It preserves figure/table identifiers.
  - It contains a classification or selection signal for LNPDB relevance.
- If failed, check:
  - Inventory file exists and is readable.
  - API credentials and model name are valid.
  - LLM response parsed into rows matching inventory items.
- Retry: Yes, after diagnosis.

### 02b_manual_review

- Purpose: Let a human review and correct the LNPDB figure/table selection.
- Script: `0_mark_down_gen/02B_FT_manual_selector_gui.py`
- Required input files: `fig_table_lnpdb_classified.csv`.
- Expected marker: `.manual_select_review_done`.
- Expected reviewed file: `fig_table_lnpdb_classified_manual_reviewed.csv`, or `fig_table_lnpdb_classified.csv` with a `manual_select` column.
- Success criteria:
  - `.manual_select_review_done` exists in the paper folder.
  - `manual_select` values are present or the reviewed copy exists.
- If failed, check:
  - Streamlit app was run against the correct paper folder.
  - Human saved review results.
- Retry: Manual only.

## AGENT_STAGES

Active agent stages must not run unless `.manual_select_review_done` exists.

### 03_figure_mapping

- Purpose: Map selected figure/table items to extracted source images, figures, or table files.
- Script: `0_mark_down_gen/03_figure_mapping.py`
- Required input files: reviewed/classified FT CSV, source figure/image/table assets.
- Expected output files: `total_figure_mapping.json` or related mapping JSON/CSV.
- Success criteria:
  - Mapping JSON exists.
  - It contains keys for source folders and selected FT item IDs.
  - Mapped paths point to existing files when paths are local.
- If failed, check:
  - Manual review marker exists.
  - Classified CSV has selected rows.
  - Source images/tables exist under the root scanned by the script.
  - The script's hard-coded `ROOT_DIR` was bypassed through wrapper/function call.
- Retry: Yes.

### 03_split_excel_blocks

- Purpose: Provide base Excel workbook/sheet splitting utilities.
- Script: `0_mark_down_gen/03_split_excel_blocks.py`
- Required input files: Excel files under `Exp_Excel` or the paper folder convention used by the project.
- Expected output files: This file primarily supplies functions; current artifact generation is handled by `03_split_excel_blocks_batch.py`.
- Success criteria:
  - Base module imports successfully.
  - Its helper functions can read target Excel workbooks/sheets.
- If failed, check:
  - Missing Python dependencies such as pandas/openpyxl.
  - Excel file corruption or unsupported file extension.
- Retry: Yes after dependency/input fix.

### 03_split_excel_blocks_batch

- Purpose: Use batch/LLM-assisted logic to classify/refine Excel blocks and save block artifacts.
- Script: `0_mark_down_gen/03_split_excel_blocks_batch.py`
- Required input files: `Exp_Excel` folder with `.xlsx` or `.csv`, source markdown/PDF, `fig_table_inventory.csv`.
- Expected output files: `excel_block_inventory.csv`, `three_core_result_all.json`, `Exp_Excel_Blocks/`, optional `excel_block_usage_inventory.csv`.
- Success criteria:
  - `excel_block_inventory.csv` exists and has at least one row when Excel inputs exist.
  - Block CSV paths listed in the inventory exist.
  - `Exp_Excel_Blocks/` contains saved block CSV/JSON files.
- If failed, check:
  - `Exp_Excel` exists and contains supported files.
  - GCS/Vertex batch configuration works.
  - Batch result files downloaded correctly.
  - Base `03_split_excel_blocks.py` imports successfully.
- Retry: Yes, but avoid duplicate expensive batch jobs unless previous job state is understood.

### 04_figure_separate

- Purpose: Separate figure images into panels or important regions.
- Script: `0_mark_down_gen/04_figure_saperate_gemini.py`
- Note: The repository currently spells the filename `saperate`, not `separate`.
- Required input files: `total_figure_mapping.json`, selected source image files, classified/reviewed CSV.
- Expected output files: `separated_panels_gemini/` folders or panel paths recorded in `total_figure_mapping.json`; optional `pdf_page_renders/` fallback pages.
- Marker-extracted images are primary candidates only.
- If a Marker image is missing, wrongly cropped, incomplete, or inconsistent with the caption, render the original PDF page with PyMuPDF and use that path as `selected_source_for_paneling`.
- If the selected source or panel boundaries remain uncertain, set `manual_required=true` and do not guess panel crops.
- Success criteria:
  - Panel output folder exists for mapped images that require panel separation.
  - Mapping JSON is updated with panel paths.
  - Panel image paths exist and are readable.
  - Fallback render paths recorded in `fallback_render` or `selected_source_for_paneling` exist when present.
- If failed, check:
  - Mapping JSON keys match source folder names.
  - OpenCV can read source images.
  - PyMuPDF is installed when PDF page fallback is needed.
  - Vertex/Gemini credentials and batch settings are valid.
- Retry: Yes, after isolating failed images.

### 04_ft_excel_matcher

- Purpose: Link selected FT items to Excel blocks/tables.
- Script: `0_mark_down_gen/04_FT-Excel_matcher.py`
- Required input files: `fig_table_lnpdb_classified.csv`, `fig_table_inventory.csv`, `excel_block_inventory.csv`, block CSV files, source PDFs.
- Expected output files: `excel_mapping.json`, `excel_mapping_rows.csv`, updated `fig_table_lnpdb_classified.csv`.
- Success criteria:
  - `excel_mapping.json` exists.
  - `excel_mapping_rows.csv` exists.
  - Matched block paths in rows exist when non-empty.
  - Classified CSV contains Excel matching columns such as `excel_item_id`, `matched_blocks`, or `matched_block_csv_path`.
- If failed, check:
  - Excel block inventory exists and block paths are readable.
  - Selected FT IDs normalize consistently between CSVs.
  - Batch job output parsing succeeded.
- Retry: Yes, but inspect previous batch job artifacts first.

### 05_smiles_structure_resolution

- Purpose: Resolve compound names and text/reference/manual-curated SMILES without Gemini/API dependencies. Molecule-structure-image-based SMILES extraction is disabled in the active workflow.
- Legacy scripts preserved under: `2_Extract_SMILES/`.
- Default mode: `external_agent`.
- Required input files: markdown/PDF sources and `total_figure_mapping.json` when available. Source images may be listed for provenance but must not be used for SMILES extraction.
- Expected output files: `compound_inventory_standardized.csv`, `smiles_resolved.csv`, `smiles_resolution_qc.csv`.
- Success criteria:
  - `smiles_resolved.csv` exists and parses.
  - It includes a name identifier column and a SMILES/resolved SMILES column.
  - Unresolved or ambiguous compounds are marked for manual review.
  - `image_structure_smiles_rows_used=0`.
  - Novel pILs remain blank unless exact text/reference/manual-curated SMILES are present.
  - These Stage 05 artifacts are not projected into current unified extraction outputs; Stage 06/07 force all output SMILES columns blank.
- If failed, check:
  - Deterministic text/name/IUPAC lookup tools such as OPSIN, PubChem, CIR, or local LNPDB references.
  - Do not use DECIMER, MolScribe, molecule image crops, `worker_mol.py`, structure-recognition `pipeline.py`, `recognition.py`, or `segmentation.py`.
- Retry: Yes, after resolving tool/input availability.

### 06_unified_lnpdb_extraction

- Purpose: Build one figure/table-item-level long table combining experimental conditions, formulation composition, Excel/source-data assay values when reliably mapped, and provenance.
- Default mode: `external_agent`.
- Replaces old independent condition/formulation extraction from `1_Extract_Exp_Figs/` and `3_Extract_Formula_by_Figs/` for the active API-free workflow.
- Experimental numeric assay/readout values may be extracted only from reliable mapped Excel/source-data blocks. The active 06 stage must not run or depend on legacy scripts under `4_Extract_Exp_Vals/`, and must not perform figure-image digitization.
- Required input files: `.manual_select_review_done`, `fig_table_lnpdb_classified.csv`, `total_figure_mapping.json`, `excel_mapping.json`, `excel_block_inventory.csv`, `Exp_Excel_Blocks/`, markdown files.
- Optional input files: `separated_panels_gemini/`, `compound_inventory_standardized.csv`, `text_extracted_iupac.csv`, `smiles_resolved.csv`, existing LNPDB reference DB files, and human-curated column/value guide files. `smiles_resolved.csv` may be used only for optional internal QC and must not populate output SMILES columns. Image-based structure-recognition outputs from `2_Extract_SMILES/FromImage/` are out of scope.
- Optional reference context:
  - Existing LNPDB references may be discovered from `LNPDB_reference.*` or `lnpdb_reference.*` in the paper folder, `reference/`, `agent_workspace/reference/`, or `LNPDB_REFERENCE_ROOT`.
  - Human guides may be discovered from `column_guides/`, `schema_guides/`, `value_guides/`, `reference/`, matching `agent_workspace/` folders, or `LNPDB_COLUMN_GUIDE_ROOT`, `LNPDB_SCHEMA_GUIDE_ROOT`, `LNPDB_VALUE_GUIDE_ROOT`.
  - Missing or unreadable reference files are warnings only and must not block 06.
- Expected output files: `unified_extraction.csv`, `unified_extraction.json`, `unified_extraction_review_flags.csv`.
- Success criteria:
  - `unified_extraction.csv` exists, parses, and contains required columns.
  - Rows use long format: one row per item/formulation/condition context.
  - Excel blocks are used for sheet/block identity, labels, headers, formulation names, group labels, condition context, provenance, and reliable source-data assay/readout values.
  - `metric_type`, `original_values`, `aggregated_value`, `unit`, and `replicate_type` may be populated only from mapped Excel/source-data blocks with provenance.
  - Graph image digitization, pixel/axis extraction, bar-height estimation, heatmap color estimation, caption-only inferred values, and hallucinated values are disallowed.
  - `IL_SMILES`, `HL_SMILES`, `CHL_SMILES`, `PEG_SMILES`, and `Fifth_component_SMILES` are present for compatibility but forced blank; component names and molar ratios remain populated when supported.
  - Figure/PDF images provide labels, axes, legends, panel identity, and visual context.
  - Markdown provides captions, methods context, dose, model, route, and formulation descriptions.
  - Optional LNPDB reference examples and human-curated guide definitions are used only to normalize concise scalar LNPDB-style condition/formulation fields.
  - Column-specific existing LNPDB examples are preferred over generic examples. If `Experiment_method` examples use assay+readout labels such as `flow_cytometry_CD8_T_cells`, preserve that style instead of reducing to `flow_cytometry`.
  - Condition fields are concise scalar values only. Full prose, semicolon-joined contexts, `or`-merged contexts, and multi-method bundles belong in `evidence_text` or require split rows/manual review.
  - Missing condition/formulation fields remain blank with `manual_required=true` where review is needed.
- If failed, check:
  - `excel_mapping.json` links selected items to block CSVs.
  - `total_figure_mapping.json` contains source image/PDF provenance.
  - Populated value columns have Excel/source-data provenance and numeric-like `original_values`/`aggregated_value`.
  - Condition columns pass scalar validation for `Model`, `Experiment_batching`, `Dose_ug_nucleicacid`, and prose-like mixed contexts.
  - External CLI agent did not hallucinate unsupported condition/formulation fields or numeric readout values and did not use image digitization.
- Retry: Yes, after fixing missing evidence or mappings.

### 07_finalize_unified_table

- Purpose: Finalize the unified extraction into an LNPDB-like value table plus numbered markdown sentence indexes, paper-package source-document context, normalized source-evidence, and figure/item-level evidence map tables with a QC report.
- Default mode: `heuristic`.
- Required input files: `unified_extraction.csv`, `unified_extraction_review_flags.csv`.
- Expected output files: `markdown_sentence_index/markdown_sentence_index_all.csv`, `markdown_sentence_index/markdown_sentence_index_manifest.json`, `paper_source_context.json`, `unified_extraction_final.csv`, `unified_extraction_lnpdb_like.csv`, `unified_extraction_source_evidence.csv`, `unified_extraction_figure_evidence_map.csv`, `unified_extraction_qc_report.json`.
- Success criteria:
  - Final and LNPDB-like CSVs parse and contain unique stable `row_id` values.
  - `unified_extraction_source_evidence.csv` parses and contains unique `evidence_id` values.
  - `markdown_sentence_index/markdown_sentence_index_all.csv` parses when source markdown exists and has unique `global_sentence_id` values.
  - Non-empty `evidence_sentence_ids` in source evidence and figure evidence map rows refer to existing sentence index IDs.
  - `unified_extraction_figure_evidence_map.csv` parses and maps evidence rows to supported LNPDB scientific condition/formulation columns by `Item_ID`.
  - Evidence mapping is grouped by figure/item evidence source; per-cell administrative/provenance mappings are not required.
  - Source-text evidence should prefer `evidence_summary + evidence_sentence_ids`; fuzzy full-sentence matching is a fallback only.
  - One selected `paper_folder` is one paper package. Main article, supplementary information, source data, and reporting summary markdown/PDF files under that folder are source documents for the same `Paper_ID`.
  - Global methods/protocol evidence may support rows derived from another source document in the same paper package. This is allowed for broadly applicable LNP preparation/formulation/dosing/method context, not for unrelated or value-bearing assay readouts.
  - QC report JSON parses.
  - No missing scientific value is invented during finalization.
- If failed, check:
  - `unified_extraction.csv` required columns.
  - Evidence IDs and row IDs are unique and linked.
  - Manual review flags and low-confidence row counts.
- Retry: Yes, after fixing unified extraction rows.
