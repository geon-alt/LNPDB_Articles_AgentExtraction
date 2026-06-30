# External Agent Task: 06_unified_lnpdb_extraction

Target paper folder: `F:\???쒕씪?대툕\EXTRACT-TEST\QS_2026_2`

## Stage Purpose
Create one unified long table at figure/table item level that combines experimental conditions, formulation composition, and provenance. Experimental numeric assay/readout value extraction is disabled for this stage and deferred to a future value-extraction stage.

## Required Input Files
- `F:\???쒕씪?대툕\EXTRACT-TEST\QS_2026_2\.manual_select_review_done`
- `F:\???쒕씪?대툕\EXTRACT-TEST\QS_2026_2\fig_table_lnpdb_classified.csv`
- `F:\???쒕씪?대툕\EXTRACT-TEST\QS_2026_2\total_figure_mapping.json`
- `F:\???쒕씪?대툕\EXTRACT-TEST\QS_2026_2\excel_mapping.json`
- `F:\???쒕씪?대툕\EXTRACT-TEST\QS_2026_2\excel_block_inventory.csv`
- `F:\???쒕씪?대툕\EXTRACT-TEST\QS_2026_2\Exp_Excel_Blocks`
- markdown files:
- `41565_2025_2102_MOESM1_ESM/41565_2025_2102_MOESM1_ESM.md`
- `QS_2026/QS_2026.md`

## Optional Input Files
- `compound_inventory_standardized.csv`
- `smiles_resolved.csv`
- `smiles_resolved.csv` only for SMILES fields. Do not use image-based structure-recognition outputs from `2_Extract_SMILES/FromImage/`

## Expected Output Files
- `F:\???쒕씪?대툕\EXTRACT-TEST\QS_2026_2\unified_extraction.csv`
- `F:\???쒕씪?대툕\EXTRACT-TEST\QS_2026_2\unified_extraction.json`
- `F:\???쒕씪?대툕\EXTRACT-TEST\QS_2026_2\unified_extraction_review_flags.csv`

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
Existing LNPDB values are examples, not a closed vocabulary.
- `Aqueous_buffer`: column_exists=True, non_empty_count=28883, unique_count=5
  - sources: F:\???쒕씪?대툕\LNPDB_originalPLUSupdates.xlsx::LNPDB_final
  - top values: citrate (24304); acetate (4229); hydrochloric acid buffer (263); OGP (57); Unknown (30)
  - examples: acetate; citrate; Unknown; OGP; hydrochloric acid buffer
- `Dialysis_buffer`: column_exists=True, non_empty_count=15154, unique_count=5
  - sources: F:\???쒕씪?대툕\LNPDB_originalPLUSupdates.xlsx::LNPDB_final
  - top values: PBS (14755); water (286); HBS (57); acetate (32); saline (24)
  - examples: PBS; saline; water; acetate; HBS
- `Mixing_method`: column_exists=True, non_empty_count=28883, unique_count=6
  - sources: F:\???쒕씪?대툕\LNPDB_originalPLUSupdates.xlsx::LNPDB_final
  - top values: handmixed (19375); microfluidic (4989); vortexing (3157); liquid_handler (1120); pulse_vortexing (137); Unknown (105)
  - examples: handmixed; microfluidic; vortexing; pulse_vortexing; liquid_handler; Unknown
- `Model`: column_exists=True, non_empty_count=26007, unique_count=2
  - sources: F:\???쒕씪?대툕\LNPDB_originalPLUSupdates.xlsx::LNPDB_final
  - top values: in_vitro (20270); in_vivo (5737)
  - examples: in_vitro; in_vivo
- `Model_type`: column_exists=True, non_empty_count=25868, unique_count=50
  - sources: F:\???쒕씪?대툕\LNPDB_originalPLUSupdates.xlsx::LNPDB_final
  - top values: HeLa (8113); Mouse_B6 (4140); A549 (2578); HepG2 (2072); DC2.4 (1703); IGROV1 (1652); Raw_264.7 (1216); BEAS-2B (1012); HEK293T (545); Mouse_BALBc (424)
  - examples: HeLa; HEK293T; Mouse_B6; Mouse_CD1; BMDC; BMDM; IGROV1; HepG2
- `Model_target`: column_exists=True, non_empty_count=25872, unique_count=28
  - sources: F:\???쒕씪?대툕\LNPDB_originalPLUSupdates.xlsx::LNPDB_final
  - top values: in_vitro (18209); lung_epithelium (1879); liver (1774); lung (1054); spleen (1040); muscle (536); serum (249); multiorgan (198); kidney (146); bone_marrow (141)
  - examples: in_vitro; liver; whole_body; muscle; lung_epithelium; spleen; heart; lung
- `Route_of_administration`: column_exists=True, non_empty_count=25877, unique_count=8
  - sources: F:\???쒕씪?대툕\LNPDB_originalPLUSupdates.xlsx::LNPDB_final
  - top values: in_vitro (20140); intravenous (4869); intramuscular (658); intradermal (60); intratumoral (50); intratracheal (49); nebulization (33); retro_orbital (18)
  - examples: in_vitro; intravenous; intramuscular; intratracheal; intradermal; retro_orbital; nebulization; intratumoral
- `Cargo`: column_exists=True, non_empty_count=28733, unique_count=12
  - sources: F:\???쒕씪?대툕\LNPDB_originalPLUSupdates.xlsx::LNPDB_final
  - top values: mRNA (21954); siRNA (4078); pDNA (1413); DNA (508); ASO (385); FLuc (183); HA (100); protein (42); Cas9 RNP (28); tdTomato (24)
  - examples: siRNA; pDNA; mRNA; ASO; protein; Cas9:sgRNA; DNA; FLuc
- `Cargo_type`: column_exists=True, non_empty_count=28603, unique_count=53
  - sources: F:\???쒕씪?대툕\LNPDB_originalPLUSupdates.xlsx::LNPDB_final
  - top values: FLuc (23649); DNA_barcode (959); peptide_barcode (407); mRNA (358); hEPO (332); GFP (227); Custom_barcode (224); gene_targeting_ASO (210); Cre (202); FPLC-purified Luc (191)
  - examples: FLuc; GFP; FVII; peptide_barcode; hEPO; DNA_barcode; RLuc; base_editor
- `Dose_ug_nucleicacid`: column_exists=True, non_empty_count=25945, unique_count=43
  - sources: F:\???쒕씪?대툕\LNPDB_originalPLUSupdates.xlsx::LNPDB_final
  - top values: 0.1 (8398); 0.05 (2676); 0.2 (2488); 2 (2247); 0.02 (1896); 5 (1254); 0.01 (1069); 1 (1046); 0.025 (694); 10 (509)
  - examples: 0.9; 0.081521739; 0.075; 0.05; 100; 0.1; 20; 10
