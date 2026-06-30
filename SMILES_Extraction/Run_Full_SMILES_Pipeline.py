#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Run the full image-SMILES pipeline.

Pipeline:
  1. SMILES_From_Image.py: DECIMER/MolScribe extraction from all selected images
  2. Name-Mol.py: agent-based molecule/name review for all extracted rows

This wrapper intentionally runs the full dataset by default:
  - SMILES_From_Image.py gets --max-images 0
  - Name-Mol.py gets --max-rows 0
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Sequence


SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent

DEFAULT_PAPER_FOLDER = "/Users/kogeon/Google Drive/내 드라이브/EXTRACT-TEST/QS_2026_3"
DEFAULT_MARKER_DIRS = "41565_2025_2102_MOESM1_ESM,QS_2026"
DEFAULT_DEVICE = "cpu"
DEFAULT_MOLSCRIBE_PYTHON = "/Users/kogeon/miniconda3/envs/mol_annotator_mac/bin/python"

# -----------------------------------------------------------------------------
# Local run configuration
# -----------------------------------------------------------------------------
# Edit this block when you want to run the full pipeline without typing CLI args:
#
#   python SMILES_Extraction/Run_Full_SMILES_Pipeline.py
#
# Command-line arguments still override these values.
USE_LOCAL_RUN_CONFIG = True

LOCAL_RUN_CONFIG = {
    "paper_folder": DEFAULT_PAPER_FOLDER,
    "repo_root": str(REPO_ROOT),
    "output_dir": "",  # blank -> <paper-folder>/SMILES_Extraction_Results/no_agent_image_test
    "marker_dirs": DEFAULT_MARKER_DIRS,
    "include_rendered_pages": False,
    "recursive_fallback": True,
    "device": DEFAULT_DEVICE,
    "no_expand": False,
    "start_index": 1,
    "start_row": 1,
    "image_python": DEFAULT_MOLSCRIBE_PYTHON,
    "name_mol_python": sys.executable,
    "no_agent": False,
    "agent_command": "",
    "stream_output": True,
    "stream_agent_output": True,
    "agent_timeout_seconds": 0,
}


def absolute_path(path: str | Path) -> Path:
    return Path(os.path.abspath(os.fspath(Path(path).expanduser())))


def run_command(command: list[str], *, cwd: Path, log_path: Path, stream: bool) -> int:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("w", encoding="utf-8", errors="replace") as log:
        log.write("command: " + " ".join(command) + "\n")
        log.write(f"cwd: {cwd}\n")
        log.write("===== BEGIN OUTPUT =====\n")

    process = subprocess.Popen(
        command,
        cwd=str(cwd),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
    )

    assert process.stdout is not None
    for line in process.stdout:
        with log_path.open("a", encoding="utf-8", errors="replace") as log:
            log.write(line)
        if stream:
            print(line, end="")

    return_code = process.wait()
    with log_path.open("a", encoding="utf-8", errors="replace") as log:
        log.write("===== END OUTPUT =====\n")
        log.write(f"return_code: {return_code}\n")
    return return_code


def build_image_command(args: argparse.Namespace, extraction_dir: Path) -> list[str]:
    command = [
        args.image_python,
        str(SCRIPT_DIR / "SMILES_From_Image.py"),
        "--paper-folder",
        str(args.paper_folder),
        "--repo-root",
        str(args.repo_root),
        "--output-dir",
        str(extraction_dir),
        "--max-images",
        "0",
        "--start-index",
        str(args.start_index),
        "--marker-dirs",
        args.marker_dirs,
        "--device",
        args.device,
    ]
    if args.include_rendered_pages:
        command.append("--include-rendered-pages")
    if args.recursive_fallback:
        command.append("--recursive-fallback")
    if args.no_expand:
        command.append("--no-expand")
    return command


def build_name_mol_command(args: argparse.Namespace, extraction_dir: Path, input_csv: Path, output_csv: Path, output_json: Path) -> list[str]:
    command = [
        args.name_mol_python,
        str(SCRIPT_DIR / "Name-Mol.py"),
        "--paper-folder",
        str(args.paper_folder),
        "--repo-root",
        str(args.repo_root),
        "--extraction-dir",
        str(extraction_dir),
        "--input-csv",
        str(input_csv),
        "--output-csv",
        str(output_csv),
        "--output-json",
        str(output_json),
        "--max-rows",
        "0",
        "--start-row",
        str(args.start_row),
    ]
    if args.no_agent:
        command.append("--no-agent")
    else:
        command.append("--run-agent")
    if args.agent_command:
        command.extend(["--agent-command", args.agent_command])
    if args.stream_agent_output:
        command.append("--stream-agent-output")
    if args.agent_timeout_seconds:
        command.extend(["--agent-timeout-seconds", str(args.agent_timeout_seconds)])
    return command


