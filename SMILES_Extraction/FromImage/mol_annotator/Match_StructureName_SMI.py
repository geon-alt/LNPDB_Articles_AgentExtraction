import json
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import cv2
import fitz  # PyMuPDF
import numpy as np
import pandas as pd
from PIL import Image, ImageDraw, ImageFont
from google.genai import types

try:
    from rdkit import Chem
    from rdkit.Chem import Draw
except Exception:
    Chem = None
    Draw = None

CURRENT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = CURRENT_DIR.parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from find_api import find_api_key_file, get_vertexai_client
from LLM_API import generate_content_with_guard
from LLM_Batch import (
    append_batch_request,
    build_batch_request_metadata,
    build_generate_content_batch_request,
    count_requests_in_jsonl,
    create_batch_job_record,
    create_batch_request_file,
    download_batch_results,
    load_batch_results_as_map,
    poll_batch_job,
    submit_batch_job,
)
from pdf_annotator import bbox_png_to_pdf

DEFAULT_GCS_BATCH_BUCKET = "gs://lnpdb-articles-extraction-batch-results-geon"
PAGE_KEYS = {"page", "page_num", "page_number", "pdf_page", "source_page"}
SOURCE_FILE_KEYS = {
    "image_file",
    "image_path",
    "crop_path",
    "panel_path",
    "source_image",
    "file",
    "filename",
}
PAGE_NUMBER_PATTERNS = [
    re.compile(r"(?:^|[\\/ _\-\s])page[_\-\s]?0*(\d+)(?:\D|$)", re.IGNORECASE),
    re.compile(r"(?:^|[\\/ _\-\s])p0*(\d+)(?:\D|$)", re.IGNORECASE),
]


def call_mol_worker(image_items, venv_python_path):
    worker_path = Path(__file__).resolve().parent / "worker_mol.py"

    normalized_items = []
    for item in image_items:
        if isinstance(item, dict):
            normalized_items.append(
                {
                    "path": str(item.get("path", "")),
                    "source_type": str(item.get("source_type", "pdf_page")),
                    "page_num": item.get("page_num"),
                }
            )
        else:
            normalized_items.append(
                {
                    "path": str(item),
                    "source_type": "pdf_page",
                    "page_num": None,
                }
            )

    with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".json", encoding="utf-8") as tf:
        json.dump(normalized_items, tf, ensure_ascii=False)
        temp_json_path = tf.name

    cmd = [str(venv_python_path), str(worker_path), str(temp_json_path)]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", shell=False)
        if result.returncode != 0:
            print(f"Worker error (code {result.returncode})")
            if result.stderr:
                print(f"  stderr: {result.stderr.strip()}")
            return []

        raw_output = result.stdout
        start_marker, end_marker = "JSON_START", "JSON_END"
        if start_marker in raw_output and end_marker in raw_output:
            json_str = raw_output.split(start_marker)[1].split(end_marker)[0].strip()
            return json.loads(json_str)
        return []
    except Exception as e:
        print(f"Worker exception: {e}")
        return []
    finally:
        if os.path.exists(temp_json_path):
            try:
                os.remove(temp_json_path)
            except OSError:
                pass


def get_image_part(file_path: Path):
    with open(file_path, "rb") as f:
        return types.Part.from_bytes(data=f.read(), mime_type="image/png")


def _safe_filename_token(value: str, max_len: int = 80) -> str:
    token = "".join(ch if ch.isalnum() or ch in ("-", "_", ".") else "_" for ch in str(value or ""))
    token = token.strip("_") or "NA"
    return token[:max_len]


def _load_default_font(size: int = 18):
    try:
        return ImageFont.truetype("Arial.ttf", size)
    except Exception:
        return ImageFont.load_default()


