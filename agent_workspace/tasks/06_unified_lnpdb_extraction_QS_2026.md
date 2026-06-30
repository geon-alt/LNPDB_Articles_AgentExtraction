# External Agent Task: 06_unified_lnpdb_extraction

Target paper folder: `F:\???쒕씪?대툕\EXTRACT-TEST\QS_2026`

## Stage Purpose
Create one unified long table at figure/table item level that combines experimental conditions, formulation composition, and provenance. Experimental numeric assay/readout value extraction is disabled for this stage and deferred to a future value-extraction stage.

## Required Input Files
- `F:\???쒕씪?대툕\EXTRACT-TEST\QS_2026\.manual_select_review_done`
- `F:\???쒕씪?대툕\EXTRACT-TEST\QS_2026\fig_table_lnpdb_classified.csv`
- `F:\???쒕씪?대툕\EXTRACT-TEST\QS_2026\total_figure_mapping.json`
- `F:\???쒕씪?대툕\EXTRACT-TEST\QS_2026\excel_mapping.json`
- `F:\???쒕씪?대툕\EXTRACT-TEST\QS_2026\excel_block_inventory.csv`
- `F:\???쒕씪?대툕\EXTRACT-TEST\QS_2026\Exp_Excel_Blocks`
- markdown files:
- `41565_2025_2102_MOESM1_ESM/41565_2025_2102_MOESM1_ESM.md`
- `QS_2026/QS_2026.md`

## Optional Input Files
- `compound_inventory_standardized.csv`
- `smiles_resolved.csv`
- `smiles_resolved.csv` only for SMILES fields. Do not use image-based structure-recognition outputs from `2_Extract_SMILES/FromImage/`

## Expected Output Files
- `F:\???쒕씪?대툕\EXTRACT-TEST\QS_2026\unified_extraction.csv`
- `F:\???쒕씪?대툕\EXTRACT-TEST\QS_2026\unified_extraction.json`
- `F:\???쒕씪?대툕\EXTRACT-TEST\QS_2026\unified_extraction_review_flags.csv`

## Required Output Columns
Use the columns documented in `agent_workspace/OUTPUT_SCHEMA.md` for `unified_extraction.csv`. Include all experimental condition, formulation composition, evidence, confidence, and manual review fields. Populate `metric_type`, `original_values`, `aggregated_value`, `unit`, and `replicate_type` only from reliable mapped Excel/source-data blocks. Leave them blank when no reliable Excel/source-data mapping exists.

## LNPDB Experimental-Condition Column Guide
- `Aqueous_buffer`: short buffer label only, e.g. citrate buffer, acetate buffer, PBS, HEPES, N/A. Optional pH/concentration is allowed as a compact scalar, e.g. `10 mM citrate buffer pH 3`. Do not include prose such as `for mRNA before mixing`.
- `Dialysis_buffer`: short buffer label only, e.g. PBS, HEPES, water, N/A. Optional compact condition is allowed. Do not include full method details such as `MWCO 20 kDa, 2 h`; put those details in `evidence_text`.
- `Mixing_method`: short method label only, e.g. pipette, handmixed, microfluidics, T-junction, vortexing, liquid_handler. Do not combine alternatives with semicolons. If different panels use different mixing methods, split rows or leave blank with `manual_required=true`.
- `Model`: must be one of `in_vitro`, `in_vivo`, `ex_vivo`, or `N/A`.
- `Model_type`: if `Model=in_vitro`, cell line only, e.g. MC38, HEK293T, A549. If `Model=in_vivo`, animal/model only, e.g. C57BL/6_mouse, BALB/c_mouse, Mouse_MC38_tumor. Do not put full phrases such as `MC38 cells or MC38 tumour-bearing mice`.
- `Model_target`: if `Model=in_vitro`, use `in_vitro` or a measured cell/target. If `Model=in_vivo`, use organ/tissue/tumor target only, e.g. tumor, spleen, liver, lung. Do not combine multiple panels into one target with slash or prose.
- `Route_of_administration`: if `Model=in_vitro`, use `in_vitro`. If `Model=in_vivo`, use intravenous, intratumoral, intramuscular, subcutaneous, inhalation, oral, etc. Do not write sentences.
- `Cargo`: nucleic acid class only, e.g. mRNA, siRNA, pDNA, sgRNA, saRNA. Do not put reporter or encoded protein here.
- `Cargo_type`: encoded/reporter payload only, e.g. FLuc, NLuc, IL-12, OVA, Cre, Cas9. Do not put `mRNA` here if `Cargo` already contains mRNA.
- `Dose_ug_nucleicacid`: numeric microgram dose only, e.g. 0.05, 0.5, 2.5. No sentence. No `per mouse` prose. Convert straightforward ng values to ug, e.g. 50 ng = 0.05. If unit/context cannot be normalized, leave blank and set `manual_required=true`.
- `Experiment_method`: concise method/readout label only, e.g. luminescence, IVIS, ELISA_IL-12, flow_cytometry_CD8_T_cells, qPCR_IFN-gamma, RNA-seq, western_blot. Follow existing LNPDB column-specific examples when available. Do not combine multiple panels as `flow cytometry/ELISA/RNA-seq`. If a figure group contains multiple panels with different methods or readouts, split rows by panel/block.
- `Experiment_batching`: must be individual, barcoded, pooled, grouped, or N/A. Prefer individual unless the paper explicitly uses barcoded/pooled screening.

