from __future__ import annotations

import argparse
import csv
import importlib.util
import json
import re
import shutil
import sys
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
]

AGENT_STAGES = {
    "03_figure_mapping",
    "03_split_excel_blocks",
    "03_split_excel_blocks_batch",
    "04_figure_separate",
    "04_ft_excel_matcher",
}


STAGE_EXECUTION_MODE = {
    "03_figure_mapping": "external_agent",
    "03_split_excel_blocks_batch": "external_agent",
    "04_figure_separate": "external_agent",
    "04_ft_excel_matcher": "external_agent",
}

VALID_STAGE_EXECUTION_MODES = {"legacy", "external_agent", "heuristic"}


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
}


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
6. Map each selected figure/table item to the most likely source image/table path.
7. Create `total_figure_mapping.json` in the paper folder root.
8. Follow `agent_workspace/OUTPUT_SCHEMA.md` for the `total_figure_mapping.json` schema.
9. Store paths relative to the paper folder when possible.
10. If uncertain, record `confidence: "low"` or `confidence: "unmatched"` and a short `reason`.

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
2. Identify entries with `source_image`.
3. Decide whether panel cropping is needed for each image.
4. Use OpenCV/PIL helper code or write a small deterministic script if crop boundaries are clear.
5. Save panel images under `separated_panels_gemini/`.
6. Add panel paths back into `total_figure_mapping.json`.
7. If automatic crop is uncertain, do not crop; record `manual_required`, `confidence`, and `reason`.

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
        mapping[paper_folder.name][item_id] = {
            "item_id": item_id,
            "base_id": base_id,
            "caption": row.get("caption", ""),
            "source_image": rel_to_paper(image_match, paper_folder) if image_match and image_score > 0 else None,
            "source_table": rel_to_paper(table_match, paper_folder) if table_match and table_score > 0 else None,
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
    if isinstance(data, dict):
        for paper_value in data.values():
            if not isinstance(paper_value, dict):
                continue
            for item_key, entry in paper_value.items():
                if item_key.startswith("_") or not isinstance(entry, dict):
                    continue
                if entry.get("source_image"):
                    entry.setdefault("panels", {})
                    entry["panel_separation"] = "not_performed"
                    entry["confidence"] = "not_separated"
                    entry["reason"] = "Panel separation not performed in heuristic mode."
                    updated += 1
    write_json(
        panel_dir / "manifest.json",
        {
            "created_by": "Agent_Task_Runner heuristic mode",
            "status": "panel separation not performed in heuristic mode",
            "updated_mapping_entries": updated,
            "created_at": utc_now(),
        },
    )
    write_json(mapping_path, data)
    return {"panel_dir": str(panel_dir), "updated_mapping_entries": updated}


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
        return isinstance(data, dict) and bool(data), [f"top_level_keys={len(data) if isinstance(data, dict) else 'not_object'}"]

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
        return isinstance(data, dict), [f"mapping_keys={len(data) if isinstance(data, dict) else 'not_object'}", f"panel_dirs={len(panel_dirs)}"]

    if stage == "04_ft_excel_matcher":
        mapping = paper_folder / "excel_mapping.json"
        rows_csv = paper_folder / "excel_mapping_rows.csv"
        if not non_empty_file(mapping):
            return False, [f"missing or empty: {mapping}"]
        data = json.loads(mapping.read_text(encoding="utf-8"))
        ok = isinstance(data, dict) and rows_csv.exists()
        return ok, [f"mapping_keys={len(data) if isinstance(data, dict) else 'not_object'}", f"rows_csv_exists={rows_csv.exists()}"]

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

    raise ValueError(f"Unknown stage: {stage}")


def run_stage(stage: str, paper_folder: Path, dry_run: bool = False, skip_backup: bool = False) -> dict[str, Any]:
    if stage not in STAGES:
        raise ValueError(f"Unknown stage: {stage}")
    if not paper_folder.exists():
        raise FileNotFoundError(f"Paper folder does not exist: {paper_folder}")
    if STAGES[stage].get("requires_manual_marker") and not has_manual_marker(paper_folder):
        raise RuntimeError(f"Refusing to run {stage}: missing {paper_folder / MANUAL_MARKER}")

    mode = STAGE_EXECUTION_MODE.get(stage, "legacy")
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
        result = run_stage(args.stage, paper_folder, dry_run=args.dry_run, skip_backup=args.skip_backup)
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
        return 0 if result.get("status") in {None, "success", "external_agent_required"} or "planned" in result else 2

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
