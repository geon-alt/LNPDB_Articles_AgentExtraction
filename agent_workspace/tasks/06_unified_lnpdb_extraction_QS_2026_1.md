# External Agent Task: 06_unified_lnpdb_extraction

Target paper folder: `F:\???쒕씪?대툕\EXTRACT-TEST\QS_2026_1`

## Stage Purpose
Create one unified long table at figure/table item level that combines experimental conditions, formulation composition, and provenance. Experimental numeric assay/readout value extraction is disabled for this stage and deferred to a future value-extraction stage.

## Required Input Files
- `F:\???쒕씪?대툕\EXTRACT-TEST\QS_2026_1\.manual_select_review_done`
- `F:\???쒕씪?대툕\EXTRACT-TEST\QS_2026_1\fig_table_lnpdb_classified.csv`
- `F:\???쒕씪?대툕\EXTRACT-TEST\QS_2026_1\total_figure_mapping.json`
- `F:\???쒕씪?대툕\EXTRACT-TEST\QS_2026_1\excel_mapping.json`
- `F:\???쒕씪?대툕\EXTRACT-TEST\QS_2026_1\excel_block_inventory.csv`
- `F:\???쒕씪?대툕\EXTRACT-TEST\QS_2026_1\Exp_Excel_Blocks`
- markdown files:
- `41565_2025_2102_MOESM1_ESM/41565_2025_2102_MOESM1_ESM.md`
- `QS_2026/QS_2026.md`

## Optional Input Files
- `compound_inventory_standardized.csv`
- `smiles_resolved.csv`
- `smiles_resolved.csv` only for SMILES fields. Do not use image-based structure-recognition outputs from `2_Extract_SMILES/FromImage/`

## Expected Output Files
- `F:\???쒕씪?대툕\EXTRACT-TEST\QS_2026_1\unified_extraction.csv`
- `F:\???쒕씪?대툕\EXTRACT-TEST\QS_2026_1\unified_extraction.json`
- `F:\???쒕씪?대툕\EXTRACT-TEST\QS_2026_1\unified_extraction_review_flags.csv`

## Required Output Columns
Use the columns documented in `agent_workspace/OUTPUT_SCHEMA.md` for `unified_extraction.csv`. Include all experimental condition, formulation composition, evidence, confidence, and manual review fields. Populate `metric_type`, `original_values`, `aggregated_value`, `unit`, and `replicate_type` only from reliable mapped Excel/source-data blocks. Leave them blank when no reliable Excel/source-data mapping exists.

## LNPDB Experimental-Condition Column Guide
- `Aqueous_buffer`: aqueous phase buffer used during LNP preparation, e.g. citrate buffer pH 4.0.
- `Dialysis_buffer`: dialysis or buffer-exchange medium after formulation, e.g. PBS.
- `Mixing_method`: formulation mixing approach or device, e.g. microfluidic mixing, pipette mixing, T-junction.
- `Model`: biological or experimental model name, e.g. MC38 cells, C57BL/6 mice, tumour-bearing mouse model.
- `Model_type`: normalized model class, e.g. in vitro cell model, in vivo mouse model, ex vivo tissue.
- `Model_target`: disease, tissue, cell, organ, or molecular target studied.
- `Route_of_administration`: dosing route, e.g. intravenous, intratumoral, subcutaneous, intramuscular.
- `Cargo`: delivered payload name, e.g. Fluc mRNA, IL-12 mRNA, OVA mRNA, siRNA.
- `Cargo_type`: normalized cargo class, e.g. mRNA, siRNA, DNA, protein, small molecule.
- `Dose_ug_nucleicacid`: nucleic-acid dose in micrograms when explicitly available; use only a concise scalar.
- `Experiment_method`: assay or experimental method label, e.g. ELISA, flow cytometry, IVIS imaging, qPCR.
- `Experiment_batching`: normalized grouping, batch, timepoint, replicate, or treatment schedule context when explicitly available.

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
- Do not copy full source sentences, captions, paragraphs, or methods prose into LNPDB fields.
- Full source sentences and captions may be stored only in `evidence_text`.
- If a concise normalized value cannot be determined, leave the field blank or mark `manual_required=true` with a reason.
- Do not use `variable` or `various` as a value unless the paper explicitly uses it as a label and no better scalar value exists.

