# 06_unified_lnpdb_extraction

Purpose: Prior experimental-condition, formulation, and experimental-value extraction patterns.

Reference paths:
- `full_copy/1_Extract_Exp_Figs/`
- `full_copy/3_Extract_Formula_by_Figs/`
- `full_copy/4_Extract_Exp_Vals/`

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
Use only for old output shapes and edge cases. Active contracts override legacy behavior.
