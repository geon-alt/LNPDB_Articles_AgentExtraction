# External Agent Task: 03_figure_mapping

Target paper folder: `F:\내 드라이브\EXTRACT-TEST\QS_2026`

## Stage Purpose
Map manually selected LNPDB-relevant figure/table items to source image, table, or PDF assets without using Gemini or any Python API key dependency.

## Required Input Files
- `F:\내 드라이브\EXTRACT-TEST\QS_2026\.manual_select_review_done`
- `F:\내 드라이브\EXTRACT-TEST\QS_2026\fig_table_lnpdb_classified.csv`
- `F:\내 드라이브\EXTRACT-TEST\QS_2026\fig_table_inventory.csv`

## Source Assets Found
Images:
- `41565_2025_2102_MOESM1_ESM/_page_20_Figure_0.jpeg`
- `41565_2025_2102_MOESM1_ESM/_page_66_Figure_0.jpeg`
- `41565_2025_2102_MOESM1_ESM/_page_80_Figure_0.jpeg`
- `41565_2025_2102_MOESM1_ESM/_page_76_Figure_2.jpeg`
- `41565_2025_2102_MOESM1_ESM/_page_81_Figure_0.jpeg`
- `41565_2025_2102_MOESM1_ESM/_page_84_Figure_0.jpeg`
- `41565_2025_2102_MOESM1_ESM/_page_70_Figure_0.jpeg`
- `41565_2025_2102_MOESM1_ESM/_page_59_Figure_0.jpeg`
- `41565_2025_2102_MOESM1_ESM/_page_77_Figure_0.jpeg`
- `41565_2025_2102_MOESM1_ESM/_page_28_Figure_2.jpeg`
- `41565_2025_2102_MOESM1_ESM/_page_93_Figure_0.jpeg`
- `41565_2025_2102_MOESM1_ESM/_page_81_Figure_2.jpeg`
- `41565_2025_2102_MOESM1_ESM/_page_97_Figure_0.jpeg`
- `41565_2025_2102_MOESM1_ESM/_page_64_Figure_0.jpeg`
- `41565_2025_2102_MOESM1_ESM/_page_60_Figure_0.jpeg`
- `41565_2025_2102_MOESM1_ESM/_page_17_Figure_0.jpeg`
- `41565_2025_2102_MOESM1_ESM/_page_63_Figure_0.jpeg`
- `41565_2025_2102_MOESM1_ESM/_page_39_Figure_0.jpeg`
- `41565_2025_2102_MOESM1_ESM/_page_19_Figure_0.jpeg`
- `41565_2025_2102_MOESM1_ESM/_page_53_Figure_0.jpeg`
- `41565_2025_2102_MOESM1_ESM/_page_87_Figure_0.jpeg`
- `41565_2025_2102_MOESM1_ESM/_page_89_Figure_0.jpeg`
- `41565_2025_2102_MOESM1_ESM/_page_49_Figure_0.jpeg`
- `41565_2025_2102_MOESM1_ESM/_page_46_Figure_0.jpeg`
- `41565_2025_2102_MOESM1_ESM/_page_94_Figure_0.jpeg`
- `41565_2025_2102_MOESM1_ESM/_page_65_Figure_0.jpeg`
- `41565_2025_2102_MOESM1_ESM/_page_85_Figure_0.jpeg`
- `41565_2025_2102_MOESM1_ESM/_page_71_Figure_0.jpeg`
- `41565_2025_2102_MOESM1_ESM/_page_69_Figure_0.jpeg`
- `41565_2025_2102_MOESM1_ESM/_page_42_Figure_1.jpeg`
- `41565_2025_2102_MOESM1_ESM/_page_31_Figure_0.jpeg`
- `41565_2025_2102_MOESM1_ESM/_page_29_Figure_0.jpeg`
- `41565_2025_2102_MOESM1_ESM/_page_52_Figure_0.jpeg`
- `41565_2025_2102_MOESM1_ESM/_page_53_Figure_1.jpeg`
- `41565_2025_2102_MOESM1_ESM/_page_28_Figure_0.jpeg`
- `41565_2025_2102_MOESM1_ESM/_page_50_Figure_0.jpeg`
- `41565_2025_2102_MOESM1_ESM/_page_74_Figure_0.jpeg`
- `41565_2025_2102_MOESM1_ESM/_page_56_Figure_0.jpeg`
- `41565_2025_2102_MOESM1_ESM/_page_79_Figure_0.jpeg`
- `41565_2025_2102_MOESM1_ESM/_page_43_Figure_0.jpeg`
- `41565_2025_2102_MOESM1_ESM/_page_86_Figure_0.jpeg`
- `41565_2025_2102_MOESM1_ESM/_page_21_Figure_0.jpeg`
- `41565_2025_2102_MOESM1_ESM/_page_57_Figure_0.jpeg`
- `41565_2025_2102_MOESM1_ESM/_page_32_Figure_0.jpeg`
- `41565_2025_2102_MOESM1_ESM/_page_68_Figure_0.jpeg`
- `41565_2025_2102_MOESM1_ESM/_page_34_Figure_0.jpeg`
- `41565_2025_2102_MOESM1_ESM/_page_61_Figure_0.jpeg`
- `41565_2025_2102_MOESM1_ESM/_page_78_Figure_2.jpeg`
- `41565_2025_2102_MOESM1_ESM/_page_25_Figure_0.jpeg`
- `41565_2025_2102_MOESM1_ESM/_page_75_Figure_0.jpeg`
- `41565_2025_2102_MOESM1_ESM/_page_27_Figure_0.jpeg`
- `41565_2025_2102_MOESM1_ESM/_page_47_Figure_0.jpeg`
- `41565_2025_2102_MOESM1_ESM/_page_22_Figure_0.jpeg`
- `41565_2025_2102_MOESM1_ESM/_page_54_Figure_0.jpeg`
- `41565_2025_2102_MOESM1_ESM/_page_23_Figure_0.jpeg`
- `41565_2025_2102_MOESM1_ESM/_page_30_Figure_0.jpeg`
- `41565_2025_2102_MOESM1_ESM/_page_48_Figure_0.jpeg`
- `41565_2025_2102_MOESM1_ESM/_page_96_Figure_0.jpeg`
- `41565_2025_2102_MOESM1_ESM/_page_16_Figure_1.jpeg`
- `41565_2025_2102_MOESM1_ESM/_page_24_Figure_0.jpeg`
- `41565_2025_2102_MOESM1_ESM/_page_76_Figure_0.jpeg`
- `41565_2025_2102_MOESM1_ESM/_page_91_Figure_0.jpeg`
- `41565_2025_2102_MOESM1_ESM/_page_41_Figure_0.jpeg`
- `41565_2025_2102_MOESM1_ESM/_page_83_Figure_0.jpeg`
- `41565_2025_2102_MOESM1_ESM/_page_92_Figure_0.jpeg`
- `41565_2025_2102_MOESM1_ESM/_page_62_Figure_0.jpeg`
- `41565_2025_2102_MOESM1_ESM/_page_72_Figure_0.jpeg`
- `41565_2025_2102_MOESM1_ESM/_page_33_Figure_0.jpeg`
- `41565_2025_2102_MOESM1_ESM/_page_26_Figure_0.jpeg`
- `41565_2025_2102_MOESM1_ESM/_page_90_Figure_0.jpeg`
- `41565_2025_2102_MOESM1_ESM/_page_98_Figure_0.jpeg`
- `41565_2025_2102_MOESM1_ESM/_page_40_Figure_1.jpeg`
- `41565_2025_2102_MOESM1_ESM/_page_58_Figure_0.jpeg`
- `41565_2025_2102_MOESM1_ESM/_page_38_Figure_1.jpeg`
- `41565_2025_2102_MOESM1_ESM/_page_18_Figure_0.jpeg`
- `41565_2025_2102_MOESM1_ESM/_page_78_Picture_0.jpeg`
- `41565_2025_2102_MOESM1_ESM/_page_45_Figure_0.jpeg`
- `41565_2025_2102_MOESM1_ESM/_page_67_Figure_0.jpeg`
- `41565_2025_2102_MOESM1_ESM/_page_44_Figure_1.jpeg`
- `41565_2025_2102_MOESM1_ESM/_page_97_Figure_1.jpeg`
- `41565_2025_2102_MOESM1_ESM/_page_88_Figure_1.jpeg`
- `41565_2025_2102_MOESM1_ESM/_page_82_Figure_0.jpeg`
- `41565_2025_2102_MOESM1_ESM/_page_42_Figure_0.jpeg`
- `41565_2025_2102_MOESM1_ESM/_page_44_Figure_0.jpeg`
- `41565_2025_2102_MOESM1_ESM/_page_18_Figure_1.jpeg`
- `41565_2025_2102_MOESM1_ESM/_page_35_Figure_0.jpeg`
- `41565_2025_2102_MOESM1_ESM/_page_95_Figure_0.jpeg`
- `41565_2025_2102_MOESM1_ESM/_page_36_Figure_0.jpeg`
- `41565_2025_2102_MOESM1_ESM/_page_73_Figure_0.jpeg`
- `41565_2025_2102_MOESM1_ESM/_page_43_Figure_1.jpeg`
- `41565_2025_2102_MOESM1_ESM/_page_38_Figure_0.jpeg`
- `41565_2025_2102_MOESM1_ESM/_page_40_Figure_0.jpeg`
- `41565_2025_2102_MOESM1_ESM/_page_55_Figure_0.jpeg`
- `41565_2025_2102_MOESM1_ESM/_page_37_Figure_0.jpeg`
- `QS_2026/_page_5_Figure_2.jpeg`
- `QS_2026/_page_1_Figure_2.jpeg`
- `QS_2026/_page_9_Figure_2.jpeg`
- `QS_2026/_page_4_Figure_4.jpeg`
- `QS_2026/_page_7_Figure_4.jpeg`
- `QS_2026/_page_2_Figure_2.jpeg`
- `QS_2026/_page_0_Picture_7.jpeg`