def smiles_to_rdkit_image(smiles: str, size=(420, 320)):
    canvas = Image.new("RGB", size, "white")
    draw = ImageDraw.Draw(canvas)
    font = _load_default_font(18)

    smiles = str(smiles or "").strip()
    if not smiles:
        draw.text((20, 20), "EMPTY SMILES", fill=(180, 0, 0), font=font)
        return canvas, "empty_smiles"

    if Chem is None or Draw is None:
        draw.text((20, 20), "RDKit import failed", fill=(180, 0, 0), font=font)
        return canvas, "rdkit_unavailable"

    try:
        mol = Chem.MolFromSmiles(smiles)
        if mol is None:
            draw.text((20, 20), "INVALID SMILES", fill=(180, 0, 0), font=font)
            draw.text((20, 55), smiles[:90], fill=(0, 0, 0), font=font)
            return canvas, "invalid_smiles"

        try:
            Chem.rdDepictor.Compute2DCoords(mol)
        except Exception:
            pass

        img = Draw.MolToImage(mol, size=size)
        if img.mode != "RGB":
            img = img.convert("RGB")
        return img, "valid"

    except Exception as e:
        draw.text((20, 20), "RDKit rendering error", fill=(180, 0, 0), font=font)
        draw.text((20, 55), str(e)[:90], fill=(0, 0, 0), font=font)
        return canvas, f"rdkit_error: {e}"


def save_structure_qc_panel(
    crop_path,
    smiles,
    qc_path,
    source_name,
    page_num,
    crop_index,
    structure_name,
    structure_type,
):
    qc_path = Path(qc_path)
    crop_path = Path(crop_path)
    qc_path.parent.mkdir(parents=True, exist_ok=True)

    max_w, max_h = 420, 320
    font_title = _load_default_font(20)
    font_body = _load_default_font(16)

    try:
        original = Image.open(crop_path).convert("RGB")
    except Exception:
        original = Image.new("RGB", (max_w, max_h), "white")
        d = ImageDraw.Draw(original)
        d.text((20, 20), "Original crop load failed", fill=(180, 0, 0), font=font_body)

    original.thumbnail((max_w, max_h), Image.LANCZOS)
    original_canvas = Image.new("RGB", (max_w, max_h), "white")
    ox = (max_w - original.width) // 2
    oy = (max_h - original.height) // 2
    original_canvas.paste(original, (ox, oy))

    rdkit_img, rdkit_status = smiles_to_rdkit_image(smiles, size=(max_w, max_h))

    margin = 24
    gap = 24
    header_h = 120
    text_h = 90
    panel_w = margin * 2 + max_w * 2 + gap
    panel_h = header_h + max_h + text_h + margin

    panel = Image.new("RGB", (panel_w, panel_h), "white")
    draw = ImageDraw.Draw(panel)

    page_label = f"page {page_num}" if page_num not in (None, "") else "marker image"
    title = f"QC #{crop_index + 1} | {source_name} | {page_label} | Name={structure_name} | Type={structure_type}"
    draw.text((margin, 18), title[:140], fill=(0, 0, 0), font=font_title)

    status_color = (0, 120, 0) if rdkit_status == "valid" else (180, 0, 0)
    draw.text((margin, 50), f"RDKit status: {rdkit_status}", fill=status_color, font=font_body)
    draw.text((margin, 78), "Left: original crop    Right: RDKit rendering from extracted SMILES", fill=(0, 0, 0), font=font_body)

    left_x = margin
    right_x = margin + max_w + gap
    img_y = header_h

    panel.paste(original_canvas, (left_x, img_y))
    panel.paste(rdkit_img, (right_x, img_y))

    draw.rectangle((left_x, img_y, left_x + max_w, img_y + max_h), outline=(0, 0, 0), width=2)
    draw.rectangle((right_x, img_y, right_x + max_w, img_y + max_h), outline=(0, 0, 0), width=2)

    draw.text((left_x, img_y + max_h + 10), "Original crop", fill=(0, 0, 0), font=font_body)
    draw.text((right_x, img_y + max_h + 10), "RDKit from SMILES", fill=(0, 0, 0), font=font_body)

    smiles_text = f"SMILES: {str(smiles or '').strip()}"
    draw.text((margin, img_y + max_h + 42), smiles_text[:180], fill=(0, 0, 0), font=font_body)

    panel.save(qc_path)
    return rdkit_status


def _sanitize_request_token(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in ("-", "_", ".") else "_" for ch in value)


def make_structure_lineage_custom_id(pdf_path: Path, page_num: int) -> str:
    return f"struct_lineage__{_sanitize_request_token(pdf_path.stem)}__page_{page_num:04d}"