## LNPDB Formulation Column Guide
- `formulation_id`: stable row-level formulation identifier from the paper or a concise derived ID.
- `Formulation_Name`: formulation label exactly enough to identify the group, normalized to a short scalar.
- `IL_name`: ionizable lipid name.
- `IL_SMILES`: ionizable lipid SMILES from resolved/local evidence only.
- `IL_molarratio`: ionizable lipid molar ratio or mol% as a concise scalar.
- `HL_name`: helper lipid name.
- `HL_SMILES`: helper lipid SMILES from resolved/local evidence only.
- `HL_molarratio`: helper lipid molar ratio or mol% as a concise scalar.
- `CHL_name`: cholesterol or cholesterol-like component name.
- `CHL_SMILES`: cholesterol component SMILES from resolved/local evidence only.
- `CHL_molarratio`: cholesterol component molar ratio or mol% as a concise scalar.
- `PEG_name`: PEG-lipid or PEG component name.
- `PEG_SMILES`: PEG-lipid SMILES from resolved/local evidence only.
- `PEG_molarratio`: PEG component molar ratio or mol% as a concise scalar.
- `Fifth_component_name`: additional non-core formulation component name, if any.
- `Fifth_component_SMILES`: additional component SMILES from resolved/local evidence only.
- `Fifth_component_molarratio`: additional component molar ratio or mol% as a concise scalar.
- `IL_to_nucleicacid_massratio`: ionizable lipid to nucleic acid mass ratio, e.g. N/P or wt/wt, when explicitly available.

## Scalar Normalization Rules
- LNPDB fields must contain concise normalized scalar values.
- Prefer column-specific examples extracted from the existing LNPDB reference over generic examples.
- If existing LNPDB examples show assay+readout in `Experiment_method`, preserve that style.
- `Model_target` remains tissue/organ/site where applicable, while `Experiment_method` may include the measured readout/cell population when that is the established LNPDB style.
- Example: `Model_target=spleen` and `Experiment_method=flow_cytometry_CD8_T_cells` is valid.
- Do not reduce readout-specific methods to `flow_cytometry` when panel identity depends on the measured cell population.
- Do not copy full source sentences, captions, paragraphs, or methods prose into LNPDB fields.
- Full source sentences and captions may be stored only in `evidence_text`.
- If a concise normalized value cannot be determined, leave the field blank or mark `manual_required=true` with a reason.
- Do not use `variable` or `various` as a value unless the paper explicitly uses it as a label and no better scalar value exists.

## Existing LNPDB Column/Value Examples
No external LNPDB reference schema/value context was available; proceed using paper evidence only.

## Column-Specific Existing LNPDB Examples
No external LNPDB reference schema/value context was available; proceed using paper evidence only.

## Human-Curated Column and Value Definitions
No external LNPDB reference schema/value context was available; proceed using paper evidence only.

## Reference Context Warnings
- No external LNPDB reference schema/value context was available; proceed using paper evidence only.

Reference-context rules:
- Existing LNPDB values are examples, not a closed vocabulary.
- Human-curated definitions are higher priority than frequency examples.
- Use reference examples to normalize values into concise scalar LNPDB-style values.
- Do not copy full source prose into LNPDB fields.
- Full source sentences/captions belong only in `evidence_text`.
- If a concise normalized value cannot be determined, leave blank and set `manual_required=true` with a reason.

## Forbidden in LNPDB Condition Fields
- Full sentences or caption fragments.
- Values containing `or` when it merges multiple experimental contexts.
- Semicolon-separated mixed contexts.
- Panel-combined values such as `in vitro treatment; intratumoural injection for panel c`.
- Multi-method bundles such as `flow cytometry/ELISA/RNA-seq`.
- Any value that belongs in `evidence_text` rather than a scalar field.

If one caption describes multiple panels with different conditions, create separate rows per panel/item/block context. Do not merge panel b and panel c conditions into one row.

## Scalar Condition Examples
Bad:
- `Model = MC38 cells or MC38 tumour-bearing mice`
- `Route_of_administration = in vitro treatment; intratumoural injection for panel c`
- `Dose_ug_nucleicacid = 50 ng/well for in vitro screening; 2.5 ug per mouse for in vivo panel c`
- `Experiment_method = luciferase bioluminescence assay / IVIS imaging`

