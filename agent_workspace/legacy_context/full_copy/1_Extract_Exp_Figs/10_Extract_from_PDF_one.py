import json
import sys
import time
import hashlib
import re
import pandas as pd
from pathlib import Path
from google.genai import types
from openpyxl.styles import Font

current_dir = Path(__file__).resolve().parent
parent_dir = current_dir.parent
if str(parent_dir) not in sys.path:
    sys.path.append(str(parent_dir))

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
    append_batch_request,
    count_requests_in_jsonl,
    upload_file_to_gcs,
)

TARGET_VISUAL_TYPES = ["barplot", "table", "chemical_structure", "heatmap"]
DEFAULT_GCS_BATCH_BUCKET = "gs://lnpdb-articles-extraction-batch-results-geon"
EMPTY_MANUAL_VALUES = {"", "nan", "none", "null", "[]", "{}"}

def get_fig_selection_value(row):
    manual = str(row.get("manual_select", "")).strip().lower()
    if is_meaningful_manual_value(manual):
        if manual in {"yes", "y", "1", "true"}:
            return "yes"
        if manual in {"no", "n", "0", "false"}:
            return "no"
        if manual == "maybe":
            return "maybe"
        return "no"

    return str(row.get("need_for_lnpdb", "")).strip().lower()

def is_meaningful_manual_value(value) -> bool:
    if value is None:
        return False
    try:
        if pd.isna(value):
            return False
    except (TypeError, ValueError):
        pass
    return str(value).strip().lower() not in EMPTY_MANUAL_VALUES

def load_total_mapping(paper_folder: Path, mapping_json_path=None):
    mapping_file = Path(mapping_json_path) if mapping_json_path is not None else paper_folder / "total_figure_mapping.json"
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
        file_bytes = f.read()
    return types.Part.from_bytes(data=file_bytes, mime_type=get_mime_type(file_path))


def get_md_texts(paper_folder: Path):
    texts = []
    for path in paper_folder.rglob("*.md"):
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



# LNPDB column definitions (hard-coded, source of truth)
LNPDB_COLUMN_DEFINITIONS = {
    "Aqueous_buffer": "Required. Aqueous buffer used in aqueous phase.",
    "Dialysis_buffer": "Required. Dialysis buffer used to dialyze LNPs, if performed. If not performed, put None.",
    "Mixing_method": "Required. Mixing preparation method.",
    "Model": "Required. Either in_vitro or in_vivo.",
    "Model_type": "Required. Model type. If Model is in_vitro, put the cell line name here. If Model is in_vivo, put the animal model here using a Mouse_<model> style value or another paper-supported animal model value.",
    "Model_target": "Required. Target model component being measured. If Model is in_vitro, just put in_vitro here as well. If Model is in_vivo, put the organ/tissue name that is being targeted or specifically measured.",
    "Route_of_administration": "Required. Route of administration of LNPs. If Model is in_vitro, can just put in_vitro here as well. If Model is in_vivo, put delivery route here.",
    "Cargo": "Required. Class of nucleic acid that is the cargo inside LNP.",
    "Cargo_type": "Required. Protein encoded by cargo.",
    "Dose_ug_nucleicacid": "Required. Dose of nucleic acid administered in micrograms.",
    "Experiment_method": "Required. Method used for experimental readout.",
    "Experiment_batching": "Required. Batching method used for experimental readout. Either individual measurements or barcoded.",
}

def get_dynamic_schema_from_db(db_path, target_cols):
    print(f"  -> LNPDB DB 로드 중.. ({db_path})")
    schema_dict = {}
    try:
        df = pd.read_csv(db_path, low_memory=False)
        for col in target_cols:
            examples = []
            if col in df.columns:
                val_counts = df[col].dropna().astype(str).map(str.strip).value_counts()
                valid_vals = [
                    v for v in val_counts.index
                    if v.lower() not in ["", "variable", "various", "nan", "n/a", "none", "null"]
                ]
                examples = valid_vals[:30]

            schema_dict[col] = {
                "column_definition": LNPDB_COLUMN_DEFINITIONS.get(col, ""),
                "examples_from_lnpdb_database": examples,
            }
        return schema_dict
    except Exception as e:
        print(f"    ! DB 읽기 실패: {e}")
        return {
            col: {
                "column_definition": LNPDB_COLUMN_DEFINITIONS.get(col, ""),
                "examples_from_lnpdb_database": [],
            }
            for col in target_cols
        }



