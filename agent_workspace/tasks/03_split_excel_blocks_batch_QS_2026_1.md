# External Agent Task: 03_split_excel_blocks_batch

Target paper folder: `F:\내 드라이브\EXTRACT-TEST\QS_2026_1`

## Stage Purpose
Split experimental Excel workbooks/sheets into API-free table blocks and classify block type by direct CLI agent judgment.

## Required Input Files
- `F:\내 드라이브\EXTRACT-TEST\QS_2026_1\.manual_select_review_done`
- Excel files under `F:\내 드라이브\EXTRACT-TEST\QS_2026_1\Exp_Excel`

Excel files found:
- `Exp_Excel/41565_2025_2102_MOESM7_ESM.xlsx`
- `Exp_Excel/41565_2025_2102_MOESM5_ESM.xlsx`
- `Exp_Excel/41565_2025_2102_MOESM6_ESM.xlsx`
- `Exp_Excel/41565_2025_2102_MOESM3_ESM.xlsx`
- `Exp_Excel/41565_2025_2102_MOESM4_ESM.xlsx`

## Expected Output Files
- `F:\내 드라이브\EXTRACT-TEST\QS_2026_1\Exp_Excel_Blocks`
- `F:\내 드라이브\EXTRACT-TEST\QS_2026_1\excel_block_inventory.csv`
- `F:\내 드라이브\EXTRACT-TEST\QS_2026_1\three_core_result_all.json`

## Work Instructions
1. Inspect the `Exp_Excel` folder.
2. Read Excel workbooks and sheets.
3. Split sheets into candidate blocks using merged cells, blank rows/columns, borders, fills, headers, and numeric density.
4. Prefer API-free helper logic such as `0_mark_down_gen/sheet_block_splitter.py`, `0_mark_down_gen/03_split_excel_blocks.py` pure utilities, or a deterministic helper script.
5. Do not use Gemini or LLM judgment.
6. Save each block CSV under `Exp_Excel_Blocks/`.
7. Create `excel_block_inventory.csv` with required columns:
   - `excel_file`
   - `excel_sheet`
   - `block_id`
   - `group_id`
   - `element_id`
   - `block_csv_path`
   - `block_meta_path`
   - `block_type`
8. Classify `block_type` by direct inspection as one of:
   - `title_and_table`
   - `table_body`
   - `table_title`
   - `multi_table`
   - `note`
   - `other`
9. Create `three_core_result_all.json` with JSON reasoning for every workbook/sheet.
10. If useful, create or run an API-free helper such as `agent_workspace/tools/api_free_excel_block_splitter.py`; use pandas/openpyxl deterministic parsing only.

## Validation Command
```bash
python Agent_Task_Runner.py validate --stage 03_split_excel_blocks_batch --paper-folder "F:\내 드라이브\EXTRACT-TEST\QS_2026_1"
```

## Constraints
- Do not run `0_mark_down_gen/03_split_excel_blocks_batch.py`.
- Do not import or require `find_api.py`.
- Do not use Gemini, Vertex, `LLM_API.py`, or `LLM_Batch.py`.
- Do not hard-code API keys or credentials.