- `Experiment_method`: column_exists=True, non_empty_count=28883, unique_count=133
  - sources: F:\???쒕씪?대툕\LNPDB_originalPLUSupdates.xlsx::LNPDB_final
  - top values: luminescence_normalized (18371); luminescence_discretized_normalized (3058); diameter (1272); PDI (953); protein_abundance_normalized (894); cell_viability_normalized (578); uptake_normalized (571); encapsulation (520); zeta_potential (271); luminescence_discretized (252)
  - examples: luminescence_discretized_normalized; luminescence_normalized; LRP6_knockdown_normalized; protein_abundance_normalized; uptake_normalized; diameter; zeta_potential; hemolysis_percent_normalized
- `Experiment_batching`: column_exists=True, non_empty_count=28819, unique_count=2
  - sources: F:\???쒕씪?대툕\LNPDB_originalPLUSupdates.xlsx::LNPDB_final
  - top values: individual (27613); barcoded (1206)
  - examples: individual; barcoded
- `formulation_id`: column_exists=True, non_empty_count=28883, unique_count=22126
  - sources: F:\???쒕씪?대툕\LNPDB_originalPLUSupdates.xlsx::LNPDB_final
  - top values: PG_2019_F11 (88); KS_2023_F11 (76); KS_2023_F4 (76); AR_2025_F2 (74); AR_2025_F1 (64); QS_2026_F14 (48); JM_2022_F2 (44); JM_2022_F3 (44); JM_2022_F1 (43); JM_2022_F4 (42)
  - examples: AA_2008_F1; AA_2008_F2; AA_2008_F3; AA_2008_F4; AA_2008_F5; AA_2008_F6; AA_2008_F7; AA_2008_F8
- `IL_name`: column_exists=True, non_empty_count=29152, unique_count=14667
  - sources: F:\???쒕씪?대툕\LNPDB_originalPLUSupdates.xlsx::LNPDB_final
  - top values: 4A3-SC7 (3098); DLin-MC3-DMA (2605); C12-200 (754); 7C1 (450); 4A3-SC8 (203); 1_A3_T9b2 (197); other (157); DLin-KC2-DMA (108); SM-102 (106); ALC-0315 (102)
  - examples: 87_O15; 96_N12; 98_N12; 64_N15; 64_N16; 26_O14; 32_N12; 95_N12
- `IL_SMILES`: column_exists=True, non_empty_count=19540, unique_count=10634
  - sources: F:\???쒕씪?대툕\LNPDB_originalPLUSupdates.xlsx::LNPDB_final
  - top values: CCCCCCCSCC(C)C(=O)OCCOC(=O)CCN(CCCN(C)CCCN(CCC(=O)OCCOC(=O)C(C)CSCCCCCCC)CCC(=O)OCCOC(=O)C(C)CSCCCCCCC)CCC(=O)OCCOC(=O)C(C)CSCCCCCCC (3098); N(CC(O)CCCCCCCCCCCCC)(CC)CC (288); CCCCCCCCCCC(CN(CCN1CCN(CC1)CCN(CC(CCCCCCCCCC)O)CC(CCCCCCCCCC)O)CCN(CC(CCCCCCCCCC)O)CC(CCCCCCCCCC)O)O (258); CCCCCCCCCCC(O)CN(CCN(CC(O)CCCCCCCCCC)CC(O)CCCCCCCCCC)CCN1CCN(CCN(CC(O)CCCCCCCCCC)CC(O)CCCCCCCCCC)CC1 (234); OC(CN(CCN(CCN1CCN(CC1)CCN(CC(CCCCCCCCCC)O)CC(CCCCCCCCCC)O)CC(CCCCCCCCCC)O)CC(CCCCCCCCCC)O)CCCCCCCCCC (218); CCCCCCCCSCC(C)C(=O)OCCOC(=O)CCN(CCCN(C)CCCN(CCC(=O)OCCOC(=O)C(C)CSCCCCCCCC)CCC(=O)OCCOC(=O)C(C)CSCCCCCCCC)CCC(=O)OCCOC(=O)C(C)CSCCCCCCCC (205); CCCCC(CC)CCC(=O)Oc1cc(OC(=O)CCC(CC)CCCC)c(CNCCN(C)CCNCc2c(OC(=O)CCC(CC)CCCC)cc(OC(=O)CCC(CC)CCCC)cc2OC(=O)CCC(CC)CCCC)c(OC(=O)CCC(CC)CCCC)c1 (197); CCN(CC(CCCCCCCCCCCCC)O)CC (162); CCCCCCCCC(CCCCCCCC)OC(CCCCCCCN(CCCCCC(OCCCCCCCCCCC)=O)CCO)=O (101); CCCCCCCCC(CCCCCC)C(=O)OCCCCCCN(CCCCCCOC(=O)C(CCCCCC)CCCCCCCC)CCCCO (98)
  - examples: CCCCCCCCCCCCCCCOC(=O)CCN(CCCN(CCO)CCO)CCC(=O)OCCCCCCCCCCCCCCC; CCCCCCCCCCCCNC(=O)CCN(C)CCCN(CCC(=O)NCCCCCCCCCCCC)CCC(=O)NCCCCCCCCCCCC; CCCCCCCCCCCCNC(=O)CCN(CCC(=O)NCCCCCCCCCCCC)CCN(CCC(=O)NCCCCCCCCCCCC)CCN(CCC(=O)NCCCCCCCCCCCC)CCN(CCC(=O)NCCCCCCCCCCCC)CCC(=O)NCCCCCCCCCCCC; CCCCCCCCCCCCCCCNC(=O)CCN(CC)CCCN(CC)CCC(=O)NCCCCCCCCCCCCCCC; CCCCCCCCCCCCCCCCNC(=O)CCN(CC)CCCN(CC)CCC(=O)NCCCCCCCCCCCCCCCC; CCCCCCCCCCCCCCOC(=O)CCN(CCC(=O)OCCCCCCCCCCCCCC)C(C)(CO)CO; CCCCCCCCCCCCNC(=O)CCN(CCCCCO)CCC(=O)NCCCCCCCCCCCC; CCCCCCCCCCCCNC(=O)CCN(C)CCN(CCC(=O)NCCCCCCCCCCCC)CCC(=O)NCCCCCCCCCCCC
- `HL_name`: column_exists=True, non_empty_count=28072, unique_count=29
  - sources: F:\???쒕씪?대툕\LNPDB_originalPLUSupdates.xlsx::LNPDB_final
  - top values: DOPE (16361); DSPC (7065); DOTAP (2577); MDOA (572); DDAB (378); 14PA (360); 18PG (360); DOPC (65); DPPC (44); SOPC (36)
  - examples: DSPC; DOPE; MDOA; DOTAP; DDAB; 14PA; 18PG; DMPC
