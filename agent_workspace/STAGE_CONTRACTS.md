# Stage Contracts

Contracts define what an external CLI agent must check before and after running a stage. Use `<PAPER_FOLDER>` for the target paper folder or root folder being processed.

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
- required: `.manual_select_review_done`, markdown/PDF sources, source images when available
- optional: `total_figure_mapping.json`, local LNPDB reference files, DECIMER/MolScribe helper outputs

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

Failure handling:
- Check deterministic tools or references such as OPSIN, PubChem, CIR, existing LNPDB references, and MolScribe/DECIMER helper outputs.
- Mark unresolved or ambiguous compounds with `manual_required=true`.
- Do not call Gemini/API helpers.

## 06_unified_lnpdb_extraction

Inputs:
- required: `.manual_select_review_done`, `fig_table_lnpdb_classified.csv`, `total_figure_mapping.json`, `excel_mapping.json`, `excel_block_inventory.csv`, `Exp_Excel_Blocks/`, markdown files
- optional: `separated_panels_gemini/`, `compound_inventory_standardized.csv`, `text_extracted_iupac.csv`, `smiles_resolved.csv`, outputs from `2_Extract_SMILES/`

Command:
```bash
python Agent_Task_Runner.py run --stage 06_unified_lnpdb_extraction --paper-folder "<PAPER_FOLDER>"
```

Outputs:
- `unified_extraction.csv`
- `unified_extraction.json`
- `unified_extraction_review_flags.csv`

Validation:
- `unified_extraction.csv` parses.
- Required unified columns exist.
- `Item_ID`, `confidence`, and `manual_required` exist.
- At least one row exists when selected items exist.
- `unified_extraction_review_flags.csv` exists.

Failure handling:
- Check selected FT rows and Excel mappings.
- Check `block_csv_path` files under `Exp_Excel_Blocks/`.
- Use Excel blocks for numeric values, figures/images for labels and visual context, and markdown for methods/caption context.
- Leave uncertain fields blank with `manual_required=true`.

## 07_finalize_unified_table

Inputs:
- required: `.manual_select_review_done`, `unified_extraction.csv`, `unified_extraction_review_flags.csv`

Command:
```bash
python Agent_Task_Runner.py run --stage 07_finalize_unified_table --paper-folder "<PAPER_FOLDER>"
```

Outputs:
- `unified_extraction_final.csv`
- `unified_extraction_lnpdb_like.csv`
- `unified_extraction_qc_report.json`

Validation:
- Final and LNPDB-like CSVs parse.
- QC report JSON parses.

Failure handling:
- Fix required columns in `unified_extraction.csv`.
- Review low-confidence and manual-required rows before treating final outputs as curated.
