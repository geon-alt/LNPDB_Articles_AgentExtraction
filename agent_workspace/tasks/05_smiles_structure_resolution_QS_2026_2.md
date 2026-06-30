# External Agent Task: 05_smiles_structure_resolution

Target paper folder: `F:\???쒕씪?대툕\EXTRACT-TEST\QS_2026_2`

## Stage Purpose
Resolve compound names and text/reference/manual-curated SMILES without Gemini/API dependencies. Molecule-structure-image-based SMILES extraction is disabled in the active workflow.

## Required Input Files
- `F:\???쒕씪?대툕\EXTRACT-TEST\QS_2026_2\.manual_select_review_done`
- markdown files and/or PDFs from the paper folder
- `F:\???쒕씪?대툕\EXTRACT-TEST\QS_2026_2\total_figure_mapping.json` when available
- source images when available

Markdown files:
- `41565_2025_2102_MOESM1_ESM/41565_2025_2102_MOESM1_ESM.md`
- `QS_2026/QS_2026.md`

PDFs:
- `41565_2025_2102_MOESM1_ESM.pdf`
- `QS_2026.pdf`

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

## Optional Input Files
- existing LNPDB reference file if configured locally
- manually curated or manually verified SMILES files, if explicitly present
- local text/IUPAC extraction outputs that do not rely on structure images

## Expected Output Files
- `F:\???쒕씪?대툕\EXTRACT-TEST\QS_2026_2\compound_inventory_standardized.csv`
- `F:\???쒕씪?대툕\EXTRACT-TEST\QS_2026_2\smiles_resolved.csv`
- `F:\???쒕씪?대툕\EXTRACT-TEST\QS_2026_2\smiles_resolution_qc.csv`

## Work Instructions
1. Collect lipid/component names, aliases, and IUPAC names from markdown, PDFs, captions, text tables, and curated/reference files.
2. Resolve SMILES only from allowed sources: exact LNPDB/reference name or alias match, curated/local known mapping, text/name/IUPAC-based deterministic lookup that does not rely on structure images, or manually curated/manual-verified SMILES files.
3. Create `compound_inventory_standardized.csv` with one row per compound/name candidate.
4. Create `smiles_resolved.csv` with at least `Name` or `compound_id`, and `SMILES` or `resolved_smiles`.
5. Create `smiles_resolution_qc.csv` with unresolved names, conflicts, ambiguous matches, and evidence notes.
6. Preserve provenance fields such as source file, item id, caption snippet, table block, or image path when available.
7. If a SMILES cannot be resolved from allowed text/reference/manual-curated sources, leave it blank and mark it for manual review.
8. Novel pILs such as `G0-SS-AA-C12`, `G0-6C-AA-C12`, `P2A-SS-AA-C10`, etc. must remain blank in SMILES unless an exact text/reference/manual-curated SMILES entry is present. Use reason: `Structure-image-based SMILES extraction is disabled; no exact text/reference SMILES was available.`

## Validation Command
```bash
python Agent_Task_Runner.py validate --stage 05_smiles_structure_resolution --paper-folder "F:\???쒕씪?대툕\EXTRACT-TEST\QS_2026_2"
```

## Constraints
- Do not run Gemini/API-assisted SMILES scripts.
- Do not import or require `find_api.py`, `LLM_API.py`, or `LLM_Batch.py`.
- Do not use Gemini, Vertex, or hard-coded credentials.
- Do not run, import, or use DECIMER, MolScribe, `worker_mol.py`, structure-recognition `pipeline.py`, `recognition.py`, or `segmentation.py`.
- Do not scan figure images for chemical structures, crop molecular structures from figures, infer SMILES from PDF/image crops, or hallucinate SMILES from visible structures.
- Do not use image-derived SMILES helper outputs unless a row is explicitly marked `human_curated` or `manual_verified`.


