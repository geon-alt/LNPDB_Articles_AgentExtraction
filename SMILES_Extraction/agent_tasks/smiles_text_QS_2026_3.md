# SMILES text compound extraction task

You are completing an API-free SMILES text-preparation stage for one paper folder.

Paper folder:
`C:\LNPDB_WORK\QS_2026_3`

Markdown files to inspect:
- C:\LNPDB_WORK\QS_2026_3\41565_2025_2102_MOESM1_ESM\41565_2025_2102_MOESM1_ESM.md
- C:\LNPDB_WORK\QS_2026_3\QS_2026\QS_2026.md

Allowed source manifest:
- `C:\LNPDB_WORK\QS_2026_3\smiles_text_source_manifest.csv`
- `C:\LNPDB_WORK\QS_2026_3\smiles_text_source_manifest.json`

## Rules

- Use only the listed allowed markdown files as evidence.
- Do not read or use `agent_workspace`, `cli_full_logs`, `smiles_extraction_logs`, previous CSV/JSON outputs, run summaries, or repo-wide files.
- Do not run repo-wide `rg`.
- If using search, search only the listed markdown files.
- You are already the external LLM agent.
- Do not run `codex`, `claude`, `openai`, Gemini, Vertex, GCS, `find_api`, `LLM_API`, or `LLM_Batch`.
- Python/PowerShell may be used only for reading the allowed markdown files and writing/validating the requested CSV/JSON.
- Do not create a regex-only deterministic extractor as the primary extraction method.
- Scripts may only format and validate the judged extraction.
- Extract compound, lipid, helper lipid, PEG lipid, ionizable lipid, cargo/reagent, and formulation component candidates.
- Capture `Name`, aliases, and `IUPAC_name` only when the source text explicitly provides them.
- Do not hallucinate IUPAC names, SMILES strings, or structures.
- Use concise evidence snippets and source paths.
- Use CSV/JSON only.
- Do not call Gemini, Vertex, GCS batch APIs, or project API helper scripts.

## Required outputs

Write:
- `C:\LNPDB_WORK\QS_2026_3\text_extracted_iupac.csv`
- `C:\LNPDB_WORK\QS_2026_3\compound_inventory_standardized.csv`
- `C:\LNPDB_WORK\QS_2026_3\smiles_text_agent_notes.json`

`compound_inventory_standardized.csv` columns, in this exact order:
compound_id, Name, alias, IUPAC_name, Novelty, component_type, source_type, source_path, Item_ID, evidence_text, manual_required, reason

Column guidance:
- `compound_id`: stable ID such as C000001.
- `Name`: source compound/component name.
- `alias`: pipe-separated aliases if explicitly present.
- `IUPAC_name`: exact source IUPAC text only, blank if absent.
- `Novelty`: one of novel, known, unclear.
- `component_type`: ionizable_lipid, helper_lipid, cholesterol, peg_lipid, cargo, reagent, formulation_component, other, unclear.
- `source_type`: markdown.
- `source_path`: markdown path.
- `Item_ID`: figure/table item if directly tied to one, otherwise blank.
- `evidence_text`: shortest useful source phrase/sentence.
- `manual_required`: true/false.
- `reason`: concise reason for uncertainty or extraction choice.