def make_structure_lineage_custom_id_from_source(pdf_path: Path, source_type: str, source_name: str, page_num=None) -> str:
    source_token = _sanitize_request_token(Path(source_name).stem)
    if source_type == "pdf_page" and page_num is not None:
        return f"struct_lineage__{_sanitize_request_token(pdf_path.stem)}__page_{int(page_num):04d}"
    return f"struct_lineage__{_sanitize_request_token(pdf_path.stem)}__{_sanitize_request_token(source_type)}__{source_token}"


def find_marker_image_folder(pdf_path: Path) -> Path | None:
    candidate = pdf_path.parent / pdf_path.stem
    if candidate.exists() and candidate.is_dir():
        return candidate
    return None


def collect_marker_images(folder: Path) -> list[Path]:
    exts = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp"}
    return sorted([p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in exts])


def infer_page_number(value) -> int | None:
    if value is None:
        return None

    if isinstance(value, bool):
        return None

    if isinstance(value, int):
        return value if value > 0 else None

    if isinstance(value, float):
        if value.is_integer() and value > 0:
            return int(value)
        return None

    text = str(value or "").strip()
    if not text:
        return None

    if text.isdigit():
        page_num = int(text)
        return page_num if page_num > 0 else None

    for pattern in PAGE_NUMBER_PATTERNS:
        match = pattern.search(text)
        if match:
            page_num = int(match.group(1))
            if page_num > 0:
                return page_num

    return None


def is_pdf_source_value(value) -> bool:
    text = str(value or "").strip().lower()
    if not text:
        return False
    return Path(text).suffix.lower() == ".pdf"


def marker_name_tokens(value) -> set[str]:
    text = str(value or "").strip()
    if not text:
        return set()

    name = Path(text).name
    stem = Path(name).stem
    tokens = {name, stem}
    tokens.update({token.lower() for token in list(tokens)})
    return {token for token in tokens if token}


def load_allowed_sources_from_mapping(mapping_json_path: Path) -> tuple[set[int], set[str]]:
    mapping_json_path = Path(mapping_json_path)
    with open(mapping_json_path, "r", encoding="utf-8") as f:
        mapping_data = json.load(f)

    allowed_pages: set[int] = set()
    allowed_marker_images: set[str] = set()

    def visit(node):
        if isinstance(node, dict):
            for raw_key, value in node.items():
                key = str(raw_key).strip().lower()

                if key in PAGE_KEYS:
                    page_num = infer_page_number(value)
                    if page_num is not None:
                        allowed_pages.add(page_num)

                if key in SOURCE_FILE_KEYS:
                    page_num = infer_page_number(value)
                    if page_num is not None:
                        allowed_pages.add(page_num)

                    if not is_pdf_source_value(value):
                        allowed_marker_images.update(marker_name_tokens(value))

                visit(value)

        elif isinstance(node, list):
            for item in node:
                visit(item)

    visit(mapping_data)
    return allowed_pages, allowed_marker_images


def marker_image_allowed(marker_img: Path, allowed_marker_images: set[str]) -> bool:
    names = {marker_img.name, marker_img.stem, marker_img.name.lower(), marker_img.stem.lower()}
    return bool(names.intersection(allowed_marker_images))


def build_lineage_prompt(request_id: str) -> str:
    return f"""
request_id: {request_id}

You are analyzing chemistry figures from a scientific paper.
The first image is the source image, and the following images are cropped candidate structure regions from that image.

Classify each cropped region and respond with JSON only.

Rules:
1. Preserve the request_id exactly.
2. Output top-level JSON with keys request_id and results.
3. results must be a list in the same order as the crop images.
4. Each result object must contain Is_Structure, Type, and Name.
5. Type must be one of "Single", "Markush", "Combinatorial", or "Unknown".
6. Name should be the nearby label such as 1, 2, A1, B1. Use "N/A" if missing.

Return exactly this JSON shape:
{{
  "request_id": "{request_id}",
  "results": [
    {{
      "Is_Structure": true,
      "Type": "Single",
      "Name": "1"
    }}
  ]
}}
"""


