# Legacy Code Index

This index points external agents to stage-relevant legacy reference files. Current active contracts override legacy behavior.

| Stage | Files to read | Why useful | Allowed use | Do-not-use warnings |
|---|---|---|---|---|
| `00_marker` | `full_copy/0_mark_down_gen/00_Marker.py` | PDF-to-markdown Marker conversion command pattern and output placement. | read-only reference | Do not execute/import Gemini/API-dependent scripts. |
| `02b_manual_review` | `full_copy/0_mark_down_gen/02B_FT_manual_selector_gui.py` | Manual selection UI behavior, manual_select semantics, and review marker conventions. | read-only reference | Do not execute/import Gemini/API-dependent scripts. |
| `03_split_excel_blocks_batch` | `full_copy/0_mark_down_gen/03_split_excel_blocks.py`<br>`full_copy/0_mark_down_gen/03_split_excel_blocks_batch.py`<br>`full_copy/0_mark_down_gen/sheet_block_splitter.py` | Excel/source-data sheet splitting, block IDs, block previews, and deterministic helper conventions. | read-only reference | Do not execute/import Gemini/API-dependent scripts. |
| `04_ft_excel_matcher` | `full_copy/0_mark_down_gen/04_FT-Excel_matcher.py` | Prior figure/table-to-Excel-block matching schema and context construction. | read-only reference | Do not execute/import Gemini/API-dependent scripts. |
| `04_figure_separate` | `full_copy/0_mark_down_gen/04_figure_saperate_gemini.py` | Prior panel separation and source-image mapping conventions. | read-only reference | Do not execute/import Gemini/API-dependent scripts. |
| `05_smiles_structure_resolution` | `full_copy/2_Extract_SMILES/` | Legacy text/name SMILES reference code. Current unified outputs force SMILES columns blank. | read-only reference | Do not execute/import Gemini/API-dependent scripts. |
| `06_unified_lnpdb_extraction` | `full_copy/1_Extract_Exp_Figs/`<br>`full_copy/3_Extract_Formula_by_Figs/`<br>`full_copy/4_Extract_Exp_Vals/` | Prior experimental-condition, formulation, and experimental-value extraction patterns. | read-only reference | Do not execute/import Gemini/API-dependent scripts. |
