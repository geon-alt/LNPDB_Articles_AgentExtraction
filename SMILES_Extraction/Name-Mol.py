

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Name-Mol.py

Agent-only molecule naming/review stage for SMILES image extraction.

Input
-----
A deterministic DECIMER/MolScribe output CSV, typically:
  <paper-folder>/SMILES_Extraction_Results/no_agent_image_test/no_agent_image_extraction.csv

The CSV is expected to contain image/crop path columns such as:
  image_path, crop_path, bbox_y0, bbox_x0, bbox_y1, bbox_x1, smiles

Output
------
A copy of the input CSV with appended agent columns. The agent should inspect
crop images, original page/figure images, markdown text, and source paper files
to infer molecule names/labels/component types. Original extraction columns are
preserved exactly.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import subprocess
import sys
import time
import traceback
from pathlib import Path
from typing import Any, Dict, Iterable, List, Sequence


# -----------------------------------------------------------------------------
# Local test configuration
# -----------------------------------------------------------------------------
# Run without CLI args:
#   python SMILES_Extraction/Name-Mol.py
USE_LOCAL_TEST_CONFIG = True

LOCAL_TEST_PAPER_FOLDER = "/Users/kogeon/Google Drive/내 드라이브/EXTRACT-TEST/QS_2026_3"
LOCAL_TEST_REPO_ROOT = "/Users/kogeon/python_projects_path/LNPDB_Articles_AgentExtraction"
LOCAL_TEST_EXTRACTION_DIR = ""  # blank -> <paper-folder>/SMILES_Extraction_Results/no_agent_image_test
LOCAL_TEST_INPUT_CSV = ""      # blank -> <extraction-dir>/no_agent_image_extraction.csv
LOCAL_TEST_OUTPUT_CSV = ""     # blank -> <extraction-dir>/name_mol_agent_review.csv
LOCAL_TEST_OUTPUT_JSON = ""    # blank -> <extraction-dir>/name_mol_agent_review.json
LOCAL_TEST_MAX_ROWS = 0         # 0 -> all rows
LOCAL_TEST_START_ROW = 1        # 1-based row index after reading CSV

RUN_AGENT = True
LOCAL_AGENT_COMMAND = 'codex exec --dangerously-bypass-approvals-and-sandbox --cd "{repo_root}"'
LOCAL_AGENT_STREAM_OUTPUT = True
LOCAL_AGENT_TIMEOUT_SECONDS = 60 * 60

# Keep task compact. The agent can open full files by path when needed.
MAX_MARKDOWN_FILES_IN_MANIFEST = 80
MAX_IMAGE_FILES_IN_MANIFEST = 200
MAX_ROWS_IN_PROMPT_PREVIEW = 80

IMAGE_SUFFIXES = {".jpeg", ".jpg", ".png", ".tif", ".tiff", ".bmp", ".webp"}
TEXT_SUFFIXES = {".md", ".markdown", ".txt", ".csv", ".tsv", ".json"}

AGENT_COLUMNS = [
    "agent_is_structure",
    "agent_structure_type",
    "agent_structure_label",
    "agent_matched_name",
    "agent_component_type",
    "agent_smiles_qc",
    "agent_confidence",
    "agent_manual_required",
    "agent_reason",
    "agent_evidence_text",
    "agent_evidence_source_path",
]


def absolute_path(path: str | Path) -> Path:
    return Path(os.path.abspath(os.fspath(Path(path).expanduser())))


