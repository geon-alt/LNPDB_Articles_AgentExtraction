# Legacy Context

This folder is reference-only. It gives external agents a stable place to inspect prior implementation logic, output shapes, naming conventions, and deterministic helper code.

It is not the active runtime path. Original legacy folders remain in their original repository locations for compatibility, and this context copy may be regenerated from those source folders.

External agents may read files here during task completion. Do not execute or import Gemini/API-dependent legacy scripts in the active workflow. Do not use `find_api.py`, `LLM_API.py`, `LLM_Batch.py`, `google.genai`, Vertex/Gemini/GCS code unless the operator explicitly requests legacy mode.

Active workflow policies:
- `agent_workspace/AGENT_INSTRUCTIONS.md`, `PIPELINE_SPEC.md`, `STAGE_CONTRACTS.md`, and `OUTPUT_SCHEMA.md` override legacy behavior.
- SMILES output columns are forced blank.
- Molecule-structure-image-based SMILES extraction is disabled.
- Excel-backed experimental values may be populated only with Excel/source-data provenance.
- Graph image digitization remains disabled.
