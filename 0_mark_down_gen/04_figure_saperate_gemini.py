import os
import sys
import cv2
import json
import pandas as pd
from pathlib import Path
import re
from typing import Any

# --- [경로 설정] 프로젝트 최상위 경로를 sys.path에 추가 ---
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from google.genai import types
from find_api import find_api_key_file, get_vertexai_client
from LLM_API import generate_content_with_guard
from LLM_Batch import (
    build_generate_content_batch_request,
    build_batch_request_metadata,
    create_batch_request_file,
    create_batch_job_record,
    submit_batch_job,
    poll_batch_job,
    download_batch_results,
    load_batch_results_as_map,
    upload_file_to_gcs,
    append_batch_request,
)
# --- [설정 섹션] ---
MODEL_NAME = "gemini-3.1-pro-preview"  # "gemini-3.1-pro-preview" "gemini-3-flash-preview"
API_JSON_NAME = "vertex.json"
BATCH_MODEL_NAME = MODEL_NAME
USE_BATCH_MODE = True
GCS_BATCH_BUCKET = "gs://lnpdb-articles-extraction-batch-results-geon"

# 추출을 진행할 특정 시각적 타입들
TARGET_VISUAL_TYPES = ['barplot', 'table', 'chemical_structure', 'heatmap']
EMPTY_MANUAL_VALUES = {"", "nan", "none", "null", "[]", "{}"}
USE_FOLDER_SCAN_FALLBACK = False
EXCLUDE_DIR_NAMES = {
    "DEBUG_RAW_ELEMENTS",
    "Exp_Excel",
    "Exp_Excel_Blocks",
    "Exp_Val",
    "Structure_Results",
    "separated_panels_gemini",
    "_auto_rule_generation",
    "_mapping_review",
    "_debug_invalid_results",
    "__pycache__",
}
EXCLUDE_DIR_NAMES_LOWER = {name.lower() for name in EXCLUDE_DIR_NAMES}