Good for Figure 2B:
- `Model = in_vitro`
- `Model_type = MC38`
- `Route_of_administration = in_vitro`
- `Dose_ug_nucleicacid = 0.05`
- `Experiment_method = luminescence`

Good for Figure 2C:
- `Model = in_vivo`
- `Model_type = Mouse_MC38_tumor`
- `Model_target = tumor`
- `Route_of_administration = intratumoral`
- `Dose_ug_nucleicacid = 2.5`
- `Experiment_method = IVIS`

QS_2026 Figure 4G-M style guidance:
- figure 4g: `Model_target=spleen`; `Experiment_method=flow_cytometry_CD8_T_cells`
- figure 4h: `Model_target=spleen`; `Experiment_method=flow_cytometry_CD4_T_cells`
- figure 4i: `Model_target=spleen`; `Experiment_method=flow_cytometry_CD8_effector_memory_T_cells`
- figure 4j: `Model_target=spleen`; `Experiment_method=flow_cytometry_CD8_central_memory_T_cells`
- figure 4k: `Model_target=spleen`; `Experiment_method=flow_cytometry_CD4_effector_memory_T_cells`
- figure 4l: `Model_target=spleen`; `Experiment_method=flow_cytometry_CD4_central_memory_T_cells`
- figure 4m: `Model_target=spleen`; `Experiment_method=flow_cytometry_regulatory_T_cells`

## Work Instructions
1. For every selected figure/table item, extract experimental conditions and formulation composition together into one unified long table.
2. Do not split the task into separate independent LLM calls for conditions and formulation.
3. Use all available condition/formulation context: markdown captions, PDF-derived images for labels/provenance only, separated panels for labels/provenance only, Excel block CSVs, `excel_mapping.json`, `total_figure_mapping.json`, and `smiles_resolved.csv` for SMILES fields.
4. Use Excel blocks only for sheet/block identity, labels, headers, formulation names, group labels, condition context, and provenance.
5. Extract experimental numeric assay/readout values only from mapped Excel/source-data blocks (`Exp_Excel_Blocks/`, source-data Excel files, `excel_mapping.json`, `excel_mapping_rows.csv`, and referenced `block_csv_path` files).
6. Populate `metric_type`, `original_values`, `aggregated_value`, `unit`, and `replicate_type` only when the value is tied to Excel/source-data provenance. Do not use captions alone for values.
7. Use figure/PDF images for labels, axes, legend, group interpretation, panel identity, and visual context.
8. Use markdown for caption, methods context, dose, model, route, and formulation descriptions.
9. If condition or formulation values are uncertain, do not hallucinate. Leave blank or set `manual_required=true` with a reason.
10. If multiple formulations, panels, methods, models, routes, or dose contexts exist in one figure/table, produce separate rows per formulation/condition/panel context.
11. Use long format.
12. Record `evidence_text`, `evidence_excel`, and `evidence_image` for every nontrivial extracted condition or formulation value.
13. Preserve provenance fields: `evidence_text`, `evidence_excel`, `evidence_image`, `confidence`, `manual_required`, and `reason`.
14. Create `unified_extraction_review_flags.csv` for missing metadata, low confidence, condition/formulation mismatch, unresolved SMILES, missing figure evidence, and any manual review need.
15. Also write `unified_extraction.json` with records and source summary.
16. When Excel has replicate columns, keep exact replicate/source values pipe-separated in `original_values`; set `aggregated_value` from an explicit mean/value column when present, or compute an arithmetic mean only when replicates are unambiguous and note that in `reason`.
17. Do not use graph image digitization, pixel/axis extraction, bar-height estimation, heatmap color estimation, or visual numeric estimation from figure images.
16. Fill `IL_SMILES`, `HL_SMILES`, `CHL_SMILES`, `PEG_SMILES`, and `Fifth_component_SMILES` only from `smiles_resolved.csv`. Do not attempt image-based fallback, crop molecular structures, infer visible structures, or generate novel SMILES in 06. If no matched SMILES exists, leave the field blank and preserve/manual-review the unresolved reason.

## Validation Command
```bash
python Agent_Task_Runner.py validate --stage 06_unified_lnpdb_extraction --paper-folder "F:\???쒕씪?대툕\EXTRACT-TEST\QS_2026"
```

## Constraints
- Do not use Gemini/API/find_api/LLM_API/LLM_Batch.
- Do not run legacy scripts from `1_Extract_Exp_Figs`, `3_Extract_Formula_by_Figs`, or `4_Extract_Exp_Vals`.
- Do not run or use DECIMER, MolScribe, `worker_mol.py`, structure-recognition `pipeline.py`, `recognition.py`, `segmentation.py`, molecule image crops, or image-derived SMILES outputs.
- Do not hard-code API keys or credentials.