def parse_lineage_payload(text: str, expected_request_id: str) -> list[dict]:
    payload = json.loads(str(text or "").replace("```json", "").replace("```", "").strip())
    response_request_id = str(payload.get("request_id", "")).strip()
    if not response_request_id:
        raise ValueError("request_id missing in response payload")
    if response_request_id != expected_request_id:
        raise ValueError(f"request_id mismatch: expected={expected_request_id} | got={response_request_id}")

    results = payload.get("results")
    if not isinstance(results, list):
        raise ValueError("results must be a list")

    normalized = []
    for row in results:
        if not isinstance(row, dict):
            continue
        if "Is_Structure" not in row or "Type" not in row or "Name" not in row:
            continue
        normalized.append(
            {
                "Is_Structure": bool(row.get("Is_Structure")),
                "Type": str(row.get("Type", "")).strip() or "Unknown",
                "Name": str(row.get("Name", "")).strip() or "N/A",
            }
        )

    if not normalized:
        raise ValueError("results missing required fields")
    return normalized


def analyze_lineage_with_gemini(client, model_name, annotated_img_path, crop_paths, request_id: str = "sync_structure_lineage"):
    main_part = get_image_part(annotated_img_path)
    crop_parts = [get_image_part(p) for p in crop_paths]

    try:
        call_result = generate_content_with_guard(
            client=client,
            model_name=model_name,
            contents=[main_part] + crop_parts,
            prompt_text=build_lineage_prompt(request_id),
            task_name="analyze_structure_lineage",
            response_mime_type="application/json",
            max_retries=1,
        )
        return parse_lineage_payload(call_result.response_text, request_id)
    except Exception as e:
        error_msg = str(e).lower()
        if "400" in error_msg or "invalid_argument" in error_msg:
            print("      ! skipped Gemini lineage due to oversized page payload")
            return []
        print(f"      ! lineage parse failed: {e}")
        return []


def run_structure_lineage_batch(batch_folder: Path, client, model_name: str, page_payloads: list[dict]) -> dict[str, dict]:
    request_file = create_batch_request_file(batch_folder, f"structure_lineage_{batch_folder.name}")
    for item in page_payloads:
        custom_id = item["custom_id"]
        metadata = build_batch_request_metadata(
            task_name="structure_lineage",
            model_name=model_name,
            custom_id=custom_id,
            stage_name="structure_lineage",
            item_id=f"page_{item['page_num']:04d}" if item.get("page_num") is not None else "marker_image",
            paper_folder=str(batch_folder),
        )
        request_body = build_generate_content_batch_request(
            model_name=model_name,
            contents=[get_image_part(item["img_path"])] + [get_image_part(path) for path in item["crop_paths"]],
            prompt_text=build_lineage_prompt(custom_id),
            response_mime_type="application/json",
        )
        append_batch_request(request_file=request_file, custom_id=custom_id, request_body=request_body, metadata=metadata)

    local_job_id = create_batch_job_record(
        paper_folder=batch_folder,
        task_name="structure_lineage",
        model_name=model_name,
        request_file=request_file,
        metadata={
            "request_count": count_requests_in_jsonl(request_file),
            "gcs_input_uri": f"{DEFAULT_GCS_BATCH_BUCKET}/batch/{request_file.name}",
            "gcs_output_uri_prefix": f"{DEFAULT_GCS_BATCH_BUCKET}/batch_output/{request_file.stem}",
        },
    )
    batch_job = submit_batch_job(
        client=client,
        paper_folder=batch_folder,
        local_job_id=local_job_id,
        display_name=f"struct-lineage-{batch_folder.name}",
    )
    print(f"  batch submit: {batch_job.name}")
    finished_job = poll_batch_job(client=client, paper_folder=batch_folder, local_job_id=local_job_id, poll_interval_seconds=30)
    state_name = getattr(getattr(finished_job, "state", None), "name", None) or str(getattr(finished_job, "state", "UNKNOWN"))
    print(f"  batch state: {state_name}")
    if state_name != "JOB_STATE_SUCCEEDED":
        raise RuntimeError(f"structure_lineage batch failed: {state_name}")
    result_file = download_batch_results(client=client, paper_folder=batch_folder, local_job_id=local_job_id)
    return load_batch_results_as_map(result_file)