## Existing LNPDB Column/Value Examples
Existing LNPDB values are examples, not a closed vocabulary.
- `Aqueous_buffer`: column_exists=True, non_empty_count=19528, unique_count=3
  - sources: F:\???쒕씪?대툕\LNPDB (1).csv
  - top values: citrate (15804); acetate (3694); Unknown (30)
  - examples: acetate; citrate; Unknown
- `Dialysis_buffer`: column_exists=True, non_empty_count=5997, unique_count=3
  - sources: F:\???쒕씪?대툕\LNPDB (1).csv
  - top values: PBS (5687); water (286); saline (24)
  - examples: PBS; saline; water
- `Mixing_method`: column_exists=True, non_empty_count=19528, unique_count=2
  - sources: F:\???쒕씪?대툕\LNPDB (1).csv
  - top values: handmixed (18310); microfluidics (1218)
  - examples: handmixed; microfluidics
- `Model`: column_exists=True, non_empty_count=19528, unique_count=2
  - sources: F:\???쒕씪?대툕\LNPDB (1).csv
  - top values: in_vitro (17140); in_vivo (2388)
  - examples: in_vitro; in_vivo
- `Model_type`: column_exists=True, non_empty_count=19528, unique_count=17
  - sources: F:\???쒕씪?대툕\LNPDB (1).csv
  - top values: HeLa (7783); A549 (2569); HepG2 (2000); Mouse_B6 (1818); DC2.4 (1703); IGROV1 (1202); RAW264.7 (1200); Mouse_BALBc (359); BeWo_b30 (260); HEK293T (256)
  - examples: HeLa; HEK293T; Mouse_B6; Mouse_CD1; BMDC; BMDM; IGROV1; HepG2
- `Model_target`: column_exists=True, non_empty_count=19528, unique_count=12
  - sources: F:\???쒕씪?대툕\LNPDB (1).csv
  - top values: in_vitro (15310); lung_epithelium (1879); liver (905); muscle (486); spleen (258); multiorgan (192); bone_marrow (141); heart (96); lung (96); kidney (95)
  - examples: in_vitro; liver; whole_body; muscle; lung_epithelium; spleen; heart; lung
- `Route_of_administration`: column_exists=True, non_empty_count=19528, unique_count=5
  - sources: F:\???쒕씪?대툕\LNPDB (1).csv
  - top values: in_vitro (17140); intravenous (1793); intramuscular (486); intradermal (60); intratracheal (49)
  - examples: in_vitro; intravenous; intramuscular; intratracheal; intradermal
- `Cargo`: column_exists=True, non_empty_count=19528, unique_count=3
  - sources: F:\???쒕씪?대툕\LNPDB (1).csv
  - top values: mRNA (14578); siRNA (3758); pDNA (1192)
  - examples: siRNA; pDNA; mRNA
- `Cargo_type`: column_exists=True, non_empty_count=19528, unique_count=8
  - sources: F:\???쒕씪?대툕\LNPDB (1).csv
  - top values: FLuc (17752); DNA_barcode (671); peptide_barcode (407); hEPO (268); base_editor (141); FVII (117); GFP (112); RLuc (60)
  - examples: FLuc; GFP; FVII; peptide_barcode; hEPO; DNA_barcode; RLuc; base_editor
- `Dose_ug_nucleicacid`: column_exists=True, non_empty_count=19797, unique_count=20
  - sources: F:\???쒕씪?대툕\LNPDB (1).csv
  - top values: 0.1 (7079); 0.05 (2479); 0.2 (2461); 0.02 (1830); 5 (1156); 0.01 (997); 1 (830); 0.025 (635); 0.003 (500); 0.9 (497)
  - examples: 0.9; 0.081521739; 0.075; 0.05; 100; 0.1; 20; 10