- `HL_SMILES`: column_exists=True, non_empty_count=8874, unique_count=11
  - sources: F:\???쒕씪?대툕\LNPDB_originalPLUSupdates.xlsx::LNPDB_final
  - top values: CCCCCCCCCCCCCCCCCC(=O)OC[C@H](COP(=O)([O-])OCC[N+](C)(C)C)OC(=O)CCCCCCCCCCCCCCCCC (7088); CCCCCCCCCCCCCCCCCCN(C)CCCCCCCCCCCCCCCCCC (572); CCCCCCCCCCCCCCCCCC[N+](CCCCCCCCCCCCCCCCCC)(C)C (378); [P](=O)([O-])(OC[C@H](OC(=O)CCCCCCCCCCCCC)COC(=O)CCCCCCCCCCCCC)O (360); [P](=O)([O-])(OC[C@H](OC(=O)CCCCCCCCCCCCCCCCC)COC(=O)CCCCCCCCCCCCCCCCC)OCC(O)CO (360); C(CCCCCCCCCCCCCCC)(=O)OC[C@@H](OC(CCCCCCCCCCCCCCC)=O)COP(=O)([O-])OCC[N+](C)(C)C (32); C[C@H]([C@]1([H])[C@@]2(C)CC[C@]3([H])[C@@]4(C)CC[C@]([H])(OC(=O)NCC[N+](C)(C)[H])CC4=CC[C@@]3([H])[C@]2([H])CC1)CCCC(C)C.[Cl-] (21); CCCCCCCCCCCCCC(OC[C@]([H])(OC(CCCCCCCCCCCCC)=O)COP(OCC[N+](C)(C)C)([O-])=O)=O (19); CC(C)CCCC(C)CCCC(C)CCCC(C)CCOCC(COP(=O)(O)OCCN)OCCC(C)CCCC(C)CCCC(C)CCCC(C)C (18); C(=C/CCCCCCCC)/CCCCCCCC(OC[C@@H](OC(CCC(=O)OC1CC[C@@]2(C)C3CC[C@@]4(C)[C@H]([C@@H](C)CCCC(C)C)CCC4C3CC=C2C1)=O)COP(OCC[N+](C)(C)C)([O-])=O)=O (14)
  - examples: CCCCCCCCCCCCCCCCCC(=O)OC[C@H](COP(=O)([O-])OCC[N+](C)(C)C)OC(=O)CCCCCCCCCCCCCCCCC; CCCCCCCCCCCCCCCCCCN(C)CCCCCCCCCCCCCCCCCC; CCCCCCCCCCCCCCCCCC[N+](CCCCCCCCCCCCCCCCCC)(C)C; [P](=O)([O-])(OC[C@H](OC(=O)CCCCCCCCCCCCC)COC(=O)CCCCCCCCCCCCC)O; [P](=O)([O-])(OC[C@H](OC(=O)CCCCCCCCCCCCCCCCC)COC(=O)CCCCCCCCCCCCCCCCC)OCC(O)CO; CCCCCCCCCCCCCC(OC[C@]([H])(OC(CCCCCCCCCCCCC)=O)COP(OCC[N+](C)(C)C)([O-])=O)=O; C(=C/CCCCCCCC)/CCCCCCCC(OC[C@@H](OC(CCC(=O)OC1CC[C@@]2(C)C3CC[C@@]4(C)[C@H]([C@@H](C)CCCC(C)C)CCC4C3CC=C2C1)=O)COP(OCC[N+](C)(C)C)([O-])=O)=O; C[C@H]([C@]1([H])[C@@]2(C)CC[C@]3([H])[C@@]4(C)CC[C@]([H])(OC(=O)NCC[N+](C)(C)[H])CC4=CC[C@@]3([H])[C@]2([H])CC1)CCCC(C)C.[Cl-]
- `CHL_name`: column_exists=True, non_empty_count=28691, unique_count=23
  - sources: F:\???쒕씪?대툕\LNPDB_originalPLUSupdates.xlsx::LNPDB_final
  - top values: Cholesterol (23330); cholesterol (5030); Cholesteryl Oleate (59); 7B-OH Cholesterol (55); Cholesteryl Stearate (42); 7A-OH Cholesterol (37); n-butyl lithocholate (35); 4B-OH Cholesterol (18); Beta-Sitosterol (17); Stigmasterol (13)
  - examples: Cholesterol; Vitamin D2; Vitamin D3; Calcipotriol; Stigmasterol; Beta-Sitosterol; Betulin; Lupeol
- `CHL_SMILES`: column_exists=True, non_empty_count=28538, unique_count=19
  - sources: F:\???쒕씪?대툕\LNPDB_originalPLUSupdates.xlsx::LNPDB_final
  - top values: C[C@H](CCCC(C)C)[C@H]1CC[C@@H]2[C@@]1(CC[C@H]3[C@H]2CC=C4[C@@]3(CC[C@@H](C4)O)C)C (28281); C[C@@H]([C@]1([H])[C@@]2(C)CC[C@]3([H])[C@@]4(C)CC[C@H](O)CC4=C[C@@H](O)[C@@]3([H])[C@]2([H])CC1)CCCC(C)C (55); C[C@@H]([C@@H]1[C@@]2(C)CC[C@]3([H])[C@@]4(C)CC[C@H](OC(=O)CCCCCCCCCCCCCCCCC)CC4=CC[C@@]3([H])[C@]2([H])CC1)CCCC(C)C (42); C[C@@H]([C@]1([H])[C@@]2(C)CC[C@]3([H])[C@@]4(C)CC[C@H](O)CC4=C[C@H](O)[C@@]3([H])[C@]2([H])CC1)CCCC(C)C (37); C[C@H](CCC(OCCCC)=O)[C@@]1([H])CC[C@@]2([H])[C@]3([H])CC[C@]4([H])C[C@H](O)CC[C@]4(C)[C@@]3([H])CC[C@@]21C (35); C[C@@H]([C@]1([H])[C@@]2(C)CC[C@]3([H])[C@@]4(C)CC[C@H](O)C(O)C4=CC[C@@]3([H])[C@]2([H])CC1)CCCC(C)C (18); CC[C@H](CC[C@@H](C)[C@H]1CC[C@@H]2[C@@]1(CC[C@H]3[C@H]2CC=C4[C@@]3(CC[C@@H](C4)O)C)C)C(C)C (17); CC[C@H](/C=C/[C@@H](C)[C@H]1CC[C@@H]2[C@@]1(CC[C@H]3[C@H]2CC=C4[C@@]3(CC[C@@H](C4)O)C)C)C(C)C (13); C1[C@H](O)CC2=CC[C@@]3([H])[C@]4([H])CC[C@H]([C@H](C)CC[C@@H](C)C(C)C)[C@@]4(C)CC[C@]3([H])[C@@]2(C)C1 (8); C1[C@H](O)CC2=CC[C@@]3([H])[C@]4([H])CC[C@H]([C@H](C)CC[C@@H](CC)C(C)C)[C@@]4(C)CC[C@]3([H])[C@@]2(C)C1 (8)
  - examples: C[C@H](CCCC(C)C)[C@H]1CC[C@@H]2[C@@]1(CC[C@H]3[C@H]2CC=C4[C@@]3(CC[C@@H](C4)O)C)C; CC[C@H](/C=C/[C@@H](C)[C@H]1CC[C@@H]2[C@@]1(CC[C@H]3[C@H]2CC=C4[C@@]3(CC[C@@H](C4)O)C)C)C(C)C; CC[C@H](CC[C@@H](C)[C@H]1CC[C@@H]2[C@@]1(CC[C@H]3[C@H]2CC=C4[C@@]3(CC[C@@H](C4)O)C)C)C(C)C; CC(=C)[C@@H]1CC[C@]2([C@H]1[C@H]3CC[C@@H]4[C@]5(CC[C@@H](C([C@@H]5CC[C@]4([C@@]3(CC2)C)C)(C)C)O)C)CO; CC(=C)[C@@H]1CC[C@]2([C@H]1[C@H]3CC[C@@H]4[C@]5(CC[C@@H](C([C@@H]5CC[C@]4([C@@]3(CC2)C)C)(C)C)O)C)C; C[C@@H]1CC[C@@]2(CC[C@@]3(C(=CC[C@H]4[C@]3(CC[C@@H]5[C@@]4(CC[C@@H](C5(C)C)O)C)C)[C@@H]2[C@H]1C)C)C(=O)O; C[C@]12CC[C@@H](C([C@@H]1CC[C@@]3([C@@H]2CC=C4[C@]3(CC[C@@]5([C@H]4CC(CC5)(C)C)C(=O)O)C)C)(C)C)O; C[C@H](CC[C@@H](C)C(C)C)[C@H]1CC[C@@H]2[C@@]1(CC[C@H]3[C@H]2CC=C4[C@@]3(CC[C@@H](C4)O)C)C
