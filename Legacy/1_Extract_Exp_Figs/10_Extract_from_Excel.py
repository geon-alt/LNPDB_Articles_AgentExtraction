import json
import math
import csv
import io
import hashlib
import pandas as pd
from pathlib import Path
import re

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
import sys
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


def list_pdf_paths(folder: Path) -> list[Path]:
    return sorted(
        [
            f for f in folder.rglob("*.pdf")
            if f.is_file() and not f.name.startswith("~") and "Exp_Excel" not in f.parts
        ]
    )


def upload_pdfs_to_gcs(folder: Path, gcs_batch_bucket: str) -> list[dict]:
    pdf_paths = list_pdf_paths(folder)
    uploaded = []
    for pdf_path in pdf_paths:
        gcs_uri = f"{gcs_batch_bucket}/papers/{folder.name}/{pdf_path.name}"
        upload_file_to_gcs(pdf_path, gcs_uri)
        uploaded.append({
            "local_path": str(pdf_path),
            "gcs_uri": gcs_uri,
            "mime_type": "application/pdf",
            "name": pdf_path.name,
        })
    return uploaded


def build_pdf_file_parts(uploaded_pdfs: list[dict]) -> list[dict]:
    parts = []
    for item in uploaded_pdfs:
        gcs_uri = str(item.get("gcs_uri", "")).strip()
        mime_type = str(item.get("mime_type", "application/pdf")).strip() or "application/pdf"
        if not gcs_uri:
            continue
        parts.append({"fileData": {"fileUri": gcs_uri, "mimeType": mime_type}})
    return parts


def get_md_text(folder: Path) -> str:
    texts = []
    for path in folder.rglob("*.md"):
        if path.is_file() and not path.name.startswith("~") and "Exp_Excel" not in path.parts:
            try:
                texts.append(path.read_text(encoding="utf-8"))
            except UnicodeDecodeError:
                texts.append(path.read_text(encoding="utf-8", errors="replace"))
    return "\n\n".join(texts)


LNPDB_COLUMN_DEFINITIONS = {
    "Aqueous_buffer": "Required. Aqueous buffer used in aqueous phase.",
    "Dialysis_buffer": "Required. Dialysis buffer used to dialyze LNPs, if performed. If not performed, put None.",
    "Mixing_method": "Required. Mixing preparation method.",
    "Model": "Required. Either in_vitro or in_vivo.",
    "Model_type": """Required. Model type. If Model is in_vitro, put the cell line name here. If Model is in_vivo, put the animal model here such as Mouse_{model}.""",
    "Model_target": "Required. Target model component being measured. If Model is in_vitro, just put in_vitro here as well. If Model is in_vivo, put the organ/tissue name that is being targeted or specifically measured.",
    "Route_of_administration": "Required. Route of administration of LNPs. If Model is in_vitro, can just put in_vitro here as well. If Model is in_vivo, put delivery route here.",
    "Cargo": "Required. Class of nucleic acid that is the cargo inside LNP.",
    "Cargo_type": "Required. Protein encoded by cargo.",
    "Dose_ug_nucleicacid": "Required. Dose of nucleic acid administered in micrograms.",
    "Experiment_method": "Required. Method used for experimental readout.",
    "Experiment_batching": "Required. Batching method used for experimental readout. Either individual measurements or barcoded.",
}


def _clean_schema_text(value) -> str:
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except Exception:
        pass
    text = str(value).strip()
    text = re.sub(r"\s+", " ", text)
    return text


