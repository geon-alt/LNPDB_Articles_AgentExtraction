# 03_split_excel_blocks_batch

Purpose: Excel/source-data sheet splitting, block IDs, block previews, and deterministic helper conventions.

Reference paths:
- `full_copy/0_mark_down_gen/03_split_excel_blocks.py`
- `full_copy/0_mark_down_gen/03_split_excel_blocks_batch.py`
- `full_copy/0_mark_down_gen/sheet_block_splitter.py`

Allowed use:
- Read-only reference for prior deterministic logic, expected output shapes, and naming conventions.

Do not use:
- `find_api.py`
- `LLM_API.py`
- `LLM_Batch.py`
- `google.genai`
- `Vertex/Gemini/GCS code`
- Do not execute or import Gemini/API-dependent scripts in active workflow.

Notes:
Read for prior Excel block shape and naming conventions. Do not execute API-dependent paths.