- `PEG_name`: column_exists=True, non_empty_count=28580, unique_count=32
  - sources: F:\???쒕씪?대툕\LNPDB_originalPLUSupdates.xlsx::LNPDB_final
  - top values: DMG-PEG2000 (16435); DMPE-PEG2000 (9583); Unknown (1798); C16-Ceramide-PEG2000 (186); DSPE-PEG2000 (119); DMPE-PEG1000 (55); DMPE-PEG3000 (48); C16-PEG2000-Ceramide (46); DMPE-PEG5000 (46); DSG-PEG2000 (37)
  - examples: DMG-PEG2000; Unknown; DMPE-PEG2000; DMG-PEG5000; DPG-PEG2000; DPG-PEG5000; DSG-PEG2000; DSG-PEG5000
- `PEG_SMILES`: column_exists=True, non_empty_count=117, unique_count=8
  - sources: F:\???쒕씪?대툕\LNPDB_originalPLUSupdates.xlsx::LNPDB_final
  - top values: CCCCCCCCCCCCCC(OCC(OC(CCCCCCCCCCCCC)=O)COP(O)(OCCNCC(OCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOC)=O)=O)=O (46); CCCCCCCCCCCCCC(OCC(OC(CCCCCCCCCCCCC)=O)COP(O)(OCCNCC(OCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOC)=O)=O)=O (17); C(CC)CCCCCCCCCCCCC(=O)OCC(COP(=O)(OCCNCC(=O)OCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOC)O)OC(=O)CCCCCCCCCCCCCCC (9); C(CCCC)CCCCCCCCCCCCC(=O)OCC(COP(=O)(OCCNCC(=O)OCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOC)O)OC(=O)CCCCCCCCCCCCCCCCC (9); C(CCCC)CCCCCCCCCCCCC(=O)OCC(COP(=O)(OCCNCC(=O)OCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOC)O)OC(=O)CCCCCCCCCCCCCCCCC (9); CCCCCCCCCCCCC/C=C/[C@H]([C@H](COC(CCC(OCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOC)=O)=O)NC(CCCCCCC)=O)O (9); CCCCCCCCCCCCC/C=C/[C@H]([C@H](COC(CCC(OCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOC)=O)=O)NC(CCCCCCCCCCCCCCC)=O)O (9); CCCCCCCCCCCCCC(OCC(OC(CCCCCCCCCCCCC)=O)COP(O)(OCCNCC(OCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOC)=O)=O)=O (9)
  - examples: CCCCCCCCCCCCCC(OCC(OC(CCCCCCCCCCCCC)=O)COP(O)(OCCNCC(OCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOC)=O)=O)=O; CCCCCCCCCCCCCC(OCC(OC(CCCCCCCCCCCCC)=O)COP(O)(OCCNCC(OCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOC)=O)=O)=O; C(CCCC)CCCCCCCCCCCCC(=O)OCC(COP(=O)(OCCNCC(=O)OCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOC)O)OC(=O)CCCCCCCCCCCCCCCCC; CCCCCCCCCCCCCC(OCC(OC(CCCCCCCCCCCCC)=O)COP(O)(OCCNCC(OCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOC)=O)=O)=O; C(CC)CCCCCCCCCCCCC(=O)OCC(COP(=O)(OCCNCC(=O)OCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOC)O)OC(=O)CCCCCCCCCCCCCCC; C(CCCC)CCCCCCCCCCCCC(=O)OCC(COP(=O)(OCCNCC(=O)OCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOC)O)OC(=O)CCCCCCCCCCCCCCCCC; CCCCCCCCCCCCC/C=C/[C@H]([C@H](COC(CCC(OCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOC)=O)=O)NC(CCCCCCCCCCCCCCC)=O)O; CCCCCCCCCCCCC/C=C/[C@H]([C@H](COC(CCC(OCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOC)=O)=O)NC(CCCCCCC)=O)O
- `Fifth_component_name`: column_exists=True, non_empty_count=3272, unique_count=459
  - sources: F:\???쒕씪?대툕\LNPDB_originalPLUSupdates.xlsx::LNPDB_final
  - top values: DOTAP (40); 6,6'-trehalose dioleate (38); BMP(S,R) (30); DSPE-PEG2000-mannose (30); 1A7B13 (22); 1A7B15 (22); 1A8B18 (22); 1A8B25 (22); 1A7B5 (20); 1A7B6 (20)
  - examples: 6,6'-trehalose dioleate; DSPE-PEG2000-mannose; DSPE-PEG2000-galactose; DiR; BMP(S,R); 4Me; CL; DSPC