def _read_lnpdb_database(db_path) -> pd.DataFrame:
    """Read the actual LNPDB database file.

    The DB file is expected to contain data columns only. Column definitions are
    hard-coded in LNPDB_COLUMN_DEFINITIONS, not read from the DB file.
    """
    df = pd.read_csv(db_path, dtype=str, low_memory=False).fillna("")

    # If a template-like file is accidentally supplied, recover by finding the
    # real header row. For the normal LNPDB database this branch is not used.
    if "Experiment_ID" not in df.columns:
        raw_df = pd.read_csv(db_path, header=None, dtype=str, low_memory=False).fillna("")
        header_row_idx = None
        for row_idx, row in raw_df.iterrows():
            cells = [_clean_schema_text(x) for x in row.tolist()]
            if "Experiment_ID" in cells and "Cargo_type" in cells and "Experiment_method" in cells:
                header_row_idx = int(row_idx)
                break
        if header_row_idx is not None:
            header = [_clean_schema_text(x) for x in raw_df.iloc[header_row_idx].tolist()]
            df = raw_df.iloc[header_row_idx + 1:].copy()
            df.columns = header
            df = df.loc[:, [c for c in df.columns if c]]

    return df


def load_dynamic_schema(db_path, target_cols):
    try:
        df = _read_lnpdb_database(db_path)

        schema = {}
        for col in target_cols:
            examples = []
            if col in df.columns:
                values = df[col].dropna().astype(str).map(str.strip)
                values = values[~values.str.lower().isin(["", "nan", "none", "null", "n/a"])]
                examples = values.drop_duplicates().head(30).tolist()

            schema[col] = {
                "column_definition": LNPDB_COLUMN_DEFINITIONS.get(col, ""),
                "examples_from_lnpdb_database": examples,
            }

        return schema
    except Exception as e:
        print(f"  ! DB 스키마 로드 실패: {e}")
        return {
            col: {
                "column_definition": LNPDB_COLUMN_DEFINITIONS.get(col, ""),
                "examples_from_lnpdb_database": [],
            }
            for col in target_cols
        }


def get_block_csv_content(folder: Path, block_csv_path: str, excel_file: str = "", excel_sheet: str = ""):
    block_csv_path = str(block_csv_path or "").strip()
    if block_csv_path:
        csv_path = folder / block_csv_path
        if csv_path.exists():
            try:
                df = pd.read_csv(csv_path, dtype=str).fillna("")
                return df.to_csv(index=False)
            except Exception as e:
                print(f"  ! block csv 로드 실패 ({block_csv_path}): {e}")

    exp_folder = folder / "Exp_Excel"
    file_path = exp_folder / excel_file
    if not file_path.exists():
        return ""
    try:
        if file_path.suffix.lower() == ".csv":
            df = pd.read_csv(file_path, dtype=str).fillna("")
        else:
            xls = pd.ExcelFile(file_path)
            df = pd.read_excel(xls, sheet_name=excel_sheet, dtype=str).fillna("")
        return df.to_csv(index=False)
    except Exception:
        return ""


def estimate_text_size_for_gemini(text: str) -> dict:
    if text is None:
        text = ""
    char_count = len(text)
    word_count = len(text.split()) if text else 0
    return {
        "char_count": char_count,
        "word_count": word_count,
        "approx_tokens": max(math.ceil(char_count / 4), math.ceil(word_count * 1.3)),
    }


def is_numeric_like(value: str) -> bool:
    if value is None:
        return False
    s = str(value).strip()
    if not s:
        return False
    s_lower = s.lower()
    if s_lower in {"nan", "na", "n/a", "none", "null", "inf", "-inf"}:
        return True
    s_clean = s.replace(",", "")
    percent_clean = s_clean[:-1] if s_clean.endswith("%") else s_clean
    if percent_clean.replace(".", "", 1).replace("-", "", 1).isdigit():
        return True
    return False


def strip_numeric_cells_from_csv(csv_text: str) -> str:
    if not csv_text or not csv_text.strip():
        return csv_text
    try:
        input_io = io.StringIO(csv_text)
        reader = csv.reader(input_io)
        output_io = io.StringIO()
        writer = csv.writer(output_io, lineterminator="\n")
        for row_idx, row in enumerate(reader):
            if row_idx == 0:
                writer.writerow(row)
                continue
            writer.writerow(["" if is_numeric_like(cell) else cell for cell in row])
        cleaned_text = output_io.getvalue().strip()
        return cleaned_text if cleaned_text else csv_text
    except Exception:
        return csv_text


