# External Agent Task: 04_ft_excel_matcher

Target paper folder: `F:\내 드라이브\EXTRACT-TEST\QS_2026_3`

## Stage Purpose
Match selected figure/table items to Excel blocks by direct CLI agent judgment without Gemini.

## Required Input Files
- `F:\내 드라이브\EXTRACT-TEST\QS_2026_3\.manual_select_review_done`
- `F:\내 드라이브\EXTRACT-TEST\QS_2026_3\fig_table_lnpdb_classified.csv`
- `F:\내 드라이브\EXTRACT-TEST\QS_2026_3\fig_table_inventory.csv`
- `F:\내 드라이브\EXTRACT-TEST\QS_2026_3\excel_block_inventory.csv`

## Expected Output Files
- `F:\내 드라이브\EXTRACT-TEST\QS_2026_3\excel_mapping.json`
- `F:\내 드라이브\EXTRACT-TEST\QS_2026_3\excel_mapping_rows.csv`
- updated `F:\내 드라이브\EXTRACT-TEST\QS_2026_3\fig_table_lnpdb_classified.csv` when possible

## Work Instructions
1. Read `fig_table_lnpdb_classified.csv`.
2. Read `fig_table_inventory.csv`.
3. Read `excel_block_inventory.csv`.
4. Match every selected FT item to candidate Excel blocks using caption, `item_id`, `base_id`, sheet name, block preview, `block_type`, and keywords.
5. Create `excel_mapping.json`.
6. Create `excel_mapping_rows.csv`.
7. When possible, update `fig_table_lnpdb_classified.csv` columns:
   - `excel_item_id`
   - `matched_blocks`
   - `matched_block_csv_path`
   - `matched_sheet`
   - `matched_sheet_file`
8. Follow `agent_workspace/OUTPUT_SCHEMA.md` for `excel_mapping.json` and `excel_mapping_rows.csv`.

## Validation Command
```bash
python Agent_Task_Runner.py validate --stage 04_ft_excel_matcher --paper-folder "F:\내 드라이브\EXTRACT-TEST\QS_2026_3"
```

## Constraints
- Do not run `0_mark_down_gen/04_FT-Excel_matcher.py`.
- Do not import or require `find_api.py`.
- Do not use Gemini, Vertex, `LLM_API.py`, or `LLM_Batch.py`.
- Do not hard-code API keys or credentials.
## Legacy context files

These files are reference-only. Do not execute or import Gemini/API-dependent scripts. Use them only to understand prior deterministic logic, expected output shapes, and naming conventions. Current stage contract and `AGENT_INSTRUCTIONS.md` override legacy behavior.

- `agent_workspace/legacy_context/by_stage/04_ft_excel_matcher/README.md` (exists)
- `agent_workspace/legacy_context/full_copy/0_mark_down_gen/04_FT-Excel_matcher.py` (exists)
- `agent_workspace/legacy_context/README.md` (context policy)
- `agent_workspace/legacy_context/LEGACY_CODE_INDEX.md` (stage-by-stage index)
