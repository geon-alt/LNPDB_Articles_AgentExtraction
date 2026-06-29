import json
import sys
import time
import hashlib
import pandas as pd
from pathlib import Path
from google.genai import types

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from find_api import find_api_key_file, get_vertexai_client
from LLM_Batch import (
    build_generate_content_batch_request,
    build_batch_request_metadata,
    create_batch_request_file,
    create_batch_job_record,
    submit_batch_job,
    poll_batch_job,
    download_batch_results,
    load_batch_results_as_map,
    append_batch_request,
    count_requests_in_jsonl,
    upload_file_to_gcs,
)

DEFAULT_GCS_BATCH_BUCKET = "gs://lnpdb-articles-extraction-batch-results-geon"
TARGET_VISUAL_TYPES = ["barplot", "table", "chemical_structure", "heatmap"]


def load_total_mapping(paper_folder: Path):
    mapping_file = paper_folder / "total_figure_mapping.json"
    if mapping_file.exists():
        with open(mapping_file, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def get_mime_type(file_path: Path):
    ext = file_path.suffix.lower()
    if ext == ".md":
        return "text/plain"
    if ext == ".pdf":
        return "application/pdf"
    if ext in [".jpg", ".jpeg"]:
        return "image/jpeg"
    if ext == ".png":
        return "image/png"
    return "application/octet-stream"


def get_document_part(file_path):
    file_path = Path(file_path)
    if not file_path.exists():
        return None

    with open(file_path, "rb") as f:
        return types.Part.from_bytes(data=f.read(), mime_type=get_mime_type(file_path))


def get_md_texts(folder: Path):
    texts = []
    for path in folder.rglob("*.md"):
        if path.is_file() and not path.name.startswith("~"):
            try:
                texts.append(path.read_text(encoding="utf-8"))
            except UnicodeDecodeError:
                texts.append(path.read_text(encoding="utf-8", errors="replace"))
    return texts


def upload_file_part_cached(local_path: Path, paper_folder: Path, upload_cache: dict):
    local_path = Path(local_path)
    cache_key = str(local_path.resolve())
    cached = upload_cache.get(cache_key)
    if cached:
        return cached

    gcs_uri = f"{DEFAULT_GCS_BATCH_BUCKET}/papers/{paper_folder.name}/{local_path.name}"
    upload_file_to_gcs(local_path, gcs_uri)
    part = {
        "fileData": {
            "fileUri": gcs_uri,
            "mimeType": get_mime_type(local_path),
        }
    }
    upload_cache[cache_key] = part
    return part


def get_dynamic_schema_from_db(db_path, target_cols):
    print(f"  -> LNPDB DB 로드 중.. ({db_path})")
    schema_dict = {}
    try:
        df = pd.read_csv(db_path)
        for col in target_cols:
            if col in df.columns:
                val_counts = df[col].dropna().astype(str).value_counts()
                valid_vals = [
                    v for v in val_counts.index
                    if v.lower() not in ["variable", "various", "nan", "n/a", "none"]
                ]
                schema_dict[col] = valid_vals[:10]
            else:
                schema_dict[col] = []
        return schema_dict
    except Exception as e:
        print(f"    ! DB 읽기 실패: {e}")
        return {col: [] for col in target_cols}


def make_pdf_group_custom_id(paper_name: str, base_name: str) -> str:
    seed = f"{paper_name}::{str(base_name).strip().lower()}"
    return "pdf_group__" + hashlib.sha1(seed.encode("utf-8")).hexdigest()[:12]


def build_pdf_group_prompt(batch_name, batch_items, dynamic_schema_dict, image_filenames, request_id):
    schema_json_str = json.dumps(dynamic_schema_dict, indent=2, ensure_ascii=False)
    attached_images_str = ", ".join(image_filenames) if image_filenames else "None (Text Only)"
    return f"""
    Using all provided documents (including Markdown text and Images), extract the experimental conditions ONLY for the following items:
    TARGET LIST: {batch_items}

    [Request Tracking]
    - request_id: {request_id}

    [Attached Image Files]
    The following image files are directly attached for your reference to analyze these items:
    {attached_images_str}

    [Reference Schema & Examples from existing Database]
    The following dictionary shows the target columns and examples of values currently existing in our database.
    Format: {{"Column_Name": ["Example1", "Example2", ...]}}

    {schema_json_str}

    * CRITICAL RULE 1: These are just EXAMPLES. If the text/image contains DIFFERENT or NEW values not listed in this dictionary, you MUST extract and use the NEW values. You MUST actively read the provided image files.
    * CRITICAL RULE 2:
      - STRICTLY FORBIDDEN: You MUST NOT use the words "variable", "various", or list multiple components with commas in a single cell.
      - If a single figure tests multiple distinct experimental groups, create a separate JSON object for EACH group.
    * CRITICAL RULE 3: If a specific column's value is truly not mentioned for an experimental group, output "N/A".
    * CRITICAL RULE 4: The top-level JSON must contain the same request_id exactly as provided.

    Return Format (JSON):
    {{
      "request_id": "{request_id}",
      "results": [
        {{
          "item_id": "figure 1a",
          "group_desc": "Tested on C57BL/6 mice (1.0 mg/kg)",
          "metadata": {{ "Model": "C57BL/6", "Dose_ug_nucleicacid": "1.0 mg/kg", "Route_of_administration": "Intravenous", "Cargo_type": "mRNA" }},
          "original_text_source": "Provide the exact sentence or paragraph from the provided document that proves these values.",
          "brief_summary": "..."
        }}
      ]
    }}
    """


def parse_pdf_group_response(response_text: str, expected_request_id: str):
    clean_text = str(response_text or "").replace("```json", "").replace("```", "").strip()
    if not clean_text:
        raise ValueError("empty_response")

    data = json.loads(clean_text)
    if not isinstance(data, dict):
        raise ValueError("response_not_dict")

    response_request_id = str(data.get("request_id", "")).strip()
    if not response_request_id:
        raise ValueError("missing_request_id")
    if response_request_id != expected_request_id:
        raise ValueError(f"request_id_mismatch::{response_request_id}")

    results = data.get("results")
    if not isinstance(results, list) or not results:
        raise ValueError("missing_results")

    for idx, entry in enumerate(results):
        if not isinstance(entry, dict):
            raise ValueError(f"result_not_dict::{idx}")
        if not str(entry.get("item_id", "")).strip():
            raise ValueError(f"missing_item_id::{idx}")
        if "metadata" not in entry or not isinstance(entry.get("metadata"), dict):
            raise ValueError(f"missing_metadata::{idx}")

    return results


def extract_metadata_for_batch_online(client, model_name, document_parts, batch_name, batch_items, dynamic_schema_dict, image_filenames, request_id):
    prompt = build_pdf_group_prompt(batch_name, batch_items, dynamic_schema_dict, image_filenames, request_id)
    max_retries = 5
    base_wait = 15

    for attempt in range(max_retries):
        try:
            response = client.models.generate_content(
                model=model_name,
                contents=document_parts + [prompt],
                config=types.GenerateContentConfig(response_mime_type="application/json"),
            )
            return parse_pdf_group_response(response.text, request_id)
        except Exception as e:
            error_msg = str(e).lower()
            if "429" in error_msg or "resource_exhausted" in error_msg:
                wait_time = base_wait * (2 ** attempt)
                print(f"      ! [429] {wait_time}초 대기 후 재시도.. ({attempt + 1}/{max_retries})")
                time.sleep(wait_time)
                continue
            if "400" in error_msg or "invalid_argument" in error_msg:
                print(f"      ! [400] 재시도.. ({attempt + 1}/{max_retries})")
                continue
            print(f"      ! 추출 실패 ({batch_name}): {e}")
            return []

    print(f"      ! 최대 재시도 횟수 초과로 추출 실패 ({batch_name})")
    return []


def process_single_paper(local_folder: Path, gdrive_base_folder: Path, client, model_name: str, dynamic_schema):
    print(f"분석 시작: {local_folder.name}")

    csv_path = local_folder / "fig_table_lnpdb_classified.csv"
    if not csv_path.exists():
        print(f"  ! 분류 CSV 파일이 없습니다. 경로: {csv_path}")
        return

    total_mapping = load_total_mapping(local_folder)

    try:
        df = pd.read_csv(csv_path)
        target_df = df[
            (df["need_for_lnpdb"].isin(["yes", "maybe"])) &
            (df["visual_type"].astype(str).str.lower().isin(TARGET_VISUAL_TYPES))
        ]
        if target_df.empty:
            print("  ! 추출 대상 Figure/Table이 없습니다.")
            return

        grouped_inventory = {}
        for base_id, group in target_df.groupby("base_id"):
            grouped_inventory[base_id] = group["item_id"].tolist()

        print(f"\n[CSV 연동 완료] 추출 대상 {len(target_df)}개 item, 총 {len(grouped_inventory)}개 그룹")
    except Exception as e:
        print(f"  ! CSV 처리 중 오류 발생: {e}")
        return

    document_files = [
        f for f in local_folder.rglob("*")
        if f.is_file() and f.suffix.lower() in {".md", ".pdf"} and not f.name.startswith("~")
    ]

    base_document_parts = []
    for doc_path in document_files:
        part = get_document_part(doc_path)
        if part:
            base_document_parts.append(part)

    md_texts = get_md_texts(local_folder)
    pdf_paths = [f for f in local_folder.rglob("*.pdf") if f.is_file() and not f.name.startswith("~")]
    upload_cache = {}
    shared_batch_contents = [text for text in md_texts if text.strip()]
    for pdf_path in pdf_paths:
        shared_batch_contents.append(upload_file_part_cached(pdf_path, local_folder, upload_cache))

    total_groups = len(grouped_inventory)
    print(f"\n[정보 추출] 총 {total_groups}개 그룹 batch 큐 구성 시작...")
    start_time = time.time()

    request_file = create_batch_request_file(local_folder, f"pdf_grouped_metadata_{local_folder.name}")
    request_specs = {}

    for i, (base_name, batch_items) in enumerate(grouped_inventory.items(), 1):
        if i == 1:
            eta_str = "계산 중.."
        else:
            elapsed_time = time.time() - start_time
            avg_time = elapsed_time / (i - 1)
            rem_seconds = int(avg_time * (total_groups - (i - 1)))
            m, s = divmod(rem_seconds, 60)
            eta_str = f"{m}분 {s}초"

        print(f"  -> [{i}/{total_groups}] {base_name} 그룹 ({len(batch_items)}개 항목) ... (남은 시간: {eta_str})", end=" ", flush=True)

        current_contents = list(base_document_parts)
        batch_contents = list(shared_batch_contents)
        image_filenames = []
        item_map = None
        first_item = batch_items[0]

        for sub_dict in total_mapping.values():
            if isinstance(sub_dict, dict) and first_item in sub_dict:
                item_map = sub_dict[first_item]
                break

        if item_map:
            full_img = item_map.get("full_image")
            if full_img:
                img_path = Path(full_img)
                part = get_document_part(img_path)
                if part:
                    current_contents.append(part)
                    image_filenames.append(img_path.name)
                batch_contents.append(upload_file_part_cached(img_path, local_folder, upload_cache))

            panels = item_map.get("panels", {})
            for p_path in panels.values():
                panel_path = Path(p_path)
                part = get_document_part(panel_path)
                if part:
                    current_contents.append(part)
                    image_filenames.append(panel_path.name)
                batch_contents.append(upload_file_part_cached(panel_path, local_folder, upload_cache))

            print(f"(원본 + 패널 {len(panels)}개 포함)", end=" ")
        else:
            print("(텍스트만 사용)", end=" ")

        custom_id = make_pdf_group_custom_id(local_folder.name, base_name)
        prompt = build_pdf_group_prompt(base_name, batch_items, dynamic_schema, image_filenames, custom_id)
        request_body = build_generate_content_batch_request(
            model_name=model_name,
            contents=batch_contents,
            prompt_text=prompt,
            response_mime_type="application/json",
        )
        metadata = build_batch_request_metadata(
            task_name="extract_pdf_group_metadata",
            model_name=model_name,
            custom_id=custom_id,
            stage_name="extract_pdf_group_metadata",
            item_id=base_name,
            paper_folder=str(local_folder),
            extra_metadata={"group_name": str(base_name), "batch_items": batch_items},
        )
        append_batch_request(request_file, custom_id, request_body, metadata)
        request_specs[custom_id] = {
            "base_name": base_name,
            "batch_items": batch_items,
            "current_contents": current_contents,
            "image_filenames": image_filenames,
        }
        print("queued")

    if not request_specs:
        print("\n  ! batch request가 없습니다.")
        return

    local_job_id = create_batch_job_record(
        paper_folder=local_folder,
        task_name="extract_pdf_group_metadata",
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
        paper_folder=local_folder,
        local_job_id=local_job_id,
        display_name=f"pdf-grouped-{local_folder.name}",
    )
    print(f"\n  ✅ Batch 제출 완료: {batch_job.name}")
    finished_job = poll_batch_job(client, local_folder, local_job_id, poll_interval_seconds=30)
    state_name = getattr(getattr(finished_job, "state", None), "name", None) or str(getattr(finished_job, "state", "UNKNOWN"))

    batch_results_map = {}
    if state_name == "JOB_STATE_SUCCEEDED":
        result_file = download_batch_results(client, local_folder, local_job_id)
        batch_results_map = load_batch_results_as_map(result_file)
    else:
        print(f"  ! Batch 실패: {state_name}")

    all_final_data = []
    failed_request_ids = []

    for custom_id, spec in request_specs.items():
        row = batch_results_map.get(custom_id)
        if not row or not row.get("success") or not str(row.get("response_text", "")).strip():
            failed_request_ids.append(custom_id)
            continue

        try:
            all_final_data.extend(parse_pdf_group_response(row.get("response_text", ""), custom_id))
        except Exception as e:
            print(f"  ! batch parse 실패 ({spec['base_name']}): {e}")
            failed_request_ids.append(custom_id)

    if failed_request_ids:
        print(f"\n  - 실패 group {len(failed_request_ids)}건 online 재시도")
    for custom_id in failed_request_ids:
        spec = request_specs[custom_id]
        batch_results = extract_metadata_for_batch_online(
            client=client,
            model_name=model_name,
            document_parts=spec["current_contents"],
            batch_name=spec["base_name"],
            batch_items=spec["batch_items"],
            dynamic_schema_dict=dynamic_schema,
            image_filenames=spec["image_filenames"],
            request_id=custom_id,
        )
        if batch_results:
            all_final_data.extend(batch_results)
        else:
            print(f"  ! 재시도 실패 ({spec['base_name']})")

    if all_final_data:
        rows = []
        for entry in all_final_data:
            row = {
                "Item_ID": entry.get("item_id"),
                "Summary": entry.get("brief_summary"),
                "Original_Text_Source": entry.get("original_text_source", "N/A"),
            }
            row.update(entry.get("metadata", {}))
            rows.append(row)
        final_df = pd.DataFrame(rows)

        target_gdrive_folder = gdrive_base_folder
        target_gdrive_folder.mkdir(parents=True, exist_ok=True)
        output_xlsx = target_gdrive_folder / f"1_{local_folder.name}_grouped_metadata.xlsx"

        from openpyxl.styles import Font
        with pd.ExcelWriter(output_xlsx, engine="openpyxl") as writer:
            final_df.to_excel(writer, index=False, sheet_name="Grouped_Metadata")
            worksheet = writer.sheets["Grouped_Metadata"]
            bold_font = Font(bold=True)

            basic_cols = ["Item_ID", "Summary", "Original_Text_Source"]
            for col_idx, col_name in enumerate(final_df.columns, 1):
                if col_name not in basic_cols:
                    for row_idx in range(2, len(final_df) + 2):
                        worksheet.cell(row=row_idx, column=col_idx).font = bold_font

        print(f"\n그룹별 추출 완료 및 저장 성공: {output_xlsx}")
    else:
        print("\n  ! 추출된 정보가 없습니다.")


if __name__ == "__main__":
    TEST_LOCAL_FOLDER = Path(r"G:\드라이브\EXTRACT-TEST\BEND-test")
    TEST_GDRIVE_FOLDER = Path(r"G:\드라이브\EXTRACT-TEST\BEND-test")
    DB_CSV_PATH = r"G:\드라이브\LNPDB (1).csv"

    LNPDB_COLS = [
        "Aqueous_buffer", "Dialysis_buffer", "Mixing_method",
        "Model", "Model_type", "Model_target",
        "Route_of_administration", "Cargo", "Cargo_type", "Dose_ug_nucleicacid",
        "Experiment_method", "Experiment_batching",
    ]
    MODEL_NAME = "gemini-3.1-pro-preview"

    try:
        api_file_path = find_api_key_file("vertex-490605-8d0be916872a.json")
        vertex_client = get_vertexai_client(api_file_path)
        test_dynamic_schema = get_dynamic_schema_from_db(DB_CSV_PATH, LNPDB_COLS)

        if TEST_LOCAL_FOLDER.exists():
            process_single_paper(
                local_folder=TEST_LOCAL_FOLDER,
                gdrive_base_folder=TEST_GDRIVE_FOLDER,
                client=vertex_client,
                model_name=MODEL_NAME,
                dynamic_schema=test_dynamic_schema,
            )
        else:
            print(f"테스트 폴더를 찾을 수 없습니다: {TEST_LOCAL_FOLDER}")
    except Exception as e:
        print(f"단독 실행 실패: {e}")