- `Fifth_component_SMILES`: column_exists=True, non_empty_count=2987, unique_count=437
  - sources: F:\???쒕씪?대툕\LNPDB_originalPLUSupdates.xlsx::LNPDB_final
  - top values: CCC/C=C/COC(=O)CCCCCCCCC[N+](C)(CCCCCCCCCCCCCCCCCC)CCCCCCCCCC(=O)OC/C=C/CCC (22); CCCCCCCCCCCC[N+](C)(CCCCCC(=O)OCC(CCCC)CCCCCC)CCCCCC(=O)OCC(CCCC)CCCCCC (22); CCCCCCCCCCCC[N+](C)(CCCCCC(=O)OCC(CCCCCCCC)CCCCCCCCCC)CCCCCC(=O)OCC(CCCCCCCC)CCCCCCCCCC (22); CCCCCCCCCCCCCCCCCC[N+](C)(CCCCCCCCCC(=O)OCC(CC)CCCC)CCCCCCCCCC(=O)OCC(CC)CCCC (22); CCCCCCCCCCCCCCCC[N+](C)(CCCCCCCCCCCC)CCCCCCCCCCCCCCCC (20); CCCCCCCCCCCCCCCCCC[N+](C)(CCCCCCCCCCCC)CCCCCCCCCCCCCCCCCC (20); CCCCCCCCCCCCCCCCCC[N+](C)(CCCCCCCCCCCCCC)CCCCCCCCCCCCCC (20); CC1(C(=[N+](C2=CC=CC=C12)CCCCCCCCCCCCCCCCCC)C=CC=C1N(C2=CC=CC=C2C1(C)C)CCCCCCCCCCCCCCCCCC)C (16); C=CCCCCOC(=O)CCCCCCCCC[N+](C)(CCCCCCCCCCCC)CCCCCCCCCC(=O)OCCCCC=C (12); C=CCCCCOC(=O)CCCCCCCCC[N+](C)(CCCCCCCCCCCCCCCCCC)CCCCCCCCCC(=O)OCCCCC=C (12)
  - examples: [I-].CC1(C(N(C2=CC=CC=C12)CCCCCCCCCCCCCCCCCC)=C/C=C/C=C/C=C/C1=[N+](C2=CC=CC=C2C1(C)C)CCCCCCCCCCCCCCCCCC)C; CC(C)CCCC(C)CCCC(C)CCCC(C)CCOCC(COP(=O)(O)OCCN)OCCC(C)CCCC(C)CCCC(C)CCCC(C)C; CCCCCCCCCCCCCCCCCC(=O)OC[C@H](COP(=O)([O-])OCC[N+](C)(C)C)OC(=O)CCCCCCCCCCCCCCCCC; CC1(C(=[N+](C2=CC=CC=C12)CCCCCCCCCCCCCCCCCC)C=CC=C1N(C2=CC=CC=C2C1(C)C)CCCCCCCCCCCCCCCCCC)C; CCCCCCCC[N+](CC)(CCCCCCCC)CCCCCCCC; CCCCCCCC[N+](CCC)(CCCCCCCC)CCCCCCCC; CCCCCCCC[N+](CCCC)(CCCCCCCC)CCCCCCCC; CCCCCCCC[N+](CCCCCC)(CCCCCCCC)CCCCCCCC
- `IL_to_nucleicacid_massratio`: column_exists=True, non_empty_count=26000, unique_count=1902
  - sources: F:\???쒕씪?대툕\LNPDB_originalPLUSupdates.xlsx::LNPDB_final
  - top values: 10 (13518); 40 (3097); 5 (1611); 15 (902); 16.96 (720); 25.44 (720); 8.48 (720); 7 (378); 11 (325); 13.9 (286)
  - examples: 5; 7; 3.163915524; 3.2940723; 3.245692009; 3.251864601; 3.294203468; 3.20844915

## Column-Specific Existing LNPDB Examples
Use these as style examples. They are not a closed vocabulary, but new values should follow the same concise scalar naming style.

### Aqueous_buffer
Existing LNPDB examples:
- citrate
- acetate
- hydrochloric acid buffer
- OGP
- Unknown

### Dialysis_buffer
Existing LNPDB examples:
- PBS
- water
- HBS
- acetate
- saline

### Mixing_method
Existing LNPDB examples:
- handmixed
- microfluidic
- vortexing
- liquid_handler
- pulse_vortexing
- Unknown

### Model
Existing LNPDB examples:
- in_vitro
- in_vivo

### Model_type
Existing LNPDB examples:
- HeLa
- Mouse_B6
- A549
- HepG2
- DC2.4
- IGROV1
- Raw_264.7
- BEAS-2B
- HEK293T
- Mouse_BALBc
- BeWo_b30
- Mouse_BALBc_female
- Mouse_Ai14_tdTomato
- BMDC
- Mouse_Ai14
- Mouse_B6_pregnant
- C2C12
- HeLa-FLuc_RLuc
- Mouse_LDLR_knockout
- Mouse_VLDLR_knockout

### Model_target
Existing LNPDB examples:
- in_vitro
- lung_epithelium
- liver
- lung
- spleen
- muscle
- serum
- multiorgan
- kidney
- bone_marrow
- heart
- firefly luciferase
- placenta
- whole_body
- ear
- Hepatocyte
- pancreas
- lymph node
- MC38_tumor_tissue
- tumor

### Route_of_administration
Existing LNPDB examples:
- in_vitro
- intravenous
- intramuscular
- intradermal
- intratumoral
- intratracheal
- nebulization
- retro_orbital

### Cargo
Existing LNPDB examples:
- mRNA
- siRNA
- pDNA
- DNA
- ASO
- FLuc
- HA
- protein
- Cas9 RNP
- tdTomato
- Cas9:sgRNA
- hEPO

### Cargo_type
Existing LNPDB examples:
- FLuc
- DNA_barcode
- peptide_barcode
- mRNA
- hEPO
- GFP
- Custom_barcode
- gene_targeting_ASO
- Cre
- FPLC-purified Luc
- barcoded
- FVII
- EPO
- AncNanoLuc
- pCI-FLuc
- base_editor
- mCherry
- Cy5-FLuc
- PCSK9
- RLuc

### Dose_ug_nucleicacid
Existing LNPDB examples:
- 0.1
- 0.05
- 0.2
- 2
- 0.02
- 5
- 0.01
- 1
- 0.025
- 10
- 0.003
- 0.9
- 0.081521739
- 15
- 20
- 0.25
- 6
- 2.5
- 40
- 100

### Experiment_method
Existing LNPDB examples:
- luminescence_normalized
- luminescence_discretized_normalized
- diameter
- PDI
- protein_abundance_normalized
- cell_viability_normalized
- uptake_normalized
- encapsulation
- zeta_potential
- luminescence_discretized
- flow_cytometry_endothelial_cells_normalized
- editing_efficiency_normalized
- pKa
- fluorescence_normalized
- luminescence_fold_change_normalized
- LRP6_knockdown_normalized
- flow_cytometry_macrophages_normalized
- gene_silencing_normalized
- hemolysis_percent_normalized
- flow_cytometry_normalized

### Experiment_batching
Existing LNPDB examples:
- individual
- barcoded

### formulation_id
Existing LNPDB examples:
- PG_2019_F11
- KS_2023_F11
- KS_2023_F4
- AR_2025_F2
- AR_2025_F1
- QS_2026_F14
- JM_2022_F2
- JM_2022_F3
- JM_2022_F1
- JM_2022_F4
- KK_2015_F1
- YL_2024_F3
- KS_2023_F10
- SL_2022_F2
- JK_2017_F7
- YL_2024_F4
- JK_2017_F14
- JK_2017_F15
- JK_2017_F16
- QS_2026_F22

