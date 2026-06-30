# Markdown Evidence Viewer

This is a local PySide6 desktop app for reviewing LNPDB-like extraction rows against grouped source evidence. It is not Streamlit and does not start a web server.

## Install

```bash
pip install pyside6 pandas
```

## Run

```bash
python Review_Apps/Markdown_Evidence_Viewer/markdown_evidence_viewer_pyside6.py
```

Optionally load a paper folder at startup:

```bash
python Review_Apps/Markdown_Evidence_Viewer/markdown_evidence_viewer_pyside6.py --paper-folder "<PAPER_FOLDER>"
```

## Required Inputs

Select a paper folder containing:

- `unified_extraction_lnpdb_like.csv`
- `unified_extraction_source_evidence.csv`
- `unified_extraction_figure_evidence_map.csv`

Optional files are used when present:

- `unified_extraction_final.csv`
- `unified_extraction.csv`
- `markdown_sentence_index/markdown_sentence_index_all.csv`
- `markdown_sentence_index/<source_md_id>.sentences.md`
- Markdown files under the paper folder
- Source images, PDFs, and Excel block CSVs referenced by the evidence tables

## Usage

1. Click **Browse** and select the paper folder.
2. Filter rows by `Item_ID`, `Experiment_method`, `Model`, `Model_target`, or text search.
3. Click a cell in the LNPDB-like table.
4. Inspect matched figure-level evidence rows.
5. Review the evidence sentence, source fields, markdown context, image preview, and block CSV preview.

Evidence matching uses:

`row_id + Item_ID + column_name -> unified_extraction_figure_evidence_map.csv -> evidence_id -> unified_extraction_source_evidence.csv`

When `evidence_sentence_ids` are available, the viewer uses them first:

`evidence_sentence_ids -> markdown_sentence_index/markdown_sentence_index_all.csv -> <source_md_id>.sentences.md`

The figure evidence map supports both pipe-separated and semicolon-separated list fields. Fuzzy markdown searching is only a fallback for evidence rows without sentence IDs.

## Notes

- PDF rendering is not implemented yet.
- PDF path and page fields are displayed for later PDF jump/highlight integration.
- PDF/image bbox and character offsets may be blank in current stage 07 outputs.
- Markdown table regions are excluded from numbered sentence indexes by design.
- Administrative/provenance columns can still be selected, but scientific evidence is required only for configured LNPDB condition/formulation columns.
- If a Streamlit-based viewer with a similar name exists later, the supported desktop viewer is `markdown_evidence_viewer_pyside6.py`.