def prepare_csv_for_prompt(csv_text: str, soft_token_limit: int = 80000):
    if not csv_text:
        return ""
    est = estimate_text_size_for_gemini(csv_text)
    if est["approx_tokens"] <= soft_token_limit:
        return csv_text
    stripped_csv = strip_numeric_cells_from_csv(csv_text)
    stripped_est = estimate_text_size_for_gemini(stripped_csv)
    if stripped_est["approx_tokens"] < est["approx_tokens"]:
        return stripped_csv
    return csv_text


def make_extraction_custom_id(block_csv_path: str) -> str:
    seed = str(block_csv_path).strip()
    return "metadata_extract__" + hashlib.sha1(seed.encode("utf-8")).hexdigest()[:12]


def is_valid_block_csv_path(value) -> bool:
    if value is None:
        return False
    text = str(value).strip()
    if not text:
        return False
    if text.lower() in {"nan", "none", "null", "n/a"}:
        return False
    return True


def get_fig_selection_value(row):
    manual = str(row.get("manual_select", "")).strip().lower()
    if manual in {"yes", "y", "1", "true", "o"}:
        return "yes"
    if manual in {"no", "n", "0", "false", "x"}:
        return "no"
    return str(row.get("need_for_lnpdb", "")).strip().lower()


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
    """Normalize cell values only for duplicate experimental-condition detection.

    This function must be robust to Gemini returning non-scalar metadata values
    such as list, tuple, dict, or numpy-like arrays.
    """
    # 1) None 처리
    if value is None:
        return "n/a"

    # 2) list / tuple / set 처리
    # 예: ["C57BL/6", "BALB/c"] -> "C57BL/6; BALB/c"
    if isinstance(value, (list, tuple, set)):
        if len(value) == 0:
            return "n/a"
        value = "; ".join(str(v) for v in value if str(v).strip())

    # 3) dict 처리
    # 예: {"cell": "HEK293", "animal": "mouse"} -> JSON string
    elif isinstance(value, dict):
        if len(value) == 0:
            return "n/a"
        value = json.dumps(value, ensure_ascii=False, sort_keys=True)

    # 4) numpy array / pandas array 계열 처리
    # np.ndarray를 직접 import하지 않아도 동작하도록 tolist() 기반으로 처리
    elif hasattr(value, "tolist") and not isinstance(value, str):
        try:
            listed = value.tolist()
            if isinstance(listed, list):
                if len(listed) == 0:
                    return "n/a"
                value = "; ".join(str(v) for v in listed if str(v).strip())
            else:
                value = listed
        except Exception:
            value = str(value)

    # 5) scalar 값에 대해서만 pd.isna 적용
    try:
        if pd.isna(value):
            return "n/a"
    except Exception:
        value = str(value)

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


def build_extraction_prompt(excel_file, excel_sheet, block_id, block_csv_path, items, current_csv_data, schema_json_str, request_id):
    return f"""
    You are analyzing a paper's experimental data block and must extract metadata only for the mapped figures.

    [Request Tracking]
    - request_id: {request_id}

    [Block Info]
    - Excel_File_Name: {excel_file}
    - Excel_Sheet_Name: {excel_sheet}
    - Block_ID: {block_id}
    - Block_CSV_Path: {block_csv_path}
    - Mapped Figure Items: {items}

    [Raw Experimental Data (Block CSV)]
    {current_csv_data}

    [LNPDB Column Guide]
    The guide below contains hard-coded LNPDB column definitions and examples observed in the current LNPDB database file. The column definitions are the source of truth for what each column means. The examples from the database are only examples, not a closed vocabulary.

    {schema_json_str}

    Rules:
    1. Match this block to the relevant mapped figures using the PDF and markdown context.
    2. Extract metadata from this block for the matched figures.
    3. If a block contains multiple figure conditions, split them into separate JSON objects.
    4. Use request_id exactly as given in the top-level JSON response.
    5. Return JSON only.

    {{
      "request_id": "{request_id}",
      "results": [
        {{
          "Excel_File_Name": "{excel_file}",
          "Excel_Sheet_Name": "{excel_sheet}",
          "Block_ID": "{block_id}",
          "Block_CSV_Path": "{block_csv_path}",
          "item_id": "figure 2a",
          "metadata": {{ "Model": "C57BL/6", "Dose_ug_nucleicacid": "1.0 mg/kg" }},
          "original_text_source": "source sentence",
          "reasoning": "why this block maps to this figure"
        }}
      ]
    }}
    """