- `Experiment_method`: column_exists=True, non_empty_count=19528, unique_count=10
  - sources: F:\???쒕씪?대툕\LNPDB (1).csv
  - top values: luminescence_normalized (14630); luminescence_discretized_normalized (3058); protein_adundance_normalized (766); uptake (479); editing_efficiency_normalized (141); LRP6_knockdown_normalized (112); diameter (96); zeta_potential (96); hemolysis_percent (90); luminescence_relative_to_Spikevax (60)
  - examples: luminescence_discretized_normalized; luminescence_normalized; LRP6_knockdown_normalized; protein_adundance_normalized; uptake; diameter; zeta_potential; hemolysis_percent
- `Experiment_batching`: column_exists=True, non_empty_count=19528, unique_count=2
  - sources: F:\???쒕씪?대툕\LNPDB (1).csv
  - top values: individual (18642); barcoded (886)
  - examples: individual; barcoded
- `formulation_id`: column_exists=True, non_empty_count=19528, unique_count=19528
  - sources: F:\???쒕씪?대툕\LNPDB (1).csv
  - top values: AA_2008_F1 (1); AA_2008_F10 (1); AA_2008_F100 (1); AA_2008_F101 (1); AA_2008_F102 (1); AA_2008_F103 (1); AA_2008_F104 (1); AA_2008_F105 (1); AA_2008_F106 (1); AA_2008_F107 (1)
  - examples: AA_2008_F1; AA_2008_F2; AA_2008_F3; AA_2008_F4; AA_2008_F5; AA_2008_F6; AA_2008_F7; AA_2008_F8
- `IL_name`: column_exists=True, non_empty_count=19797, unique_count=13016
  - sources: F:\???쒕씪?대툕\LNPDB (1).csv
  - top values: DLin-MC3-DMA (2194); 1_A3_T9b2 (197); other (157); ALC-0315 (96); RM_branched_ester_M3_R14 (44); RM_branched_ester_M3_R7 (44); IR_red_amin_IRh20_IRt11 (42); RM_branched_ester_M3_R6 (42); RM_branched_ester_M3_R13 (25); RM_branched_ester_M68_R10 (25)
  - examples: 87_O15; 96_N12; 98_N12; 64_N15; 64_N16; 26_O14; 32_N12; 95_N12
