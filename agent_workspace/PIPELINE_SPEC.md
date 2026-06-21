# Pipeline Specification

This document defines the pipeline stages that external coding agents should follow. Existing code stays in `0_mark_down_gen/`; do not move it.

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
- Expected output files: `separated_panels_gemini/` folders or panel paths recorded in `total_figure_mapping.json`.
- Success criteria:
  - Panel output folder exists for mapped images that require panel separation.
  - Mapping JSON is updated with panel paths.
  - Panel image paths exist and are readable.
- If failed, check:
  - Mapping JSON keys match source folder names.
  - OpenCV can read source images.
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

