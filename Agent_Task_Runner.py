from __future__ import annotations

import argparse
import csv
import importlib.util
import json
import re
import shlex
import shutil
import subprocess
import sys
import threading
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parent
WORKSPACE = PROJECT_ROOT / "agent_workspace"
STATE_PATH = WORKSPACE / "agent_state.json"
QUEUE_PATH = WORKSPACE / "task_queue.json"
LOG_DIR = WORKSPACE / "logs"
TASK_DIR = WORKSPACE / "tasks"
MANUAL_MARKER = ".manual_select_review_done"
PROJECT_EXCLUDE_DIRS = {
    ".git",
    ".idea",
    "__pycache__",
    "0_mark_down_gen",
    "agent_workspace",
}

FALLBACK_SOURCE_QUALITIES = {
    "suspect_crop",
    "missing_image",
    "caption_image_mismatch",
}

VALID_SOURCE_QUALITIES = FALLBACK_SOURCE_QUALITIES | {
    "ok",
    "pdf_page_render_fallback",
    "manual_required",
}


STAGE_ORDER = [
    "00_marker",
    "01_make_ft_csv",
    "02_ft_selector",
    "02b_manual_review",
    "03_figure_mapping",
    "03_split_excel_blocks",
    "03_split_excel_blocks_batch",
    "04_figure_separate",
    "04_ft_excel_matcher",
    "05_smiles_structure_resolution",
    "06_unified_lnpdb_extraction",
    "07_finalize_unified_table",
]

AGENT_STAGES = {
    "03_figure_mapping",
    "03_split_excel_blocks",
    "03_split_excel_blocks_batch",
    "04_figure_separate",
    "04_ft_excel_matcher",
    "05_smiles_structure_resolution",
    "06_unified_lnpdb_extraction",
    "07_finalize_unified_table",
}


STAGE_EXECUTION_MODE = {
    "03_figure_mapping": "external_agent",
    "03_split_excel_blocks_batch": "external_agent",
    "04_figure_separate": "external_agent",
    "04_ft_excel_matcher": "external_agent",
    "05_smiles_structure_resolution": "external_agent",
    "06_unified_lnpdb_extraction": "external_agent",
    "07_finalize_unified_table": "heuristic",
}

VALID_STAGE_EXECUTION_MODES = {"legacy", "external_agent", "heuristic"}

DEFAULT_AGENT_ACTIVE_STAGES = [
    "03_figure_mapping",
    "03_split_excel_blocks_batch",
    "04_figure_separate",
    "04_ft_excel_matcher",
    "05_smiles_structure_resolution",
    "06_unified_lnpdb_extraction",
    "07_finalize_unified_table",
]

DEFAULT_AGENT_COMMAND_TEMPLATES = {
    "codex": 'codex exec --cd "{project_root}" --dangerously-bypass-approvals-and-sandbox --add-dir "{paper_folder}" -',
    "claude": 'claude -p "{prompt_text}"',
}


STAGES: dict[str, dict[str, Any]] = {
    "00_marker": {
        "script": "0_mark_down_gen/00_Marker.py",
        "outputs": ["*.md"],
    },
    "01_make_ft_csv": {
        "script": "0_mark_down_gen/01_make_FT_csv.py",
        "outputs": ["fig_table_inventory.csv"],
    },
    "02_ft_selector": {
        "script": "0_mark_down_gen/02_FT_selector.py",
        "outputs": ["fig_table_lnpdb_classified.csv"],
    },
    "02b_manual_review": {
        "script": "0_mark_down_gen/02B_FT_manual_selector_gui.py",
        "outputs": [MANUAL_MARKER],
        "manual": True,
    },
    "03_figure_mapping": {
        "script": "0_mark_down_gen/03_figure_mapping.py",
        "outputs": ["total_figure_mapping.json"],
        "requires_manual_marker": True,
    },
    "03_split_excel_blocks": {
        "script": "0_mark_down_gen/03_split_excel_blocks.py",
        "outputs": [],
        "requires_manual_marker": True,
        "utility_only": True,
    },
    "03_split_excel_blocks_batch": {
        "script": "0_mark_down_gen/03_split_excel_blocks_batch.py",
        "outputs": ["excel_block_inventory.csv", "three_core_result_all.json", "Exp_Excel_Blocks"],
        "requires_manual_marker": True,
    },
    "04_figure_separate": {
        "script": "0_mark_down_gen/04_figure_saperate_gemini.py",
        "outputs": ["separated_panels_gemini"],
        "requires_manual_marker": True,
    },
    "04_ft_excel_matcher": {
        "script": "0_mark_down_gen/04_FT-Excel_matcher.py",
        "outputs": ["excel_mapping.json", "excel_mapping_rows.csv"],
        "requires_manual_marker": True,
    },
    "05_smiles_structure_resolution": {
        "script": "2_Extract_SMILES/FromIUPAC/Extract_Text_Lipid.py",
        "outputs": ["compound_inventory_standardized.csv", "smiles_resolved.csv", "smiles_resolution_qc.csv"],
        "requires_manual_marker": True,
    },
    "06_unified_lnpdb_extraction": {
        "script": "4_Extract_Exp_Vals/Exp_Vals_From_Exles/42_Extract_Exp_Vals_Router.py",
        "outputs": ["unified_extraction.csv", "unified_extraction.json", "unified_extraction_review_flags.csv"],
        "requires_manual_marker": True,
    },
    "07_finalize_unified_table": {
        "script": "Agent_Task_Runner.py",
        "outputs": ["unified_extraction_final.csv", "unified_extraction_lnpdb_like.csv", "unified_extraction_qc_report.json"],
        "requires_manual_marker": True,
    },
}

LEGACY_STAGE_SCRIPT_GROUPS: dict[str, list[str]] = {
    "05_smiles_structure_resolution": [
        "2_Extract_SMILES/FromIUPAC/20_Text_to_SMILES.py",
        "2_Extract_SMILES/FromIUPAC/Extract_Text_Lipid.py",
        "2_Extract_SMILES/FromIUPAC/Extract_Lipid_SMILES.py",
        "2_Extract_SMILES/FromImage/mol_annotator/*.py",
    ],
    "06_unified_lnpdb_extraction": [
        "1_Extract_Exp_Figs/10_Extract_from_Excel.py",
        "1_Extract_Exp_Figs/10_Extract_from_PDF_one.py",
        "1_Extract_Exp_Figs/10_Extract_from_PDF_grouped.py",
        "3_Extract_Formula_by_Figs/30_Extract_Formula_by_Excel.py",
        "3_Extract_Formula_by_Figs/30_Extract_Formula_by_Figs.py",
        "4_Extract_Exp_Vals/Exp_Vals_From_Exles/40_Extract_Exp_Vals_Norm.py",
        "4_Extract_Exp_Vals/Exp_Vals_From_Exles/41_Extract_Exp_Vals_DirectLLM.py",
        "4_Extract_Exp_Vals/Exp_Vals_From_Exles/42_Extract_Exp_Vals_Router.py",
        "4_Extract_Exp_Vals/Exp_Vals_From_Exles/Fig_Excel_Matching.py",
        "4_Extract_Exp_Vals/Exp_Vals_From_Tables/50_Tabel_Extractor.py",
        "4_Extract_Exp_Vals/Exp_Vals_From_Tables/TableExtractor.py",
    ],
}

UNIFIED_EXTRACTION_COLUMNS = [
    "Paper_ID",
    "Item_ID",
    "visual_type",
    "source_type",
    "source_image",
    "source_pdf",
    "source_page",
    "selected_source_for_paneling",
    "excel_file",
    "excel_sheet",
    "block_id",
    "block_csv_path",
    "Aqueous_buffer",
    "Dialysis_buffer",
    "Mixing_method",
    "Model",
    "Model_type",
    "Model_target",
    "Route_of_administration",
    "Cargo",
    "Cargo_type",
    "Dose_ug_nucleicacid",
    "Experiment_method",
    "Experiment_batching",
    "formulation_id",
    "Formulation_Name",
    "IL_name",
    "IL_SMILES",
    "IL_molarratio",
    "HL_name",
    "HL_SMILES",
    "HL_molarratio",
    "CHL_name",
    "CHL_SMILES",
    "CHL_molarratio",
    "PEG_name",
    "PEG_SMILES",
    "PEG_molarratio",
    "Fifth_component_name",
    "Fifth_component_SMILES",
    "Fifth_component_molarratio",
    "IL_to_nucleicacid_massratio",
    "condition_1_name",
    "condition_1_value",
    "condition_2_name",
    "condition_2_value",
    "condition_3_name",
    "condition_3_value",
    "condition_4_name",
    "condition_4_value",
    "metric_type",
    "original_values",
    "aggregated_value",
    "unit",
    "replicate_type",
    "evidence_text",
    "evidence_image",
    "evidence_excel",
    "confidence",
    "manual_required",
    "reason",
]

UNIFIED_REVIEW_FLAG_COLUMNS = [
    "Paper_ID",
    "Item_ID",
    "block_id",
    "field",
    "issue",
    "severity",
    "reason",
]


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def append_log(paper_folder: Path, event: dict[str, Any]) -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    safe_name = paper_folder.name or "root"
    log_path = LOG_DIR / f"{safe_name}.jsonl"
    record = {"timestamp": utc_now(), "paper_folder": str(paper_folder), **event}
    with log_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def update_state(paper_folder: Path, stage: str | None, status: str, detail: dict[str, Any] | None = None) -> None:
    state = load_json(
        STATE_PATH,
        {
            "schema_version": 1,
            "project": "LNPDB_Articles_AgentExtraction",
            "mode": "external_cli_agent_workspace",
            "stage_status": {},
        },
    )
    state["active_paper_folder"] = str(paper_folder)
    state["current_stage"] = stage
    state["last_updated"] = utc_now()
    state["last_event"] = {"stage": stage, "status": status, "detail": detail or {}}
    if stage:
        state.setdefault("stage_status", {})[stage] = {
            "status": status,
            "updated": state["last_updated"],
            "detail": detail or {},
        }
    state["manual_review_required"] = not (paper_folder / MANUAL_MARKER).exists()
    write_json(STATE_PATH, state)


def resolve_paper_folder(value: str) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return path.resolve()


