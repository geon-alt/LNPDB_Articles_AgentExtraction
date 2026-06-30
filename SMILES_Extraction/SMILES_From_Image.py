

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Run image-based molecular extraction without any external LLM/agent stage.

This script directly runs:
  1. DECIMER segmentation via FromImage/mol_annotator/segmentation.py
  2. MolScribe recognition via FromImage/mol_annotator/recognition.py
  3. crop image saving
  4. CSV/JSON summary output

It is intended for debugging whether segmentation/recognition works before
connecting the results to the agent lineage/name-matching stage.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import traceback
from pathlib import Path
from typing import Any, Dict, Iterable, List, Sequence

import numpy as np
from PIL import Image


IMAGE_SUFFIXES = {".jpeg", ".jpg", ".png", ".tif", ".tiff", ".bmp", ".webp"}
DEFAULT_MARKER_DIR_NAMES = ("41565_2025_2102_MOESM1_ESM", "QS_2026")

# -----------------------------------------------------------------------------
# Local test configuration
# -----------------------------------------------------------------------------
# Edit these values directly when you want to run this script without CLI args.
# Example:
#   python SMILES_Extraction/image_extraction_no_agent.py
USE_LOCAL_TEST_CONFIG = True

LOCAL_TEST_PAPER_FOLDER = "/Users/kogeon/Google Drive/내 드라이브/EXTRACT-TEST/QS_2026_3"
LOCAL_TEST_REPO_ROOT = "/Users/kogeon/python_projects_path/LNPDB_Articles_AgentExtraction"
LOCAL_TEST_OUTPUT_DIR = ""  # blank -> <paper-folder>/SMILES_Extraction_Results/no_agent_image_test
LOCAL_TEST_MAX_IMAGES = 20
LOCAL_TEST_START_INDEX = 1
LOCAL_TEST_MARKER_DIRS = "41565_2025_2102_MOESM1_ESM,QS_2026"
LOCAL_TEST_INCLUDE_RENDERED_PAGES = False
LOCAL_TEST_RECURSIVE_FALLBACK = True
LOCAL_TEST_DEVICE = "cpu"
LOCAL_TEST_NO_EXPAND = False
LOCAL_TEST_PYTHON_EXECUTABLE = "/Users/kogeon/miniconda3/envs/mol_annotator_mac/bin/python"
AUTO_REEXEC_WITH_LOCAL_PYTHON = True


OUTPUT_COLUMNS = [
    "image_index",
    "image_path",
    "image_name",
    "image_source_kind",
    "crop_index",
    "crop_path",
    "bbox_y0",
    "bbox_x0",
    "bbox_y1",
    "bbox_x1",
    "smiles",
    "status",
    "error",
]


def absolute_path(path: str | Path) -> Path:
    return Path(os.path.abspath(os.fspath(Path(path).expanduser())))


def same_python_executable(current: Path, target: Path) -> bool:
    try:
        return current.resolve() == target.resolve()
    except Exception:
        return os.path.abspath(os.fspath(current)) == os.path.abspath(os.fspath(target))


def maybe_reexec_with_local_python() -> None:
    """Restart this script with LOCAL_TEST_PYTHON_EXECUTABLE when requested.

    This keeps the script runnable as:
        python SMILES_Extraction/image_extraction_no_agent.py

    while ensuring that the actual segmentation/recognition run happens under
    the MolScribe/DECIMER environment Python.
    """
    if not USE_LOCAL_TEST_CONFIG or not AUTO_REEXEC_WITH_LOCAL_PYTHON:
        return

    target_text = str(LOCAL_TEST_PYTHON_EXECUTABLE or "").strip()
    if not target_text:
        return

    if os.environ.get("IMAGE_EXTRACTION_NO_AGENT_REEXEC") == "1":
        return

    target_python = absolute_path(target_text)
    if not target_python.exists():
        print(f"[WARN] LOCAL_TEST_PYTHON_EXECUTABLE not found: {target_python}", file=sys.stderr)
        return

    current_python = absolute_path(sys.executable)
    if same_python_executable(current_python, target_python):
        return

    os.environ["IMAGE_EXTRACTION_NO_AGENT_REEXEC"] = "1"
    cmd = [str(target_python), os.fspath(Path(__file__).resolve()), *sys.argv[1:]]
    print(f"[INFO] re-executing with local Python: {target_python}")
    os.execv(str(target_python), cmd)


