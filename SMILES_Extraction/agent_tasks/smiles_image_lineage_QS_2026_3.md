# SMILES image structure lineage task

This is an API-free external-agent judgment stage.

Paper folder:
`C:\LNPDB_WORK\QS_2026_3`

Candidate table:
`C:\LNPDB_WORK\QS_2026_3\SMILES_Extraction_Results\image_candidates\structure_candidates.csv`

Candidate context table:
`C:\LNPDB_WORK\QS_2026_3\SMILES_Extraction_Results\image_candidates\structure_candidate_context.csv`

Optional total figure mapping JSON:
`C:\LNPDB_WORK\QS_2026_3\total_figure_mapping.json`

## Rules

- Inspect `structure_candidates.csv`, `structure_candidate_context.csv`, contact sheets, crop images, page images, and the listed allowed marker markdown context when available.
- Judge `candidate_id` rows at crop level. When `structure_candidates.csv` contains crop rows, do not judge page-level fallback rows as replacements.
- Use `crop_path`, `contact_sheet_path`, `page_image_path`, and candidate context for each row.
- Decide whether each candidate crop is a chemical structure and whether it can be matched to a paper compound name.
- Match names only from candidate context or allowed marker markdown.
- `matched_name` must be exactly one paper compound name or blank.
- Never put semicolon-separated or pipe-separated multiple compound names in `matched_name`.
- If one crop corresponds to multiple compounds or a whole library panel, set `manual_required=true` and leave `matched_name` blank unless a single name is unambiguous.
- Do not overwrite or edit `molscribe_smiles`; it is supplied by the deterministic worker output and remains in `structure_candidates.csv`.
- Do not infer `matched_name` from the structure image alone.
- If context is insufficient, leave `matched_name` blank and set `manual_required=true`.
- If visual inspection is unavailable in your CLI environment, use filenames/contact sheets/markdown context and mark uncertain rows `manual_required=true`.
- Do not read previous logs, `agent_workspace`, old outputs, CSV/JSON run summaries, or repo-wide files.
- Do not run repo-wide `rg`.
- If using search, search only the candidate/context files and allowed marker markdown files referenced in `structure_candidate_context.csv`.
- Do not call Gemini, Vertex, GCS batch APIs, or project API helper scripts.

## Required output

Write:
- `C:\LNPDB_WORK\QS_2026_3\SMILES_Extraction_Results\image_agent\structure_lineage_agent.csv`
- `C:\LNPDB_WORK\QS_2026_3\SMILES_Extraction_Results\image_agent\structure_lineage_agent.json`

CSV columns, in this exact order:
candidate_id, is_structure, structure_type, structure_label, matched_name, component_type, confidence, manual_required, reason, evidence_text, evidence_source_path

Column guidance:
- `is_structure`: true/false/unclear.
- `structure_type`: Single, Markush, Combinatorial, Unknown.
- `structure_label`: nearby figure label such as 1, 2, A1, B1, H1 when inferable.
- `matched_name`: paper compound name only if source context supports it.
- `component_type`: ionizable_lipid, helper_lipid, cholesterol, peg_lipid, other, unclear.
- `confidence`: high, medium, low.
- `manual_required`: true/false.
- `reason`: concise evidence-level reason.
- `evidence_text`: source phrase/context used for matching.
- `evidence_source_path`: markdown/image/pdf/candidate path supporting the judgment.