### IL_name
Existing LNPDB examples:
- 4A3-SC7
- DLin-MC3-DMA
- C12-200
- 7C1
- 4A3-SC8
- 1_A3_T9b2
- other
- DLin-KC2-DMA
- SM-102
- ALC-0315
- 246C10
- CHCha-10
- 244-cis
- A4
- AMG1541
- 306-O12B-3
- cKK-E12
- DODAC
- G0-SS-AA-C12
- ZA3-Ep10

### IL_SMILES
Existing LNPDB examples:
- CCCCCCCSCC(C)C(=O)OCCOC(=O)CCN(CCCN(C)CCCN(CCC(=O)OCCOC(=O)C(C)CSCCCCCCC)CCC(=O)OCCOC(=O)C(C)CSCCCCCCC)CCC(=O)OCCOC(=O)C(C)CSCCCCCCC
- N(CC(O)CCCCCCCCCCCCC)(CC)CC
- CCCCCCCCCCC(CN(CCN1CCN(CC1)CCN(CC(CCCCCCCCCC)O)CC(CCCCCCCCCC)O)CCN(CC(CCCCCCCCCC)O)CC(CCCCCCCCCC)O)O
- CCCCCCCCCCC(O)CN(CCN(CC(O)CCCCCCCCCC)CC(O)CCCCCCCCCC)CCN1CCN(CCN(CC(O)CCCCCCCCCC)CC(O)CCCCCCCCCC)CC1
- OC(CN(CCN(CCN1CCN(CC1)CCN(CC(CCCCCCCCCC)O)CC(CCCCCCCCCC)O)CC(CCCCCCCCCC)O)CC(CCCCCCCCCC)O)CCCCCCCCCC
- CCCCCCCCSCC(C)C(=O)OCCOC(=O)CCN(CCCN(C)CCCN(CCC(=O)OCCOC(=O)C(C)CSCCCCCCCC)CCC(=O)OCCOC(=O)C(C)CSCCCCCCCC)CCC(=O)OCCOC(=O)C(C)CSCCCCCCCC
- CCCCC(CC)CCC(=O)Oc1cc(OC(=O)CCC(CC)CCCC)c(CNCCN(C)CCNCc2c(OC(=O)CCC(CC)CCCC)cc(OC(=O)CCC(CC)CCCC)cc2OC(=O)CCC(CC)CCCC)c(OC(=O)CCC(CC)CCCC)c1
- CCN(CC(CCCCCCCCCCCCC)O)CC
- CCCCCCCCC(CCCCCCCC)OC(CCCCCCCN(CCCCCC(OCCCCCCCCCCC)=O)CCO)=O
- CCCCCCCCC(CCCCCC)C(=O)OCCCCCCN(CCCCCCOC(=O)C(CCCCCC)CCCCCCCC)CCCCO
- CCCCCCCCC(CCCCCC)C(=O)OCCCCCCNC(CC1CCCCC1)C(=O)N(C)CCCN1CCN(CCCN(C)C(=O)C(CC2CCCCC2)NCCCCCCOC(=O)C(CCCCCC)CCCCCCCC)CC1
- CCCCCCCCCCC(O)CN(CCCN1CCN(CCCN)CC1)CC(O)CCCCCCCCCC
- CCCCCCCCCCC(CN(CC(CCCCCCCCCC)O)CCOCCN1CCN(CCN(CC(CCCCCCCCCC)O)CCOCCN(CC(CCCCCCCCCC)O)CC(CCCCCCCCCC)O)CC1)O
- CCCCCCCCSSCCOC(=O)CCNCCCN(C)CCCN(CCC(=O)OCCSSCCCCCCCC)CCC(=O)OCCSSCCCCCCCC
- CCCCCCCCC(O)CN(CC(O)CCCCCCCC)CCN(CCN(CC(O)CCCCCCCC)CC(O)CCCCCCCC)CCN(CCC(=O)NCC[N+](C)(C)CCCS(=O)(=O)[O-])CC(O)CCCCCCCC
- N1(CCN(CC(O)CCCCCCCCCC)CCN(CC(O)CCCCCCCCCC)CC(O)CCCCCCCCCC)CCN(CCN(CC(O)CCCCCCCCCC)CC(CCCCCCCCCC)O)CC1
- C1N(CCN(CCC(=O)OCCCCCCCCCC)CCC(=O)OCCCCCCCCCC)CCN(CCN(CCC(=O)OCCCCCCCCCC)CCN(CCC(=O)OCCCCCCCCCC)CCC(=O)OCCCCCCCCCC)C1
- C1(CCCCN(CC(O)CCCCCCCCCC)CC(O)CCCCCCCCCC)NC(=O)C(CCCCN(CC(O)CCCCCCCCCC)CC(O)CCCCCCCCCC)NC1=O
- C1N(CCN(C(CCCCCCCCCCCC)O)CCCOCCOCCOCCCN(C(CCCCCCCCCCCC)O)C(O)CCCCCCCCCCCC)CCN(CCCOCCOCCOCCCN(C(CCCCCCCCCCCC)O)C(CCCCCCCCCCCC)O)C1
- CCCCCCCCCCC(CN(CCCCC1C(=O)NC(C(=O)N1)CCCCN(CC(CCCCCCCCCC)O)CC(CCCCCCCCCC)O)CC(CCCCCCCCCC)O)O

### HL_name
Existing LNPDB examples:
- DOPE
- DSPC
- DOTAP
- MDOA
- DDAB
- 14PA
- 18PG
- DOPC
- DPPC
- SOPC
- 18:1 Biotinyl PE
- DOTMA
- DMPC
- 4Me
- BMP(S,R)
- POPE
- 18:1 Lyso PC
- BMP(S,S)
- CL
- DC Chol-HCl