def process_single_pdf(
    pdf_path: Path,
    output_root: Path,
    client,
    model_name,
    venv_python_path,
    allowed_pages: set[int] | None = None,
    allowed_marker_images: set[str] | None = None,
):
    clean_stem = pdf_path.stem.strip()
    pdf_output_dir = output_root / f"{clean_stem}_structure"
    pdf_output_dir.mkdir(parents=True, exist_ok=True)
    qc_output_dir = pdf_output_dir / "structure_qc"
    qc_output_dir.mkdir(parents=True, exist_ok=True)

    print(f"\n[Start] {pdf_path.name}")
    doc = fitz.open(str(pdf_path))
    annotated_doc = fitz.open(str(pdf_path))
    page_contexts = []

    if allowed_pages is None:
        print("  PDF page filter: all pages will be processed")
    else:
        print(f"  PDF page filter: selected pages={sorted(allowed_pages)}")

    for page_num in range(1, len(doc) + 1):
        if allowed_pages is not None and page_num not in allowed_pages:
            print(f"  [Page {page_num}] skipped by allowed_pages")
            continue

        print(f"  [Page {page_num}] processing...", end=" ", flush=True)
        page = doc[page_num - 1]
        pix = page.get_pixmap(dpi=300)
        img_path = pdf_output_dir / f"page_{page_num:04d}.png"
        pix.save(str(img_path))
        print(f"rendered: {img_path}")

        mol_data = call_mol_worker(
            [
                {
                    "path": img_path,
                    "source_type": "pdf_page",
                    "page_num": page_num,
                }
            ],
            venv_python_path,
        )
        if not mol_data or not mol_data[0].get("bboxes"):
            print("    no structures detected")
            continue

        page_result = mol_data[0]
        bboxes = page_result.get("bboxes", [])
        smiles_list = page_result.get("smiles", [])
        time.sleep(0.5)

        try:
            img_array = np.fromfile(str(img_path), np.uint8)
            img = cv2.imdecode(img_array, cv2.IMREAD_COLOR)
        except Exception as e:
            print(f"    image load failed: {e}")
            continue

        if img is None:
            print("    image decode failed")
            continue

        h, w, _ = img.shape
        crop_paths = []
        for i, bbox in enumerate(bboxes):
            y0, x0, y1, x1 = bbox
            crop = img[max(0, y0 - 10):min(h, y1 + 10), max(0, x0 - 10):min(w, x1 + 10)]
            c_path = pdf_output_dir / f"page_{page_num:04d}_crop_{i}.png"
            is_success, im_buf_arr = cv2.imencode(".png", crop)
            if is_success:
                im_buf_arr.tofile(str(c_path))
                crop_paths.append(c_path)

        page_contexts.append(
            {
                "page_num": page_num,
                "img_path": img_path,
                "source_type": "pdf_page",
                "source_name": img_path.name,
                "crop_paths": crop_paths,
                "bboxes": bboxes,
                "smiles_list": smiles_list,
                "pix_width": pix.width,
                "pix_height": pix.height,
                "custom_id": make_structure_lineage_custom_id_from_source(
                    pdf_path, "pdf_page", img_path.name, page_num=page_num
                ),
                "gemini_results": [],
            }
        )

    marker_folder = find_marker_image_folder(pdf_path)
    if marker_folder:
        marker_images = collect_marker_images(marker_folder)
        if marker_images:
            print(f"  marker image folder found: {marker_folder}")
            if allowed_marker_images is None:
                print("  marker image filter: all marker images will be processed")
            else:
                print(f"  marker image filter: selected marker images={len(allowed_marker_images)}")
        for marker_img in marker_images:
            if allowed_marker_images is not None and not marker_image_allowed(marker_img, allowed_marker_images):
                print(f"  [Marker] skipped by allowed_marker_images: {marker_img.name}")
                continue

            print(f"  [Marker] processing... {marker_img.name}")
            mol_data = call_mol_worker(
                [
                    {
                        "path": marker_img,
                        "source_type": "marker_image",
                        "page_num": None,
                    }
                ],
                venv_python_path,
            )
            if not mol_data or not mol_data[0].get("bboxes"):
                print("    no structures detected")
                continue

            marker_result = mol_data[0]
            bboxes = marker_result.get("bboxes", [])
            smiles_list = marker_result.get("smiles", [])
            time.sleep(0.5)

            try:
                img_array = np.fromfile(str(marker_img), np.uint8)
                img = cv2.imdecode(img_array, cv2.IMREAD_COLOR)
            except Exception as e:
                print(f"    image load failed: {e}")
                continue

            if img is None:
                print("    image decode failed")
                continue

            h, w, _ = img.shape
            crop_paths = []
            for i, bbox in enumerate(bboxes):
                y0, x0, y1, x1 = bbox
                crop = img[max(0, y0 - 10):min(h, y1 + 10), max(0, x0 - 10):min(w, x1 + 10)]
                c_path = pdf_output_dir / f"{marker_img.stem}_crop_{i}.png"
                is_success, im_buf_arr = cv2.imencode(".png", crop)
                if is_success:
                    im_buf_arr.tofile(str(c_path))
                    crop_paths.append(c_path)

            page_contexts.append(
                {
                    "page_num": None,
                    "img_path": marker_img,
                    "source_type": "marker_image",
                    "source_name": marker_img.name,
                    "crop_paths": crop_paths,
                    "bboxes": bboxes,
                    "smiles_list": smiles_list,
                    "pix_width": w,
                    "pix_height": h,
                    "custom_id": make_structure_lineage_custom_id_from_source(
                        pdf_path, "marker_image", marker_img.name, page_num=None
                    ),
                    "gemini_results": [],
                }
            )
    else:
        print("  no marker image folder found")

    batch_items = [ctx for ctx in page_contexts if ctx["crop_paths"]]
    results_map = {}
    failed_items = []

    if batch_items:
        try:
            results_map = run_structure_lineage_batch(pdf_output_dir, client, model_name, batch_items)
        except Exception as e:
            print(f"  batch failed, falling back to per-item retry: {e}")
            failed_items = list(batch_items)

    if not failed_items:
        for item in batch_items:
            row = results_map.get(item["custom_id"])
            if not row or not row.get("success"):
                failed_items.append(item)
                continue

            response_text = str(row.get("response_text", "")).strip()
            if not response_text:
                failed_items.append(item)
                continue

            try:
                item["gemini_results"] = parse_lineage_payload(response_text, item["custom_id"])
            except Exception:
                failed_items.append(item)

    if failed_items:
        print(f"  retrying failed items individually: {len(failed_items)}")
        for item in failed_items:
            records = analyze_lineage_with_gemini(
                client,
                model_name,
                item["img_path"],
                item["crop_paths"],
                request_id=item["custom_id"],
            )
            item["gemini_results"] = records if records else []

    all_page_results = []
    for item in page_contexts:
        gemini_results = item["gemini_results"]
        source_type = item.get("source_type", "pdf_page")
        source_name = item.get("source_name", item["img_path"].name)
        page_num = item.get("page_num")

        annot_page = None
        if source_type == "pdf_page" and page_num is not None:
            annot_page = annotated_doc[page_num - 1]

        for i, (bbox, smiles) in enumerate(zip(item["bboxes"], item["smiles_list"])):
            meta = gemini_results[i] if i < len(gemini_results) else {}
            is_struct = meta.get("Is_Structure", True)
            s_type = meta.get("Type", "Unknown")
            s_name = meta.get("Name", "N/A")

            qc_path = ""
            rdkit_status = "not_created"
            crop_paths_for_item = item.get("crop_paths", [])

            if i < len(crop_paths_for_item):
                qc_name = (
                    f"{_safe_filename_token(Path(source_name).stem)}"
                    f"_page_{page_num if page_num is not None else 'marker'}"
                    f"_crop_{i:03d}"
                    f"_{_safe_filename_token(s_name)}.png"
                )
                qc_file = qc_output_dir / qc_name

                rdkit_status = save_structure_qc_panel(
                    crop_path=Path(crop_paths_for_item[i]),
                    smiles=smiles,
                    qc_path=qc_file,
                    source_name=source_name,
                    page_num=page_num,
                    crop_index=i,
                    structure_name=s_name,
                    structure_type=s_type,
                )
                qc_path = str(qc_file)

            all_page_results.append(
                {
                    "Source_Type": source_type,
                    "Source_Name": source_name,
                    "Source_Path": str(item["img_path"]),
                    "Page": page_num if page_num is not None else "",
                    "SMILES": smiles,
                    "Type": s_type,
                    "Is_Structure": is_struct,
                    "Name": s_name,
                    "BBox": bbox,
                    "RDKit_Status": rdkit_status,
                    "QC_Image_Path": qc_path,
                }
            )

            if annot_page is not None:
                pdf_rect = bbox_png_to_pdf(bbox, item["pix_width"], item["pix_height"], annot_page)
                highlight = annot_page.add_highlight_annot(pdf_rect)
                color = [0, 1, 0] if s_type == "Single" else ([1, 0.5, 0] if s_type == "Markush" else [0, 0, 1])
                highlight.set_colors(stroke=color)
                highlight.update()

                note_text = f"Type: {s_type}\nName: {s_name}\nSMILES: {smiles}"
                annot = annot_page.add_text_annot(pdf_rect.top_left, note_text, icon="Note")
                annot.update()

    if all_page_results:
        final_df = pd.DataFrame(all_page_results)
        final_df.to_csv(pdf_output_dir / f"{clean_stem}_unified_results.csv", index=False, encoding="utf-8-sig")
        annotated_doc.save(str(pdf_output_dir / f"{clean_stem}_annotated.pdf"))
        print("Saved final outputs.")

    doc.close()
    annotated_doc.close()