def add_mol_annotator_to_path(repo_root: Path) -> Path:
    mol_dir = repo_root / "SMILES_Extraction" / "FromImage" / "mol_annotator"
    if not mol_dir.exists():
        raise FileNotFoundError(
            f"mol_annotator directory not found: {mol_dir}\n"
            "Expected files: segmentation.py and recognition.py under "
            "SMILES_Extraction/FromImage/mol_annotator/."
        )
    sys.path.insert(0, str(mol_dir))
    return mol_dir


def iter_images_in_dir(folder: Path) -> Iterable[Path]:
    if not folder.exists() or not folder.is_dir():
        return []
    return sorted(p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in IMAGE_SUFFIXES)


def infer_source_kind(path: Path, paper_folder: Path) -> str:
    pages_dir = paper_folder / "SMILES_Extraction_Results" / "image_candidates" / "pages"
    try:
        path.relative_to(pages_dir)
        return "rendered_pdf_page"
    except ValueError:
        pass

    if path.name.lower().startswith("_page_"):
        return "marker_image"
    return "image"


def collect_images(
    paper_folder: Path,
    marker_dirs: Sequence[str],
    include_rendered_pages: bool,
    recursive_fallback: bool,
) -> List[Path]:
    images: List[Path] = []

    # Prefer marker-rendered figure/picture images, because full PDF pages often
    # contain too much unrelated text and are harder for DECIMER segmentation.
    for dirname in marker_dirs:
        images.extend(iter_images_in_dir(paper_folder / dirname))

    if include_rendered_pages:
        pages_dir = paper_folder / "SMILES_Extraction_Results" / "image_candidates" / "pages"
        images.extend(sorted(pages_dir.glob("*.png")) if pages_dir.exists() else [])

    if recursive_fallback and not images:
        images.extend(sorted(p for p in paper_folder.rglob("*") if p.is_file() and p.suffix.lower() in IMAGE_SUFFIXES))

    unique: List[Path] = []
    seen: set[str] = set()
    for image in images:
        key = os.fspath(image)
        if key in seen:
            continue
        seen.add(key)
        unique.append(image)
    return unique


def safe_crop_filename(image_index: int, crop_index: int, image_path: Path) -> str:
    stem = "".join(ch if ch.isalnum() or ch in ("-", "_", ".") else "_" for ch in image_path.stem)
    stem = stem[:80] or "image"
    return f"img{image_index:03d}_crop{crop_index:03d}_{stem}.png"