def validate_extraction_result_rows(results):
    if not isinstance(results, list) or not results:
        raise ValueError("missing_results")

    for idx, res in enumerate(results):
        if not isinstance(res, dict):
            raise ValueError(f"result_not_dict::{idx}")
        if not str(res.get("item_id", "")).strip():
            raise ValueError(f"missing_item_id::{idx}")
        if "metadata" not in res or not isinstance(res.get("metadata"), dict):
            raise ValueError(f"missing_metadata::{idx}")
        if not str(res.get("original_text_source", "")).strip():
            raise ValueError(f"missing_original_text_source::{idx}")
        if not str(res.get("reasoning", "")).strip():
            raise ValueError(f"missing_reasoning::{idx}")


def run_extraction_batch(folder: Path, client, model_name: str, block_to_items: dict, block_to_meta: dict, uploaded_pdfs: list, md_text: str, dynamic_schema: dict, task_suffix: str = ""):
    request_file = create_batch_request_file(folder, f"metadata_extraction_{folder.name}{task_suffix}")
    shared_contents = build_pdf_file_parts(uploaded_pdfs)
    if md_text.strip():
        shared_contents.append(md_text)

    schema_json_str = json.dumps(dynamic_schema, indent=2, ensure_ascii=False)

    for block_csv_path, items in block_to_items.items():
        if not is_valid_block_csv_path(block_csv_path):
            print(f"  ! invalid block csv path라 batch 요청에서 제외됨: {block_csv_path}")
            continue

        meta = block_to_meta.get(block_csv_path, {})
        excel_file = meta.get("excel_file", "")
        excel_sheet = meta.get("excel_sheet", "")
        block_id = meta.get("block_id", "")

        full_csv_content = get_block_csv_content(folder, block_csv_path, excel_file, excel_sheet)
        if not full_csv_content:
            print(f"  ! block csv 내용이 비어 batch 요청에서 제외됨: {block_csv_path}")
            continue

        current_csv_data = prepare_csv_for_prompt(full_csv_content)
        custom_id = make_extraction_custom_id(block_csv_path)
        prompt = build_extraction_prompt(
            excel_file=excel_file,
            excel_sheet=excel_sheet,
            block_id=block_id,
            block_csv_path=block_csv_path,
            items=items,
            current_csv_data=current_csv_data,
            schema_json_str=schema_json_str,
            request_id=custom_id,
        )

        metadata = build_batch_request_metadata(
            task_name="metadata_extraction",
            model_name=model_name,
            custom_id=custom_id,
            stage_name="metadata_extraction",
            item_id=block_csv_path,
            paper_folder=str(folder),
            extra_metadata={
                "excel_file": excel_file,
                "excel_sheet": excel_sheet,
                "block_id": block_id,
                "block_csv_path": block_csv_path,
            },
        )
        request_body = build_generate_content_batch_request(
            model_name=model_name,
            contents=list(shared_contents),
            prompt_text=prompt,
            response_mime_type="application/json",
        )
        append_batch_request(request_file, custom_id, request_body, metadata)

    request_count = count_requests_in_jsonl(request_file)
    print(f"  - metadata extraction batch 실제 요청 개수: {request_count}")
    if request_count == 0:
        print("  ! metadata extraction batch 요청이 0건이라 batch 제출을 건너뜁니다.")
        return {}

    local_job_id = create_batch_job_record(
        paper_folder=folder,
        task_name="metadata_extraction",
        model_name=model_name,
        request_file=request_file,
        metadata={
            "request_count": request_count,
            "gcs_input_uri": f"{DEFAULT_GCS_BATCH_BUCKET}/batch/{request_file.name}",
            "gcs_output_uri_prefix": f"{DEFAULT_GCS_BATCH_BUCKET}/batch_output/{request_file.stem}",
        },
    )

    batch_job = submit_batch_job(
        client=client,
        paper_folder=folder,
        local_job_id=local_job_id,
        display_name=f"metadata-extract-{folder.name}{task_suffix}",
    )
    print(f"  ✅ Batch 제출 완료: {batch_job.name}")

    finished_job = poll_batch_job(client, folder, local_job_id, poll_interval_seconds=30)
    state_name = getattr(getattr(finished_job, "state", None), "name", None) or str(getattr(finished_job, "state", "UNKNOWN"))
    print(f"  ✅ Batch 종료 상태: {state_name}")
    if state_name != "JOB_STATE_SUCCEEDED":
        raise RuntimeError(f"metadata_extraction batch 실패: {state_name}")

    result_file = download_batch_results(client, folder, local_job_id)
    return load_batch_results_as_map(result_file)