def normalize_ft_item_id(value):
    s = str(value or "").strip().lower()
    s = s.replace("–", "-").replace("—", "-")
    s = re.sub(r"\s+", " ", s)

    s = re.sub(r"\bextended\s+data\s+fig\.", "extended data figure", s)
    s = re.sub(r"\bextended\s+data\s+fig\b", "extended data figure", s)
    s = re.sub(r"\bextended\s+data\s+figure\b", "extended data figure", s)
    s = re.sub(r"\bextended\s+data\s+table\b", "extended data table", s)

    s = re.sub(r"\bsupplementary\s+fig\.", "supplementary figure", s)
    s = re.sub(r"\bsupplementary\s+fig\b", "supplementary figure", s)
    s = re.sub(r"\bsupp\.?\s+fig\.", "supplementary figure", s)
    s = re.sub(r"\bsupp\.?\s+fig\b", "supplementary figure", s)
    s = re.sub(r"\bsupp\.?\s+table\.", "supplementary table", s)
    s = re.sub(r"\bsupp\.?\s+table\b", "supplementary table", s)

    s = re.sub(r"\bfig\.", "figure", s)
    s = re.sub(r"\bfig\b", "figure", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s

def is_meaningful_manual_value(value) -> bool:
    if value is None:
        return False
    try:
        if pd.isna(value):
            return False
    except (TypeError, ValueError):
        pass
    text = str(value).strip().lower()
    return text not in EMPTY_MANUAL_VALUES

def normalize_manual_select(value) -> str:
    text = str(value).strip().lower()
    if text in EMPTY_MANUAL_VALUES:
        return ""
    if text in {"yes", "y", "1", "true"}:
        return "yes"
    if text == "maybe":
        return "maybe"
    if text in {"no", "n", "0", "false"}:
        return "no"
    return "no"

def get_fig_selection_value(row):
    manual = row.get("manual_select", "")
    if is_meaningful_manual_value(manual):
        return normalize_manual_select(manual)
    return str(row.get("need_for_lnpdb", "")).strip().lower()

def build_selection_mask_with_manual_override(
    df: pd.DataFrame,
    auto_mask: pd.Series,
    include_values=("yes", "maybe"),
) -> pd.Series:
    if "manual_select" in df.columns:
        manual_has_value = df["manual_select"].apply(is_meaningful_manual_value)
        manual_norm = df["manual_select"].apply(normalize_manual_select)
    else:
        manual_has_value = pd.Series(False, index=df.index)
        manual_norm = pd.Series("", index=df.index)

    auto_mask = auto_mask.fillna(False)

    manual_include = manual_has_value & manual_norm.isin(include_values)
    manual_exclude = manual_has_value & ~manual_norm.isin(include_values)

    final_mask = manual_include | ((~manual_has_value) & auto_mask)
    final_mask = final_mask & (~manual_exclude)
    return final_mask

def build_panel_detection_prompt(request_id: str) -> str:
    return f"""
    Identify all distinct sub-panels in this scientific figure.
    request_id: {request_id}
    Extended Data figures may contain panels such as Extended Data Fig. 5a.
    If the requested item is 'extended data figure 5a', crop only panel 5a from Extended Data Fig. 5.
    Return coordinates in normalized [ymin, xmin, ymax, xmax] format (0-1000).
    Return ONLY a JSON object:
    {{
      "request_id": "{request_id}",
      "panels": [ {{ "panel_id": "A", "box_2d": [ymin, xmin, ymax, xmax] }} ]
    }}
    """



def build_image_filedata_part(gcs_uri: str, image_path: Path) -> dict[str, Any]:
    ext = image_path.suffix.lower()
    mime_type = "image/png" if ext == ".png" else "image/jpeg"
    return {
        "fileData": {
            "fileUri": gcs_uri,
            "mimeType": mime_type,
        }
    }



def make_image_batch_custom_id(folder_name: str, image_path: Path) -> str:
    return f"{folder_name}__{image_path.stem}"



def sanitize_panel_id(panel_id: str) -> str:
    return "".join(c for c in str(panel_id) if c.isalnum())



def extract_target_suffix(item_id: str) -> str | None:
    normalized_item_id = normalize_ft_item_id(item_id)
    match = re.search(r'\d+([a-z]+)\b', normalized_item_id)
    return match.group(1) if match else None

def get_image_part(image_path: Path):
    ext = image_path.suffix.lower()
    mime_type = "image/png" if ext == '.png' else "image/jpeg"
    with open(image_path, "rb") as f:
        return types.Part.from_bytes(data=f.read(), mime_type=mime_type)


def parse_panel_detection_payload(response_text: str, expected_request_id: str) -> list[dict]:
    clean_text = str(response_text or "").replace("```json", "").replace("```", "").strip()
    if not clean_text:
        raise ValueError("empty response_text")
    data = json.loads(clean_text)
    if not isinstance(data, dict):
        raise ValueError("panel detection payload must be a JSON object")
    response_request_id = str(data.get("request_id", "")).strip()
    if not response_request_id:
        raise ValueError("missing request_id")
    if response_request_id != expected_request_id:
        raise ValueError(f"request_id mismatch: expected={expected_request_id} | got={response_request_id}")
    panels = data.get("panels", [])
    if not isinstance(panels, list):
        raise ValueError("panels must be a list")
    for idx, panel in enumerate(panels, 1):
        if not isinstance(panel, dict):
            raise ValueError(f"panel #{idx} must be a JSON object")
        panel_id = str(panel.get("panel_id", "")).strip()
        box = panel.get("box_2d")
        if not panel_id:
            raise ValueError(f"panel #{idx} missing panel_id")
        if not isinstance(box, list) or len(box) != 4:
            raise ValueError(f"panel #{idx} invalid box_2d")
    return panels

def get_panel_bboxes_from_gemini(client, model_name, image_path: Path, img_width: int, img_height: int):
    image_part = get_image_part(image_path)
    request_id = make_image_batch_custom_id(image_path.parent.name, image_path)
    prompt = build_panel_detection_prompt(request_id)
    
    try:
        call_result = generate_content_with_guard(
            client=client,
            model_name=model_name,
            contents=[image_part],
            prompt_text=prompt,
            task_name="figure_panel_detection",
            response_mime_type="application/json",
            max_retries=5,
        )
        return parse_panel_detection_payload(call_result.response_text, request_id)
    except Exception as e:
        print(f"    ! 패널 분리 실패: {e}")
        return []

def load_total_mapping(root_path: Path, mapping_json_path=None):
    mapping_file = Path(mapping_json_path) if mapping_json_path is not None else root_path / "total_figure_mapping.json"
    if mapping_file.exists():
        with open(mapping_file, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {}

def get_total_mapping_path(root_path: Path, mapping_json_path=None) -> Path:
    return Path(mapping_json_path) if mapping_json_path is not None else root_path / "total_figure_mapping.json"

def looks_like_figure_table_item_id(value) -> bool:
    text = normalize_ft_item_id(value)
    return bool(re.match(r"^(?:supplementary\s+)?(?:figure|table)\s+\d+[a-z]?$", text))

def is_excluded_source_dir(path: Path) -> bool:
    return path.name.lower() in EXCLUDE_DIR_NAMES_LOWER or path.name.startswith(".")

def is_source_folder_mapping_key(key: str, value: Any, root: Path) -> bool:
    candidate = root / str(key)
    if not candidate.exists() or not candidate.is_dir():
        return False
    if is_excluded_source_dir(candidate):
        return False
    if not isinstance(value, dict):
        return False
    return any(looks_like_figure_table_item_id(inner_key) for inner_key in value.keys())

def select_source_folders_from_total_mapping(root: Path, total_mapping: dict[str, Any]) -> tuple[list[Path], list[str]]:
    subfolders: list[Path] = []
    ignored_keys: list[str] = []
    seen: set[Path] = set()

    for key, value in total_mapping.items():
        key_text = str(key)
        candidate = root / key_text
        if is_source_folder_mapping_key(key_text, value, root):
            resolved = candidate.resolve()
            if resolved not in seen:
                subfolders.append(candidate)
                seen.add(resolved)
            continue

        ignored_keys.append(key_text)
        if not candidate.exists() and isinstance(value, dict) and any(looks_like_figure_table_item_id(inner_key) for inner_key in value.keys()):
            print(f"⚠️ mapping key has no matching folder: {key_text}")

    return sorted(subfolders, key=lambda p: p.name.lower()), ignored_keys

def scan_source_folders_fallback(root: Path) -> list[Path]:
    return sorted(
        [
            p for p in root.iterdir()
            if p.is_dir() and not is_excluded_source_dir(p)
        ],
        key=lambda p: p.name.lower(),
    )

def print_selected_source_folder_log(mapping_path: Path, subfolders: list[Path], ignored_keys: list[str]):
    if mapping_path.exists():
        print(f"📄 total_figure_mapping loaded: {mapping_path}")
    else:
        print(f"⚠️ total_figure_mapping not found: {mapping_path}")
    print(f"📂 source folders selected from total mapping: {len(subfolders)}")
    for folder in subfolders:
        print(f"  - {folder.name}")
    print(f"\n🚫 ignored mapping keys or non-source folders: {len(ignored_keys)}")
    for key in ignored_keys:
        print(f"  - {key}")

def save_total_mapping(root_path: Path, mapping_data, mapping_json_path=None):
    mapping_file = Path(mapping_json_path) if mapping_json_path is not None else root_path / "total_figure_mapping.json"
    with open(mapping_file, 'w', encoding='utf-8') as f:
        json.dump(mapping_data, f, indent=4, ensure_ascii=False)
    print(f"\n✨ 통합 매핑 파일 최종 업데이트 완료: {mapping_file}")


def crop_and_save_panels(
    img_path: Path,
    panels: list[dict[str, Any]],
    output_dir: Path,
    item_ids: list[str],
    folder_mapping: dict[str, Any],
) -> int:
    """패널 bbox 결과를 이용해 실제 crop 저장 및 item-panel 매핑을 수행한다."""
    img_cv = cv2.imread(str(img_path))
    if img_cv is None:
        return 0

    h, w = img_cv.shape[:2]

    for item in item_ids:
        folder_mapping[item] = {
            "full_image": str(img_path),
            "panels": {}
        }

    for idx, panel in enumerate(panels):
        p_id = panel.get("panel_id", str(idx))
        box = panel.get("box_2d", [])
        if len(box) != 4:
            continue

        y1, x1, y2, x2 = [int((val / 1000.0) * (h if i % 2 == 0 else w)) for i, val in enumerate(box)]
        crop = img_cv[max(0, y1):min(h, y2), max(0, x1):min(w, x2)]

        safe_id = sanitize_panel_id(p_id)
        p_filename = f"{img_path.stem}_panel_{safe_id}.jpg"
        save_path = output_dir / p_filename
        cv2.imwrite(str(save_path), crop)

        for item in item_ids:
            target_suffix = extract_target_suffix(item)
            if (target_suffix and p_id.lower() == target_suffix) or len(panels) == 1:
                folder_mapping[item]["panels"][p_id] = str(save_path)
                print(f"    🎯 정밀 매칭 성공: {item} -> 패널 {p_id}")

    return len(panels)

def collect_image_to_items(folder_path: Path, total_mapping: dict[str, Any], classified_csv_path=None) -> tuple[dict[str, list[str]], pd.DataFrame] | tuple[dict, None]:
    folder_path = Path(folder_path)
    folder_name = folder_path.name
    this_folder_mapping = total_mapping.get(folder_name, {})
    if not this_folder_mapping:
        return {}, None

    if classified_csv_path is None:
        classified_csv = folder_path.parent / "fig_table_lnpdb_classified.csv"
        if not classified_csv.exists():
            classified_csv = folder_path / "fig_table_lnpdb_classified.csv"
    else:
        classified_csv = Path(classified_csv_path)
    if not classified_csv.exists():
        return {}, None

    df_cls = pd.read_csv(classified_csv)
    if "item_id" in df_cls.columns:
        df_cls["item_id"] = df_cls["item_id"].apply(normalize_ft_item_id)
    if "base_id" in df_cls.columns:
        df_cls["base_id"] = df_cls["base_id"].apply(normalize_ft_item_id)
    df_cls["_fig_select"] = df_cls.apply(get_fig_selection_value, axis=1)

    visual_series = df_cls["visual_type"].astype(str).str.lower() if "visual_type" in df_cls.columns else pd.Series("", index=df_cls.index)
    auto_mask = (
        df_cls["_fig_select"].isin(["yes", "maybe"])
        & visual_series.isin(TARGET_VISUAL_TYPES)
    )

    final_mask = build_selection_mask_with_manual_override(df_cls, auto_mask)

    if "manual_select" in df_cls.columns:
        manual_has_value = df_cls["manual_select"].apply(is_meaningful_manual_value)
        manual_norm = df_cls["manual_select"].apply(normalize_manual_select)
        print(f"  - panel target manual_select include rows: {int((manual_has_value & manual_norm.isin(['yes', 'maybe'])).sum())}")
        print(f"  - panel target manual_select exclude rows: {int((manual_has_value & ~manual_norm.isin(['yes', 'maybe'])).sum())}")
        print(f"  - panel target automatic visual_type rows: {int(((~manual_has_value) & auto_mask).sum())}")

    target_ids = set(
        df_cls.loc[final_mask, "item_id"].astype(str).map(normalize_ft_item_id).str.strip().tolist()
    )

    print(f"  - final panel target_ids count: {len(target_ids)}")

    image_to_items: dict[str, list[str]] = {}
    for item_id, item_map in this_folder_mapping.items():
        clean_item_id = normalize_ft_item_id(item_id)
        if clean_item_id not in target_ids:
            continue
        if not item_map:
            continue

        # 예전 구조: 문자열 경로
        if isinstance(item_map, str):
            image_path = item_map.strip()
            if image_path:
                image_to_items.setdefault(image_path, []).append(clean_item_id)
            continue

        # 패널 분리 이후 구조: dict
        if isinstance(item_map, dict):
            full_image = str(item_map.get("full_image", "")).strip()
            if full_image:
                image_to_items.setdefault(full_image, []).append(clean_item_id)
            continue

    return image_to_items, df_cls

def process_folder_vlm_online(folder_path: Path, client, model_name, total_mapping, classified_csv_path=None, panel_output_dir=None):
    """기존 online 방식으로 패널 분리를 수행한다."""
    folder_path = Path(folder_path)
    folder_name = folder_path.name

    image_to_items, _ = collect_image_to_items(folder_path, total_mapping, classified_csv_path=classified_csv_path)
    if not image_to_items:
        return True

    output_dir = Path(panel_output_dir) if panel_output_dir is not None else folder_path / "separated_panels_gemini"
    os.makedirs(output_dir, exist_ok=True)

    print(f"  📸 {folder_name}: 총 {len(image_to_items)}개 이미지 파일 분석 시작...")

    for img_path_str, item_ids in image_to_items.items():
        img_path = Path(img_path_str)
        if not img_path.exists():
            continue

        print(f"    -> 분석 중: {img_path.name} (대상: {item_ids})")

        img_cv = cv2.imread(str(img_path))
        if img_cv is None:
            continue
        h, w = img_cv.shape[:2]

        panels = get_panel_bboxes_from_gemini(client, model_name, img_path, w, h)
        panel_count = crop_and_save_panels(
            img_path=img_path,
            panels=panels,
            output_dir=output_dir,
            item_ids=item_ids,
            folder_mapping=total_mapping[folder_name],
        )
        print(f"      ✅ {panel_count}개 패널 분리 완료")

    return True



def process_folder_vlm_batch(root_path: Path, folder_path: Path, client, model_name, total_mapping, classified_csv_path=None, panel_output_dir=None):
    """Vertex batch 방식으로 이미지별 panel detection을 수행하고 로컬 후처리를 진행한다."""
    root_path = Path(root_path)
    folder_path = Path(folder_path)
    folder_name = folder_path.name

    image_to_items, _ = collect_image_to_items(folder_path, total_mapping, classified_csv_path=classified_csv_path)
    if not image_to_items:
        return True

    output_dir = Path(panel_output_dir) if panel_output_dir is not None else folder_path / "separated_panels_gemini"
    os.makedirs(output_dir, exist_ok=True)

    request_file = create_batch_request_file(folder_path, f"panel_detection_{folder_name}")
    print(f"  📸 {folder_name}: 총 {len(image_to_items)}개 이미지 파일 batch 요청 생성 시작...")

    image_info_map: dict[str, dict[str, Any]] = {}

    for idx, (img_path_str, item_ids) in enumerate(image_to_items.items(), 1):
        img_path = Path(img_path_str)
        if not img_path.exists():
            continue

        gcs_image_uri = f"{GCS_BATCH_BUCKET}/panel_images/{folder_name}/{img_path.name}"
        upload_file_to_gcs(img_path, gcs_image_uri)

        custom_id = make_image_batch_custom_id(folder_name, img_path)
        metadata = build_batch_request_metadata(
            task_name=f"panel_detection_{folder_name}",
            model_name=model_name,
            custom_id=custom_id,
            stage_name="figure_panel_detection_batch",
            item_id=";".join(item_ids),
            paper_folder=str(folder_path),
            cached_content_name=None,
            extra_metadata={
                "image_path": str(img_path),
                "gcs_image_uri": gcs_image_uri,
                "item_ids": item_ids,
            },
        )

        request_body = build_generate_content_batch_request(
            model_name=model_name,
            contents=[build_image_filedata_part(gcs_image_uri, img_path)],
            prompt_text=build_panel_detection_prompt(custom_id),
            response_mime_type="application/json",
        )
        append_batch_request(
            request_file=request_file,
            custom_id=custom_id,
            request_body=request_body,
            metadata=metadata,
        )

        image_info_map[custom_id] = {
            "img_path": img_path,
            "item_ids": item_ids,
        }
        print(f"    -> batch 요청 추가: {img_path.name} ({idx}/{len(image_to_items)})")

    local_job_id = create_batch_job_record(
        paper_folder=folder_path,
        task_name=f"panel_detection_{folder_name}",
        model_name=model_name,
        request_file=request_file,
        metadata={
            "request_count": len(image_info_map),
            "gcs_input_uri": f"{GCS_BATCH_BUCKET}/batch/panel_detection_{folder_name}.jsonl",
            "gcs_output_uri_prefix": f"{GCS_BATCH_BUCKET}/batch_output/panel_detection_{folder_name}",
            "folder_name": folder_name,
        },
    )

    print(f"  ✅ local batch job 준비 완료: {local_job_id}")
    batch_job = submit_batch_job(
        client=client,
        paper_folder=folder_path,
        local_job_id=local_job_id,
        display_name=f"panel-detect-{folder_name}",
    )
    print(f"  ✅ batch 제출 완료: {batch_job.name}")

    finished_job = poll_batch_job(
        client=client,
        paper_folder=folder_path,
        local_job_id=local_job_id,
        poll_interval_seconds=30,
    )
    state_name = getattr(getattr(finished_job, "state", None), "name", None) or str(getattr(finished_job, "state", "UNKNOWN"))
    print(f"  ✅ batch 종료 상태: {state_name}")

    if state_name != "JOB_STATE_SUCCEEDED":
        return False

    result_file = download_batch_results(
        client=client,
        paper_folder=folder_path,
        local_job_id=local_job_id,
    )
    print(f"  ✅ batch 결과 저장 완료: {result_file}")

    results_map = load_batch_results_as_map(result_file)
    folder_mapping = total_mapping[folder_name]

    for custom_id, info in image_info_map.items():
        row = results_map.get(custom_id)
        if not row:
            print(f"    ! batch 결과 없음: {custom_id}")
            continue

        if not row.get("success"):
            print(f"    ! batch panel 분리 실패: {custom_id} | {row.get('error')}")
            continue

        response_text = row.get("response_text") or ""
        try:
            panels = parse_panel_detection_payload(response_text, custom_id)
            if not panels:
                raise ValueError("empty panels")
        except Exception as e:
            print(f"    ! batch 결과 검증 실패: {custom_id} | {e}")
            continue

        panel_count = crop_and_save_panels(
            img_path=info["img_path"],
            panels=panels,
            output_dir=output_dir,
            item_ids=info["item_ids"],
            folder_mapping=folder_mapping,
        )
        print(f"    -> 후처리 완료: {info['img_path'].name} | panels={panel_count}")

    return True


def process_folder_vlm_batch_with_retry(root_path: Path, folder_path: Path, client, model_name, total_mapping, classified_csv_path=None, panel_output_dir=None):
    ok = process_folder_vlm_batch(root_path, folder_path, client, model_name, total_mapping, classified_csv_path=classified_csv_path, panel_output_dir=panel_output_dir)
    if not ok:
        return False

    folder_path = Path(folder_path)
    folder_name = folder_path.name
    output_dir = Path(panel_output_dir) if panel_output_dir is not None else folder_path / "separated_panels_gemini"
    image_to_items, _ = collect_image_to_items(folder_path, total_mapping, classified_csv_path=classified_csv_path)
    image_info_map = {
        make_image_batch_custom_id(folder_name, Path(img_path_str)): {
            "img_path": Path(img_path_str),
            "item_ids": item_ids,
        }
        for img_path_str, item_ids in image_to_items.items()
    }

    batch_dir = folder_path / "_batch_jobs"
    result_files = sorted(batch_dir.glob("*.result.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not result_files:
        return True

    results_map = load_batch_results_as_map(result_files[0])
    folder_mapping = total_mapping[folder_name]
    failed_custom_ids: list[str] = []

    for custom_id in image_info_map.keys():
        row = results_map.get(custom_id)
        if not row or not row.get("success"):
            failed_custom_ids.append(custom_id)
            continue
        try:
            panels = parse_panel_detection_payload(row.get("response_text") or "", custom_id)
        except Exception:
            failed_custom_ids.append(custom_id)
            continue
        if not panels:
            failed_custom_ids.append(custom_id)

    if not failed_custom_ids:
        return True

    print(f"  ?봽 batch ?ㅽ뙣 {len(failed_custom_ids)}媛??대?吏 sync fallback ?ъ떆??")
    for custom_id in failed_custom_ids:
        info = image_info_map.get(custom_id)
        if not info:
            continue
        img_path = info["img_path"]
        try:
            image = cv2.imread(str(img_path))
            if image is None:
                raise ValueError(f"image read failed: {img_path}")
            h, w = image.shape[:2]
            panels = get_panel_bboxes_from_gemini(client, model_name, img_path, w, h)
            if not panels:
                print(f"    ! fallback empty response: {img_path.name}")
                continue
            panel_count = crop_and_save_panels(
                img_path=img_path,
                panels=panels,
                output_dir=output_dir,
                item_ids=info["item_ids"],
                folder_mapping=folder_mapping,
            )
            print(f"    -> fallback ?깃났: {img_path.name} | panels={panel_count}")
        except Exception as e:
            print(f"    ! fallback ?ㅽ뙣: {img_path.name} | {e}")

    return True


def process_folder_vlm(folder_path: Path, client, model_name, total_mapping, use_batch_mode: bool = False, root_path: Path | None = None, classified_csv_path=None, mapping_json_path=None, panel_output_dir=None):
    """설정에 따라 online 또는 Vertex batch 방식으로 패널 분리를 진행한다."""
    if use_batch_mode:
        ok = process_folder_vlm_batch_with_retry(root_path or folder_path.parent, folder_path, client, model_name, total_mapping, classified_csv_path=classified_csv_path, panel_output_dir=panel_output_dir)
    else:
        ok = process_folder_vlm_online(folder_path, client, model_name, total_mapping, classified_csv_path=classified_csv_path, panel_output_dir=panel_output_dir)

    if mapping_json_path is not None:
        save_total_mapping(Path(folder_path), total_mapping, mapping_json_path=mapping_json_path)
    return ok

def run_batch_vlm_separation(root_path, model_name, client, use_batch_mode: bool = False):
    root = Path(root_path)
    mapping_path = get_total_mapping_path(root)
    total_mapping = load_total_mapping(root)

    subfolders, ignored_keys = select_source_folders_from_total_mapping(root, total_mapping)
    print_selected_source_folder_log(mapping_path, subfolders, ignored_keys)

    if not subfolders:
        if USE_FOLDER_SCAN_FALLBACK:
            print("\n⚠️ source folder key를 찾지 못해 fallback folder scan을 사용합니다.")
            subfolders = scan_source_folders_fallback(root)
            print(f"📂 fallback source folders selected: {len(subfolders)}")
            for folder in subfolders:
                print(f"  - {folder.name}")
        else:
            print("\n⚠️ total_figure_mapping에서 처리할 source folder를 찾지 못했습니다.")
            print("   USE_FOLDER_SCAN_FALLBACK=False 이므로 root 하위 폴더 전체 scan은 수행하지 않습니다.")
            return

    print("\n" + "="*50)

    for i, folder in enumerate(subfolders, 1):
        print(f"[{i}/{len(subfolders)}] {folder.name}")
        process_folder_vlm(folder, client, model_name, total_mapping, use_batch_mode=use_batch_mode, root_path=root)
    
    save_total_mapping(root, total_mapping)

if __name__ == "__main__":
    ROOT_FOLDER = r"/Users/kogeon/Google Drive/내 드라이브/LNPDB_new/FG_2026"
    try:
        api_key = find_api_key_file(API_JSON_NAME)

        with open(api_key, "r", encoding="utf-8") as f:
            cred_data = json.load(f)

        project_id = cred_data.get("project_id")
        if not project_id:
            raise ValueError(f"서비스 계정 JSON에 project_id가 없습니다: {api_key}")

        print(f"🔧 Vertex 프로젝트 설정: {project_id}")
        vertex_client = get_vertexai_client(api_key, project=project_id)
        run_batch_vlm_separation(ROOT_FOLDER, BATCH_MODEL_NAME if USE_BATCH_MODE else MODEL_NAME, vertex_client, use_batch_mode=USE_BATCH_MODE)
    except Exception as e:
        print(f"❌ 실패: {e}")