if __name__ == "__main__":
    INPUT_PDF_DIR_LIST = [
        r"F:\내 드라이브\LNPDB_new\FG_2026",
        r"F:\내 드라이브\LNPDB_new\QS_2026",
        r"F:\내 드라이브\LNPDB_new\ZT_2026",
    ]

    RESULT_FOLDER_NAME = "Structure_Results_2"

    RESULT_ROOT_DIR_LIST = [
        Path(input_pdf_dir) / RESULT_FOLDER_NAME
        for input_pdf_dir in INPUT_PDF_DIR_LIST
    ]

    VENV_PYTHON_PATH = r"C:\Users\kogun\anaconda3\envs\mol_annotator_win\python.exe"
    # Mac example:
    # VENV_PYTHON_PATH = r"/Users/kogeon/miniconda3/envs/mol_annotator_mac/bin/python"

    API_JSON_NAME = "vertex.json"

    FILTERED_MAPPING_JSON = None
    # FILTERED_MAPPING_JSON = r"/path/to/total_mapping.json"
    # FILTERED_MAPPING_JSON = r"/path/to/total_figure_mapping.json"

    try:
        api_file_path = find_api_key_file(API_JSON_NAME)

        with open(api_file_path, "r", encoding="utf-8") as f:
            cred_data = json.load(f)

        project_id = cred_data.get("project_id")
        if not project_id:
            raise ValueError(f"service account JSON missing project_id: {api_file_path}")

        print(f"Vertex project: {project_id}")
        client = get_vertexai_client(api_file_path, project=project_id)

    except Exception as e:
        print(f"API load failed: {e}")
        sys.exit(1)

    allowed_pages = None
    allowed_marker_images = None

    if FILTERED_MAPPING_JSON is not None:
        mapping_json_path = Path(FILTERED_MAPPING_JSON)

        if mapping_json_path.exists():
            allowed_pages_loaded, allowed_marker_images_loaded = load_allowed_sources_from_mapping(mapping_json_path)

            allowed_pages = allowed_pages_loaded
            allowed_marker_images = allowed_marker_images_loaded

            print(f"Filtered mapping JSON path: {mapping_json_path}")
            print(f"Allowed pages count: {len(allowed_pages)}")
            print(f"Allowed pages: {sorted(allowed_pages)}")
            print(f"Allowed marker images count: {len(allowed_marker_images)}")

        else:
            print(f"Filtered mapping JSON not found, running default full scan: {mapping_json_path}")

    for input_pdf_dir, result_root_dir in zip(INPUT_PDF_DIR_LIST, RESULT_ROOT_DIR_LIST):
        input_pdf_dir = Path(input_pdf_dir)
        result_root_dir = Path(result_root_dir)

        print("=" * 80)
        print(f"Input PDF dir : {input_pdf_dir}")
        print(f"Result root   : {result_root_dir}")
        print("=" * 80)

        result_root_dir.mkdir(parents=True, exist_ok=True)

        pdf_files = sorted(list(input_pdf_dir.glob("*.pdf")))

        if not pdf_files:
            print(f"No PDF files found: {input_pdf_dir}")
            continue

        for pdf in pdf_files:
            try:
                process_single_pdf(
                    pdf_path=pdf,
                    output_root=result_root_dir,
                    client=client,
                    model_name="gemini-3.1-pro-preview",
                    venv_python_path=VENV_PYTHON_PATH,
                    allowed_pages=allowed_pages,
                    allowed_marker_images=allowed_marker_images,
                )

            except Exception as e:
                print(f"{pdf.name} failed: {e}")