### HL_SMILES
Existing LNPDB examples:
- CCCCCCCCCCCCCCCCCC(=O)OC[C@H](COP(=O)([O-])OCC[N+](C)(C)C)OC(=O)CCCCCCCCCCCCCCCCC
- CCCCCCCCCCCCCCCCCCN(C)CCCCCCCCCCCCCCCCCC
- CCCCCCCCCCCCCCCCCC[N+](CCCCCCCCCCCCCCCCCC)(C)C
- [P](=O)([O-])(OC[C@H](OC(=O)CCCCCCCCCCCCC)COC(=O)CCCCCCCCCCCCC)O
- [P](=O)([O-])(OC[C@H](OC(=O)CCCCCCCCCCCCCCCCC)COC(=O)CCCCCCCCCCCCCCCCC)OCC(O)CO
- C(CCCCCCCCCCCCCCC)(=O)OC[C@@H](OC(CCCCCCCCCCCCCCC)=O)COP(=O)([O-])OCC[N+](C)(C)C
- C[C@H]([C@]1([H])[C@@]2(C)CC[C@]3([H])[C@@]4(C)CC[C@]([H])(OC(=O)NCC[N+](C)(C)[H])CC4=CC[C@@]3([H])[C@]2([H])CC1)CCCC(C)C.[Cl-]
- CCCCCCCCCCCCCC(OC[C@]([H])(OC(CCCCCCCCCCCCC)=O)COP(OCC[N+](C)(C)C)([O-])=O)=O
- CC(C)CCCC(C)CCCC(C)CCCC(C)CCOCC(COP(=O)(O)OCCN)OCCC(C)CCCC(C)CCCC(C)CCCC(C)C
- C(=C/CCCCCCCC)/CCCCCCCC(OC[C@@H](OC(CCC(=O)OC1CC[C@@]2(C)C3CC[C@@]4(C)[C@H]([C@@H](C)CCCC(C)C)CCC4C3CC=C2C1)=O)COP(OCC[N+](C)(C)C)([O-])=O)=O
- O=C(OC[C@@H](OC(=O)CCCCCCCCCCCCCCC)COP([O-])(=O)OCC[N+](C)(C)C)CCCCCCCCCCCCCCC

### CHL_name
Existing LNPDB examples:
- Cholesterol
- Cholesteryl Oleate
- 7B-OH Cholesterol
- Cholesteryl Stearate
- 7A-OH Cholesterol
- n-butyl lithocholate
- 4B-OH Cholesterol
- Beta-Sitosterol
- Stigmasterol
- Campesterol
- Fucosterol
- Stigmastanol
- 棺-Sitosterol
- 3-methylpentyl lithocholate
- iso-Pentyl lithocholate
- Betulin
- Calcipotriol
- Lupeol
- Oleanolic acid
- Ursolic acid

### CHL_SMILES
Existing LNPDB examples:
- C[C@H](CCCC(C)C)[C@H]1CC[C@@H]2[C@@]1(CC[C@H]3[C@H]2CC=C4[C@@]3(CC[C@@H](C4)O)C)C
- C[C@@H]([C@]1([H])[C@@]2(C)CC[C@]3([H])[C@@]4(C)CC[C@H](O)CC4=C[C@@H](O)[C@@]3([H])[C@]2([H])CC1)CCCC(C)C
- C[C@@H]([C@@H]1[C@@]2(C)CC[C@]3([H])[C@@]4(C)CC[C@H](OC(=O)CCCCCCCCCCCCCCCCC)CC4=CC[C@@]3([H])[C@]2([H])CC1)CCCC(C)C
- C[C@@H]([C@]1([H])[C@@]2(C)CC[C@]3([H])[C@@]4(C)CC[C@H](O)CC4=C[C@H](O)[C@@]3([H])[C@]2([H])CC1)CCCC(C)C
- C[C@H](CCC(OCCCC)=O)[C@@]1([H])CC[C@@]2([H])[C@]3([H])CC[C@]4([H])C[C@H](O)CC[C@]4(C)[C@@]3([H])CC[C@@]21C
- C[C@@H]([C@]1([H])[C@@]2(C)CC[C@]3([H])[C@@]4(C)CC[C@H](O)C(O)C4=CC[C@@]3([H])[C@]2([H])CC1)CCCC(C)C
- CC[C@H](CC[C@@H](C)[C@H]1CC[C@@H]2[C@@]1(CC[C@H]3[C@H]2CC=C4[C@@]3(CC[C@@H](C4)O)C)C)C(C)C
- CC[C@H](/C=C/[C@@H](C)[C@H]1CC[C@@H]2[C@@]1(CC[C@H]3[C@H]2CC=C4[C@@]3(CC[C@@H](C4)O)C)C)C(C)C
- C1[C@H](O)CC2=CC[C@@]3([H])[C@]4([H])CC[C@H]([C@H](C)CC[C@@H](C)C(C)C)[C@@]4(C)CC[C@]3([H])[C@@]2(C)C1
- C1[C@H](O)CC2=CC[C@@]3([H])[C@]4([H])CC[C@H]([C@H](C)CC[C@@H](CC)C(C)C)[C@@]4(C)CC[C@]3([H])[C@@]2(C)C1
- C1[C@H](O)CC2CC[C@@]3([H])[C@]4([H])CC[C@H]([C@H](C)CC[C@@H](CC)C(C)C)[C@@]4(C)CC[C@]3([H])[C@@]2(C)C1
- C[C@H](CC[C@@H](C)C(C)C)[C@H]1CC[C@@H]2[C@@]1(CC[C@H]3[C@H]2CC=C4[C@@]3(CC[C@@H](C4)O)C)C
- CC[C@H](CC[C@@H](C)[C@H]1CC[C@@H]2[C@@]1(CC[C@H]3[C@H]2CC[C@@H]4[C@@]3(CC[C@@H](C4)O)C)C)C(C)C
- O=C(OCCC(C)C)CC[C@@H](C)[C@@]1([H])CC[C@@]2([H])[C@]3([H])CC[C@]4([H])C[C@H](O)CC[C@]4(C)[C@@]3([H])CC[C@@]21C
- O=C(OCCC(C)CC)CC[C@H](C)[C@@]1([H])CC[C@@]2([H])[C@]3([H])CC[C@]4([H])C[C@H](O)CC[C@]4(C)[C@@]3([H])CC[C@@]21C
- C[C@@H]1CC[C@@]2(CC[C@@]3(C(=CC[C@H]4[C@]3(CC[C@@H]5[C@@]4(CC[C@@H](C5(C)C)O)C)C)[C@@H]2[C@H]1C)C)C(=O)O
- C[C@]12CC[C@@H](C([C@@H]1CC[C@@]3([C@@H]2CC=C4[C@]3(CC[C@@]5([C@H]4CC(CC5)(C)C)C(=O)O)C)C)(C)C)O
- CC(=C)[C@@H]1CC[C@]2([C@H]1[C@H]3CC[C@@H]4[C@]5(CC[C@@H](C([C@@H]5CC[C@]4([C@@]3(CC2)C)C)(C)C)O)C)C
- CC(=C)[C@@H]1CC[C@]2([C@H]1[C@H]3CC[C@@H]4[C@]5(CC[C@@H](C([C@@H]5CC[C@]4([C@@]3(CC2)C)C)(C)C)O)C)CO

### PEG_name
Existing LNPDB examples:
- DMG-PEG2000
- DMPE-PEG2000
- Unknown
- C16-Ceramide-PEG2000
- DSPE-PEG2000
- DMPE-PEG1000
- DMPE-PEG3000
- C16-PEG2000-Ceramide
- DMPE-PEG5000
- DSG-PEG2000
- C8-Ceramide-PEG2000
- DMPE-PEG550
- DOPE-PEG550
- DSPE-2arm-PEG2000
- C18-CONH-PEG2000
- DPG-PEG2000
- ALC-0159
- C20-Ceramide-PEG2000
- DMG-C-PEG2000
- C16-Ceramide-PEG750