def write_csv(path: Path, rows: Sequence[Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=OUTPUT_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({col: "" if row.get(col) is None else row.get(col, "") for col in OUTPUT_COLUMNS})


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def run_extraction(args: argparse.Namespace) -> int:
    repo_root = absolute_path(args.repo_root)
    paper_folder = absolute_path(args.paper_folder)
    output_dir = absolute_path(args.output_dir) if args.output_dir else paper_folder / "SMILES_Extraction_Results" / "no_agent_image_test"
    crop_dir = output_dir / "crops"

    if not paper_folder.exists():
        print(f"[ERROR] paper folder not found: {paper_folder}", file=sys.stderr)
        return 2

    mol_dir = add_mol_annotator_to_path(repo_root)

    try:
        from segmentation import segment_with_bboxes  # type: ignore
        from recognition import load_molscribe, predict_smiles_batch  # type: ignore
    except Exception as exc:
        print(f"[ERROR] failed to import segmentation/recognition from {mol_dir}: {exc}", file=sys.stderr)
        return 2

    output_dir.mkdir(parents=True, exist_ok=True)
    crop_dir.mkdir(parents=True, exist_ok=True)

    marker_dirs = [x.strip() for x in args.marker_dirs.split(",") if x.strip()]
    images = collect_images(
        paper_folder=paper_folder,
        marker_dirs=marker_dirs,
        include_rendered_pages=args.include_rendered_pages,
        recursive_fallback=args.recursive_fallback,
    )

    if args.start_index < 1:
        print("[ERROR] --start-index must be >= 1", file=sys.stderr)
        return 2

    start_zero = args.start_index - 1
    if args.max_images is not None and args.max_images > 0:
        images = images[start_zero : start_zero + args.max_images]
    else:
        images = images[start_zero:]

    summary: Dict[str, Any] = {
        "repo_root": str(repo_root),
        "paper_folder": str(paper_folder),
        "mol_annotator_dir": str(mol_dir),
        "output_dir": str(output_dir),
        "crop_dir": str(crop_dir),
        "device": args.device,
        "selected_image_count": len(images),
        "total_segment_count": 0,
        "total_bbox_count": 0,
        "total_smiles_count": 0,
        "total_crop_files": 0,
        "errors": [],
    }

    print(f"[INFO] repo_root : {repo_root}")
    print(f"[INFO] paper     : {paper_folder}")
    print(f"[INFO] mol_dir   : {mol_dir}")
    print(f"[INFO] output    : {output_dir}")
    print(f"[INFO] crop_dir  : {crop_dir}")
    print(f"[INFO] images    : {len(images)}")

    if not images:
        print("[ERROR] no image files were selected.", file=sys.stderr)
        write_json(output_dir / "no_agent_image_extraction_summary.json", summary)
        return 1

    for i, image_path in enumerate(images, start=1):
        print(f"  [{i:03d}] {image_path}")

    print(f"[INFO] loading MolScribe model on device={args.device!r} ...")
    try:
        model = load_molscribe(device=args.device)
    except Exception as exc:
        summary["errors"].append({"stage": "load_molscribe", "error": str(exc), "traceback": traceback.format_exc()})
        write_json(output_dir / "no_agent_image_extraction_summary.json", summary)
        print(f"[ERROR] MolScribe model load failed: {exc}", file=sys.stderr)
        return 1
    print("[INFO] MolScribe loaded")

    rows: List[Dict[str, Any]] = []

    for image_index, image_path in enumerate(images, start=1):
        source_kind = infer_source_kind(image_path, paper_folder)
        print(f"\n[IMAGE {image_index}/{len(images)}] {image_path.name} ({source_kind})")

        try:
            pil_img = Image.open(image_path)
            image_array = np.array(pil_img)
            print(f"  image mode/size: {pil_img.mode} {pil_img.size}")

            segments, bboxes = segment_with_bboxes(image_array, expand=not args.no_expand)
            print(f"  segments/bboxes: {len(segments)} / {len(bboxes)}")

            if not segments:
                rows.append(
                    {
                        "image_index": image_index,
                        "image_path": str(image_path),
                        "image_name": image_path.name,
                        "image_source_kind": source_kind,
                        "status": "no_bbox",
                    }
                )
                continue

            smiles_list = predict_smiles_batch(model, segments)

            summary["total_segment_count"] += len(segments)
            summary["total_bbox_count"] += len(bboxes)
            summary["total_smiles_count"] += sum(1 for smiles in smiles_list if str(smiles).strip())

            for crop_index, (segment, bbox) in enumerate(zip(segments, bboxes), start=1):
                bbox_values = [int(v) for v in bbox]
                y0, x0, y1, x1 = bbox_values
                crop_path = crop_dir / safe_crop_filename(image_index, crop_index, image_path)
                Image.fromarray(segment).save(crop_path)
                summary["total_crop_files"] += 1

                smiles = smiles_list[crop_index - 1] if crop_index - 1 < len(smiles_list) else ""
                status = "ok" if str(smiles).strip() else "bbox_no_smiles"

                print(f"    crop {crop_index}: bbox=({y0},{x0},{y1},{x1}) smiles={smiles}")

                rows.append(
                    {
                        "image_index": image_index,
                        "image_path": str(image_path),
                        "image_name": image_path.name,
                        "image_source_kind": source_kind,
                        "crop_index": crop_index,
                        "crop_path": str(crop_path),
                        "bbox_y0": y0,
                        "bbox_x0": x0,
                        "bbox_y1": y1,
                        "bbox_x1": x1,
                        "smiles": smiles,
                        "status": status,
                        "error": "",
                    }
                )

        except Exception as exc:
            print(f"  [ERROR] {exc}")
            summary["errors"].append(
                {
                    "image_path": str(image_path),
                    "error": str(exc),
                    "traceback": traceback.format_exc(),
                }
            )
            rows.append(
                {
                    "image_index": image_index,
                    "image_path": str(image_path),
                    "image_name": image_path.name,
                    "image_source_kind": source_kind,
                    "status": "error",
                    "error": str(exc),
                }
            )

    csv_path = output_dir / "no_agent_image_extraction.csv"
    json_path = output_dir / "no_agent_image_extraction.json"
    summary_path = output_dir / "no_agent_image_extraction_summary.json"

    write_csv(csv_path, rows)
    write_json(json_path, rows)
    write_json(summary_path, summary)

    print("\n[DONE]")
    print(f"CSV     : {csv_path}")
    print(f"JSON    : {json_path}")
    print(f"SUMMARY : {summary_path}")
    print(f"CROPS   : {crop_dir}")
    print(f"total_bbox_count   : {summary['total_bbox_count']}")
    print(f"total_smiles_count : {summary['total_smiles_count']}")
    print(f"total_crop_files   : {summary['total_crop_files']}")

    return 0


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run image-based DECIMER/MolScribe extraction without external agent."
    )
    parser.add_argument(
        "--paper-folder",
        default="",
        help="Paper folder containing marker images and/or rendered pages.",
    )
    parser.add_argument(
        "--repo-root",
        default="",
        help="Repository root. Default: parent of SMILES_Extraction.",
    )
    parser.add_argument(
        "--output-dir",
        default="",
        help="Output directory. Default: <paper-folder>/SMILES_Extraction_Results/no_agent_image_test.",
    )
    parser.add_argument("--max-images", type=int, default=None, help="Maximum number of images to process. Use 0 for all images.")
    parser.add_argument("--start-index", type=int, default=None, help="1-based start index after image collection.")
    parser.add_argument(
        "--marker-dirs",
        default="",
        help="Comma-separated marker image subdirectories to scan first.",
    )
    parser.add_argument(
        "--include-rendered-pages",
        action="store_true",
        default=None,
        help="Also include <paper>/SMILES_Extraction_Results/image_candidates/pages/*.png after marker images.",
    )
    parser.add_argument(
        "--recursive-fallback",
        action="store_true",
        default=None,
        help="If no marker/rendered images are found, recursively search the paper folder for image files.",
    )
    parser.add_argument("--device", default="", choices=["", "cpu", "cuda"], help="MolScribe device.")
    parser.add_argument("--no-expand", action="store_true", default=None, help="Disable DECIMER expanded masks.")

    parsed = parser.parse_args(argv)

    # When no CLI values are supplied, use the editable constants near the top
    # of this file. CLI values still override the local constants.
    if USE_LOCAL_TEST_CONFIG:
        if not parsed.paper_folder:
            parsed.paper_folder = LOCAL_TEST_PAPER_FOLDER
        if not parsed.repo_root:
            parsed.repo_root = LOCAL_TEST_REPO_ROOT
        if not parsed.output_dir:
            parsed.output_dir = LOCAL_TEST_OUTPUT_DIR
        if parsed.max_images is None:
            parsed.max_images = LOCAL_TEST_MAX_IMAGES
        if parsed.start_index is None:
            parsed.start_index = LOCAL_TEST_START_INDEX
        if not parsed.marker_dirs:
            parsed.marker_dirs = LOCAL_TEST_MARKER_DIRS
        if parsed.include_rendered_pages is None:
            parsed.include_rendered_pages = LOCAL_TEST_INCLUDE_RENDERED_PAGES
        if parsed.recursive_fallback is None:
            parsed.recursive_fallback = LOCAL_TEST_RECURSIVE_FALLBACK
        if not parsed.device:
            parsed.device = LOCAL_TEST_DEVICE
        if parsed.no_expand is None:
            parsed.no_expand = LOCAL_TEST_NO_EXPAND
    else:
        if not parsed.paper_folder:
            parser.error("--paper-folder is required unless USE_LOCAL_TEST_CONFIG=True")
        if not parsed.repo_root:
            parsed.repo_root = str(Path(__file__).resolve().parents[1])
        if parsed.max_images is None:
            parsed.max_images = 20
        if parsed.start_index is None:
            parsed.start_index = 1
        if not parsed.marker_dirs:
            parsed.marker_dirs = ",".join(DEFAULT_MARKER_DIR_NAMES)
        if parsed.include_rendered_pages is None:
            parsed.include_rendered_pages = False
        if parsed.recursive_fallback is None:
            parsed.recursive_fallback = False
        if not parsed.device:
            parsed.device = "cpu"
        if parsed.no_expand is None:
            parsed.no_expand = False

    return parsed


def main(argv: Sequence[str] | None = None) -> int:
    maybe_reexec_with_local_python()
    args = parse_args(argv)
    print(f"[INFO] active Python: {sys.executable}")
    return run_extraction(args)


if __name__ == "__main__":
    raise SystemExit(main())