Tables:
- `figure_only_value_pending.csv`
- `fig_table_lnpdb_classified.csv`
- `fig_table_inventory.csv`
- `Exp_Excel/41565_2025_2102_MOESM7_ESM.xlsx`
- `Exp_Excel/41565_2025_2102_MOESM5_ESM.xlsx`
- `Exp_Excel/41565_2025_2102_MOESM6_ESM.xlsx`
- `Exp_Excel/41565_2025_2102_MOESM3_ESM.xlsx`
- `Exp_Excel/41565_2025_2102_MOESM4_ESM.xlsx`

PDFs:
- `QS_2026.pdf`
- `41565_2025_2102_MOESM1_ESM.pdf`

## Expected Output Files
- `F:\내 드라이브\EXTRACT-TEST\QS_2026\total_figure_mapping.json`

## Work Instructions
1. Read `fig_table_lnpdb_classified.csv`.
2. Use rows where `manual_select` is `yes` or `maybe` as selected FT items.
3. If `manual_select` is absent, fall back to `need_for_lnpdb` values `yes` or `maybe`.
4. For every selected item, inspect `item_id`, `base_id`, `caption`, and `reason`.
5. Search the paper folder for source image, table, and PDF assets.
6. Map each selected figure/table item to the most likely source image/table path.
7. Create `total_figure_mapping.json` in the paper folder root.
8. Follow `agent_workspace/OUTPUT_SCHEMA.md` for the `total_figure_mapping.json` schema.
9. Store paths relative to the paper folder when possible.
10. If uncertain, record `confidence: "low"` or `confidence: "unmatched"` and a short `reason`.

## Validation Command
```bash
python Agent_Task_Runner.py validate --stage 03_figure_mapping --paper-folder "F:\내 드라이브\EXTRACT-TEST\QS_2026"
```

## Constraints
- Do not run `0_mark_down_gen/03_figure_mapping.py`.
- Do not import or require `find_api.py`.
- Do not use Gemini, Vertex, `LLM_API.py`, or `LLM_Batch.py`.
- Do not hard-code API keys or credentials.