def write_summary(path: Path, summary: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    defaults = LOCAL_RUN_CONFIG if USE_LOCAL_RUN_CONFIG else {
        "paper_folder": DEFAULT_PAPER_FOLDER,
        "repo_root": str(REPO_ROOT),
        "output_dir": "",
        "marker_dirs": DEFAULT_MARKER_DIRS,
        "include_rendered_pages": False,
        "recursive_fallback": True,
        "device": DEFAULT_DEVICE,
        "no_expand": False,
        "start_index": 1,
        "start_row": 1,
        "image_python": DEFAULT_MOLSCRIBE_PYTHON,
        "name_mol_python": sys.executable,
        "no_agent": False,
        "agent_command": "",
        "stream_output": False,
        "stream_agent_output": False,
        "agent_timeout_seconds": 0,
    }

    parser = argparse.ArgumentParser(description="Run full SMILES image extraction and Name-Mol review pipeline.")
    parser.add_argument("--paper-folder", default=defaults["paper_folder"], help="Paper folder to process.")
    parser.add_argument("--repo-root", default=defaults["repo_root"], help="Repository root.")
    parser.add_argument(
        "--output-dir",
        default=defaults["output_dir"],
        help="Extraction output directory. Default: <paper-folder>/SMILES_Extraction_Results/no_agent_image_test.",
    )
    parser.add_argument("--marker-dirs", default=defaults["marker_dirs"])
    parser.add_argument("--include-rendered-pages", action="store_true", default=defaults["include_rendered_pages"])
    parser.add_argument("--recursive-fallback", action="store_true", default=defaults["recursive_fallback"])
    parser.add_argument("--no-recursive-fallback", action="store_false", dest="recursive_fallback")
    parser.add_argument("--device", default=defaults["device"], choices=["cpu", "cuda"])
    parser.add_argument("--no-expand", action="store_true", default=defaults["no_expand"])
    parser.add_argument("--start-index", type=int, default=defaults["start_index"], help="1-based image start index.")
    parser.add_argument("--start-row", type=int, default=defaults["start_row"], help="1-based Name-Mol row start.")
    parser.add_argument("--image-python", default=defaults["image_python"], help="Python executable for SMILES_From_Image.py.")
    parser.add_argument("--name-mol-python", default=defaults["name_mol_python"], help="Python executable for Name-Mol.py.")
    parser.add_argument("--no-agent", action="store_true", default=defaults["no_agent"], help="Create Name-Mol seeded output/task only; do not run external agent.")
    parser.add_argument("--agent-command", default=defaults["agent_command"], help="Override Name-Mol agent command.")
    parser.add_argument("--stream-output", action="store_true", default=defaults["stream_output"], help="Stream wrapper subprocess output.")
    parser.add_argument("--stream-agent-output", action="store_true", default=defaults["stream_agent_output"], help="Ask Name-Mol to stream external agent output.")
    parser.add_argument("--agent-timeout-seconds", type=int, default=defaults["agent_timeout_seconds"])
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    args.paper_folder = absolute_path(args.paper_folder)
    args.repo_root = absolute_path(args.repo_root)

    extraction_dir = absolute_path(args.output_dir) if args.output_dir else args.paper_folder / "SMILES_Extraction_Results" / "no_agent_image_test"
    input_csv = extraction_dir / "no_agent_image_extraction.csv"
    name_mol_csv = extraction_dir / "name_mol_agent_review.csv"
    name_mol_json = extraction_dir / "name_mol_agent_review.json"
    pipeline_dir = extraction_dir / "full_pipeline"
    summary_path = pipeline_dir / "full_smiles_pipeline_summary.json"

    summary: dict[str, Any] = {
        "paper_folder": str(args.paper_folder),
        "repo_root": str(args.repo_root),
        "extraction_dir": str(extraction_dir),
        "input_csv": str(input_csv),
        "name_mol_csv": str(name_mol_csv),
        "name_mol_json": str(name_mol_json),
        "started_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "steps": [],
    }

    if not args.paper_folder.exists():
        print(f"[ERROR] paper folder not found: {args.paper_folder}", file=sys.stderr)
        summary["error"] = "paper folder not found"
        write_summary(summary_path, summary)
        return 2
    if not args.repo_root.exists():
        print(f"[ERROR] repo root not found: {args.repo_root}", file=sys.stderr)
        summary["error"] = "repo root not found"
        write_summary(summary_path, summary)
        return 2

    image_command = build_image_command(args, extraction_dir)
    image_log = pipeline_dir / "01_smiles_from_image.log"
    print("[STEP 1/2] Running SMILES_From_Image.py on all selected images")
    print(" ".join(image_command))
    rc1 = run_command(image_command, cwd=args.repo_root, log_path=image_log, stream=args.stream_output)
    summary["steps"].append({"name": "SMILES_From_Image", "return_code": rc1, "log": str(image_log)})
    write_summary(summary_path, summary)
    if rc1 != 0:
        print(f"[ERROR] SMILES_From_Image.py failed with return code {rc1}", file=sys.stderr)
        return rc1
    if not input_csv.exists():
        print(f"[ERROR] expected extraction CSV missing: {input_csv}", file=sys.stderr)
        summary["error"] = "expected extraction CSV missing"
        write_summary(summary_path, summary)
        return 1

    name_command = build_name_mol_command(args, extraction_dir, input_csv, name_mol_csv, name_mol_json)
    name_log = pipeline_dir / "02_name_mol.log"
    print("[STEP 2/2] Running Name-Mol.py on all extracted rows")
    print(" ".join(name_command))
    rc2 = run_command(name_command, cwd=args.repo_root, log_path=name_log, stream=args.stream_output)
    summary["steps"].append({"name": "Name-Mol", "return_code": rc2, "log": str(name_log)})
    summary["finished_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    write_summary(summary_path, summary)
    if rc2 != 0:
        print(f"[ERROR] Name-Mol.py failed with return code {rc2}", file=sys.stderr)
        return rc2

    print("\n[DONE] Full SMILES pipeline complete")
    print(f"Extraction CSV : {input_csv}")
    print(f"Name-Mol CSV   : {name_mol_csv}")
    print(f"Name-Mol JSON  : {name_mol_json}")
    print(f"Summary        : {summary_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