- `IL_SMILES`: column_exists=True, non_empty_count=19797, unique_count=12844
  - sources: F:\???쒕씪?대툕\LNPDB (1).csv
  - top values: CCCCC/C=C\C/C=C\CCCCCCCCC(CCCCCCCC/C=C\C/C=C\CCCCC)OC(=O)CCCN(C)C (2165); CCCCC(CC)CCC(=O)Oc1cc(OC(=O)CCC(CC)CCCC)c(CNCCN(C)CCNCc2c(OC(=O)CCC(CC)CCCC)cc(OC(=O)CCC(CC)CCCC)cc2OC(=O)CCC(CC)CCCC)c(OC(=O)CCC(CC)CCCC)c1 (197); CCCCCCCCC(CCCCCC)C(=O)OCCCCCCN(CCCCCCOC(=O)C(CCCCCC)CCCCCCCC)CCCCO (96); CCCCC/C=C\C/C=C\CCCCCCCC(=O)OC(C/C=C\CCCCCCCCOC(=O)CCN(CCCN(CC)CC)CCC(=O)OCCCCCCCC/C=C\CC(CCCCCC)OC(=O)CCCCCCC/C=C\C/C=C\CCCCC)CCCCCC (45); CCCCCCCC/C=C\CCCCCCCC(=O)OCCCCCC(O)C(CCCCOC(=O)CCCCCCC/C=C\CCCCCCCC)CN(C)CCCn1cccn1 (42); CCCCC/C=C\C/C=C\CCCCCCCCC(OC(=O)CCCN(C)C)CCCCCCCC/C=C\C/C=C\CCCCC (30); CCCCCCCC/C=C\CCCCCCCC(=O)OC(C/C=C\CCCCCCCCOC(=O)CCN(CCC(=O)OCCCCCCCC/C=C\CC(CCCCCC)OC(=O)CCCCCCC/C=C\CCCCCCCC)CCN1CCCC1)CCCCCC (26); CCCCCCCCC(CCCCCC)C(=O)OC(C/C=C\CCCCCCCCOC(=O)CCN(CCCN(CC)CC)CCC(=O)OCCCCCCCC/C=C\CC(CCCCCC)OC(=O)C(CCCCCC)CCCCCCCC)CCCCCC (26); CCCCCCCCCCC(O)CN(CCCCC1NC(=O)C(CCCCN(CC(O)CCCCCCCCCC)CC(O)CCCCCCCCCC)NC1=O)CC(O)CCCCCCCCCC (26); CCCCCCCCCCCC(=O)OC(C/C=C\CCCCCCCCOC(=O)CCN(CCC(=O)OCCCCCCCC/C=C\CC(CCCCCC)OC(=O)CCCCCCCCCCC)CCN1CCCC1)CCCCCC (26)
  - examples: CCCCCCCCCCCCCCCOC(=O)CCN(CCCN(CCO)CCO)CCC(=O)OCCCCCCCCCCCCCCC; CCCCCCCCCCCCNC(=O)CCN(C)CCCN(CCC(=O)NCCCCCCCCCCCC)CCC(=O)NCCCCCCCCCCCC; CCCCCCCCCCCCNC(=O)CCN(CCC(=O)NCCCCCCCCCCCC)CCN(CCC(=O)NCCCCCCCCCCCC)CCN(CCC(=O)NCCCCCCCCCCCC)CCN(CCC(=O)NCCCCCCCCCCCC)CCC(=O)NCCCCCCCCCCCC; CCCCCCCCCCCCCCCNC(=O)CCN(CC)CCCN(CC)CCC(=O)NCCCCCCCCCCCCCCC; CCCCCCCCCCCCCCCCNC(=O)CCN(CC)CCCN(CC)CCC(=O)NCCCCCCCCCCCCCCCC; CCCCCCCCCCCCCCOC(=O)CCN(CCC(=O)OCCCCCCCCCCCCCC)C(C)(CO)CO; CCCCCCCCCCCCNC(=O)CCN(CCCCCO)CCC(=O)NCCCCCCCCCCCC; CCCCCCCCCCCCNC(=O)CCN(C)CCN(CCC(=O)NCCCCCCCCCCCC)CCC(=O)NCCCCCCCCCCCC
- `HL_name`: column_exists=True, non_empty_count=18959, unique_count=7
  - sources: F:\???쒕씪?대툕\LNPDB (1).csv
  - top values: DOPE (9312); DSPC (5525); DOTAP (2470); MDOA (572); 14PA (360); 18PG (360); DDAB (360)
  - examples: DSPC; DOPE; MDOA; DOTAP; DDAB; 14PA; 18PG
- `HL_SMILES`: column_exists=True, non_empty_count=19797, unique_count=9
  - sources: F:\???쒕씪?대툕\LNPDB (1).csv
  - top values: [H][C@@](COP([O-])(OCC[NH3+])=O)(OC(CCCCCCC/C=C\\CCCCCCCC)=O)COC(CCCCCCC/C=C\\CCCCCCCC)=O (9271); CCCCCCCCCCCCCCCCCC(=O)OC[C@H](COP(=O)([O-])OCC[N+](C)(C)C)OC(=O)CCCCCCCCCCCCCCCCC (5525); [H]C(C[N+](C)(C)C)(OC(CCCCCCC/C=C\CCCCCCCC)=O)COC(CCCCCCC/C=C\CCCCCCCC)=O (2470); NA (838); CCCCCCCCCCCCCCCCCCN(C)CCCCCCCCCCCCCCCCCC (572); [P](=O)([O-])(OC[C@H](OC(=O)CCCCCCCCCCCCC)COC(=O)CCCCCCCCCCCCC)O (360); [P](=O)([O-])(OC[C@H](OC(=O)CCCCCCCCCCCCCCCCC)COC(=O)CCCCCCCCCCCCCCCCC)OCC(O)CO (360); CCCCCCCCCCCCCCCCCC[N+](CCCCCCCCCCCCCCCCCC)(C)C (360); [H][C@@](COP([O-])(OCC[NH3+])=O)(OC(CCCCCCC/C=C\CCCCCCCC)=O)COC(CCCCCCC/C=C\CCCCCCCC)=O (41)
  - examples: NA; CCCCCCCCCCCCCCCCCC(=O)OC[C@H](COP(=O)([O-])OCC[N+](C)(C)C)OC(=O)CCCCCCCCCCCCCCCCC; [H][C@@](COP([O-])(OCC[NH3+])=O)(OC(CCCCCCC/C=C\\CCCCCCCC)=O)COC(CCCCCCC/C=C\\CCCCCCCC)=O; CCCCCCCCCCCCCCCCCCN(C)CCCCCCCCCCCCCCCCCC; [H]C(C[N+](C)(C)C)(OC(CCCCCCC/C=C\CCCCCCCC)=O)COC(CCCCCCC/C=C\CCCCCCCC)=O; CCCCCCCCCCCCCCCCCC[N+](CCCCCCCCCCCCCCCCCC)(C)C; [P](=O)([O-])(OC[C@H](OC(=O)CCCCCCCCCCCCC)COC(=O)CCCCCCCCCCCCC)O; [P](=O)([O-])(OC[C@H](OC(=O)CCCCCCCCCCCCCCCCC)COC(=O)CCCCCCCCCCCCCCCCC)OCC(O)CO