def read_csv_rows(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        fieldnames = list(reader.fieldnames or [])
        rows = [dict(row) for row in reader]
    return fieldnames, rows


def write_csv_rows(path: Path, fieldnames: Sequence[str], rows: Sequence[Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(fieldnames), extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({key: "" if row.get(key) is None else row.get(key, "") for key in fieldnames})


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def select_rows(rows: Sequence[Dict[str, str]], start_row: int, max_rows: int) -> list[dict[str, str]]:
    if start_row < 1:
        raise ValueError("start_row must be >= 1")
    start = start_row - 1
    if max_rows and max_rows > 0:
        selected = rows[start : start + max_rows]
    else:
        selected = rows[start:]
    return [dict(row) for row in selected]


def append_agent_columns(fieldnames: Sequence[str]) -> list[str]:
    out = list(fieldnames)
    for column in AGENT_COLUMNS:
        if column not in out:
            out.append(column)
    return out


def seed_agent_columns(rows: Sequence[Dict[str, Any]]) -> list[dict[str, Any]]:
    seeded: list[dict[str, Any]] = []
    for row in rows:
        new_row = dict(row)
        for column in AGENT_COLUMNS:
            new_row.setdefault(column, "")
        seeded.append(new_row)
    return seeded


def safe_relative(path: Path, root: Path) -> str:
    try:
        return os.fspath(path.relative_to(root))
    except ValueError:
        return os.fspath(path)


def iter_files(root: Path, suffixes: set[str]) -> Iterable[Path]:
    if not root.exists():
        return []
    return sorted(
        p for p in root.rglob("*")
        if p.is_file()
        and p.suffix.lower() in suffixes
        and ".git" not in p.parts
        and "__pycache__" not in p.parts
    )


def discover_context_files(paper_folder: Path, extraction_dir: Path) -> dict[str, Any]:
    markdown_files = []
    image_files = []
    pdf_files = []
    excel_files = []

    for p in iter_files(paper_folder, {".md", ".markdown", ".txt"}):
        markdown_files.append({"path": str(p), "relative_path": safe_relative(p, paper_folder)})
        if len(markdown_files) >= MAX_MARKDOWN_FILES_IN_MANIFEST:
            break

    for p in iter_files(paper_folder, IMAGE_SUFFIXES):
        # Exclude generated crop folder from source-context list. Crop paths are
        # already available row-by-row in the CSV.
        try:
            p.relative_to(extraction_dir / "crops")
            continue
        except ValueError:
            pass
        image_files.append({"path": str(p), "relative_path": safe_relative(p, paper_folder)})
        if len(image_files) >= MAX_IMAGE_FILES_IN_MANIFEST:
            break

    for p in iter_files(paper_folder, {".pdf"}):
        pdf_files.append({"path": str(p), "relative_path": safe_relative(p, paper_folder)})

    for p in iter_files(paper_folder, {".xlsx", ".xlsm", ".xls", ".csv"}):
        excel_files.append({"path": str(p), "relative_path": safe_relative(p, paper_folder)})

    return {
        "markdown_or_text_files": markdown_files,
        "source_image_files": image_files,
        "pdf_files": pdf_files,
        "table_files": excel_files[:120],
    }


def make_row_preview(rows: Sequence[Dict[str, Any]], limit: int = MAX_ROWS_IN_PROMPT_PREVIEW) -> list[dict[str, Any]]:
    preview = []
    for i, row in enumerate(rows[:limit], start=1):
        preview.append(
            {
                "preview_index": i,
                "image_index": row.get("image_index", ""),
                "image_name": row.get("image_name", ""),
                "image_path": row.get("image_path", ""),
                "crop_index": row.get("crop_index", ""),
                "crop_path": row.get("crop_path", ""),
                "bbox_y0": row.get("bbox_y0", ""),
                "bbox_x0": row.get("bbox_x0", ""),
                "bbox_y1": row.get("bbox_y1", ""),
                "bbox_x1": row.get("bbox_x1", ""),
                "smiles": row.get("smiles", row.get("molscribe_smiles", "")),
                "status": row.get("status", ""),
            }
        )
    return preview


def create_agent_task(
    *,
    paper_folder: Path,
    repo_root: Path,
    extraction_dir: Path,
    input_csv: Path,
    output_csv: Path,
    output_json: Path,
    manifest_path: Path,
    selected_rows: Sequence[Dict[str, Any]],
    total_rows: int,
) -> Path:
    task_dir = extraction_dir / "name_mol_agent"
    task_dir.mkdir(parents=True, exist_ok=True)
    task_path = task_dir / "name_mol_agent_task.md"

    row_preview_json = json.dumps(make_row_preview(selected_rows), ensure_ascii=False, indent=2)

    task = f"""# Name-Mol agent task

You are the post-processing agent for image-based SMILES extraction.
DECIMER/MolScribe has already produced crop images, bounding boxes, and raw SMILES.
Your job is to infer molecule names/labels by looking at the crop images and by using the paper context.

## Paths

Paper folder:
`{paper_folder}`

Repository root:
`{repo_root}`

Extraction directory:
`{extraction_dir}`

Input CSV:
`{input_csv}`

Output CSV to write:
`{output_csv}`

Output JSON to write:
`{output_json}`

Context manifest:
`{manifest_path}`

## Input rows

Total rows in original CSV: {total_rows}
Rows selected for this run: {len(selected_rows)}

Preview of selected rows:
```json
{row_preview_json}
```

## Required work

1. Read the input CSV.
2. Preserve every original column and value exactly.
3. Append or fill these columns only:
   {', '.join(AGENT_COLUMNS)}
4. For each row, inspect `crop_path` first. If needed, inspect `image_path` and nearby source files listed in the context manifest.
5. Use paper-derived markdown/text, source images, PDF-derived figures, and table files to infer the visible molecule label/name.
6. Write the completed table to the output CSV path.
7. Write the same completed records as a JSON array to the output JSON path.

## Column definitions

- `agent_is_structure`: true, false, or unclear.
- `agent_structure_type`: Single, Markush, Combinatorial, ReactionScheme, NonStructure, or Unknown.
- `agent_structure_label`: visible label near the molecule, such as A1, H1, compound number, lipid name, panel label, or blank.
- `agent_matched_name`: exactly one likely molecule/component name from the paper context. Leave blank if not unambiguous.
- `agent_component_type`: ionizable_lipid, helper_lipid, cholesterol, peg_lipid, reagent, cargo, solvent, other, or unclear.
- `agent_smiles_qc`: ok, suspicious, invalid, noisy_crop, non_structure, or unclear.
- `agent_confidence`: high, medium, or low.
- `agent_manual_required`: true or false.
- `agent_reason`: concise reason for the decision.
- `agent_evidence_text`: short evidence text, visible label, filename cue, or source context.
- `agent_evidence_source_path`: crop_path, image_path, markdown path, table path, or source image path used as evidence.

## Rules

- Do not change the raw `smiles` value.
- Do not change `crop_path`, `image_path`, bbox columns, status, or any original column.
- `agent_matched_name` must contain at most one name. Never use semicolon-separated or pipe-separated multiple names.
- If the crop contains a plot, spectrum, legend, text, arrow, or non-molecular content, set `agent_is_structure=false` and `agent_smiles_qc=non_structure` or `noisy_crop`.
- If the crop contains a valid molecular drawing but no reliable name can be inferred, set `agent_is_structure=true`, leave `agent_matched_name` blank, and set `agent_manual_required=true`.
- Mark suspicious MolScribe output when it contains obvious repeated noise such as `C.C.C.C`, `*.*.*.*`, `[HH]`, `[2HH]`, or unlikely OCR atoms such as `[He]`, `[Th]`, `[K]`, `[In]`, unless those atoms are visibly present in the drawing.
- Prefer paper-visible labels and nearby captions over guessing from raw SMILES.
- Use the context manifest to locate markdown, figures, supplementary images, PDFs, and table files.

## Output constraints

- The output CSV must include all original input columns plus all agent columns.
- The output JSON must be a JSON array of row objects with the same records as the CSV.
- Keep row order unchanged.
"""
    task_path.write_text(task, encoding="utf-8")
    return task_path


def format_agent_command(command_template: str, *, repo_root: Path, paper_folder: Path, extraction_dir: Path) -> str:
    return command_template.format(
        repo_root=str(repo_root),
        paper_folder=str(paper_folder),
        extraction_dir=str(extraction_dir),
    )


def run_agent(command: str, prompt: str, *, cwd: Path, log_path: Path, stream: bool, timeout_seconds: int) -> int:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("w", encoding="utf-8", errors="replace") as log:
        log.write(f"command: {command}\n")
        log.write(f"cwd: {cwd}\n")
        log.write("===== BEGIN PROMPT =====\n")
        log.write(prompt)
        log.write("\n===== END PROMPT =====\n")
        log.write("===== BEGIN OUTPUT =====\n")

    process = subprocess.Popen(
        command,
        cwd=str(cwd),
        shell=True,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
    )

    assert process.stdin is not None
    process.stdin.write(prompt)
    process.stdin.close()

    start = time.time()
    assert process.stdout is not None
    for line in process.stdout:
        with log_path.open("a", encoding="utf-8", errors="replace") as log:
            log.write(line)
        if stream:
            print(line, end="")
        if time.time() - start > timeout_seconds:
            process.kill()
            with log_path.open("a", encoding="utf-8", errors="replace") as log:
                log.write("\n[TIMEOUT] agent command killed\n")
            return 124

    return_code = process.wait()
    with log_path.open("a", encoding="utf-8", errors="replace") as log:
        log.write("\n===== END OUTPUT =====\n")
        log.write(f"return_code: {return_code}\n")
    return return_code


def validate_output_csv(path: Path, expected_columns: Sequence[str], expected_rows: int) -> list[str]:
    messages: list[str] = []
    if not path.exists():
        return [f"output CSV missing: {path}"]

    try:
        fieldnames, rows = read_csv_rows(path)
    except Exception as exc:
        return [f"failed to read output CSV: {exc}"]

    missing = [col for col in expected_columns if col not in fieldnames]
    if missing:
        messages.append(f"missing columns: {missing}")
    if len(rows) != expected_rows:
        messages.append(f"row count changed: expected {expected_rows}, got {len(rows)}")
    return messages


def run_name_mol(args: argparse.Namespace) -> int:
    paper_folder = absolute_path(args.paper_folder)
    repo_root = absolute_path(args.repo_root)
    extraction_dir = absolute_path(args.extraction_dir) if args.extraction_dir else paper_folder / "SMILES_Extraction_Results" / "no_agent_image_test"
    input_csv = absolute_path(args.input_csv) if args.input_csv else extraction_dir / "no_agent_image_extraction.csv"
    output_csv = absolute_path(args.output_csv) if args.output_csv else extraction_dir / "name_mol_agent_review.csv"
    output_json = absolute_path(args.output_json) if args.output_json else extraction_dir / "name_mol_agent_review.json"

    if not paper_folder.exists():
        print(f"[ERROR] paper folder not found: {paper_folder}", file=sys.stderr)
        return 2
    if not repo_root.exists():
        print(f"[ERROR] repo root not found: {repo_root}", file=sys.stderr)
        return 2
    if not input_csv.exists():
        print(f"[ERROR] input CSV not found: {input_csv}", file=sys.stderr)
        return 2

    fieldnames, all_rows = read_csv_rows(input_csv)
    selected_rows = select_rows(all_rows, args.start_row, args.max_rows)
    augmented_fieldnames = append_agent_columns(fieldnames)
    seeded_rows = seed_agent_columns(selected_rows)

    output_csv.parent.mkdir(parents=True, exist_ok=True)
    agent_dir = extraction_dir / "name_mol_agent"
    agent_dir.mkdir(parents=True, exist_ok=True)

    write_csv_rows(output_csv, augmented_fieldnames, seeded_rows)
    write_json(output_json, seeded_rows)

    context_manifest = {
        "paper_folder": str(paper_folder),
        "repo_root": str(repo_root),
        "extraction_dir": str(extraction_dir),
        "input_csv": str(input_csv),
        "output_csv": str(output_csv),
        "output_json": str(output_json),
        "total_input_rows": len(all_rows),
        "selected_rows": len(selected_rows),
        "context_files": discover_context_files(paper_folder, extraction_dir),
    }
    manifest_path = agent_dir / "name_mol_context_manifest.json"
    write_json(manifest_path, context_manifest)

    task_path = create_agent_task(
        paper_folder=paper_folder,
        repo_root=repo_root,
        extraction_dir=extraction_dir,
        input_csv=input_csv,
        output_csv=output_csv,
        output_json=output_json,
        manifest_path=manifest_path,
        selected_rows=selected_rows,
        total_rows=len(all_rows),
    )

    summary = {
        "paper_folder": str(paper_folder),
        "repo_root": str(repo_root),
        "extraction_dir": str(extraction_dir),
        "input_csv": str(input_csv),
        "output_csv": str(output_csv),
        "output_json": str(output_json),
        "manifest_path": str(manifest_path),
        "task_path": str(task_path),
        "run_agent": args.run_agent,
        "agent_command": "",
        "agent_log": "",
        "agent_return_code": None,
        "validation_messages": [],
        "errors": [],
    }

    if args.run_agent:
        command = format_agent_command(
            args.agent_command,
            repo_root=repo_root,
            paper_folder=paper_folder,
            extraction_dir=extraction_dir,
        )
        log_path = agent_dir / f"name_mol_agent_{int(time.time())}.log"
        summary["agent_command"] = command
        summary["agent_log"] = str(log_path)

        print("[INFO] Name-Mol seeded output created")
        print(f"[INFO] input CSV : {input_csv}")
        print(f"[INFO] output CSV: {output_csv}")
        print(f"[INFO] task      : {task_path}")
        print(f"[INFO] manifest  : {manifest_path}")
        print("[INFO] starting external agent")

        try:
            prompt = task_path.read_text(encoding="utf-8")
            return_code = run_agent(
                command,
                prompt,
                cwd=repo_root,
                log_path=log_path,
                stream=args.stream_agent_output,
                timeout_seconds=args.agent_timeout_seconds,
            )
            summary["agent_return_code"] = return_code
        except Exception as exc:
            summary["errors"].append(
                {
                    "stage": "agent_run",
                    "error": str(exc),
                    "traceback": traceback.format_exc(),
                }
            )
    else:
        print("[INFO] agent execution disabled; seeded output and task were created only")

    validation_messages = validate_output_csv(output_csv, augmented_fieldnames, len(selected_rows))
    summary["validation_messages"] = validation_messages
    summary_path = agent_dir / "name_mol_summary.json"
    write_json(summary_path, summary)

    print("\n[DONE]")
    print(f"INPUT CSV : {input_csv}")
    print(f"OUTPUT CSV: {output_csv}")
    print(f"OUTPUT JSON: {output_json}")
    print(f"TASK     : {task_path}")
    print(f"MANIFEST : {manifest_path}")
    print(f"SUMMARY  : {summary_path}")
    if summary.get("agent_log"):
        print(f"AGENT LOG: {summary['agent_log']}")
    if validation_messages:
        print(f"[WARN] validation messages: {validation_messages}")

    return 0 if not validation_messages else 1


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run agent-only molecule naming/review for image-extracted SMILES CSV."
    )
    parser.add_argument("--paper-folder", default="")
    parser.add_argument("--repo-root", default="")
    parser.add_argument("--extraction-dir", default="")
    parser.add_argument("--input-csv", default="")
    parser.add_argument("--output-csv", default="")
    parser.add_argument("--output-json", default="")
    parser.add_argument("--max-rows", type=int, default=None)
    parser.add_argument("--start-row", type=int, default=None)
    parser.add_argument("--run-agent", action="store_true", default=None)
    parser.add_argument("--no-agent", action="store_true")
    parser.add_argument("--agent-command", default="")
    parser.add_argument("--stream-agent-output", action="store_true", default=None)
    parser.add_argument("--agent-timeout-seconds", type=int, default=None)

    args = parser.parse_args(argv)

    if USE_LOCAL_TEST_CONFIG:
        if not args.paper_folder:
            args.paper_folder = LOCAL_TEST_PAPER_FOLDER
        if not args.repo_root:
            args.repo_root = LOCAL_TEST_REPO_ROOT
        if not args.extraction_dir:
            args.extraction_dir = LOCAL_TEST_EXTRACTION_DIR
        if not args.input_csv:
            args.input_csv = LOCAL_TEST_INPUT_CSV
        if not args.output_csv:
            args.output_csv = LOCAL_TEST_OUTPUT_CSV
        if not args.output_json:
            args.output_json = LOCAL_TEST_OUTPUT_JSON
        if args.max_rows is None:
            args.max_rows = LOCAL_TEST_MAX_ROWS
        if args.start_row is None:
            args.start_row = LOCAL_TEST_START_ROW
        if args.run_agent is None:
            args.run_agent = RUN_AGENT
        if args.no_agent:
            args.run_agent = False
        if not args.agent_command:
            args.agent_command = LOCAL_AGENT_COMMAND
        if args.stream_agent_output is None:
            args.stream_agent_output = LOCAL_AGENT_STREAM_OUTPUT
        if args.agent_timeout_seconds is None:
            args.agent_timeout_seconds = LOCAL_AGENT_TIMEOUT_SECONDS
    else:
        if not args.paper_folder:
            parser.error("--paper-folder is required unless USE_LOCAL_TEST_CONFIG=True")
        if not args.repo_root:
            args.repo_root = str(Path(__file__).resolve().parents[1])
        if args.max_rows is None:
            args.max_rows = 0
        if args.start_row is None:
            args.start_row = 1
        if args.run_agent is None:
            args.run_agent = not args.no_agent
        if not args.agent_command:
            args.agent_command = LOCAL_AGENT_COMMAND
        if args.stream_agent_output is None:
            args.stream_agent_output = False
        if args.agent_timeout_seconds is None:
            args.agent_timeout_seconds = LOCAL_AGENT_TIMEOUT_SECONDS

    return args


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    return run_name_mol(args)


if __name__ == "__main__":
    raise SystemExit(main())