def import_module_from_path(module_name: str, script_path: Path):
    if str(script_path.parent) not in sys.path:
        sys.path.insert(0, str(script_path.parent))
    if str(PROJECT_ROOT) not in sys.path:
        sys.path.insert(0, str(PROJECT_ROOT))
    spec = importlib.util.spec_from_file_location(module_name, script_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot import {script_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def read_csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def non_empty_file(path: Path) -> bool:
    return path.is_file() and path.stat().st_size > 0


def has_manual_marker(paper_folder: Path) -> bool:
    return (paper_folder / MANUAL_MARKER).exists()


def iter_paper_files(paper_folder: Path):
    for path in paper_folder.rglob("*"):
        try:
            rel_parts = path.relative_to(paper_folder).parts
        except ValueError:
            rel_parts = path.parts
        if any(part in PROJECT_EXCLUDE_DIRS for part in rel_parts):
            continue
        if path.is_file():
            yield path


def rel_to_paper(path: Path, paper_folder: Path) -> str:
    try:
        return path.resolve().relative_to(paper_folder.resolve()).as_posix()
    except ValueError:
        return str(path)


def path_from_mapping_value(paper_folder: Path, value: Any) -> Path | None:
    if not isinstance(value, str) or not value.strip():
        return None
    path = Path(value.strip())
    if not path.is_absolute():
        path = paper_folder / path
    return path


def iter_total_figure_mapping_entries(data: Any):
    if not isinstance(data, dict):
        return
    for key, value in data.items():
        if not isinstance(value, dict):
            continue
        if isinstance(key, str) and key.startswith("_"):
            continue
        if any(field in value for field in ("source_image", "source_pdf", "source_page", "panels", "caption")):
            yield value
            continue
        for item_key, entry in value.items():
            if isinstance(item_key, str) and item_key.startswith("_"):
                continue
            if isinstance(entry, dict):
                yield entry


def render_pdf_page(paper_folder: Path, source_pdf: str, source_page: int, dpi: int = 220) -> str:
    try:
        import fitz
    except ImportError as exc:
        raise RuntimeError("PyMuPDF is required for PDF page render fallback. Install package 'pymupdf'.") from exc

    if source_page < 1:
        raise ValueError(f"source_page must be a 1-based positive integer, got {source_page!r}")

    pdf_path = Path(source_pdf)
    if not pdf_path.is_absolute():
        pdf_path = paper_folder / pdf_path
    if not pdf_path.is_file():
        raise FileNotFoundError(f"source_pdf does not exist: {pdf_path}")

    out_dir = paper_folder / "pdf_page_renders"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{pdf_path.stem}_page_{source_page:03d}.png"
    if out_path.exists():
        return rel_to_paper(out_path, paper_folder)

    doc = fitz.open(str(pdf_path))
    try:
        if source_page > doc.page_count:
            raise ValueError(f"source_page {source_page} exceeds page count {doc.page_count} for {pdf_path}")
        page = doc[source_page - 1]
        pix = page.get_pixmap(dpi=dpi)
        pix.save(str(out_path))
    finally:
        doc.close()
    return rel_to_paper(out_path, paper_folder)


def is_local_path_value(value: Any) -> bool:
    if not isinstance(value, str) or not value.strip():
        return False
    lowered = value.strip().lower()
    return not re.match(r"^[a-z][a-z0-9+.-]*://", lowered) and not lowered.startswith("data:")


def missing_mapping_paths(paper_folder: Path, data: Any, fields: set[str]) -> list[str]:
    missing: list[str] = []
    for entry in iter_total_figure_mapping_entries(data):
        for field in fields:
            value = entry.get(field)
            if not is_local_path_value(value):
                continue
            path = path_from_mapping_value(paper_folder, value)
            if path and not path.exists():
                missing.append(f"{field}={value}")
    return missing


def invalid_source_quality_values(data: Any) -> list[str]:
    invalid: list[str] = []
    for entry in iter_total_figure_mapping_entries(data):
        value = entry.get("source_quality")
        if value is None or value == "":
            continue
        if str(value) not in VALID_SOURCE_QUALITIES:
            invalid.append(str(value))
    return invalid


def safe_name(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "_", value.strip())
    return cleaned.strip("._") or "paper"


def normalize_token(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.lower())


def truthy_selection(value: str) -> bool:
    return value.strip().lower() in {"yes", "maybe", "y", "true", "1", "selected"}


def row_item_id(row: dict[str, str]) -> str:
    for key in ("item_id", "pdf_item_id", "item", "label", "base_id"):
        value = (row.get(key) or "").strip()
        if value:
            return value
    return "unknown_item"


def selected_ft_rows(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    if not rows:
        return []
    columns = set(rows[0])
    if "manual_select" in columns:
        selected = [row for row in rows if truthy_selection(row.get("manual_select", ""))]
        if selected:
            return selected
    if "need_for_lnpdb" in columns:
        return [row for row in rows if truthy_selection(row.get("need_for_lnpdb", ""))]
    for fallback in ("is_lnpdb", "lnpdb_relevant", "selected"):
        if fallback in columns:
            selected = [row for row in rows if truthy_selection(row.get(fallback, ""))]
            if selected:
                return selected
    return []


def require_existing_file(path: Path, stage: str) -> None:
    if path.name == MANUAL_MARKER and path.exists():
        return
    if not non_empty_file(path):
        raise FileNotFoundError(f"{stage} requires a non-empty file: {path}")


def task_file_path(stage: str, paper_folder: Path) -> Path:
    TASK_DIR.mkdir(parents=True, exist_ok=True)
    return TASK_DIR / f"{stage}_{safe_name(paper_folder.name)}.md"


def write_task_file(stage: str, paper_folder: Path, content: str) -> Path:
    path = task_file_path(stage, paper_folder)
    path.write_text(content.rstrip() + "\n", encoding="utf-8")
    return path


def asset_list(paper_folder: Path, suffixes: set[str], limit: int = 200) -> list[str]:
    found = [rel_to_paper(p, paper_folder) for p in iter_paper_files(paper_folder) if p.suffix.lower() in suffixes]
    return found[:limit]


def render_bullet_list(items: list[str]) -> str:
    if not items:
        return "- none found"
    return "\n".join(f"- `{item}`" for item in items)


def create_external_agent_task(stage: str, paper_folder: Path) -> dict[str, Any]:
    if stage == "03_figure_mapping":
        require_existing_file(paper_folder / MANUAL_MARKER, stage)
        require_existing_file(paper_folder / "fig_table_lnpdb_classified.csv", stage)
        require_existing_file(paper_folder / "fig_table_inventory.csv", stage)
        images = asset_list(paper_folder, {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp"})
        tables = asset_list(paper_folder, {".csv", ".xlsx", ".xls"})
        pdfs = asset_list(paper_folder, {".pdf"})
        content = f"""# External Agent Task: 03_figure_mapping

Target paper folder: `{paper_folder}`

## Stage Purpose
Map manually selected LNPDB-relevant figure/table items to source image, table, or PDF assets without using Gemini or any Python API key dependency.

## Required Input Files
- `{paper_folder / MANUAL_MARKER}`
- `{paper_folder / "fig_table_lnpdb_classified.csv"}`
- `{paper_folder / "fig_table_inventory.csv"}`

## Source Assets Found
Images:
{render_bullet_list(images)}

Tables:
{render_bullet_list(tables)}

PDFs:
{render_bullet_list(pdfs)}

## Expected Output Files
- `{paper_folder / "total_figure_mapping.json"}`

## Work Instructions
1. Read `fig_table_lnpdb_classified.csv`.
2. Use rows where `manual_select` is `yes` or `maybe` as selected FT items.
3. If `manual_select` is absent, fall back to `need_for_lnpdb` values `yes` or `maybe`.
4. For every selected item, inspect `item_id`, `base_id`, `caption`, and `reason`.
5. Search the paper folder for source image, table, and PDF assets.
6. Treat Marker-extracted `_page_x_Figure_y.jpeg` images as primary candidates only, not ground truth.
7. Map each selected figure/table item to the most likely source image/table path.
8. When possible, record `source_pdf` and 1-based `source_page` for each mapping entry.
9. Infer `source_page` from markdown image/caption page and order when explicit page metadata is unavailable.
10. If the source image is far from the caption, appears to include only part of the figure, or does not match the expected panel count, set `source_quality: "suspect_crop"`.
11. If no plausible image exists, set `source_quality: "missing_image"` and `manual_required: true`.
12. If image and caption appear mismatched, set `source_quality: "caption_image_mismatch"`.
13. If the source image is complete and caption-consistent, set `source_quality: "ok"`.
14. Create `total_figure_mapping.json` in the paper folder root.
15. Follow `agent_workspace/OUTPUT_SCHEMA.md` for the `total_figure_mapping.json` schema.
16. Store paths relative to the paper folder when possible.
17. If uncertain, record `confidence: "low"` or `confidence: "unmatched"` and a short `reason`; do not guess.

## Optional Mapping Fields
- `source_image`
- `source_pdf`
- `source_page`
- `source_quality`
- `fallback_render`
- `selected_source_for_paneling`
- `manual_required`
- `confidence`
- `reason`

## Validation Command
```bash
python Agent_Task_Runner.py validate --stage 03_figure_mapping --paper-folder "{paper_folder}"
```

## Constraints
- Do not run `0_mark_down_gen/03_figure_mapping.py`.
- Do not import or require `find_api.py`.
- Do not use Gemini, Vertex, `LLM_API.py`, or `LLM_Batch.py`.
- Do not hard-code API keys or credentials.
"""
    elif stage == "03_split_excel_blocks_batch":
        require_existing_file(paper_folder / MANUAL_MARKER, stage)
        exp_excel = paper_folder / "Exp_Excel"
        excel_files = [
            rel_to_paper(p, paper_folder)
            for p in iter_paper_files(exp_excel)
            if p.suffix.lower() in {".xlsx", ".xls", ".csv"}
        ] if exp_excel.exists() else []
        content = f"""# External Agent Task: 03_split_excel_blocks_batch

Target paper folder: `{paper_folder}`

## Stage Purpose
Split experimental Excel workbooks/sheets into API-free table blocks and classify block type by direct CLI agent judgment.

## Required Input Files
- `{paper_folder / MANUAL_MARKER}`
- Excel files under `{paper_folder / "Exp_Excel"}`

Excel files found:
{render_bullet_list(excel_files)}

## Expected Output Files
- `{paper_folder / "Exp_Excel_Blocks"}`
- `{paper_folder / "excel_block_inventory.csv"}`
- `{paper_folder / "three_core_result_all.json"}`

## Work Instructions
1. Inspect the `Exp_Excel` folder.
2. Read Excel workbooks and sheets.
3. Split sheets into candidate blocks using merged cells, blank rows/columns, borders, fills, headers, and numeric density.
4. Prefer API-free helper logic such as `0_mark_down_gen/sheet_block_splitter.py`, `0_mark_down_gen/03_split_excel_blocks.py` pure utilities, or a deterministic helper script.
5. Do not use Gemini or LLM judgment.
6. Save each block CSV under `Exp_Excel_Blocks/`.
7. Create `excel_block_inventory.csv` with required columns:
   - `excel_file`
   - `excel_sheet`
   - `block_id`
   - `group_id`
   - `element_id`
   - `block_csv_path`
   - `block_meta_path`
   - `block_type`
8. Classify `block_type` by direct inspection as one of:
   - `title_and_table`
   - `table_body`
   - `table_title`
   - `multi_table`
   - `note`
   - `other`
9. Create `three_core_result_all.json` with JSON reasoning for every workbook/sheet.
10. If useful, create or run an API-free helper such as `agent_workspace/tools/api_free_excel_block_splitter.py`; use pandas/openpyxl deterministic parsing only.

## Validation Command
```bash
python Agent_Task_Runner.py validate --stage 03_split_excel_blocks_batch --paper-folder "{paper_folder}"
```

## Constraints
- Do not run `0_mark_down_gen/03_split_excel_blocks_batch.py`.
- Do not import or require `find_api.py`.
- Do not use Gemini, Vertex, `LLM_API.py`, or `LLM_Batch.py`.
- Do not hard-code API keys or credentials.
"""
    elif stage == "04_figure_separate":
        require_existing_file(paper_folder / MANUAL_MARKER, stage)
        require_existing_file(paper_folder / "total_figure_mapping.json", stage)
        content = f"""# External Agent Task: 04_figure_separate

Target paper folder: `{paper_folder}`

## Stage Purpose
Separate mapped source images into panels or mark entries for manual review without using Gemini.

## Required Input Files
- `{paper_folder / MANUAL_MARKER}`
- `{paper_folder / "total_figure_mapping.json"}`

## Expected Output Files
- `{paper_folder / "separated_panels_gemini"}`
- updated `{paper_folder / "total_figure_mapping.json"}`

## Work Instructions
1. Read `total_figure_mapping.json`.
2. For each entry, first inspect `source_image`.
3. If `source_image` appears complete and consistent with the caption, use it as the paneling source and set `selected_source_for_paneling` to that path.
4. If `source_image` appears incomplete, wrongly cropped, missing panel labels, merged with unrelated content, or inconsistent with the caption, do not rely on it and do not force-crop it.
5. If `source_pdf` and 1-based `source_page` are available for a suspect entry, render the corresponding original PDF page using PyMuPDF.
6. Save rendered pages under `pdf_page_renders/`.
7. Add the rendered page path as `fallback_render`.
8. Set `selected_source_for_paneling = fallback_render`.
9. Set `source_quality = "pdf_page_render_fallback"`.
10. Decide whether panel cropping is needed from `selected_source_for_paneling`.
11. Use OpenCV/PIL helper code or write a small deterministic script only if crop boundaries are clear.
12. Save panel images under `separated_panels_gemini/`.
13. Add panel paths back into `total_figure_mapping.json`.
14. If panel boundaries remain uncertain, set `manual_required: true`, `confidence: "low"`, and a short `reason`; do not hallucinate panel crops.
15. If PyMuPDF is unavailable, record a dependency note in `reason` and keep `manual_required: true`.

## PyMuPDF Render Example
```python
import fitz
from pathlib import Path

pdf_path = Path("source.pdf")
source_page = 1
out_path = Path("pdf_page_renders/source_page_001.png")

doc = fitz.open(str(pdf_path))
page = doc[source_page - 1]
pix = page.get_pixmap(dpi=220)
pix.save(str(out_path))
doc.close()
```

## Validation Command
```bash
python Agent_Task_Runner.py validate --stage 04_figure_separate --paper-folder "{paper_folder}"
```

## Constraints
- Do not run `0_mark_down_gen/04_figure_saperate_gemini.py`.
- Do not import or require `find_api.py`.
- Do not use Gemini, Vertex, `LLM_API.py`, or `LLM_Batch.py`.
- Do not hard-code API keys or credentials.
"""
    elif stage == "04_ft_excel_matcher":
        require_existing_file(paper_folder / MANUAL_MARKER, stage)
        require_existing_file(paper_folder / "fig_table_lnpdb_classified.csv", stage)
        require_existing_file(paper_folder / "fig_table_inventory.csv", stage)
        require_existing_file(paper_folder / "excel_block_inventory.csv", stage)
        content = f"""# External Agent Task: 04_ft_excel_matcher

Target paper folder: `{paper_folder}`

## Stage Purpose
Match selected figure/table items to Excel blocks by direct CLI agent judgment without Gemini.

## Required Input Files
- `{paper_folder / MANUAL_MARKER}`
- `{paper_folder / "fig_table_lnpdb_classified.csv"}`
- `{paper_folder / "fig_table_inventory.csv"}`
- `{paper_folder / "excel_block_inventory.csv"}`

## Expected Output Files
- `{paper_folder / "excel_mapping.json"}`
- `{paper_folder / "excel_mapping_rows.csv"}`
- updated `{paper_folder / "fig_table_lnpdb_classified.csv"}` when possible

## Work Instructions
1. Read `fig_table_lnpdb_classified.csv`.
2. Read `fig_table_inventory.csv`.
3. Read `excel_block_inventory.csv`.
4. Match every selected FT item to candidate Excel blocks using caption, `item_id`, `base_id`, sheet name, block preview, `block_type`, and keywords.
5. Create `excel_mapping.json`.
6. Create `excel_mapping_rows.csv`.
7. When possible, update `fig_table_lnpdb_classified.csv` columns:
   - `excel_item_id`
   - `matched_blocks`
   - `matched_block_csv_path`
   - `matched_sheet`
   - `matched_sheet_file`
8. Follow `agent_workspace/OUTPUT_SCHEMA.md` for `excel_mapping.json` and `excel_mapping_rows.csv`.

## Validation Command
```bash
python Agent_Task_Runner.py validate --stage 04_ft_excel_matcher --paper-folder "{paper_folder}"
```

## Constraints
- Do not run `0_mark_down_gen/04_FT-Excel_matcher.py`.
- Do not import or require `find_api.py`.
- Do not use Gemini, Vertex, `LLM_API.py`, or `LLM_Batch.py`.
- Do not hard-code API keys or credentials.
"""
    elif stage == "05_smiles_structure_resolution":
        require_existing_file(paper_folder / MANUAL_MARKER, stage)
        require_existing_file(paper_folder / "total_figure_mapping.json", stage)
        markdowns = asset_list(paper_folder, {".md"})
        pdfs = asset_list(paper_folder, {".pdf"})
        images = asset_list(paper_folder, {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp"})
        content = f"""# External Agent Task: 05_smiles_structure_resolution

Target paper folder: `{paper_folder}`

## Stage Purpose
Resolve compound names, IUPAC names, and structure-derived SMILES from text and image sources without Gemini/API dependencies.

## Required Input Files
- `{paper_folder / MANUAL_MARKER}`
- markdown files and/or PDFs from the paper folder
- `{paper_folder / "total_figure_mapping.json"}` when available
- source images when available

Markdown files:
{render_bullet_list(markdowns)}

PDFs:
{render_bullet_list(pdfs)}

Images:
{render_bullet_list(images)}

## Optional Input Files
- existing LNPDB reference file if configured locally
- outputs from DECIMER/MolScribe helpers if already available
- legacy outputs from `2_Extract_SMILES/`

## Expected Output Files
- `{paper_folder / "compound_inventory_standardized.csv"}`
- `{paper_folder / "smiles_resolved.csv"}`
- `{paper_folder / "smiles_resolution_qc.csv"}`

## Work Instructions
1. Collect lipid/component names, aliases, IUPAC names, and structure image references from markdown, PDFs, captions, tables, and mapped source images.
2. Use deterministic or lookup tools when available: OPSIN, PubChem, CIR, existing LNPDB references, and MolScribe/DECIMER helper outputs for structure crops.
3. Create `compound_inventory_standardized.csv` with one row per compound/name candidate.
4. Create `smiles_resolved.csv` with at least `Name` or `compound_id`, and `SMILES` or `resolved_smiles`.
5. Create `smiles_resolution_qc.csv` with unresolved names, conflicts, ambiguous matches, and evidence notes.
6. Preserve provenance fields such as source file, item id, caption snippet, table block, or image path when available.
7. If a SMILES cannot be resolved deterministically, leave it blank and mark it for manual review.

## Validation Command
```bash
python Agent_Task_Runner.py validate --stage 05_smiles_structure_resolution --paper-folder "{paper_folder}"
```

## Constraints
- Do not run Gemini/API-assisted SMILES scripts.
- Do not import or require `find_api.py`, `LLM_API.py`, or `LLM_Batch.py`.
- Do not use Gemini, Vertex, or hard-coded credentials.
"""
    elif stage == "06_unified_lnpdb_extraction":
        require_existing_file(paper_folder / MANUAL_MARKER, stage)
        require_existing_file(paper_folder / "fig_table_lnpdb_classified.csv", stage)
        require_existing_file(paper_folder / "total_figure_mapping.json", stage)
        require_existing_file(paper_folder / "excel_mapping.json", stage)
        require_existing_file(paper_folder / "excel_block_inventory.csv", stage)
        if not (paper_folder / "Exp_Excel_Blocks").is_dir():
            raise FileNotFoundError(f"{stage} requires a directory: {paper_folder / 'Exp_Excel_Blocks'}")
        markdowns = asset_list(paper_folder, {".md"})
        optional_inputs = [
            "separated_panels_gemini",
            "compound_inventory_standardized.csv",
            "text_extracted_iupac.csv",
            "smiles_resolved.csv",
        ]
        content = f"""# External Agent Task: 06_unified_lnpdb_extraction

Target paper folder: `{paper_folder}`

## Stage Purpose
Create one unified long table at figure/table item level that combines experimental conditions, formulation composition, experimental values, and provenance. This replaces the old independent extraction of experimental metadata, formulation composition, and experimental values.

## Required Input Files
- `{paper_folder / MANUAL_MARKER}`
- `{paper_folder / "fig_table_lnpdb_classified.csv"}`
- `{paper_folder / "total_figure_mapping.json"}`
- `{paper_folder / "excel_mapping.json"}`
- `{paper_folder / "excel_block_inventory.csv"}`
- `{paper_folder / "Exp_Excel_Blocks"}`
- markdown files:
{render_bullet_list(markdowns)}

## Optional Input Files
{render_bullet_list([item for item in optional_inputs if (paper_folder / item).exists()])}
- any outputs from `2_Extract_SMILES/`

## Expected Output Files
- `{paper_folder / "unified_extraction.csv"}`
- `{paper_folder / "unified_extraction.json"}`
- `{paper_folder / "unified_extraction_review_flags.csv"}`

## Required Output Columns
Use the columns documented in `agent_workspace/OUTPUT_SCHEMA.md` for `unified_extraction.csv`. Include all experimental condition, formulation composition, experimental value, evidence, confidence, and manual review fields even when values are blank.

## Work Instructions
1. For every selected figure/table item, extract experimental conditions, formulation composition, and experimental values into one unified long table.
2. Do not split the task into separate independent LLM calls for conditions/formulation/values.
3. Use all available context: markdown captions, PDF-derived images, separated panels, Excel block CSVs, `excel_mapping.json`, `total_figure_mapping.json`, and SMILES outputs.
4. Treat Excel numeric values as authoritative for experimental values.
5. Use figure/PDF images for labels, axes, legend, group interpretation, panel identity, and visual context.
6. Use markdown for caption, methods context, dose, model, route, and formulation descriptions.
7. If exact values are missing, do not hallucinate. Leave blank and set `manual_required=true`.
8. If multiple formulations or groups exist in one figure/table, produce one row per formulation/condition/metric/value.
9. Use long format.
10. Preserve `original_values` exactly; `aggregated_value` may be a mean only when replicates are explicit.
11. Record `evidence_text`, `evidence_excel`, and `evidence_image` for every nontrivial extracted value.
12. Record `confidence` and `reason`.
13. Create `unified_extraction_review_flags.csv` for missing metadata, low confidence, value/formulation mismatch, unresolved SMILES, missing figure evidence, and any manual review need.
14. Also write `unified_extraction.json` with records and source summary.

## Validation Command
```bash
python Agent_Task_Runner.py validate --stage 06_unified_lnpdb_extraction --paper-folder "{paper_folder}"
```

## Constraints
- Do not use Gemini/API/find_api/LLM_API/LLM_Batch.
- Do not run legacy scripts from `1_Extract_Exp_Figs`, `3_Extract_Formula_by_Figs`, or `4_Extract_Exp_Vals`.
- Do not hard-code API keys or credentials.
"""
    elif stage == "07_finalize_unified_table":
        require_existing_file(paper_folder / MANUAL_MARKER, stage)
        require_existing_file(paper_folder / "unified_extraction.csv", stage)
        content = f"""# External Agent Task: 07_finalize_unified_table

Target paper folder: `{paper_folder}`

## Stage Purpose
Finalize `unified_extraction.csv` into reviewed final and LNPDB-like tables, with a QC report.

## Required Input Files
- `{paper_folder / MANUAL_MARKER}`
- `{paper_folder / "unified_extraction.csv"}`
- `{paper_folder / "unified_extraction_review_flags.csv"}`

## Expected Output Files
- `{paper_folder / "unified_extraction_final.csv"}`
- `{paper_folder / "unified_extraction_lnpdb_like.csv"}`
- `{paper_folder / "unified_extraction_qc_report.json"}`

## Work Instructions
1. Read `unified_extraction.csv`.
2. Preserve source rows and provenance.
3. Normalize booleans and blank values without inventing missing scientific data.
4. Create `unified_extraction_final.csv`.
5. Create `unified_extraction_lnpdb_like.csv` using the same rows and LNPDB-facing columns where available.
6. Create `unified_extraction_qc_report.json` with row counts, missing critical fields, low-confidence rows, and manual review counts.

## Validation Command
```bash
python Agent_Task_Runner.py validate --stage 07_finalize_unified_table --paper-folder "{paper_folder}"
```

## Constraints
- Do not use Gemini/API/find_api/LLM_API/LLM_Batch.
- Do not hallucinate missing values during finalization.
"""
    else:
        raise ValueError(f"No external agent task template for stage: {stage}")

    path = write_task_file(stage, paper_folder, content)
    return {
        "status": "external_agent_required",
        "stage": stage,
        "task_file": str(path),
        "message": "Legacy Gemini script was not executed. Ask Codex/Claude CLI agent to complete this task file.",
    }


def write_csv_dicts(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in fieldnames})


def write_csv_matrix(path: Path, rows: list[list[Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerows(rows)


def is_blank_cell(value: Any) -> bool:
    return value is None or str(value).strip() == ""


def read_csv_matrix(path: Path) -> list[list[Any]]:
    for encoding in ("utf-8-sig", "cp949", "latin-1"):
        try:
            with path.open("r", encoding=encoding, newline="") as f:
                return [row for row in csv.reader(f)]
        except UnicodeDecodeError:
            continue
    with path.open("r", encoding="utf-8-sig", errors="replace", newline="") as f:
        return [row for row in csv.reader(f)]


def contiguous_groups(indices: list[int]) -> list[list[int]]:
    if not indices:
        return []
    groups = [[indices[0]]]
    for index in indices[1:]:
        if index == groups[-1][-1] + 1:
            groups[-1].append(index)
        else:
            groups.append([index])
    return groups


def trim_matrix(matrix: list[list[Any]]) -> list[list[Any]]:
    while matrix and all(is_blank_cell(cell) for cell in matrix[-1]):
        matrix.pop()
    if not matrix:
        return []
    max_width = max(len(row) for row in matrix)
    padded = [row + [""] * (max_width - len(row)) for row in matrix]
    while padded and padded[0] and all(is_blank_cell(row[-1]) for row in padded):
        padded = [row[:-1] for row in padded]
    return padded


def split_matrix_blocks(matrix: list[list[Any]]) -> list[dict[str, Any]]:
    matrix = trim_matrix([list(row) for row in matrix])
    if not matrix:
        return []
    max_width = max(len(row) for row in matrix)
    padded = [row + [""] * (max_width - len(row)) for row in matrix]
    non_empty_rows = [i for i, row in enumerate(padded) if any(not is_blank_cell(cell) for cell in row)]
    blocks: list[dict[str, Any]] = []
    for row_group in contiguous_groups(non_empty_rows):
        row_slice = padded[row_group[0] : row_group[-1] + 1]
        non_empty_cols = [
            j for j in range(max_width) if any(not is_blank_cell(row[j]) for row in row_slice)
        ]
        for col_group in contiguous_groups(non_empty_cols):
            cells = [row[col_group[0] : col_group[-1] + 1] for row in row_slice]
            cells = trim_matrix(cells)
            if cells:
                blocks.append(
                    {
                        "row_start": row_group[0] + 1,
                        "row_end": row_group[-1] + 1,
                        "col_start": col_group[0] + 1,
                        "col_end": col_group[-1] + 1,
                        "cells": cells,
                    }
                )
    return blocks


def numeric_cell(value: Any) -> bool:
    text = str(value).strip().replace(",", "").replace("%", "")
    if not text:
        return False
    try:
        float(text)
        return True
    except ValueError:
        return False


def infer_block_type(cells: list[list[Any]]) -> str:
    non_empty = [cell for row in cells for cell in row if not is_blank_cell(cell)]
    numeric_count = sum(1 for cell in non_empty if numeric_cell(cell))
    text_count = len(non_empty) - numeric_count
    row_count = len(cells)
    col_count = max((len(row) for row in cells), default=0)
    first_row_text = sum(1 for cell in (cells[0] if cells else []) if not is_blank_cell(cell) and not numeric_cell(cell))
    if row_count <= 2 and numeric_count == 0:
        return "table_title" if text_count <= 6 else "note"
    if row_count >= 12 and col_count >= 8 and numeric_count >= 10:
        return "multi_table"
    if numeric_count >= 3 and first_row_text > 0:
        return "title_and_table"
    if numeric_count >= max(3, text_count) and row_count >= 2:
        return "table_body"
    if row_count <= 3 and text_count > numeric_count:
        return "note"
    return "other"


def load_excel_like_sheets(path: Path) -> list[tuple[str, list[list[Any]], str | None]]:
    suffix = path.suffix.lower()
    if suffix == ".csv":
        return [("csv", read_csv_matrix(path), None)]
    if suffix == ".xlsx":
        try:
            from openpyxl import load_workbook
        except ImportError as exc:
            return [("workbook", [], f"openpyxl is required for {path.name}: {exc}")]
        workbook = load_workbook(path, read_only=False, data_only=True)
        sheets = []
        for sheet in workbook.worksheets:
            matrix = [
                [sheet.cell(row=i, column=j).value for j in range(1, sheet.max_column + 1)]
                for i in range(1, sheet.max_row + 1)
            ]
            sheets.append((sheet.title, matrix, None))
        return sheets
    if suffix == ".xls":
        try:
            import pandas as pd
        except ImportError as exc:
            return [("workbook", [], f"pandas/xlrd is required for {path.name}: {exc}")]
        try:
            sheet_map = pd.read_excel(path, sheet_name=None, header=None)
        except Exception as exc:
            return [("workbook", [], f"failed to read {path.name}: {exc}")]
        return [(name, frame.fillna("").values.tolist(), None) for name, frame in sheet_map.items()]
    return []


def run_heuristic_figure_mapping(paper_folder: Path) -> dict[str, Any]:
    classified = paper_folder / "fig_table_lnpdb_classified.csv"
    require_existing_file(classified, "03_figure_mapping")
    rows = read_csv_rows(classified)
    selected = selected_ft_rows(rows)
    image_files = [
        p for p in iter_paper_files(paper_folder)
        if p.suffix.lower() in {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp"}
    ]
    table_files = [
        p for p in iter_paper_files(paper_folder)
        if p.suffix.lower() in {".csv", ".xlsx", ".xls"}
        and p.name not in {
            "fig_table_inventory.csv",
            "fig_table_lnpdb_classified.csv",
            "excel_block_inventory.csv",
            "excel_mapping_rows.csv",
        }
    ]
    mapping: dict[str, Any] = {
        paper_folder.name: {
            "_metadata": {
                "created_by": "Agent_Task_Runner heuristic mode",
                "accuracy_note": "Low-accuracy temporary mapping based on filename substring matching only.",
                "created_at": utc_now(),
            }
        }
    }
    for row in selected:
        item_id = row_item_id(row)
        base_id = (row.get("base_id") or "").strip()
        tokens = [normalize_token(v) for v in (item_id, base_id) if normalize_token(v)]

        def score(path: Path) -> int:
            name = normalize_token(path.stem)
            return max((len(token) for token in tokens if token and (token in name or name in token)), default=0)

        image_match = max(image_files, key=score, default=None)
        table_match = max(table_files, key=score, default=None)
        image_score = score(image_match) if image_match else 0
        table_score = score(table_match) if table_match else 0
        matched = image_score > 0 or table_score > 0
        image_found = bool(image_match and image_score > 0)
        mapping[paper_folder.name][item_id] = {
            "item_id": item_id,
            "base_id": base_id,
            "caption": row.get("caption", ""),
            "source_image": rel_to_paper(image_match, paper_folder) if image_found else None,
            "source_table": rel_to_paper(table_match, paper_folder) if table_match and table_score > 0 else None,
            "source_quality": "ok" if image_found else "missing_image",
            "manual_required": not image_found,
            "confidence": "low" if matched else "unmatched",
            "reason": "Filename matched item_id/base_id in heuristic mode." if matched else "No filename matched item_id/base_id in heuristic mode.",
        }
    write_json(paper_folder / "total_figure_mapping.json", mapping)
    return {"selected_items": len(selected), "output": str(paper_folder / "total_figure_mapping.json")}


def run_heuristic_split_excel_blocks(paper_folder: Path) -> dict[str, Any]:
    exp_excel = paper_folder / "Exp_Excel"
    block_root = paper_folder / "Exp_Excel_Blocks"
    block_root.mkdir(parents=True, exist_ok=True)
    excel_files = []
    if exp_excel.exists():
        excel_files = [
            p for p in exp_excel.rglob("*")
            if p.is_file() and p.suffix.lower() in {".xlsx", ".xls", ".csv"}
        ]
    inventory_rows: list[dict[str, Any]] = []
    summary: list[dict[str, Any]] = []
    fieldnames = [
        "excel_file",
        "excel_sheet",
        "block_id",
        "group_id",
        "element_id",
        "block_csv_path",
        "block_meta_path",
        "block_type",
    ]
    for excel_file in excel_files:
        sheet_results = []
        for sheet_name, matrix, error in load_excel_like_sheets(excel_file):
            if error:
                sheet_results.append({"excel_sheet": sheet_name, "error": error, "blocks": 0})
                continue
            blocks = split_matrix_blocks(matrix)
            sheet_results.append({"excel_sheet": sheet_name, "blocks": len(blocks), "method": "blank_row_column_components"})
            for index, block in enumerate(blocks, start=1):
                block_id = f"block_{len(inventory_rows) + 1:04d}"
                rel_dir = Path("Exp_Excel_Blocks") / safe_name(excel_file.stem) / safe_name(sheet_name)
                block_csv = paper_folder / rel_dir / f"{block_id}.csv"
                block_meta = paper_folder / rel_dir / f"{block_id}.json"
                block_type = infer_block_type(block["cells"])
                write_csv_matrix(block_csv, block["cells"])
                write_json(
                    block_meta,
                    {
                        "excel_file": rel_to_paper(excel_file, paper_folder),
                        "excel_sheet": sheet_name,
                        "block_id": block_id,
                        "bounds": {
                            "row_start": block["row_start"],
                            "row_end": block["row_end"],
                            "col_start": block["col_start"],
                            "col_end": block["col_end"],
                        },
                        "block_type": block_type,
                        "created_by": "Agent_Task_Runner heuristic mode",
                    },
                )
                inventory_rows.append(
                    {
                        "excel_file": rel_to_paper(excel_file, paper_folder),
                        "excel_sheet": sheet_name,
                        "block_id": block_id,
                        "group_id": f"{safe_name(excel_file.stem)}_{safe_name(sheet_name)}",
                        "element_id": f"{safe_name(excel_file.stem)}_{safe_name(sheet_name)}_{index:03d}",
                        "block_csv_path": rel_to_paper(block_csv, paper_folder),
                        "block_meta_path": rel_to_paper(block_meta, paper_folder),
                        "block_type": block_type,
                    }
                )
        summary.append(
            {
                "excel_file": rel_to_paper(excel_file, paper_folder),
                "result": sheet_results,
                "created_by": "Agent_Task_Runner heuristic mode",
            }
        )
    write_csv_dicts(paper_folder / "excel_block_inventory.csv", inventory_rows, fieldnames)
    write_json(paper_folder / "three_core_result_all.json", summary)
    return {"excel_files": len(excel_files), "blocks": len(inventory_rows)}


def run_heuristic_figure_separate(paper_folder: Path) -> dict[str, Any]:
    mapping_path = paper_folder / "total_figure_mapping.json"
    require_existing_file(mapping_path, "04_figure_separate")
    data = load_json(mapping_path, {})
    panel_dir = paper_folder / "separated_panels_gemini"
    panel_dir.mkdir(parents=True, exist_ok=True)
    updated = 0
    fallback_render_count = 0
    fallback_render_errors: list[str] = []
    for entry in iter_total_figure_mapping_entries(data):
        source_quality = str(entry.get("source_quality") or "").strip()
        if source_quality in FALLBACK_SOURCE_QUALITIES and entry.get("source_pdf") and entry.get("source_page"):
            try:
                source_page = int(entry["source_page"])
                fallback_render = render_pdf_page(paper_folder, str(entry["source_pdf"]), source_page)
            except Exception as exc:
                message = f"PDF page render fallback failed: {exc}"
                entry["manual_required"] = True
                entry["confidence"] = "low"
                entry["reason"] = f"{entry.get('reason', '').strip()} {message}".strip()
                fallback_render_errors.append(message)
            else:
                entry["fallback_render"] = fallback_render
                entry["selected_source_for_paneling"] = fallback_render
                entry["source_quality"] = "pdf_page_render_fallback"
                entry["manual_required"] = True
                entry["confidence"] = "low"
                entry["reason"] = (
                    f"{entry.get('reason', '').strip()} "
                    "Heuristic mode rendered the source PDF page because the Marker image was not reliable; "
                    "panel separation still requires manual review."
                ).strip()
                fallback_render_count += 1
        if entry.get("source_image") or entry.get("fallback_render"):
            entry.setdefault("panels", {})
            entry["panel_separation"] = "not_performed"
            if not entry.get("fallback_render"):
                entry["confidence"] = "not_separated"
                entry["reason"] = "Panel separation not performed in heuristic mode."
            updated += 1
    write_json(
        panel_dir / "manifest.json",
        {
            "created_by": "Agent_Task_Runner heuristic mode",
            "status": "panel separation not performed in heuristic mode",
            "updated_mapping_entries": updated,
            "fallback_render_count": fallback_render_count,
            "fallback_render_errors": fallback_render_errors,
            "created_at": utc_now(),
        },
    )
    write_json(mapping_path, data)
    return {
        "panel_dir": str(panel_dir),
        "updated_mapping_entries": updated,
        "fallback_render_count": fallback_render_count,
        "fallback_render_errors": fallback_render_errors,
    }


def keyword_set(*values: str) -> set[str]:
    stopwords = {"figure", "fig", "table", "the", "and", "with", "from", "that", "this", "for", "lnpdb"}
    words: set[str] = set()
    for value in values:
        for word in re.findall(r"[A-Za-z0-9]+", value.lower()):
            if len(word) >= 3 and word not in stopwords:
                words.add(word)
    return words


def block_preview_text(paper_folder: Path, block_csv_path: str, max_rows: int = 20) -> str:
    if not block_csv_path:
        return ""
    path = paper_folder / block_csv_path
    if not path.exists():
        return ""
    rows = read_csv_matrix(path)[:max_rows]
    return " ".join(str(cell) for row in rows for cell in row if str(cell).strip())


def selected_item_rows_by_id(paper_folder: Path) -> dict[str, dict[str, str]]:
    classified = paper_folder / "fig_table_lnpdb_classified.csv"
    if not classified.exists():
        return {}
    rows = selected_ft_rows(read_csv_rows(classified))
    return {row_item_id(row): row for row in rows}


def mapping_entries_by_item(paper_folder: Path) -> dict[str, dict[str, Any]]:
    data = load_json(paper_folder / "total_figure_mapping.json", {})
    entries: dict[str, dict[str, Any]] = {}
    for entry in iter_total_figure_mapping_entries(data):
        item_id = str(entry.get("item_id") or entry.get("pdf_item_id") or entry.get("Item_ID") or "").strip()
        if item_id:
            entries[item_id] = entry
    return entries


def excel_matches_by_item(paper_folder: Path) -> dict[str, list[dict[str, Any]]]:
    data = load_json(paper_folder / "excel_mapping.json", {})
    matches: dict[str, list[dict[str, Any]]] = {}
    if isinstance(data, dict):
        for item_id, value in data.items():
            if isinstance(value, list):
                matches[str(item_id)] = [entry for entry in value if isinstance(entry, dict)]
            elif isinstance(value, dict):
                matches[str(item_id)] = [value]
    return matches


def normalize_bool_text(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    text = str(value or "").strip().lower()
    if text in {"1", "true", "yes", "y"}:
        return "true"
    if text in {"0", "false", "no", "n"}:
        return "false"
    return "true" if text else ""


def numeric_string(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    normalized = text.replace(",", "")
    if normalized.endswith("%"):
        normalized = normalized[:-1].strip()
    if re.fullmatch(r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?", normalized):
        return normalized
    return ""


def cell_has_numeric_value(value: Any) -> bool:
    text = str(value or "").strip()
    return bool(text and re.search(r"[-+]?\d", text))


def nearest_row_label(row: list[Any], col_index: int) -> str:
    for idx in range(min(col_index, len(row)) - 1, -1, -1):
        text = str(row[idx] or "").strip()
        if text and not cell_has_numeric_value(text):
            return text
    return ""


def nearest_column_label(matrix: list[list[Any]], row_index: int, col_index: int) -> str:
    for idx in range(row_index - 1, -1, -1):
        if col_index < len(matrix[idx]):
            text = str(matrix[idx][col_index] or "").strip()
            if text and not cell_has_numeric_value(text):
                return text
    return ""


def base_unified_row(paper_folder: Path, item_id: str, item_row: dict[str, str], mapping_entry: dict[str, Any] | None) -> dict[str, Any]:
    entry = mapping_entry or {}
    row = {column: "" for column in UNIFIED_EXTRACTION_COLUMNS}
    row.update(
        {
            "Paper_ID": paper_folder.name,
            "Item_ID": item_id,
            "visual_type": item_row.get("type") or item_row.get("visual_type") or item_row.get("label") or "",
            "source_image": entry.get("source_image", ""),
            "source_pdf": entry.get("source_pdf", ""),
            "source_page": entry.get("source_page", ""),
            "selected_source_for_paneling": entry.get("selected_source_for_paneling", ""),
            "evidence_text": item_row.get("caption", ""),
            "evidence_image": entry.get("selected_source_for_paneling") or entry.get("fallback_render") or entry.get("source_image", ""),
            "confidence": "low",
            "manual_required": "true",
            "reason": "Heuristic unified extraction; complex metadata requires manual or external-agent review.",
        }
    )
    return row


def run_heuristic_unified_lnpdb_extraction(paper_folder: Path) -> dict[str, Any]:
    selected_by_id = selected_item_rows_by_id(paper_folder)
    mapping_by_item = mapping_entries_by_item(paper_folder)
    matches_by_item = excel_matches_by_item(paper_folder)
    output_rows: list[dict[str, Any]] = []
    review_flags: list[dict[str, Any]] = []

    for item_id, item_row in selected_by_id.items():
        item_output_count = 0
        matches = matches_by_item.get(item_id, [])
        for match in matches:
            block_csv_path = str(match.get("block_csv_path") or "").strip()
            block_path = path_from_mapping_value(paper_folder, block_csv_path)
            if not block_csv_path or not block_path or not block_path.exists():
                review_flags.append(
                    {
                        "Paper_ID": paper_folder.name,
                        "Item_ID": item_id,
                        "block_id": match.get("block_id", ""),
                        "field": "block_csv_path",
                        "issue": "missing Excel block mapping",
                        "severity": "high",
                        "reason": f"Mapped block CSV is missing: {block_csv_path}",
                    }
                )
                continue
            matrix = read_csv_matrix(block_path)
            block_output_count = 0
            for row_index, matrix_row in enumerate(matrix):
                for col_index, cell in enumerate(matrix_row):
                    if not cell_has_numeric_value(cell):
                        continue
                    original = str(cell).strip()
                    row_label = nearest_row_label(matrix_row, col_index)
                    column_label = nearest_column_label(matrix, row_index, col_index)
                    out = base_unified_row(paper_folder, item_id, item_row, mapping_by_item.get(item_id))
                    out.update(
                        {
                            "source_type": "excel_block",
                            "excel_file": match.get("excel_file", ""),
                            "excel_sheet": match.get("excel_sheet", ""),
                            "block_id": match.get("block_id", ""),
                            "block_csv_path": block_csv_path,
                            "condition_1_name": "row_label" if row_label else "",
                            "condition_1_value": row_label,
                            "condition_2_name": "column_label" if column_label else "",
                            "condition_2_value": column_label,
                            "metric_type": column_label or row_label or match.get("block_id", ""),
                            "original_values": original,
                            "aggregated_value": numeric_string(original),
                            "evidence_excel": f"{block_csv_path}#R{row_index + 1}C{col_index + 1}",
                        }
                    )
                    output_rows.append(out)
                    block_output_count += 1
                    item_output_count += 1
            if block_output_count == 0:
                review_flags.append(
                    {
                        "Paper_ID": paper_folder.name,
                        "Item_ID": item_id,
                        "block_id": match.get("block_id", ""),
                        "field": "original_values",
                        "issue": "no numeric values detected",
                        "severity": "medium",
                        "reason": f"No numeric cells were detected in {block_csv_path}.",
                    }
                )
        if item_output_count == 0:
            out = base_unified_row(paper_folder, item_id, item_row, mapping_by_item.get(item_id))
            out["source_type"] = "manual_review_placeholder"
            out["reason"] = "No mapped numeric Excel value could be converted heuristically; manual extraction required."
            output_rows.append(out)
            review_flags.append(
                {
                    "Paper_ID": paper_folder.name,
                    "Item_ID": item_id,
                    "block_id": "",
                    "field": "row",
                    "issue": "unified extraction placeholder only",
                    "severity": "high",
                    "reason": out["reason"],
                }
            )

    write_csv_dicts(paper_folder / "unified_extraction.csv", output_rows, UNIFIED_EXTRACTION_COLUMNS)
    write_json(
        paper_folder / "unified_extraction.json",
        {
            "created_by": "Agent_Task_Runner heuristic mode",
            "created_at": utc_now(),
            "records": output_rows,
            "source_summary": {
                "selected_items": len(selected_by_id),
                "excel_mapped_items": len(matches_by_item),
            },
        },
    )
    write_csv_dicts(paper_folder / "unified_extraction_review_flags.csv", review_flags, UNIFIED_REVIEW_FLAG_COLUMNS)
    return {"rows": len(output_rows), "review_flags": len(review_flags), "selected_items": len(selected_by_id)}


def run_heuristic_finalize_unified_table(paper_folder: Path) -> dict[str, Any]:
    source = paper_folder / "unified_extraction.csv"
    require_existing_file(source, "07_finalize_unified_table")
    rows = read_csv_rows(source)
    for row in rows:
        row["manual_required"] = normalize_bool_text(row.get("manual_required", ""))
        row.setdefault("confidence", "")
    fieldnames = list(rows[0].keys()) if rows else UNIFIED_EXTRACTION_COLUMNS
    write_csv_dicts(paper_folder / "unified_extraction_final.csv", rows, fieldnames)
    write_csv_dicts(paper_folder / "unified_extraction_lnpdb_like.csv", rows, fieldnames)
    manual_count = sum(1 for row in rows if normalize_bool_text(row.get("manual_required")) == "true")
    low_confidence_count = sum(1 for row in rows if str(row.get("confidence", "")).strip().lower() in {"", "low", "unmatched"})
    missing_item_id = sum(1 for row in rows if not str(row.get("Item_ID", "")).strip())
    write_json(
        paper_folder / "unified_extraction_qc_report.json",
        {
            "created_by": "Agent_Task_Runner heuristic mode",
            "created_at": utc_now(),
            "rows": len(rows),
            "manual_required_rows": manual_count,
            "low_confidence_rows": low_confidence_count,
            "missing_item_id_rows": missing_item_id,
            "source": "unified_extraction.csv",
        },
    )
    return {"rows": len(rows), "manual_required_rows": manual_count, "low_confidence_rows": low_confidence_count}


def run_heuristic_ft_excel_matcher(paper_folder: Path) -> dict[str, Any]:
    classified = paper_folder / "fig_table_lnpdb_classified.csv"
    inventory = paper_folder / "excel_block_inventory.csv"
    require_existing_file(classified, "04_ft_excel_matcher")
    require_existing_file(inventory, "04_ft_excel_matcher")
    classified_rows = read_csv_rows(classified)
    block_rows = read_csv_rows(inventory)
    selected = selected_ft_rows(classified_rows)
    block_keywords: list[tuple[dict[str, str], set[str], str]] = []
    for block in block_rows:
        preview = block_preview_text(paper_folder, block.get("block_csv_path", ""))
        words = keyword_set(
            block.get("excel_file", ""),
            block.get("excel_sheet", ""),
            block.get("block_id", ""),
            block.get("block_type", ""),
            preview,
        )
        block_keywords.append((block, words, preview))

    mapping: dict[str, list[dict[str, Any]]] = {}
    row_outputs: list[dict[str, Any]] = []
    best_by_item: dict[str, dict[str, Any]] = {}
    for row in selected:
        item_id = row_item_id(row)
        words = keyword_set(item_id, row.get("base_id", ""), row.get("caption", ""), row.get("reason", ""))
        best_block: dict[str, str] | None = None
        best_score = 0
        for block, words_for_block, _preview in block_keywords:
            score = len(words & words_for_block)
            normalized_targets = [normalize_token(item_id), normalize_token(row.get("base_id", ""))]
            block_text = normalize_token(" ".join([block.get("excel_file", ""), block.get("excel_sheet", ""), block.get("block_id", "")]))
            score += sum(2 for token in normalized_targets if token and token in block_text)
            if score > best_score:
                best_score = score
                best_block = block
        if best_block and best_score > 0:
            match = {
                "pdf_item_id": item_id,
                "excel_item_id": best_block.get("element_id") or best_block.get("block_id", ""),
                "excel_file": best_block.get("excel_file", ""),
                "excel_sheet": best_block.get("excel_sheet", ""),
                "block_id": best_block.get("block_id", ""),
                "block_csv_path": best_block.get("block_csv_path", ""),
                "confidence": "low",
                "reason": f"Heuristic keyword overlap score={best_score}.",
            }
            mapping[item_id] = [match]
            row_outputs.append(match)
            best_by_item[item_id] = match
        else:
            mapping[item_id] = []

    extra_cols = ["excel_item_id", "matched_blocks", "matched_block_csv_path", "matched_sheet", "matched_sheet_file"]
    existing_fields = list(classified_rows[0].keys()) if classified_rows else []
    fieldnames = existing_fields + [col for col in extra_cols if col not in existing_fields]
    for row in classified_rows:
        item_id = row_item_id(row)
        match = best_by_item.get(item_id)
        if match:
            row["excel_item_id"] = match["excel_item_id"]
            row["matched_blocks"] = match["block_id"]
            row["matched_block_csv_path"] = match["block_csv_path"]
            row["matched_sheet"] = match["excel_sheet"]
            row["matched_sheet_file"] = match["excel_file"]
    write_json(paper_folder / "excel_mapping.json", mapping)
    write_csv_dicts(
        paper_folder / "excel_mapping_rows.csv",
        row_outputs,
        ["pdf_item_id", "excel_item_id", "excel_file", "excel_sheet", "block_id", "block_csv_path", "confidence", "reason"],
    )
    if classified_rows:
        write_csv_dicts(classified, classified_rows, fieldnames)
    return {"selected_items": len(selected), "matched_items": len(row_outputs)}


def run_heuristic_stage(stage: str, paper_folder: Path) -> Any:
    if stage == "03_figure_mapping":
        return run_heuristic_figure_mapping(paper_folder)
    if stage == "03_split_excel_blocks_batch":
        return run_heuristic_split_excel_blocks(paper_folder)
    if stage == "04_figure_separate":
        return run_heuristic_figure_separate(paper_folder)
    if stage == "04_ft_excel_matcher":
        return run_heuristic_ft_excel_matcher(paper_folder)
    if stage == "06_unified_lnpdb_extraction":
        return run_heuristic_unified_lnpdb_extraction(paper_folder)
    if stage == "07_finalize_unified_table":
        return run_heuristic_finalize_unified_table(paper_folder)
    raise ValueError(f"No heuristic implementation for stage: {stage}")


def find_markdown_files(paper_folder: Path) -> list[Path]:
    return [p for p in iter_paper_files(paper_folder) if p.suffix.lower() == ".md" and p.stat().st_size > 0]


def validate_stage(stage: str, paper_folder: Path) -> tuple[bool, list[str]]:
    messages: list[str] = []

    if stage in AGENT_STAGES and not has_manual_marker(paper_folder):
        return False, [f"missing required manual review marker: {paper_folder / MANUAL_MARKER}"]

    if stage == "00_marker":
        md_files = find_markdown_files(paper_folder)
        ok = bool(md_files)
        messages.append(f"non-empty markdown files: {len(md_files)}")
        return ok, messages

    if stage == "01_make_ft_csv":
        path = paper_folder / "fig_table_inventory.csv"
        if not non_empty_file(path):
            return False, [f"missing or empty: {path}"]
        rows = read_csv_rows(path)
        cols = set(rows[0].keys()) if rows else set()
        id_cols = {"item_id", "pdf_item_id", "item"} & cols
        return bool(rows and id_cols), [f"rows={len(rows)}", f"id_columns={sorted(id_cols)}"]

    if stage == "02_ft_selector":
        path = paper_folder / "fig_table_lnpdb_classified.csv"
        if not non_empty_file(path):
            return False, [f"missing or empty: {path}"]
        rows = read_csv_rows(path)
        return bool(rows), [f"rows={len(rows)}"]

    if stage == "02b_manual_review":
        marker = paper_folder / MANUAL_MARKER
        classified = paper_folder / "fig_table_lnpdb_classified.csv"
        reviewed = paper_folder / "fig_table_lnpdb_classified_manual_reviewed.csv"
        has_review_file = reviewed.exists()
        has_manual_col = False
        if classified.exists():
            rows = read_csv_rows(classified)
            has_manual_col = bool(rows and "manual_select" in rows[0])
        ok = marker.exists() and (has_review_file or has_manual_col)
        return ok, [f"marker={marker.exists()}", f"reviewed_copy={has_review_file}", f"manual_select_column={has_manual_col}"]

    if stage == "03_figure_mapping":
        path = paper_folder / "total_figure_mapping.json"
        if not non_empty_file(path):
            return False, [f"missing or empty: {path}"]
        data = json.loads(path.read_text(encoding="utf-8"))
        invalid_qualities = invalid_source_quality_values(data)
        fallback_missing = missing_mapping_paths(
            paper_folder,
            data,
            {"fallback_render", "selected_source_for_paneling"},
        )
        return isinstance(data, dict) and bool(data) and not invalid_qualities, [
            f"top_level_keys={len(data) if isinstance(data, dict) else 'not_object'}",
            f"invalid_source_quality_values={len(invalid_qualities)}",
            f"missing_fallback_or_selected_paths={len(fallback_missing)}",
        ]

    if stage == "03_split_excel_blocks":
        script = PROJECT_ROOT / STAGES[stage]["script"]
        exp_excel = paper_folder / "Exp_Excel"
        excel_files = []
        if exp_excel.exists():
            excel_files = [p for p in iter_paper_files(exp_excel) if p.suffix.lower() in {".xlsx", ".xls", ".csv"}]
        return script.exists(), [f"utility_script_exists={script.exists()}", f"excel_inputs={len(excel_files)}"]

    if stage == "03_split_excel_blocks_batch":
        inv = paper_folder / "excel_block_inventory.csv"
        summary = paper_folder / "three_core_result_all.json"
        block_dir = paper_folder / "Exp_Excel_Blocks"
        if not non_empty_file(inv):
            return False, [f"missing or empty: {inv}"]
        rows = read_csv_rows(inv)
        missing_paths = []
        for row in rows:
            rel = (row.get("block_csv_path") or "").strip()
            if rel and not (paper_folder / rel).exists():
                missing_paths.append(rel)
        ok = bool(rows) and block_dir.exists() and not missing_paths
        return ok, [f"rows={len(rows)}", f"summary_exists={summary.exists()}", f"block_dir_exists={block_dir.exists()}", f"missing_block_paths={len(missing_paths)}"]

    if stage == "04_figure_separate":
        mapping = paper_folder / "total_figure_mapping.json"
        if not non_empty_file(mapping):
            return False, [f"missing or empty: {mapping}"]
        data = json.loads(mapping.read_text(encoding="utf-8"))
        panel_dirs = list(paper_folder.rglob("separated_panels_gemini"))
        invalid_qualities = invalid_source_quality_values(data)
        missing_paths = missing_mapping_paths(
            paper_folder,
            data,
            {"fallback_render", "selected_source_for_paneling"},
        )
        ok = isinstance(data, dict) and not invalid_qualities and not missing_paths
        return ok, [
            f"mapping_keys={len(data) if isinstance(data, dict) else 'not_object'}",
            f"panel_dirs={len(panel_dirs)}",
            f"invalid_source_quality_values={len(invalid_qualities)}",
            f"missing_fallback_or_selected_paths={len(missing_paths)}",
        ]

    if stage == "04_ft_excel_matcher":
        mapping = paper_folder / "excel_mapping.json"
        rows_csv = paper_folder / "excel_mapping_rows.csv"
        if not non_empty_file(mapping):
            return False, [f"missing or empty: {mapping}"]
        data = json.loads(mapping.read_text(encoding="utf-8"))
        ok = isinstance(data, dict) and rows_csv.exists()
        return ok, [f"mapping_keys={len(data) if isinstance(data, dict) else 'not_object'}", f"rows_csv_exists={rows_csv.exists()}"]

    if stage == "05_smiles_structure_resolution":
        path = paper_folder / "smiles_resolved.csv"
        if not non_empty_file(path):
            return False, [f"missing or empty: {path}"]
        rows = read_csv_rows(path)
        cols = set(rows[0].keys()) if rows else set()
        name_cols = {"Name", "name", "compound_id", "Compound_ID"} & cols
        smiles_cols = {"SMILES", "smiles", "resolved_smiles", "Resolved_SMILES"} & cols
        ok = bool(rows and name_cols and smiles_cols)
        return ok, [f"rows={len(rows)}", f"name_columns={sorted(name_cols)}", f"smiles_columns={sorted(smiles_cols)}"]

    if stage == "06_unified_lnpdb_extraction":
        path = paper_folder / "unified_extraction.csv"
        flags = paper_folder / "unified_extraction_review_flags.csv"
        json_path = paper_folder / "unified_extraction.json"
        if not non_empty_file(path):
            return False, [f"missing or empty: {path}"]
        rows = read_csv_rows(path)
        cols = set(rows[0].keys()) if rows else set()
        missing_cols = [col for col in UNIFIED_EXTRACTION_COLUMNS if col not in cols]
        selected_count = len(selected_item_rows_by_id(paper_folder))
        empty_item_ids = sum(1 for row in rows if not str(row.get("Item_ID", "")).strip())
        ok_json = True
        if json_path.exists():
            try:
                json.loads(json_path.read_text(encoding="utf-8"))
            except Exception:
                ok_json = False
        ok = (
            bool(rows)
            and not missing_cols
            and empty_item_ids == 0
            and "confidence" in cols
            and "manual_required" in cols
            and flags.exists()
            and ok_json
            and (selected_count == 0 or len(rows) >= 1)
        )
        return ok, [
            f"rows={len(rows)}",
            f"selected_items={selected_count}",
            f"missing_required_columns={len(missing_cols)}",
            f"empty_item_ids={empty_item_ids}",
            f"review_flags_exists={flags.exists()}",
            f"json_parses={ok_json}",
        ]

    if stage == "07_finalize_unified_table":
        final_csv = paper_folder / "unified_extraction_final.csv"
        lnpdb_csv = paper_folder / "unified_extraction_lnpdb_like.csv"
        qc_json = paper_folder / "unified_extraction_qc_report.json"
        if not non_empty_file(final_csv):
            return False, [f"missing or empty: {final_csv}"]
        if not non_empty_file(lnpdb_csv):
            return False, [f"missing or empty: {lnpdb_csv}"]
        if not non_empty_file(qc_json):
            return False, [f"missing or empty: {qc_json}"]
        try:
            qc = json.loads(qc_json.read_text(encoding="utf-8"))
        except Exception as exc:
            return False, [f"qc_report_parse_error={exc}"]
        final_rows = read_csv_rows(final_csv)
        lnpdb_rows = read_csv_rows(lnpdb_csv)
        ok = isinstance(qc, dict) and bool(final_rows) and bool(lnpdb_rows)
        return ok, [f"final_rows={len(final_rows)}", f"lnpdb_like_rows={len(lnpdb_rows)}", "qc_report_parses=true"]

    raise ValueError(f"Unknown stage: {stage}")


def observe(paper_folder: Path) -> dict[str, Any]:
    paper_files = list(iter_paper_files(paper_folder)) if paper_folder.exists() else []
    files = {
        "pdf": len([p for p in paper_files if p.suffix.lower() == ".pdf"]),
        "markdown": len(find_markdown_files(paper_folder)) if paper_folder.exists() else 0,
        "excel": len([p for p in paper_files if p.suffix.lower() in {".xlsx", ".csv"}]),
    }
    artifacts = {
        "manual_marker": has_manual_marker(paper_folder),
        "fig_table_inventory.csv": (paper_folder / "fig_table_inventory.csv").exists(),
        "fig_table_lnpdb_classified.csv": (paper_folder / "fig_table_lnpdb_classified.csv").exists(),
        "total_figure_mapping.json": (paper_folder / "total_figure_mapping.json").exists(),
        "excel_block_inventory.csv": (paper_folder / "excel_block_inventory.csv").exists(),
        "excel_mapping.json": (paper_folder / "excel_mapping.json").exists(),
        "smiles_resolved.csv": (paper_folder / "smiles_resolved.csv").exists(),
        "unified_extraction.csv": (paper_folder / "unified_extraction.csv").exists(),
        "unified_extraction_final.csv": (paper_folder / "unified_extraction_final.csv").exists(),
    }
    result = {"exists": paper_folder.exists(), "files": files, "artifacts": artifacts}
    append_log(paper_folder, {"action": "observe", "result": result})
    update_state(paper_folder, None, "observed", result)
    return result


def next_stage(paper_folder: Path) -> dict[str, Any]:
    for stage in STAGE_ORDER:
        ok, messages = validate_stage(stage, paper_folder)
        if not ok:
            if stage in AGENT_STAGES and not has_manual_marker(paper_folder):
                return {"next_stage": "02b_manual_review", "blocked": True, "reason": "manual review marker is required before active agent stages"}
            return {"next_stage": stage, "blocked": STAGES.get(stage, {}).get("manual", False), "reason": "; ".join(messages)}
    return {"next_stage": None, "blocked": False, "reason": "all known stages validate"}


def backup_outputs(stage: str, paper_folder: Path) -> list[str]:
    backups: list[str] = []
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    for output in STAGES[stage].get("outputs", []):
        path = paper_folder / output
        if "*" in output:
            continue
        if path.exists():
            backup = path.with_name(f"{path.name}.bak_{timestamp}")
            if path.is_dir():
                shutil.copytree(path, backup)
            else:
                shutil.copy2(path, backup)
            backups.append(str(backup))
    return backups


def run_legacy_stage(stage: str, paper_folder: Path) -> Any:
    script = PROJECT_ROOT / STAGES[stage]["script"]

    if stage == "00_marker":
        module = import_module_from_path("stage_00_marker", script)
        return module.process_all_pdfs(paper_folder)

    if stage == "01_make_ft_csv":
        module = import_module_from_path("stage_01_make_ft_csv", script)
        return module.process_single_folder(
            target_folder=paper_folder,
            model_name=getattr(module, "MODEL_NAME", "gemini-3.1-pro-preview"),
            api_mode=getattr(module, "API_MODE", "vertex"),
            api_json_name=getattr(module, "API_JSON_NAME", "vertex.json"),
            api_txt_name=getattr(module, "API_TXT_NAME", "gemini_api.txt"),
            project=getattr(module, "PROJECT_ID", None),
            location=getattr(module, "LOCATION", "global"),
            max_input_tokens=getattr(module, "MAX_INPUT_TOKENS", 200000),
            token_count_only=getattr(module, "TOKEN_COUNT_ONLY", False),
        )

    if stage == "02_ft_selector":
        module = import_module_from_path("stage_02_ft_selector", script)
        return module.classify_fig_table_csv_for_lnpdb(
            target_folder=paper_folder,
            inventory_csv_name="fig_table_inventory.csv",
            output_csv_name="fig_table_lnpdb_classified.csv",
            model_name=getattr(module, "MODEL_NAME", "gemini-3.1-pro-preview"),
            api_mode=getattr(module, "API_MODE", "vertex"),
            api_json_name=getattr(module, "API_JSON_NAME", "vertex.json"),
            api_txt_name=getattr(module, "API_TXT_NAME", "gemini_api.txt"),
            project=getattr(module, "PROJECT_ID", None),
            location=getattr(module, "LOCATION", "global"),
            count_only=getattr(module, "COUNT_ONLY_MODE", False),
        )

    if stage == "02b_manual_review":
        raise RuntimeError("Manual review must be run by a human with Streamlit.")

    if stage == "03_figure_mapping":
        module = import_module_from_path("stage_03_figure_mapping", script)
        api_mode = getattr(module, "MAIN_API_MODE", "vertex")
        api_json_name = getattr(module, "MAIN_API_JSON_NAME", "vertex.json")
        project_id = getattr(module, "PROJECT_ID", None)
        if api_mode == "vertex" and hasattr(module, "find_api_key_file"):
            api_key_path = module.find_api_key_file(api_json_name)
            cred_data = json.loads(Path(api_key_path).read_text(encoding="utf-8"))
            project_id = cred_data.get("project_id") or project_id
        return module.run_mapping_main(
            root_dir=paper_folder,
            model_name=getattr(module, "MAIN_MODEL_NAME", "gemini-3.1-pro-preview"),
            api_mode=api_mode,
            api_json_name=api_json_name,
            api_txt_name=getattr(module, "MAIN_API_TXT_NAME", "gemini_api.txt"),
            project_id=project_id,
            location=getattr(module, "MAIN_LOCATION", "global"),
            token_count_only=getattr(module, "MAIN_TOKEN_COUNT_ONLY", False),
            max_input_tokens=getattr(module, "MAIN_MAX_INPUT_TOKENS", 160000),
            classified_csv_path=None,
            exclude_excel_covered=False,
        )

    if stage == "03_split_excel_blocks":
        module = import_module_from_path("stage_03_split_excel_blocks", script)
        return {"imported": bool(module)}

    if stage == "03_split_excel_blocks_batch":
        module = import_module_from_path("stage_03_split_excel_blocks_batch", script)
        api_key_path = module.find_api_key_file(getattr(module, "API_JSON_NAME", "vertex.json"))
        cred_data = json.loads(Path(api_key_path).read_text(encoding="utf-8"))
        project_id = cred_data.get("project_id")
        if not project_id:
            raise ValueError(f"project_id missing in credentials: {api_key_path}")
        client = module.get_vertexai_client(api_key_path, project=project_id)
        return module.process_excel_block_splitter(
            paper_folder,
            client,
            getattr(module, "MODEL_NAME", "gemini-3.1-pro-preview"),
            gcs_bucket=getattr(module, "DEFAULT_GCS_BATCH_BUCKET"),
        )

    if stage == "04_figure_separate":
        module = import_module_from_path("stage_04_figure_separate", script)
        api_key_path = module.find_api_key_file(getattr(module, "API_JSON_NAME", "vertex.json"))
        cred_data = json.loads(Path(api_key_path).read_text(encoding="utf-8"))
        project_id = cred_data.get("project_id")
        if not project_id:
            raise ValueError(f"project_id missing in credentials: {api_key_path}")
        client = module.get_vertexai_client(api_key_path, project=project_id)
        model_name = getattr(module, "BATCH_MODEL_NAME", getattr(module, "MODEL_NAME", "gemini-3.1-pro-preview"))
        return module.run_batch_vlm_separation(
            paper_folder,
            model_name,
            client,
            use_batch_mode=getattr(module, "USE_BATCH_MODE", True),
        )

    if stage == "04_ft_excel_matcher":
        module = import_module_from_path("stage_04_ft_excel_matcher", script)
        api_key_path = module.find_api_key_file(getattr(module, "API_JSON_NAME", "vertex.json"))
        cred_data = json.loads(Path(api_key_path).read_text(encoding="utf-8"))
        project_id = cred_data.get("project_id")
        if not project_id:
            raise ValueError(f"project_id missing in credentials: {api_key_path}")
        client = module.get_vertexai_client(api_key_path, project=project_id)
        return module.process_excel_matcher(paper_folder, client, getattr(module, "MODEL_NAME", "gemini-3.1-pro-preview"))

    if stage in LEGACY_STAGE_SCRIPT_GROUPS:
        scripts = "\n".join(f"- {script_path}" for script_path in LEGACY_STAGE_SCRIPT_GROUPS[stage])
        raise RuntimeError(
            f"{stage} replaces multiple legacy Gemini/API-assisted scripts and has no single safe legacy runner. "
            f"Legacy scripts are preserved for manual legacy mode only:\n{scripts}"
        )

    raise ValueError(f"Unknown stage: {stage}")


def tail_text(value: str, max_chars: int = 4000) -> str:
    if not value:
        return ""
    return value[-max_chars:]


def run_subprocess_streaming(command_args: list[str], stdin_text: str | None = None) -> dict[str, Any]:
    process = subprocess.Popen(
        command_args,
        cwd=PROJECT_ROOT,
        stdin=subprocess.PIPE if stdin_text is not None else None,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    stdout_parts: list[str] = []
    stderr_parts: list[str] = []

    def reader(pipe, output, parts: list[str]) -> None:
        try:
            for line in iter(pipe.readline, ""):
                parts.append(line)
                output.write(line)
                output.flush()
        finally:
            pipe.close()

    stdout_thread = threading.Thread(target=reader, args=(process.stdout, sys.stdout, stdout_parts), daemon=True)
    stderr_thread = threading.Thread(target=reader, args=(process.stderr, sys.stderr, stderr_parts), daemon=True)
    stdout_thread.start()
    stderr_thread.start()

    if stdin_text is not None and process.stdin is not None:
        try:
            process.stdin.write(stdin_text)
            process.stdin.close()
        except (BrokenPipeError, OSError, ValueError):
            pass

    returncode = process.wait()
    stdout_thread.join()
    stderr_thread.join()
    return {
        "returncode": returncode,
        "stdout_tail": tail_text("".join(stdout_parts)),
        "stderr_tail": tail_text("".join(stderr_parts)),
    }


def validation_result_dict(ok: bool, messages: list[str]) -> dict[str, Any]:
    return {"ok": ok, "messages": messages}


def append_validation_failure_feedback(task_file: Path, validation_result: dict[str, Any], attempt: int) -> None:
    messages = validation_result.get("messages", [])
    lines = [
        "",
        "## Validation Failure Feedback",
        "",
        f"Attempt: {attempt}",
        "",
        "Validation did not pass. Re-read the task instructions and fix the output files without using Gemini/API/find_api/LLM_API/LLM_Batch.",
        "",
        "Validation messages:",
    ]
    lines.extend(f"- {message}" for message in messages)
    lines.extend(
        [
            "",
            "Retry instructions:",
            "- Inspect the current outputs and the validation messages.",
            "- Modify or create only the required output CSV/JSON files.",
            "- Preserve provenance and mark uncertain values with manual_required=true.",
            "- Run the validation command again after changes.",
            "",
        ]
    )
    with task_file.open("a", encoding="utf-8") as f:
        f.write("\n".join(lines))


def build_agent_prompt(stage: str, paper_folder: Path, task_file: Path, validation_result: dict[str, Any] | None = None) -> str:
    task_text = task_file.read_text(encoding="utf-8")
    validation_text = ""
    if validation_result:
        validation_text = (
            "\n\nPrevious validation result:\n"
            + json.dumps(validation_result, ensure_ascii=False, indent=2)
            + "\nFix the validation failures and rerun validation.\n"
        )
    return f"""You are an external CLI coding agent working in the LNPDB_Articles_AgentExtraction repository.

Stage: {stage}
Target paper folder: {paper_folder}
Task file: {task_file}

Read and complete the task markdown below. Use the target paper folder from both this prompt and the task file.

Hard constraints:
- Do not use Gemini/API/find_api/LLM_API/LLM_Batch.
- Do not run legacy Gemini scripts.
- Follow agent_workspace/OUTPUT_SCHEMA.md.
- Create or modify the required output files so Agent_Task_Runner.py validation passes.
- If exact values are missing, leave them blank and set manual_required=true.
- Record evidence/provenance for nontrivial extracted values.
- Do not delete original PDF or Excel files.
- If overwrite is needed, create a backup or follow the runner backup policy.
- Stage-specific task markdown instructions have priority.
- If you fail, record the cause and what you changed.
{validation_text}
Task markdown:

{task_text}
"""


def split_agent_command(command: str) -> list[str]:
    try:
        parts = shlex.split(command, posix=False)
    except ValueError:
        parts = shlex.split(command)
    cleaned: list[str] = []
    for part in parts:
        if len(part) >= 2 and part[0] == part[-1] and part[0] in {"'", '"'}:
            cleaned.append(part[1:-1])
        else:
            cleaned.append(part)
    return cleaned


def build_agent_command_args(
    command_template: str,
    prompt_text: str,
    task_file: Path,
    paper_folder: Path,
    stage: str,
) -> tuple[list[str], str, bool]:
    parts = split_agent_command(command_template)
    stdin_mode = "{prompt_stdin}" in command_template or "-" in parts
    replacements = {
        "{prompt_text}": "" if stdin_mode else prompt_text,
        "{prompt_stdin}": "-",
        "{prompt_file}": str(task_file),
        "{stage}": stage,
        "{paper_folder}": str(paper_folder),
        "{project_root}": str(PROJECT_ROOT),
    }
    command_args: list[str] = []
    display_parts: list[str] = []
    for part in parts:
        arg = part
        display = part
        for placeholder, value in replacements.items():
            arg = arg.replace(placeholder, value)
            if placeholder == "{prompt_text}":
                display = display.replace(placeholder, "<prompt_text>" if not stdin_mode else "")
            elif placeholder == "{prompt_stdin}":
                display = display.replace(placeholder, "-")
            else:
                display = display.replace(placeholder, value)
        if arg != "":
            command_args.append(arg)
        if display != "":
            display_parts.append(display)
    return command_args, " ".join(display_parts), stdin_mode


def run_external_cli_agent(
    agent: str,
    task_file: Path,
    paper_folder: Path,
    stage: str,
    command_template: str | None = None,
    dry_run: bool = False,
    validation_result: dict[str, Any] | None = None,
    stream_output: bool = False,
) -> dict[str, Any]:
    if agent not in {"codex", "claude", "custom"}:
        raise ValueError(f"Unsupported agent: {agent}")
    if agent == "custom":
        if not command_template:
            raise ValueError("--agent-command is required when --agent custom")
        template = command_template
    else:
        template = command_template or DEFAULT_AGENT_COMMAND_TEMPLATES[agent]

    prompt_text = build_agent_prompt(stage, paper_folder, task_file, validation_result=validation_result)
    command_args, command_display, stdin_mode = build_agent_command_args(template, prompt_text, task_file, paper_folder, stage)
    result: dict[str, Any] = {
        "agent": agent,
        "stage": stage,
        "task_file": str(task_file),
        "prompt_file": str(task_file),
        "prompt_length": len(prompt_text),
        "command": command_display,
        "stdin_mode": stdin_mode,
        "dry_run": dry_run,
        "stream_output": stream_output,
    }
    if dry_run:
        result.update({"returncode": None, "stdout_tail": "", "stderr_tail": "", "skipped": True})
        return result

    try:
        if stream_output:
            completed_result = run_subprocess_streaming(command_args, prompt_text if stdin_mode else None)
            result.update(completed_result)
            return result
        completed = subprocess.run(
            command_args,
            cwd=PROJECT_ROOT,
            input=prompt_text if stdin_mode else None,
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
        )
    except FileNotFoundError as exc:
        result.update({"returncode": None, "stdout_tail": "", "stderr_tail": str(exc), "error": str(exc)})
        return result

    result.update(
        {
            "returncode": completed.returncode,
            "stdout_tail": tail_text(completed.stdout),
            "stderr_tail": tail_text(completed.stderr),
        }
    )
    return result


def run_agent_active(
    paper_folder: Path,
    stages: list[str] | None,
    agent: str,
    command_template: str | None,
    dry_run: bool,
    continue_on_error: bool,
    max_agent_retries: int,
    skip_valid: bool = True,
    stream_agent_output: bool = False,
) -> dict[str, Any]:
    if not paper_folder.exists():
        raise FileNotFoundError(f"Paper folder does not exist: {paper_folder}")
    if not has_manual_marker(paper_folder):
        raise RuntimeError(f"Refusing active agent run: missing {paper_folder / MANUAL_MARKER}")
    if max_agent_retries < 0:
        raise ValueError("--max-agent-retries must be >= 0")

    selected_stages = stages or DEFAULT_AGENT_ACTIVE_STAGES
    unknown = [stage for stage in selected_stages if stage not in STAGES]
    if unknown:
        raise ValueError(f"Unknown stages: {unknown}")

    summary: dict[str, Any] = {
        "status": "completed",
        "paper_folder": str(paper_folder),
        "agent": agent,
        "dry_run": dry_run,
        "stream_agent_output": stream_agent_output,
        "stages": [],
    }
    append_log(
        paper_folder,
        {
            "action": "run_agent_active_start",
            "agent": agent,
            "stages": selected_stages,
            "dry_run": dry_run,
            "continue_on_error": continue_on_error,
            "max_agent_retries": max_agent_retries,
            "skip_valid": skip_valid,
            "stream_agent_output": stream_agent_output,
        },
    )

    for stage in selected_stages:
        ok, messages = validate_stage(stage, paper_folder)
        validation = validation_result_dict(ok, messages)
        mode = STAGE_EXECUTION_MODE.get(stage, "legacy")
        print(f"[RUN_AGENT_ACTIVE] stage={stage} mode={mode}")
        print(f"[VALIDATE] stage={stage}")
        print(f"[VALIDATE] ok={str(ok).lower()} messages={messages}")
        if ok and skip_valid:
            stage_result = {"stage": stage, "status": "skipped_valid", "validation": validation}
            summary["stages"].append(stage_result)
            append_log(paper_folder, {"action": "stage_skip_valid", "stage": stage, "validation": validation})
            update_state(paper_folder, stage, "validated", validation)
            continue

        stage_result: dict[str, Any] = {
            "stage": stage,
            "status": "running",
            "mode": mode,
            "attempts": 0,
            "validation": validation,
        }
        last_agent_result: dict[str, Any] | None = None
        try:
            run_result = run_stage(stage, paper_folder, dry_run=dry_run)
            stage_result["run_result"] = run_result
            if dry_run:
                stage_result["status"] = "planned"
                summary["stages"].append(stage_result)
                continue

            if run_result.get("status") == "external_agent_required":
                task_file = Path(run_result["task_file"])
                stage_result["task_file"] = str(task_file)
                validation_feedback: dict[str, Any] | None = None
                for attempt in range(max_agent_retries + 1):
                    stage_result["attempts"] = attempt + 1
                    preview_template = command_template
                    if not preview_template:
                        if agent == "custom":
                            preview_template = ""
                        else:
                            preview_template = DEFAULT_AGENT_COMMAND_TEMPLATES[agent]
                    preview_prompt = build_agent_prompt(stage, paper_folder, task_file, validation_result=validation_feedback)
                    _preview_args, preview_command, preview_stdin_mode = build_agent_command_args(
                        preview_template,
                        preview_prompt,
                        task_file,
                        paper_folder,
                        stage,
                    )
                    print(f"[EXTERNAL_AGENT] command={preview_command}")
                    print(f"[EXTERNAL_AGENT] task_file={task_file}")
                    print(
                        "[EXTERNAL_AGENT] "
                        f"stdin_mode={str(preview_stdin_mode).lower()} "
                        f"prompt_length={len(preview_prompt)}"
                    )
                    agent_result = run_external_cli_agent(
                        agent,
                        task_file,
                        paper_folder,
                        stage,
                        command_template=command_template,
                        dry_run=dry_run,
                        validation_result=validation_feedback,
                        stream_output=stream_agent_output,
                    )
                    last_agent_result = agent_result
                    append_log(paper_folder, {"action": "external_agent_call", **agent_result})
                    if agent_result.get("returncode") not in {0, None}:
                        stage_result["status"] = "agent_failed"
                        stage_result["agent_result"] = agent_result
                    print(f"[VALIDATE] stage={stage}")
                    ok, messages = validate_stage(stage, paper_folder)
                    validation_feedback = validation_result_dict(ok, messages)
                    print(f"[VALIDATE] ok={str(ok).lower()} messages={messages}")
                    stage_result["validation"] = validation_feedback
                    append_log(
                        paper_folder,
                        {"action": "stage_validation", "stage": stage, "task_file": str(task_file), "validation": validation_feedback},
                    )
                    if ok:
                        stage_result["status"] = "completed"
                        stage_result["agent_result"] = agent_result
                        update_state(paper_folder, stage, "validated", validation_feedback)
                        break
                    if attempt < max_agent_retries:
                        append_validation_failure_feedback(task_file, validation_feedback, attempt + 1)
                        append_log(
                            paper_folder,
                            {
                                "action": "stage_retry",
                                "stage": stage,
                                "task_file": str(task_file),
                                "attempt": attempt + 1,
                                "validation": validation_feedback,
                            },
                        )
                else:
                    stage_result["status"] = "validation_failed"
            else:
                print(f"[VALIDATE] stage={stage}")
                ok, messages = validate_stage(stage, paper_folder)
                validation = validation_result_dict(ok, messages)
                print(f"[VALIDATE] ok={str(ok).lower()} messages={messages}")
                stage_result["validation"] = validation
                append_log(paper_folder, {"action": "stage_validation", "stage": stage, "validation": validation})
                if ok:
                    stage_result["status"] = "completed"
                    update_state(paper_folder, stage, "validated", validation)
                else:
                    stage_result["status"] = "validation_failed"

            if stage_result["status"] != "completed":
                failure_detail = {
                    "stage": stage,
                    "status": stage_result["status"],
                    "validation": stage_result.get("validation"),
                    "agent_result": last_agent_result,
                }
                update_state(paper_folder, stage, "failed", failure_detail)
                if not continue_on_error:
                    summary["status"] = "failed"
                    summary["stages"].append(stage_result)
                    append_log(paper_folder, {"action": "run_agent_active_done", **summary})
                    return summary
        except Exception as exc:
            stage_result.update(
                {
                    "status": "failed",
                    "error": str(exc),
                    "traceback": traceback.format_exc(),
                }
            )
            update_state(paper_folder, stage, "failed", stage_result)
            if not continue_on_error:
                summary["status"] = "failed"
                summary["stages"].append(stage_result)
                append_log(paper_folder, {"action": "run_agent_active_done", **summary})
                return summary

        summary["stages"].append(stage_result)

    if any(stage_result.get("status") not in {"completed", "skipped_valid", "planned"} for stage_result in summary["stages"]):
        summary["status"] = "completed_with_errors" if continue_on_error else "failed"
    append_log(paper_folder, {"action": "run_agent_active_done", **summary})
    return summary


def run_stage(
    stage: str,
    paper_folder: Path,
    dry_run: bool = False,
    skip_backup: bool = False,
    mode_override: str | None = None,
) -> dict[str, Any]:
    if stage not in STAGES:
        raise ValueError(f"Unknown stage: {stage}")
    if not paper_folder.exists():
        raise FileNotFoundError(f"Paper folder does not exist: {paper_folder}")
    if STAGES[stage].get("requires_manual_marker") and not has_manual_marker(paper_folder):
        raise RuntimeError(f"Refusing to run {stage}: missing {paper_folder / MANUAL_MARKER}")

    mode = mode_override or STAGE_EXECUTION_MODE.get(stage, "legacy")
    if mode not in VALID_STAGE_EXECUTION_MODES:
        raise ValueError(f"Invalid execution mode for {stage}: {mode}")
    script = PROJECT_ROOT / STAGES[stage]["script"]
    detail = {"stage": stage, "mode": mode, "script": str(script), "dry_run": dry_run}
    append_log(paper_folder, {"action": "stage_start", **detail})
    update_state(paper_folder, stage, "running" if not dry_run else "dry_run", detail)

    if dry_run:
        return {"planned": detail}

    if mode == "external_agent":
        try:
            final = create_external_agent_task(stage, paper_folder)
            append_log(paper_folder, {"action": "stage_external_agent_task_created", "stage": stage, **final})
            update_state(paper_folder, stage, "external_agent_required", final)
            return final
        except Exception as exc:
            final = {
                "status": "failed",
                "mode": mode,
                "error": str(exc),
                "traceback": traceback.format_exc(),
                "backups": [],
            }
            append_log(paper_folder, {"action": "stage_failed", "stage": stage, **final})
            update_state(paper_folder, stage, "failed", final)
            raise

    backups = [] if skip_backup else backup_outputs(stage, paper_folder)
    try:
        if mode == "heuristic":
            result = run_heuristic_stage(stage, paper_folder)
        elif mode == "legacy":
            result = run_legacy_stage(stage, paper_folder)
        else:
            raise ValueError(f"Unsupported execution mode for {stage}: {mode}")
        ok, messages = validate_stage(stage, paper_folder)
        status = "success" if ok else "validation_failed"
        final = {"status": status, "mode": mode, "validation": messages, "backups": backups, "result": result}
        append_log(paper_folder, {"action": "stage_complete", "stage": stage, **final})
        update_state(paper_folder, stage, status, final)
        return final
    except Exception as exc:
        final = {
            "status": "failed",
            "mode": mode,
            "error": str(exc),
            "traceback": traceback.format_exc(),
            "backups": backups,
        }
        append_log(paper_folder, {"action": "stage_failed", "stage": stage, **final})
        update_state(paper_folder, stage, "failed", final)
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description="External CLI agent task runner for LNPDB extraction.")
    sub = parser.add_subparsers(dest="command", required=True)

    for command in ["observe", "next"]:
        p = sub.add_parser(command)
        p.add_argument("--paper-folder", required=True)

    p_validate = sub.add_parser("validate")
    p_validate.add_argument("--stage", required=True, choices=STAGE_ORDER)
    p_validate.add_argument("--paper-folder", required=True)

    p_run = sub.add_parser("run")
    p_run.add_argument("--stage", required=True, choices=STAGE_ORDER)
    p_run.add_argument("--paper-folder", required=True)
    p_run.add_argument("--dry-run", action="store_true")
    p_run.add_argument("--skip-backup", action="store_true")
    p_run.add_argument("--mode", choices=sorted(VALID_STAGE_EXECUTION_MODES))

    p_run_agent = sub.add_parser("run-agent-active")
    p_run_agent.add_argument("--paper-folder", required=True)
    p_run_agent.add_argument("--agent", choices=["codex", "claude", "custom"], default="codex")
    p_run_agent.add_argument("--agent-command", default=None)
    p_run_agent.add_argument("--stages", nargs="*", default=None, choices=STAGE_ORDER)
    p_run_agent.add_argument("--dry-run", action="store_true")
    p_run_agent.add_argument("--continue-on-error", action="store_true")
    p_run_agent.add_argument("--max-agent-retries", type=int, default=1)
    p_run_agent.add_argument("--no-skip-valid", action="store_true")
    p_run_agent.add_argument("--stream-agent-output", action="store_true")

    args = parser.parse_args()
    paper_folder = resolve_paper_folder(args.paper_folder)

    if args.command == "observe":
        print(json.dumps(observe(paper_folder), ensure_ascii=False, indent=2))
        return 0

    if args.command == "next":
        result = next_stage(paper_folder)
        append_log(paper_folder, {"action": "next", "result": result})
        update_state(paper_folder, result.get("next_stage"), "next_stage_selected", result)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    if args.command == "validate":
        ok, messages = validate_stage(args.stage, paper_folder)
        result = {"ok": ok, "messages": messages}
        append_log(paper_folder, {"action": "validate", "stage": args.stage, "result": result})
        update_state(paper_folder, args.stage, "validated" if ok else "validation_failed", result)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if ok else 2

    if args.command == "run":
        result = run_stage(
            args.stage,
            paper_folder,
            dry_run=args.dry_run,
            skip_backup=args.skip_backup,
            mode_override=args.mode,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
        return 0 if result.get("status") in {None, "success", "external_agent_required"} or "planned" in result else 2

    if args.command == "run-agent-active":
        result = run_agent_active(
            paper_folder=paper_folder,
            stages=args.stages,
            agent=args.agent,
            command_template=args.agent_command,
            dry_run=args.dry_run,
            continue_on_error=args.continue_on_error,
            max_agent_retries=args.max_agent_retries,
            skip_valid=not args.no_skip_valid,
            stream_agent_output=args.stream_agent_output,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
        return 0 if result.get("status") in {"completed", "completed_with_errors"} else 2

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