def consume_extraction_batch_results(batch_results_map, block_paths, block_to_meta, model_name: str):
    all_final_data = []
    usage_rows = []
    failed_blocks = []

    for block_csv_path in block_paths:
        if not is_valid_block_csv_path(block_csv_path):
            print(f"  ! invalid block csv path라 결과 소비에서 제외됨: {block_csv_path}")
            continue

        custom_id = make_extraction_custom_id(block_csv_path)
        row = batch_results_map.get(custom_id)
        meta_info = block_to_meta.get(block_csv_path, {})

        if not row or not row.get("success") or not str(row.get("response_text", "")).strip():
            print(f"⚠️ Batch 누락/실패 (재시도 대기): {block_csv_path}")
            if is_valid_block_csv_path(block_csv_path):
                failed_blocks.append(block_csv_path)
            continue

        cost_info = row.get("cost_info") or {}
        usage_rows.append({
            "block_csv_path": block_csv_path,
            "task_name": "metadata_extraction",
            "model_name": model_name,
            "input_tokens": row.get("input_tokens"),
            "output_tokens": row.get("output_tokens"),
            "total_tokens": row.get("total_tokens"),
            "billed_output_tokens": row.get("billed_output_tokens"),
            "total_cost_usd": cost_info.get("total_cost_usd", 0.0),
        })

        clean_text = str(row.get("response_text", "")).replace("```json", "").replace("```", "").strip()
        try:
            data = json.loads(clean_text)
            if not isinstance(data, dict):
                raise ValueError("response_not_dict")

            response_request_id = str(data.get("request_id", "")).strip()
            if not response_request_id:
                raise ValueError("missing_request_id")
            if response_request_id != custom_id:
                raise ValueError(f"request_id_mismatch::{response_request_id}")

            results = data.get("results")
            validate_extraction_result_rows(results)

            for res in results:
                res["Excel_File_Name"] = meta_info.get("excel_file", "N/A")
                res["Excel_Sheet_Name"] = meta_info.get("excel_sheet", "N/A")
                res["Block_ID"] = meta_info.get("block_id", "N/A")
                res["Block_CSV_Path"] = block_csv_path

            all_final_data.extend(results)
        except Exception as e:
            print(f"⚠️ JSON 검증 실패 (재시도 대기) ({block_csv_path}): {e}")
            if is_valid_block_csv_path(block_csv_path):
                failed_blocks.append(block_csv_path)

    return all_final_data, usage_rows, failed_blocks