- `CHL_name`: column_exists=True, non_empty_count=19528, unique_count=16
  - sources: F:\???쒕씪?대툕\LNPDB (1).csv
  - top values: Cholesterol (19464); n-butyl lithocholate (35); Beta-Sitosterol (5); Campesterol (4); Fucosterol (4); Stigmastanol (4); 3-methylpentyl lithocholate (2); iso-Pentyl lithocholate (2); Betulin (1); Calcipotriol (1)
  - examples: Cholesterol; Vitamin D2; Vitamin D3; Calcipotriol; Stigmasterol; Beta-Sitosterol; Betulin; Lupeol
- `CHL_SMILES`: column_exists=True, non_empty_count=19528, unique_count=16
  - sources: F:\???쒕씪?대툕\LNPDB (1).csv
  - top values: C[C@H](CCCC(C)C)[C@H]1CC[C@@H]2[C@@]1(CC[C@H]3[C@H]2CC=C4[C@@]3(CC[C@@H](C4)O)C)C (19464); C[C@H](CCC(OCCCC)=O)[C@@]1([H])CC[C@@]2([H])[C@]3([H])CC[C@]4([H])C[C@H](O)CC[C@]4(C)[C@@]3([H])CC[C@@]21C (35); CC[C@H](CC[C@@H](C)[C@H]1CC[C@@H]2[C@@]1(CC[C@H]3[C@H]2CC=C4[C@@]3(CC[C@@H](C4)O)C)C)C(C)C (5); C/C=C(\CC[C@@H](C)[C@H]1CC[C@@H]2[C@@]1(CC[C@H]3[C@H]2CC=C4[C@@]3(CC[C@@H](C4)O)C)C)/C(C)C (4); C[C@H](CC[C@@H](C)C(C)C)[C@H]1CC[C@@H]2[C@@]1(CC[C@H]3[C@H]2CC=C4[C@@]3(CC[C@@H](C4)O)C)C (4); CC[C@H](CC[C@@H](C)[C@H]1CC[C@@H]2[C@@]1(CC[C@H]3[C@H]2CC[C@@H]4[C@@]3(CC[C@@H](C4)O)C)C)C(C)C (4); O=C(OCCC(C)C)CC[C@@H](C)[C@@]1([H])CC[C@@]2([H])[C@]3([H])CC[C@]4([H])C[C@H](O)CC[C@]4(C)[C@@]3([H])CC[C@@]21C (2); O=C(OCCC(C)CC)CC[C@H](C)[C@@]1([H])CC[C@@]2([H])[C@]3([H])CC[C@]4([H])C[C@H](O)CC[C@]4(C)[C@@]3([H])CC[C@@]21C (2); C[C@@H]1CC[C@@]2(CC[C@@]3(C(=CC[C@H]4[C@]3(CC[C@@H]5[C@@]4(CC[C@@H](C5(C)C)O)C)C)[C@@H]2[C@H]1C)C)C(=O)O (1); C[C@]12CC[C@@H](C([C@@H]1CC[C@@]3([C@@H]2CC=C4[C@]3(CC[C@@]5([C@H]4CC(CC5)(C)C)C(=O)O)C)C)(C)C)O (1)
  - examples: C[C@H](CCCC(C)C)[C@H]1CC[C@@H]2[C@@]1(CC[C@H]3[C@H]2CC=C4[C@@]3(CC[C@@H](C4)O)C)C; C[C@H](CCCC(C)C)[C@H]1CC[C@@H]\2[C@@]1(CCC/C2=C\C=C/3\C[C@H](CCC3=C)O)C; C[C@H](/C=C/[C@H](C)C(C)C)[C@H]1CCC\2[C@@]1(CCC/C2=C\C=C\3/CC(CCC3=C)O[C@H]4[C@@H]([C@H]([C@@H]([C@H](O4)C(=O)O)O)O)O)C; C[C@H](/C=C/[C@H](C1CC1)O)[C@H]2CC[C@@H]\3[C@@]2(CCC/C3=C\C=C/4\C[C@H](C[C@@H](C4=C)O)O)C; CC[C@H](/C=C/[C@@H](C)[C@H]1CC[C@@H]2[C@@]1(CC[C@H]3[C@H]2CC=C4[C@@]3(CC[C@@H](C4)O)C)C)C(C)C; CC[C@H](CC[C@@H](C)[C@H]1CC[C@@H]2[C@@]1(CC[C@H]3[C@H]2CC=C4[C@@]3(CC[C@@H](C4)O)C)C)C(C)C; CC(=C)[C@@H]1CC[C@]2([C@H]1[C@H]3CC[C@@H]4[C@]5(CC[C@@H](C([C@@H]5CC[C@]4([C@@]3(CC2)C)C)(C)C)O)C)CO; CC(=C)[C@@H]1CC[C@]2([C@H]1[C@H]3CC[C@@H]4[C@]5(CC[C@@H](C([C@@H]5CC[C@]4([C@@]3(CC2)C)C)(C)C)O)C)C