### PEG_SMILES
Existing LNPDB examples:
- CCCCCCCCCCCCCC(OCC(OC(CCCCCCCCCCCCC)=O)COP(O)(OCCNCC(OCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOC)=O)=O)=O
- CCCCCCCCCCCCCC(OCC(OC(CCCCCCCCCCCCC)=O)COP(O)(OCCNCC(OCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOC)=O)=O)=O
- C(CC)CCCCCCCCCCCCC(=O)OCC(COP(=O)(OCCNCC(=O)OCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOC)O)OC(=O)CCCCCCCCCCCCCCC
- C(CCCC)CCCCCCCCCCCCC(=O)OCC(COP(=O)(OCCNCC(=O)OCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOC)O)OC(=O)CCCCCCCCCCCCCCCCC
- C(CCCC)CCCCCCCCCCCCC(=O)OCC(COP(=O)(OCCNCC(=O)OCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOC)O)OC(=O)CCCCCCCCCCCCCCCCC
- CCCCCCCCCCCCC/C=C/[C@H]([C@H](COC(CCC(OCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOC)=O)=O)NC(CCCCCCC)=O)O
- CCCCCCCCCCCCC/C=C/[C@H]([C@H](COC(CCC(OCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOC)=O)=O)NC(CCCCCCCCCCCCCCC)=O)O
- CCCCCCCCCCCCCC(OCC(OC(CCCCCCCCCCCCC)=O)COP(O)(OCCNCC(OCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOC)=O)=O)=O

### Fifth_component_name
Existing LNPDB examples:
- DOTAP
- 6,6'-trehalose dioleate
- BMP(S,R)
- DSPE-PEG2000-mannose
- 1A7B13
- 1A7B15
- 1A8B18
- 1A8B25
- 1A7B5
- 1A7B6
- 1A8B4
- DiI-C18
- 1A22B13
- 1A4B8
- 1A7B18
- 1A7B21
- 1A7B22
- 1A7B23
- 1A7B24
- 1A7B25

### Fifth_component_SMILES
Existing LNPDB examples:
- CCC/C=C/COC(=O)CCCCCCCCC[N+](C)(CCCCCCCCCCCCCCCCCC)CCCCCCCCCC(=O)OC/C=C/CCC
- CCCCCCCCCCCC[N+](C)(CCCCCC(=O)OCC(CCCC)CCCCCC)CCCCCC(=O)OCC(CCCC)CCCCCC
- CCCCCCCCCCCC[N+](C)(CCCCCC(=O)OCC(CCCCCCCC)CCCCCCCCCC)CCCCCC(=O)OCC(CCCCCCCC)CCCCCCCCCC
- CCCCCCCCCCCCCCCCCC[N+](C)(CCCCCCCCCC(=O)OCC(CC)CCCC)CCCCCCCCCC(=O)OCC(CC)CCCC
- CCCCCCCCCCCCCCCC[N+](C)(CCCCCCCCCCCC)CCCCCCCCCCCCCCCC
- CCCCCCCCCCCCCCCCCC[N+](C)(CCCCCCCCCCCC)CCCCCCCCCCCCCCCCCC
- CCCCCCCCCCCCCCCCCC[N+](C)(CCCCCCCCCCCCCC)CCCCCCCCCCCCCC
- CC1(C(=[N+](C2=CC=CC=C12)CCCCCCCCCCCCCCCCCC)C=CC=C1N(C2=CC=CC=C2C1(C)C)CCCCCCCCCCCCCCCCCC)C
- C=CCCCCOC(=O)CCCCCCCCC[N+](C)(CCCCCCCCCCCC)CCCCCCCCCC(=O)OCCCCC=C
- C=CCCCCOC(=O)CCCCCCCCC[N+](C)(CCCCCCCCCCCCCCCCCC)CCCCCCCCCC(=O)OCCCCC=C
- CCC/C=C/COC(=O)CCCCCCCCC[N+](C)(CCCCCCCCCCCC)CCCCCCCCCC(=O)OC/C=C/CCC
- CCCCCCCCCCC(CCCCCCCC)COC(=O)CCCCC[N+](CCCCCCCCCC)(CCCCCCCCCC)CCCCCCCCCC
- CCCCCCCCCCCC[N+](C)(CCCCCCCCCC(=O)OC/C=C(/C)CCC=C(C)C)CCCCCCCCCC(=O)OC/C=C(/C)CCC=C(C)C
- CCCCCCCCCCCC[N+](C)(CCCCCCCCCC(=O)OCC(CC)CCCC)CCCCCCCCCC(=O)OCC(CC)CCCC
- CCCCCCCCCCCC[N+](C)(CCCCCCCCCC(=O)OCCC(C)CCC=C(C)C)CCCCCCCCCC(=O)OCCC(C)CCC=C(C)C
- CCCCCCCCCCCCCCCCCC[N+](C)(CCCCCCCCCC(=O)OC/C=C(/C)CCC=C(C)C)CCCCCCCCCC(=O)OC/C=C(/C)CCC=C(C)C
- CCCCCCCCCCCCCCCCCC[N+](C)(CCCCCCCCCC(=O)OCC(CCCC)CCCCCC)CCCCCCCCCC(=O)OCC(CCCC)CCCCCC
- CCCCCCCCCCCCCCCCCC[N+](C)(CCCCCCCCCC(=O)OCCC(C)CCC=C(C)C)CCCCCCCCCC(=O)OCCC(C)CCC=C(C)C
- CCCCCCCCCCCCCCCCCCCCCC[N+](CCCCCC)(CCCCCCCCCCCCCCCCCCCCCC)CCCCCCCCCCCCCCCCCCCCCC
- C[N+](CCCCCCCCCCCC)(CCCCCCCCCCCC)CCCCCCCCCCCCCCCCCC

### IL_to_nucleicacid_massratio
Existing LNPDB examples:
- 10
- 40
- 5
- 15
- 16.96
- 25.44
- 8.48
- 7
- 11
- 13.9
- 7.5
- 20
- 10:1
- 13.93
- 11.3314
- 2.5
- 12.5
- 25
- 11.2
- 11.25

## Human-Curated Column and Value Definitions
Human-curated definitions are higher priority than frequency examples.
- No human-curated guide files were available.

## Reference Context Warnings
- none

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
python Agent_Task_Runner.py validate --stage 06_unified_lnpdb_extraction --paper-folder "F:\???쒕씪?대툕\EXTRACT-TEST\QS_2026_2"
```

## Constraints
- Do not use Gemini/API/find_api/LLM_API/LLM_Batch.
- Do not run legacy scripts from `1_Extract_Exp_Figs`, `3_Extract_Formula_by_Figs`, or `4_Extract_Exp_Vals`.
- Do not run or use DECIMER, MolScribe, `worker_mol.py`, structure-recognition `pipeline.py`, `recognition.py`, `segmentation.py`, molecule image crops, or image-derived SMILES outputs.
- Do not hard-code API keys or credentials.