def process_sheet_base_extraction(folder: Path, gdrive_folder: Path, client, model_name: str, dynamic_schema):
    print(f"📊 [시트 중첩 메타데이터 추출] 멀티모달 BATCH 분석 시작: {folder.name}")

    csv_path = folder / "fig_table_lnpdb_classified.csv"
    if not csv_path.exists():
        return
    df = pd.read_csv(csv_path, low_memory=False)
    df["_fig_select"] = df.apply(get_fig_selection_value, axis=1)
    df["_visual_type_norm"] = (
        df["visual_type"]
        .astype(str)
        .str.strip()
        .str.lower()
        .replace({"raw_data_table": "table"})
    )

    valid_items = (
        df[
            df["_fig_select"].isin(["yes", "maybe"])
            & df["_visual_type_norm"].isin(TARGET_VISUAL_TYPES)
        ]["item_id"]
        .astype(str)
        .str.strip()
        .unique()
        .tolist()
    )
    valid_item_set = {str(item).lower().strip() for item in valid_items}

    print(f"  - valid_items 개수: {len(valid_items)}")
    if valid_items:
        print("  - valid_items 예시:")
        for x in valid_items[:30]:
            print(f"    * {x}")

    map_path = folder / "excel_mapping.json"
    if not map_path.exists():
        return
    with open(map_path, "r", encoding="utf-8") as f:
        excel_mapping = json.load(f)

    invalid_block_path_excluded_count = 0
    classified_block_map = {}
    if "matched_block_csv_path" in df.columns:
        for _, row in df.iterrows():
            item_id = str(row.get("item_id", "")).lower().strip()
            if item_id not in valid_item_set:
                continue
            raw_paths = str(row.get("matched_block_csv_path", "")).strip()
            if not raw_paths:
                continue
            for p in [x.strip() for x in raw_paths.split(" | ") if is_valid_block_csv_path(x)]:
                classified_block_map.setdefault(p, [])
                if item_id not in classified_block_map[p]:
                    classified_block_map[p].append(item_id)
            invalid_block_path_excluded_count += sum(
                1 for x in raw_paths.split(" | ") if not is_valid_block_csv_path(x)
            )

    block_to_items = {}
    block_to_meta = {}

    for item_id, mappings in excel_mapping.items():
        clean_item_id = item_id.lower().strip()
        if clean_item_id not in valid_item_set:
            continue
        for m in mappings:
            block_csv_path = str(m.get("block_csv_path", "")).strip()
            if not is_valid_block_csv_path(block_csv_path):
                invalid_block_path_excluded_count += 1
                continue
            block_to_items.setdefault(block_csv_path, [])
            if clean_item_id not in block_to_items[block_csv_path]:
                block_to_items[block_csv_path].append(clean_item_id)

            if block_csv_path not in block_to_meta:
                block_to_meta[block_csv_path] = {
                    "excel_file": str(m.get("excel_file", "")).strip(),
                    "excel_sheet": str(m.get("excel_sheet", "")).strip(),
                    "block_id": str(m.get("block_id", "")).strip(),
                    "block_csv_path": block_csv_path,
                }

    for block_csv_path, items in classified_block_map.items():
        block_to_items.setdefault(block_csv_path, [])
        for item in items:
            if item not in block_to_items[block_csv_path]:
                block_to_items[block_csv_path].append(item)
        if block_csv_path not in block_to_meta:
            parts = Path(block_csv_path).parts
            block_to_meta[block_csv_path] = {
                "excel_file": f"{parts[-3]}.xlsx" if len(parts) >= 3 else "",
                "excel_sheet": parts[-2] if len(parts) >= 3 else "",
                "block_id": Path(block_csv_path).stem,
                "block_csv_path": block_csv_path,
            }

    valid_block_to_items = {}
    valid_block_to_meta = {}

    for block_csv_path, items in block_to_items.items():
        if not is_valid_block_csv_path(block_csv_path):
            invalid_block_path_excluded_count += 1
            continue
        clean_items = [str(x).strip().lower() for x in items if str(x).strip()]
        clean_items = list(dict.fromkeys(clean_items))
        if not clean_items:
            continue
        valid_block_to_items[block_csv_path] = clean_items
        if block_csv_path in block_to_meta:
            valid_block_to_meta[block_csv_path] = block_to_meta[block_csv_path]

    block_to_items = valid_block_to_items
    block_to_meta = valid_block_to_meta

    print(f"  - invalid block path 때문에 제외된 개수: {invalid_block_path_excluded_count}")
    print(f"  - 실제 매핑된 유효 block CSV 개수: {len(block_to_items)}")
    if block_to_items:
        print("  - 실제 유효 block CSV 목록:")
        for p in sorted(block_to_items.keys()):
            print(f"    * {p}")

    if not block_to_items:
        print("  ! 추출할 유효 block CSV가 없습니다.")
        return

    print("  - PDF 문서 GCS 업로드 및 텍스트 취합 중..")
    uploaded_pdfs = upload_pdfs_to_gcs(folder, DEFAULT_GCS_BATCH_BUCKET)
    md_text = get_md_text(folder)

    batch_results_map = run_extraction_batch(
        folder=folder,
        client=client,
        model_name=model_name,
        block_to_items=block_to_items,
        block_to_meta=block_to_meta,
        uploaded_pdfs=uploaded_pdfs,
        md_text=md_text,
        dynamic_schema=dynamic_schema,
    )

    all_final_data, usage_rows, failed_blocks = consume_extraction_batch_results(
        batch_results_map=batch_results_map,
        block_paths=list(block_to_items.keys()),
        block_to_meta=block_to_meta,
        model_name=model_name,
    )

    if failed_blocks:
        print(f"\n🔁 실패한 {len(failed_blocks)}개 block만 batch 재시도합니다..")
        retry_failed_blocks = [k for k in failed_blocks if is_valid_block_csv_path(k)]
        retry_failed_blocks = list(dict.fromkeys(retry_failed_blocks))
        print(f"  - retry 대상 유효 block 개수: {len(retry_failed_blocks)}")

        retry_block_to_items = {k: block_to_items[k] for k in retry_failed_blocks if k in block_to_items}
        retry_block_to_meta = {k: block_to_meta[k] for k in retry_failed_blocks if k in block_to_meta}

        if not retry_block_to_items:
            print("⚠️ 재시도할 유효 block가 없어 retry batch를 건너뜁니다.")
            retry_failed_blocks = []
        else:
            retry_results_map = run_extraction_batch(
                folder=folder,
                client=client,
                model_name=model_name,
                block_to_items=retry_block_to_items,
                block_to_meta=retry_block_to_meta,
                uploaded_pdfs=uploaded_pdfs,
                md_text=md_text,
                dynamic_schema=dynamic_schema,
                task_suffix="_retry",
            )
            retry_data, retry_usage_rows, retry_failed_blocks = consume_extraction_batch_results(
                batch_results_map=retry_results_map,
                block_paths=retry_failed_blocks,
                block_to_meta=block_to_meta,
                model_name=model_name,
            )
            all_final_data.extend(retry_data)
            usage_rows.extend(retry_usage_rows)
        if retry_failed_blocks:
            print(f"⚠️ 재시도 후에도 실패한 block {len(retry_failed_blocks)}개")

    if all_final_data:
        rows = [{
            "Excel_File_Name": e.get("Excel_File_Name", "N/A"),
            "Excel_Sheet_Name": e.get("Excel_Sheet_Name", "N/A"),
            "Block_ID": e.get("Block_ID", "N/A"),
            "Block_CSV_Path": e.get("Block_CSV_Path", "N/A"),
            "Item_ID": e.get("item_id", "N/A"),
            "Reasoning": e.get("reasoning", "N/A"),
            "Original_Text_Source": e.get("original_text_source", "N/A"),
            **e.get("metadata", {}),
        } for e in all_final_data]

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

        if "Excel_File_Name" in final_df.columns:
            sort_cols = [c for c in ["Excel_File_Name", "Excel_Sheet_Name", "Block_ID", "Item_ID"] if c in final_df.columns]
            final_df.sort_values(by=sort_cols, inplace=True)
        if not removed_dedup_df.empty and "Excel_File_Name" in removed_dedup_df.columns:
            sort_cols = [c for c in ["Excel_File_Name", "Excel_Sheet_Name", "Block_ID", "Item_ID"] if c in removed_dedup_df.columns]
            removed_dedup_df.sort_values(by=sort_cols, inplace=True)

        gdrive_folder.mkdir(parents=True, exist_ok=True)
        output_xlsx = gdrive_folder / f"1_{folder.name}_multimodal_extracted.xlsx"

        with pd.ExcelWriter(output_xlsx, engine="openpyxl") as writer:
            final_df.to_excel(writer, index=False, sheet_name="Vision_Excel_Data")
            if not removed_dedup_df.empty:
                removed_dedup_df.to_excel(writer, index=False, sheet_name="Dedup_Removed_Rows")
            ws = writer.sheets["Vision_Excel_Data"]
            from openpyxl.styles import Font
            bold_font = Font(bold=True)
            basic_cols = ["Excel_File_Name", "Excel_Sheet_Name", "Block_ID", "Block_CSV_Path", "Item_ID", "Reasoning", "Original_Text_Source"]
            for col_idx, col_name in enumerate(final_df.columns, 1):
                if col_name not in basic_cols:
                    for row_idx in range(2, len(final_df) + 2):
                        ws.cell(row=row_idx, column=col_idx).font = bold_font

        print(f"\n시트 기반 메타데이터 BATCH 추출 완료: {output_xlsx}")
    else:
        print("\n  ! 추출된 정보가 없습니다.")

    if usage_rows:
        usage_csv_path = folder / "10_extraction_usage_inventory.csv"
        pd.DataFrame(usage_rows).to_csv(usage_csv_path, index=False, encoding="utf-8-sig")

        total_input_tokens = sum(int(r.get("input_tokens") or 0) for r in usage_rows)
        total_output_tokens = sum(int(r.get("output_tokens") or 0) for r in usage_rows)
        total_tokens = sum(int(r.get("total_tokens") or 0) for r in usage_rows)
        total_cost_usd = sum(float(r.get("total_cost_usd") or 0.0) for r in usage_rows)

        print("\n=== BATCH TOKEN / COST SUMMARY (10_Extract) ===")
        print(f"total_input_tokens: {total_input_tokens:,}")
        print(f"total_output_tokens: {total_output_tokens:,}")
        print(f"total_tokens: {total_tokens:,}")
        print(f"total_cost_usd: {total_cost_usd:.10f}")
        print(f"🧾 사용량 CSV 저장 완료: {usage_csv_path.name}")