- `PEG_name`: column_exists=True, non_empty_count=19344, unique_count=15
  - sources: F:\???쒕씪?대툕\LNPDB (1).csv
  - top values: DMG-PEG2000 (11145); DMPE-PEG2000 (6322); Unknown (1798); DSG-PEG2000 (13); ALC-0159 (12); C16-Ceramide-PEG2000 (12); C8-Ceramide-PEG2000 (12); DMG-C-PEG2000 (12); DSPE-PEG2000 (12); DMG-PEG5000 (1)
  - examples: DMG-PEG2000; Unknown; DMPE-PEG2000; DMG-PEG5000; DPG-PEG2000; DPG-PEG5000; DSG-PEG2000; DSG-PEG5000
- `PEG_SMILES`: column_exists=True, non_empty_count=17546, unique_count=14
  - sources: F:\???쒕씪?대툕\LNPDB (1).csv
  - top values: O=C(CCCCCCCCCCCCC)OCC(OC(CCCCCCCCCCCCC)=O)COCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOC (13047); CCCCCCCCCCCCCC(=O)OCC(COP(=O)(OCCNCC(=O)OCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOC)O)OC(=O)CCCCCCCCCCCCC (4420); O=C(CCCCCCCCCCCCCCCCC)OCC(OC(CCCCCCCCCCCCCCCCC)=O)COCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOC (13); [H][C@](/C=C/CCCCCCCCCCCCC)(O)[C@@]([H])(NC(CCCCCCC)=O)COC(CCC(OOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOC)=O)=O (12); CCCCCCCCCCCCC/C=C/[C@@H](O)[C@@H](NC(=O)CCCCCCCCCCCCCCC)COC(=O)CCC(=O)OCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOC (12); CCCCCCCCCCCCCC(O[C@H](COC(CCCCCCCCCCCCC)=O)COC(NCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOC)=O)=O (12); CCCCCCCCCCCCCCCCCC(=O)OCC(COP(=O)(OCCNCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOC)O)OC(=O)CCCCCCCCCCCCCCCCCC (12); CCCCCCCCCCCCCCN(CCCCCCCCCCCCCC)C(COCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOC)=O (12); CCCCCCCC/C=C\CCCCCCC(=O)OCC(COC(=O)CCCCCCC/C=C\CCCCCCC)OCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOC (1); CCCCCCCC/C=C\CCCCCCC(=O)OCC(COC(=O)CCCCCCC/C=C\CCCCCCC)OCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOC (1)
  - examples: O=C(CCCCCCCCCCCCC)OCC(OC(CCCCCCCCCCCCC)=O)COCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOC; CCCCCCCCCCCCCC(=O)OCC(COP(=O)(OCCNCC(=O)OCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOC)O)OC(=O)CCCCCCCCCCCCC; O=C(CCCCCCCCCCCCC)OCC(OC(CCCCCCCCCCCCC)=O)COCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOC; CCCCCCCCCCCCCCCC(=O)OCC(COC(=O)CCCCCCCCCCCCCCCC)OCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOC; CCCCCCCCCCCCCCCC(=O)OCC(COC(=O)CCCCCCCCCCCCCCCC)OCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOC; O=C(CCCCCCCCCCCCCCCCC)OCC(OC(CCCCCCCCCCCCCCCCC)=O)COCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOC; O=C(CCCCCCCCCCCCCCCCC)OCC(OC(CCCCCCCCCCCCCCCCC)=O)COCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOC; CCCCCCCC/C=C\CCCCCCC(=O)OCC(COC(=O)CCCCCCC/C=C\CCCCCCC)OCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOC
- `Fifth_component_name`: column_exists=True, non_empty_count=38, unique_count=1
  - sources: F:\???쒕씪?대툕\LNPDB (1).csv
  - top values: 6,6'-trehalose dioleate (38)
  - examples: 6,6'-trehalose dioleate
- `Fifth_component_SMILES`: column_exists=True, non_empty_count=19797, unique_count=2
  - sources: F:\???쒕씪?대툕\LNPDB (1).csv
  - top values: NA (19759); O[C@@H]1[C@@H](O)[C@H](O)[C@@H](COC(CCCCCCC/C=C\CCCCCCCC)=O)O[C@@H]1O[C@@H]2[C@H](O)[C@@H](O)[C@H](O)[C@@H](COC(CCCCCCC/C=C\CCCCCCCC)=O)O2 (38)
  - examples: NA; O[C@@H]1[C@@H](O)[C@H](O)[C@@H](COC(CCCCCCC/C=C\CCCCCCCC)=O)O[C@@H]1O[C@@H]2[C@H](O)[C@@H](O)[C@H](O)[C@@H](COC(CCCCCCC/C=C\CCCCCCCC)=O)O2
- `IL_to_nucleicacid_massratio`: column_exists=True, non_empty_count=19797, unique_count=1891
  - sources: F:\???쒕씪?대툕\LNPDB (1).csv
  - top values: 10 (11053); 5 (1458); 16.96 (720); 25.44 (720); 8.48 (720); 15 (693); 7 (378); 11 (325); 13.9 (286); NA (269)
  - examples: 5; 7; 3.163915524; 3.2940723; 3.245692009; 3.251864601; 3.294203468; 3.20844915

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
10. If multiple formulations or condition groups exist in one figure/table, produce one row per formulation/condition context.
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
python Agent_Task_Runner.py validate --stage 06_unified_lnpdb_extraction --paper-folder "F:\???쒕씪?대툕\EXTRACT-TEST\QS_2026_1"
```

## Constraints
- Do not use Gemini/API/find_api/LLM_API/LLM_Batch.
- Do not run legacy scripts from `1_Extract_Exp_Figs`, `3_Extract_Formula_by_Figs`, or `4_Extract_Exp_Vals`.
- Do not run or use DECIMER, MolScribe, `worker_mol.py`, structure-recognition `pipeline.py`, `recognition.py`, `segmentation.py`, molecule image crops, or image-derived SMILES outputs.
- Do not hard-code API keys or credentials.