def make_pdf_one_custom_id(paper_name: str, item_id: str) -> str:
    seed = f"{paper_name}::{str(item_id).strip().lower()}"
    return "pdf_one__" + hashlib.sha1(seed.encode("utf-8")).hexdigest()[:12]

# ===================== Experiment Deduplication =====================
EXPERIMENT_METADATA_COLUMNS = [
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
]


def normalize_for_experiment_dedup(value) -> str:
    """Normalize cell values only for duplicate experimental-condition detection."""
    if pd.isna(value):
        return "n/a"

    text = str(value).strip()
    text = re.sub(r"\s+", " ", text)

    if not text:
        return "n/a"

    lowered = text.lower()
    if lowered in {
        "na",
        "n/a",
        "none",
        "null",
        "nan",
        "-",
        "not reported",
        "not specified",
        "not mentioned",
        "unknown",
    }:
        return "n/a"

    return lowered


def deduplicate_same_experiment_rows_within_item(
    df: pd.DataFrame,
    experiment_columns: list[str] | None = None,
    item_col: str = "Item_ID",
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Remove duplicated metadata rows within the same Item_ID when all experimental
    metadata columns are identical.

    This is intended for metadata extraction output only. It does not use
    Reasoning, Original_Text_Source, group description, or formulation-related
    labels as deduplication keys.
    """
    if df.empty:
        return df.copy(), df.copy()

    if item_col not in df.columns:
        print(f"  ! metadata dedup skipped: missing item column '{item_col}'")
        return df.copy(), df.iloc[0:0].copy()

    if experiment_columns is None:
        experiment_columns = EXPERIMENT_METADATA_COLUMNS

    work = df.copy()

    for col in experiment_columns:
        if col not in work.columns:
            work[col] = "N/A"

    key_cols = [item_col] + experiment_columns
    norm_key_cols = []

    for col in key_cols:
        norm_col = f"__dedup_norm__{col}"
        work[norm_col] = work[col].apply(normalize_for_experiment_dedup)
        norm_key_cols.append(norm_col)

    duplicated_mask = work.duplicated(subset=norm_key_cols, keep="first")

    kept_df = work.loc[~duplicated_mask].copy()
    removed_df = work.loc[duplicated_mask].copy()

    for out_df in (kept_df, removed_df):
        if not out_df.empty:
            out_df["Dedup_Same_Experiment_Key"] = out_df[norm_key_cols].agg(" | ".join, axis=1)
        else:
            out_df["Dedup_Same_Experiment_Key"] = []
        out_df.drop(columns=norm_key_cols, inplace=True, errors="ignore")

    return kept_df.reset_index(drop=True), removed_df.reset_index(drop=True)


def build_pdf_one_prompt(item_id, dynamic_schema_dict, image_filenames, request_id):
    schema_json_str = json.dumps(dynamic_schema_dict, indent=2, ensure_ascii=False)
    attached_images_str = ", ".join(image_filenames) if image_filenames else "None (Text Only)"
    return f"""
    Using all provided documents (including Markdown text, PDF, and Images), extract the experimental conditions ONLY for the following specific item:
    TARGET ITEM: {item_id}

    [Request Tracking]
    - request_id: {request_id}

    [Attached Image Files]
    The following image files are directly attached for your reference to analyze this item:
    {attached_images_str}

    [LNPDB Column Guide]
    The guide below contains hard-coded LNPDB column definitions and examples observed in the current LNPDB database file. The column definitions are the source of truth for what each column means. The examples from the database are only examples, not a closed vocabulary.
    Format: {{"Column_Name": {{"column_definition": "...", "examples_from_lnpdb_database": ["Example1", "Example2", ...]}}}}

    {schema_json_str}

    * CRITICAL RULE 1: Focus ONLY on the data relevant to '{item_id}'. You MUST actively read the provided image files to confirm exact values or conditions that might be missing from the text.
    * CRITICAL RULE 2: Database examples are just EXAMPLES, not a closed vocabulary. If the text/image contains DIFFERENT or NEW values not listed in this dictionary, you MUST extract and use the NEW paper-supported values.
    * CRITICAL RULE 3:
      - STRICTLY FORBIDDEN: You MUST NOT use the words "variable", "various", or list multiple components with commas in a single cell.
      - If a single figure tests multiple distinct experimental groups, create a separate JSON object for EACH group.
    * CRITICAL RULE 4: If a specific column's value is truly not mentioned for an experimental group, output "N/A".
    * CRITICAL RULE 5: The top-level JSON must contain the same request_id exactly as provided.

    Return Format (JSON):
    {{
      "request_id": "{request_id}",
      "results": [
        {{
          "item_id": "{item_id}",
          "group_desc": "Tested on C57BL/6 mice (1.0 mg/kg)",
          "metadata": {{ "Model": "C57BL/6", "Dose_ug_nucleicacid": "1.0 mg/kg" }},
          "original_text_source": "Provide the exact sentence from text or 'Found in Image Legend'",
          "reasoning": "Why this metadata was assigned to this figure/group",
          "brief_summary": "..."
        }}
      ]
    }}
    """


def parse_pdf_one_response(response_text: str, expected_request_id: str):
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


def extract_metadata_for_item(client, model_name, document_parts, item_id, dynamic_schema_dict, image_filenames, request_id):
    prompt = build_pdf_one_prompt(item_id, dynamic_schema_dict, image_filenames, request_id)
    max_retries = 5

    for attempt in range(max_retries):
        try:
            call_result = generate_content_with_guard(
                client=client,
                model_name=model_name,
                contents=document_parts,
                prompt_text=prompt,
                task_name="extract_pdf_item_metadata_retry",
                response_mime_type="application/json",
                max_retries=1,
            )
            return parse_pdf_one_response(call_result.response_text, request_id)
        except Exception as e:
            error_msg = str(e).lower()
            if "400" in error_msg or "invalid_argument" in error_msg:
                print(f"      ! [400] 프롬프트 재시도 ({attempt + 1}/{max_retries})")
                continue
            print(f"      ! 추출 실패 ({item_id}): {e}")
            return []
    return []


def build_item_context(item_id: str, total_mapping: dict, base_document_parts: list):
    current_contents = list(base_document_parts)
    image_filenames = []
    item_map = None

    for _, sub_doc_dict in total_mapping.items():
        if isinstance(sub_doc_dict, dict) and item_id in sub_doc_dict:
            item_map = sub_doc_dict[item_id]
            break

    if isinstance(item_map, dict):
        full_img = item_map.get("full_image")
        if full_img:
            img_path = Path(full_img)
            img_part = get_document_part(img_path)
            if img_part:
                current_contents.append(img_part)
                image_filenames.append(img_path.name)

        panels_dict = item_map.get("panels", {})
        if panels_dict:
            for _, p_path in panels_dict.items():
                panel_path = Path(p_path)
                img_part = get_document_part(panel_path)
                if img_part:
                    current_contents.append(img_part)
                    image_filenames.append(panel_path.name)
    elif isinstance(item_map, str):
        single_path = Path(item_map)
        img_part = get_document_part(single_path)
        if img_part:
            current_contents.append(img_part)
            image_filenames.append(single_path.name)

    return current_contents, image_filenames, item_map


def process_paper_folder(paper_folder: Path, gdrive_base_folder: Path, client, model_name: str, dynamic_schema, classified_csv_path=None, output_xlsx_path=None, mapping_json_path=None):
    print(f"논문 폴더 분석 시작: {paper_folder.name}")

    csv_path = Path(classified_csv_path) if classified_csv_path is not None else paper_folder / "fig_table_lnpdb_classified.csv"
    if not csv_path.exists():
        print(f"  ! 분류 CSV 파일이 없습니다 ({csv_path}).")
        return

    total_mapping = load_total_mapping(paper_folder, mapping_json_path=mapping_json_path)

    try:
        df = pd.read_csv(csv_path)
        df["_fig_select"] = df.apply(get_fig_selection_value, axis=1)

        if "manual_select" in df.columns:
            manual_mask = df["manual_select"].apply(is_meaningful_manual_value)
        else:
            manual_mask = pd.Series(False, index=df.index)
        selected_mask = df["_fig_select"].isin(["yes", "maybe"])
        visual_mask = df["visual_type"].astype(str).str.lower().isin(TARGET_VISUAL_TYPES)
        target_mask = (manual_mask & selected_mask) | (~manual_mask & visual_mask & selected_mask)
        manual_selected_count = int((manual_mask & selected_mask).sum())
        manual_excluded_count = int((manual_mask & ~selected_mask).sum())
        auto_selected_count = int((~manual_mask & visual_mask & selected_mask).sum())
        print(f"  - rows selected by manual_select override: {manual_selected_count}")
        print(f"  - rows selected by automatic criteria: {auto_selected_count}")
        print(f"  - rows excluded by manual_select=no/invalid: {manual_excluded_count}")

        target_items = df[target_mask]["item_id"].tolist()

        if not target_items:
            print("  ! 추출 대상 Figure/Table이 없습니다.")
            return

        total_count = len(target_items)
        print(f"\n[CSV 연동 완료] 추출 대상 {total_count}개 item")
    except Exception as e:
        print(f"  ! CSV 처리 오류: {e}")
        return

    allowed_extensions = {".md", ".pdf"}
    document_files = [
        f for f in paper_folder.rglob("*")
        if f.is_file() and f.suffix.lower() in allowed_extensions and not f.name.startswith("~")
    ]

    base_document_parts = []
    print(f"  - 문서 파트({len(document_files)}개) 로드 중..")
    for doc_path in document_files:
        part = get_document_part(doc_path)
        if part:
            base_document_parts.append(part)

    md_texts = get_md_texts(paper_folder)
    pdf_paths = [f for f in paper_folder.rglob("*.pdf") if f.is_file() and not f.name.startswith("~")]
    upload_cache = {}
    shared_batch_contents = [text for text in md_texts if text.strip()]
    for pdf_path in pdf_paths:
        shared_batch_contents.append(upload_file_part_cached(pdf_path, paper_folder, upload_cache))

    request_file = create_batch_request_file(paper_folder, f"pdf_one_metadata_{paper_folder.name}")
    request_specs = {}
    start_time = time.time()

    print("\n[정보 추출] item 단위 batch 큐 구성 시작...")
    for i, item_id in enumerate(target_items, 1):
        if i == 1:
            eta_str = "계산 중.."
        else:
            elapsed_time = time.time() - start_time
            avg_time_per_item = elapsed_time / (i - 1)
            remaining_items = total_count - (i - 1)
            eta_seconds = int(avg_time_per_item * remaining_items)
            m, s = divmod(eta_seconds, 60)
            eta_str = f"{m}분 {s}초"

        print(f"  -> [{i}/{total_count}] {item_id} 큐 등록 중.. (남은 시간: {eta_str})", end=" ")

        current_contents, image_filenames, item_map = build_item_context(item_id, total_mapping, base_document_parts)
        batch_contents = list(shared_batch_contents)

        if isinstance(item_map, dict):
            full_img = item_map.get("full_image")
            if full_img:
                batch_contents.append(upload_file_part_cached(Path(full_img), paper_folder, upload_cache))
            for p_path in item_map.get("panels", {}).values():
                batch_contents.append(upload_file_part_cached(Path(p_path), paper_folder, upload_cache))
        elif isinstance(item_map, str):
            batch_contents.append(upload_file_part_cached(Path(item_map), paper_folder, upload_cache))

        custom_id = make_pdf_one_custom_id(paper_folder.name, item_id)
        prompt = build_pdf_one_prompt(item_id, dynamic_schema, image_filenames, custom_id)
        request_body = build_generate_content_batch_request(
            model_name=model_name,
            contents=batch_contents,
            prompt_text=prompt,
            response_mime_type="application/json",
        )
        metadata = build_batch_request_metadata(
            task_name="extract_pdf_item_metadata",
            model_name=model_name,
            custom_id=custom_id,
            stage_name="extract_pdf_item_metadata",
            item_id=item_id,
            paper_folder=str(paper_folder),
            extra_metadata={"item_id": item_id},
        )
        append_batch_request(request_file, custom_id, request_body, metadata)
        request_specs[custom_id] = {
            "item_id": item_id,
            "current_contents": current_contents,
            "image_filenames": image_filenames,
        }
        print("queued")

    if not request_specs:
        print("\n  ! batch request가 없습니다.")
        return

    local_job_id = create_batch_job_record(
        paper_folder=paper_folder,
        task_name="extract_pdf_item_metadata",
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
        paper_folder=paper_folder,
        local_job_id=local_job_id,
        display_name=f"pdf-one-{paper_folder.name}",
    )
    print(f"\n  ✅ Batch 제출 완료: {batch_job.name}")
    finished_job = poll_batch_job(client, paper_folder, local_job_id, poll_interval_seconds=30)
    state_name = getattr(getattr(finished_job, "state", None), "name", None) or str(getattr(finished_job, "state", "UNKNOWN"))

    batch_results_map = {}
    if state_name == "JOB_STATE_SUCCEEDED":
        result_file = download_batch_results(client, paper_folder, local_job_id)
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
            all_final_data.extend(parse_pdf_one_response(row.get("response_text", ""), custom_id))
        except Exception as e:
            print(f"  ! batch parse 실패 ({spec['item_id']}): {e}")
            failed_request_ids.append(custom_id)

    if failed_request_ids:
        print(f"\n  - 실패 item {len(failed_request_ids)}건 online 재시도")
    for custom_id in failed_request_ids:
        spec = request_specs[custom_id]
        item_results = extract_metadata_for_item(
            client=client,
            model_name=model_name,
            document_parts=spec["current_contents"],
            item_id=spec["item_id"],
            dynamic_schema_dict=dynamic_schema,
            image_filenames=spec["image_filenames"],
            request_id=custom_id,
        )
        if item_results:
            all_final_data.extend(item_results)
        else:
            print(f"  ! 재시도 실패 ({spec['item_id']})")

    if all_final_data:
        rows = []
        for entry in all_final_data:
            figure_item_id = str(entry.get("item_id", "N/A") or "N/A").strip()
            group_desc = str(entry.get("group_desc", "") or "").strip()
            brief_summary = str(entry.get("brief_summary", "") or "").strip()
            reasoning = str(entry.get("reasoning", "") or "").strip()

            if not reasoning:
                if group_desc and brief_summary:
                    reasoning = f"{group_desc} | {brief_summary}"
                elif group_desc:
                    reasoning = group_desc
                elif brief_summary:
                    reasoning = brief_summary
                else:
                    reasoning = "N/A"

            row = {
                "Excel_File_Name": "N/A",
                "Excel_Sheet_Name": "N/A",
                "Block_ID": "N/A",
                "Block_CSV_Path": "N/A",
                "Item_ID": figure_item_id,
                "source_item_id": figure_item_id,
                "figure_item_id": figure_item_id,
                "figure_label": figure_item_id,
                "split_reason": "single_figure_pdf_extraction",
                "source_row_count": "1",
                "Reasoning": reasoning,
                "Original_Text_Source": entry.get("original_text_source", "N/A"),
            }
            row.update(entry.get("metadata", {}))
            rows.append(row)

        final_df = pd.DataFrame(rows)

        before_dedup_rows = len(final_df)
        final_df, removed_dedup_df = deduplicate_same_experiment_rows_within_item(
            final_df,
            experiment_columns=EXPERIMENT_METADATA_COLUMNS,
            item_col="Item_ID",
        )
        after_dedup_rows = len(final_df)
        removed_dedup_rows = before_dedup_rows - after_dedup_rows
        print(
            f"  - 동일 Item_ID 내 동일 실험조건 dedup: "
            f"{before_dedup_rows} -> {after_dedup_rows} rows "
            f"(removed={removed_dedup_rows})"
        )

        preferred_order = [
            "Excel_File_Name", "Excel_Sheet_Name", "Block_ID", "Block_CSV_Path",
            "Item_ID", "source_item_id", "figure_item_id", "figure_label",
            "split_reason", "source_row_count", "Reasoning", "Original_Text_Source",
        ]
        other_cols = [c for c in final_df.columns if c not in preferred_order]
        final_df = final_df[[c for c in preferred_order if c in final_df.columns] + other_cols]

        if not removed_dedup_df.empty:
            removed_other_cols = [c for c in removed_dedup_df.columns if c not in preferred_order]
            removed_dedup_df = removed_dedup_df[
                [c for c in preferred_order if c in removed_dedup_df.columns] + removed_other_cols
            ]

        target_gdrive_folder = gdrive_base_folder
        target_gdrive_folder.mkdir(parents=True, exist_ok=True)
        output_xlsx = Path(output_xlsx_path) if output_xlsx_path is not None else target_gdrive_folder / f"1_{paper_folder.name}_one_metadata.xlsx"

        with pd.ExcelWriter(output_xlsx, engine="openpyxl") as writer:
            final_df.to_excel(writer, index=False, sheet_name="Extracted_Data")
            if not removed_dedup_df.empty:
                removed_dedup_df.to_excel(writer, index=False, sheet_name="Dedup_Removed_Rows")
            worksheet = writer.sheets["Extracted_Data"]
            bold_font = Font(bold=True)

            basic_cols = [
                "Excel_File_Name", "Excel_Sheet_Name", "Block_ID", "Block_CSV_Path",
                "Item_ID", "source_item_id", "figure_item_id", "figure_label",
                "split_reason", "source_row_count", "Reasoning", "Original_Text_Source",
            ]
            for col_idx, col_name in enumerate(final_df.columns, 1):
                if col_name not in basic_cols:
                    for row_idx in range(2, len(final_df) + 2):
                        worksheet.cell(row=row_idx, column=col_idx).font = bold_font

        print(f"\n추출 완료 및 저장 성공: {output_xlsx}")
    else:
        print("\n  ! 추출된 정보가 없습니다.")


def run_extraction_pipeline(target_root_str, gdrive_base_str, db_csv_str, target_cols, model_name, api_json_name):
    target_root_folder = Path(target_root_str)
    gdrive_base_folder = Path(gdrive_base_str)

    try:
        api_file_path = find_api_key_file(api_json_name)
        with open(api_file_path, "r", encoding="utf-8") as f:
            cred_data = json.load(f)

        project_id = cred_data.get("project_id")
        if not project_id:
            raise ValueError(f"서비스 계정 JSON에 project_id가 없습니다: {api_file_path}")

        print(f"Vertex 프로젝트 설정: {project_id}")
        client = get_vertexai_client(api_file_path, project=project_id)
    except Exception as e:
        print(f"API 키 로드 실패: {e}")
        return

    dynamic_schema = get_dynamic_schema_from_db(db_csv_str, target_cols)

    if not target_root_folder.exists():
        print(f"대상 폴더를 찾을 수 없습니다: {target_root_folder}")
        return

    paper_folders = [f for f in target_root_folder.iterdir() if f.is_dir() and not f.name.startswith(".")]
    print(f"\n'{target_root_folder.name}' 아래 논문 폴더 {len(paper_folders)}개 발견")

    for paper_folder in paper_folders:
        print("\n" + "=" * 50)
        try:
            process_paper_folder(
                paper_folder=paper_folder,
                gdrive_base_folder=gdrive_base_folder,
                client=client,
                model_name=model_name,
                dynamic_schema=dynamic_schema,
            )
        except Exception as e:
            print(f"  !! {paper_folder.name} 처리 중 오류: {e}")


if __name__ == "__main__":
    TEST_LOCAL_FOLDER = Path(r"/Users/kogeon/python_projects_path/LNPDB_Articles_Extraction/Extraction_Examples/36")
    TEST_GDRIVE_FOLDER = Path(r"/Users/kogeon/python_projects_path/LNPDB_Articles_Extraction/Extraction_Examples/36")
    DB_CSV_PATH = r"/Users/kogeon/Library/CloudStorage/GoogleDrive-geon@molcube.com/내 드라이브/LNPDB (1).csv"

    LNPDB_COLS = [
        "Aqueous_buffer", "Dialysis_buffer", "Mixing_method",
        "Model", "Model_type", "Model_target",
        "Route_of_administration", "Cargo", "Cargo_type", "Dose_ug_nucleicacid",
        "Experiment_method", "Experiment_batching",
    ]

    MODEL_NAME = "gemini-3.1-pro-preview"
    API_JSON_NAME = "vertex.json"

    try:
        api_file_path = find_api_key_file(API_JSON_NAME)
        with open(api_file_path, "r", encoding="utf-8") as f:
            cred_data = json.load(f)

        project_id = cred_data.get("project_id")
        if not project_id:
            raise ValueError(f"서비스 계정 JSON에 project_id가 없습니다: {api_file_path}")

        vertex_client = get_vertexai_client(api_file_path, project=project_id)
        test_dynamic_schema = get_dynamic_schema_from_db(DB_CSV_PATH, LNPDB_COLS)

        if TEST_LOCAL_FOLDER.exists():
            process_paper_folder(
                paper_folder=TEST_LOCAL_FOLDER,
                gdrive_base_folder=TEST_GDRIVE_FOLDER,
                client=vertex_client,
                model_name=MODEL_NAME,
                dynamic_schema=test_dynamic_schema,
            )
        else:
            print(f"대상 폴더를 찾을 수 없습니다: {TEST_LOCAL_FOLDER}")
    except Exception as e:
        print(f"실행 실패: {e}")