if __name__ == "__main__":
    TEST_LOCAL = Path(r"C:\Users\kogun\PycharmProjects\LNPDB_Articles_Extraction\Extraction_Examples\excel_o")
    DB_PATH = Path(r"F:\내 드라이브/LNPDB (1).csv")
    API_JSON_NAME = "vertex.json"

    LNPDB_COLS = [
        "Aqueous_buffer", "Dialysis_buffer", "Mixing_method",
        "Model", "Model_type", "Model_target",
        "Route_of_administration", "Cargo", "Cargo_type", "Dose_ug_nucleicacid",
        "Experiment_method", "Experiment_batching",
    ]
    MODEL = "gemini-3.1-pro-preview"

    try:
        api_key = find_api_key_file(API_JSON_NAME)
        with open(api_key, "r", encoding="utf-8") as f:
            cred_data = json.load(f)
        project_id = cred_data.get("project_id")
        if not project_id:
            raise ValueError(f"서비스 계정 JSON에 project_id가 없습니다: {api_key}")

        client = get_vertexai_client(api_key, project=project_id)
        schema = load_dynamic_schema(DB_PATH, LNPDB_COLS)
        if TEST_LOCAL.exists():
            process_sheet_base_extraction(TEST_LOCAL, TEST_LOCAL, client, MODEL, schema)
        else:
            print(f"지정한 폴더가 없습니다: {TEST_LOCAL}")
    except Exception as e:
        print(f"오류: {e}")
