import ast
import io
import json
import re
import sys
import hashlib
from itertools import product
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd
from openpyxl.styles import Font

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
MODEL_NAME = "gemini-3.1-pro-preview"

BASIC_COLS = [
    "Excel_File_Name",
    "Excel_Sheet_Name",
    "Block_ID",
    "Block_CSV_Path",
    "Item_ID",
    "Reasoning",
    "Original_Text_Source",
]

TARGET_COLS = [
    "Aqueous_buffer", "Dialysis_buffer", "Mixing_method",
    "Model", "Model_type", "Model_target",
    "Route_of_administration", "Cargo", "Cargo_type", "Dose_ug_nucleicacid",
    "Experiment_method", "Experiment_batching",
]

SPLITTABLE_TARGET_COLS = TARGET_COLS.copy()


def list_pdf_paths(folder: Path) -> list[Path]:
    return sorted([f for f in folder.rglob("*.pdf") if f.is_file() and not f.name.startswith("~") and "Exp_Excel" not in f.parts])


def upload_pdfs_to_gcs(folder: Path, gcs_batch_bucket: str) -> list[dict]:
    pdf_paths = list_pdf_paths(folder)
    uploaded = []
    for pdf_path in pdf_paths:
        gcs_uri = f"{gcs_batch_bucket}/papers/{folder.name}/{pdf_path.name}"
        upload_file_to_gcs(pdf_path, gcs_uri)
        uploaded.append({"gcs_uri": gcs_uri, "mime_type": "application/pdf"})
    return uploaded


def build_pdf_file_parts(uploaded_pdfs: list[dict]) -> list[dict]:
    parts = []
    for item in uploaded_pdfs:
        parts.append({"fileData": {"fileUri": item["gcs_uri"], "mimeType": item["mime_type"]}})
    return parts


def make_postprocess_custom_id(excel_file: str, excel_sheet: str, block_id: str, block_csv_path: str) -> str:
    seed = f"postprocess__{excel_file}__{excel_sheet}__{block_id}__{block_csv_path}"
    return "pp_gemini__" + hashlib.sha1(seed.encode("utf-8")).hexdigest()[:12]


def load_dynamic_schema(db_path: Optional[Path], target_cols: List[str]) -> Dict[str, List[str]]:
    if not db_path or not db_path.exists():
        return {col: [] for col in target_cols}
    try:
        df = pd.read_csv(db_path)
        schema: Dict[str, List[str]] = {}
        for col in target_cols:
            if col in df.columns:
                vals = []
                for v in df[col].dropna().astype(str).tolist():
                    s = v.strip()
                    if not s or s.lower() in {"nan", "none", "n/a"}:
                        continue
                    if s not in vals:
                        vals.append(s)
                    if len(vals) >= 12:
                        break
                schema[col] = vals
            else:
                schema[col] = []
        return schema
    except Exception:
        return {col: [] for col in target_cols}


def safe_text(value: Any) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    return str(value).strip()


def looks_like_list_string(s: str) -> bool:
    s = s.strip()
    return (s.startswith("[") and s.endswith("]")) or (s.startswith("(") and s.endswith(")"))


def split_outside_parentheses(text: str) -> List[str]:
    text = safe_text(text)
    if not text:
        return []
    if looks_like_list_string(text):
        try:
            parsed = ast.literal_eval(text)
            if isinstance(parsed, (list, tuple, set)):
                return [safe_text(x) for x in parsed if safe_text(x)]
        except Exception:
            pass
    if text.startswith("[") and text.endswith("]"):
        try:
            parsed = json.loads(text)
            if isinstance(parsed, list):
                return [safe_text(x) for x in parsed if safe_text(x)]
        except Exception:
            pass

    cleaned = text.strip()
    if cleaned.startswith("[") and cleaned.endswith("]"):
        cleaned = cleaned[1:-1].strip()

    result, current = [], []
    depth_round, depth_square = 0, 0
    for ch in cleaned:
        if ch == "(":
            depth_round += 1
        elif ch == ")" and depth_round > 0:
            depth_round -= 1
        elif ch == "[":
            depth_square += 1
        elif ch == "]" and depth_square > 0:
            depth_square -= 1

        if ch in {",", ";", "\n"} and depth_round == 0 and depth_square == 0:
            token = "".join(current).strip().strip("'\"")
            if token:
                result.append(token)
            current = []
        else:
            current.append(ch)

    token = "".join(current).strip().strip("'\"")
    if token:
        result.append(token)
    return result or ([cleaned.strip()] if cleaned.strip() else [])


def normalize_single_value(value: Any) -> str:
    s = safe_text(value)
    if not s:
        return ""
    parts = split_outside_parentheses(s)
    if len(parts) == 1:
        s = parts[0]
    elif len(parts) > 1:
        s = "; ".join(parts)
    s = re.sub(r"^\[+|\]+$", "", s).strip()
    s = re.sub(r"^'+|'+$", "", s).strip()
    s = re.sub(r'^"+|"+$', "", s).strip()
    s = re.sub(r"\s+", " ", s)
    if s.lower() in {"n/a", "na", "none", "null", "not applicable", "not available"}:
        return "N/A"
    return s


def normalize_item_id(value: Any) -> str:
    s = normalize_single_value(value).lower()
    return re.sub(r"\s+", " ", s)


def df_to_tsv(df: pd.DataFrame) -> str:
    buf = io.StringIO()
    df.to_csv(buf, sep="\t", index=False)
    return buf.getvalue()


def expand_item_ids(item_text: Any) -> List[str]:
    text = normalize_single_value(item_text)
    if not text or text == "N/A":
        return []
    return [normalize_item_id(x) for x in split_outside_parentheses(text)]


def explode_row_by_conditions(row: Dict[str, Any]) -> List[Dict[str, Any]]:
    value_lists: Dict[str, List[str]] = {}
    for col in SPLITTABLE_TARGET_COLS:
        raw = row.get(col, "")
        s = normalize_single_value(raw)
        if not s or s == "N/A":
            value_lists[col] = ["N/A"]
            continue
        parts = [normalize_single_value(x) for x in split_outside_parentheses(s) if normalize_single_value(x)]
        value_lists[col] = parts or ["N/A"]

    keys = list(value_lists.keys())
    combos = list(product(*[value_lists[k] for k in keys]))
    if not combos:
        return [row]

    exploded = []
    for combo in combos:
        new_row = dict(row)
        for k, v in zip(keys, combo):
            new_row[k] = v
        exploded.append(new_row)
    return exploded


def normalize_result_rows(result_rows: List[Dict[str, Any]], fallback_group_df: pd.DataFrame) -> pd.DataFrame:
    normalized: List[Dict[str, Any]] = []
    for rec in result_rows:
        base: Dict[str, Any] = {}
        base["source_item_id"] = normalize_single_value(rec.get("source_item_id", "N/A")) or "N/A"
        base["figure_item_id"] = normalize_item_id(rec.get("figure_item_id", "N/A")) or "N/A"
        base["figure_label"] = normalize_single_value(rec.get("figure_label", base["figure_item_id"])) or "N/A"
        base["split_reason"] = normalize_single_value(rec.get("split_reason", "N/A")) or "N/A"
        base["source_row_count"] = normalize_single_value(rec.get("source_row_count", "1")) or "1"
        base["Reasoning"] = normalize_single_value(rec.get("Reasoning", "N/A")) or "N/A"
        base["Original_Text_Source"] = normalize_single_value(rec.get("Original_Text_Source", "N/A")) or "N/A"
        for col in TARGET_COLS:
            base[col] = normalize_single_value(rec.get(col, "N/A")) or "N/A"

        figure_ids = expand_item_ids(base["figure_item_id"]) or ["N/A"]
        for fig_id in figure_ids:
            rec2 = dict(base)
            rec2["figure_item_id"] = fig_id
            normalized.extend(explode_row_by_conditions(rec2))

    out = pd.DataFrame(normalized)
    if out.empty:
        return out

    out.insert(0, "Excel_File_Name", fallback_group_df["Excel_File_Name"].iloc[0])
    out.insert(1, "Excel_Sheet_Name", fallback_group_df["Excel_Sheet_Name"].iloc[0])
    out.insert(2, "Block_ID", safe_text(fallback_group_df.get("Block_ID", pd.Series(["N/A"])).iloc[0]) or "N/A")
    out.insert(3, "Block_CSV_Path", safe_text(fallback_group_df.get("Block_CSV_Path", pd.Series(["N/A"])).iloc[0]) or "N/A")
    out.insert(4, "Item_ID", out["figure_item_id"])

    for col in out.columns:
        out[col] = out[col].map(normalize_single_value).replace({"": "N/A", "nan": "N/A", "None": "N/A"})
    return out.drop_duplicates().reset_index(drop=True)


def fallback_split_without_gemini(group_df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for _, src in group_df.iterrows():
        src_dict = {k: safe_text(v) for k, v in src.to_dict().items()}
        item_ids = expand_item_ids(src_dict.get("Item_ID", "")) or [normalize_item_id(src_dict.get("Item_ID", "N/A"))]
        base = {
            "Excel_File_Name": safe_text(src_dict.get("Excel_File_Name", "N/A")),
            "Excel_Sheet_Name": safe_text(src_dict.get("Excel_Sheet_Name", "N/A")),
            "Block_ID": safe_text(src_dict.get("Block_ID", "N/A")) or "N/A",
            "Block_CSV_Path": safe_text(src_dict.get("Block_CSV_Path", "N/A")) or "N/A",
            "Reasoning": safe_text(src_dict.get("Reasoning", "N/A")) or "N/A",
            "Original_Text_Source": safe_text(src_dict.get("Original_Text_Source", "N/A")) or "N/A",
            "source_item_id": safe_text(src_dict.get("Item_ID", "N/A")) or "N/A",
            "figure_label": safe_text(src_dict.get("Item_ID", "N/A")) or "N/A",
            "split_reason": "fallback local split",
            "source_row_count": "1",
        }
        for col in TARGET_COLS:
            base[col] = safe_text(src_dict.get(col, "N/A")) or "N/A"
        for item_id in item_ids:
            rec = dict(base)
            rec["figure_item_id"] = item_id
            for x in explode_row_by_conditions(rec):
                x["Item_ID"] = x["figure_item_id"]
                rows.append(x)

    if not rows:
        return pd.DataFrame()
    out = pd.DataFrame(rows)
    ordered = ["Excel_File_Name", "Excel_Sheet_Name", "Block_ID", "Block_CSV_Path", "Item_ID", "source_item_id", "figure_item_id", "figure_label", "split_reason", "source_row_count", "Reasoning", "Original_Text_Source", *TARGET_COLS]
    return out[[c for c in ordered if c in out.columns]].drop_duplicates().reset_index(drop=True)


def build_second_pass_prompt(excel_file: str, excel_sheet: str, block_id: str, block_csv_path: str, stage1_tsv: str, dynamic_schema: Dict[str, List[str]], request_id: str) -> str:
    schema_json = json.dumps(dynamic_schema, ensure_ascii=False, indent=2)
    return f"""
    You are postprocessing stage-1 extraction output for LNPDB normalization.
    Split rows to figure-level and condition-level outputs, and return strict JSON only.

    [Request Tracking]
    - request_id: {request_id}

    [File Info]
    - Excel_File_Name: {excel_file}
    - Excel_Sheet_Name: {excel_sheet}
    - Block_ID: {block_id}
    - Block_CSV_Path: {block_csv_path}

    [Stage-1 TSV]
    {stage1_tsv}

    [Schema]
    {schema_json}

    Rules:
    1. Split to figure-level rows.
    2. Split mixed conditions into separate rows.
    3. Scalar values only. No Python lists or JSON arrays inside cells.
    4. Copy request_id exactly into the top-level JSON.

    {{
      "request_id": "{request_id}",
      "results": [
        {{
          "source_item_id": "figure 7d, figure 7e",
          "figure_item_id": "figure 7d",
          "figure_label": "Figure 7d",
          "split_reason": "original row contained multiple figures and multiple cargo conditions",
          "source_row_count": "1",
          "Reasoning": "why split was needed",
          "Original_Text_Source": "source sentence",
          "Aqueous_buffer": "acetate",
          "Dialysis_buffer": "PBS",
          "Mixing_method": "microfluidic",
          "Model": "N/A",
          "Model_type": "N/A",
          "Model_target": "N/A",
          "Route_of_administration": "N/A",
          "Cargo": "mRNA",
          "Cargo_type": "Cy5-FLuc",
          "Dose_ug_nucleicacid": "N/A",
          "Experiment_method": "diameter",
          "Experiment_batching": "individual"
        }}
      ]
    }}
    """


def validate_postprocess_results(results):
    if not isinstance(results, list) or not results:
        raise ValueError("missing_results")
    required_fields = ["source_item_id", "figure_item_id", "figure_label", "split_reason", "source_row_count", "Reasoning", "Original_Text_Source"]
    for idx, rec in enumerate(results):
        if not isinstance(rec, dict):
            raise ValueError(f"result_not_dict::{idx}")
        for field in required_fields:
            if not str(rec.get(field, "")).strip():
                raise ValueError(f"missing_{field}::{idx}")


def run_postprocess_batch(root_folder: Path, client, model_name: str, groups, group_cols, dynamic_schema: Dict[str, List[str]], task_suffix: str = ""):
    uploaded_pdfs = upload_pdfs_to_gcs(root_folder, DEFAULT_GCS_BATCH_BUCKET) if root_folder else []
    shared_pdf_parts = build_pdf_file_parts(uploaded_pdfs)
    request_file = create_batch_request_file(root_folder, f"postprocess_gemini_{root_folder.name}{task_suffix}")

    for group_key, group_df in groups:
        if not isinstance(group_key, tuple):
            group_key = (group_key,)
        key_map = dict(zip(group_cols, group_key))
        excel_file = safe_text(key_map.get("Excel_File_Name", "N/A"))
        excel_sheet = safe_text(key_map.get("Excel_Sheet_Name", "N/A"))
        block_id = safe_text(key_map.get("Block_ID", "N/A"))
        block_csv_path = safe_text(key_map.get("Block_CSV_Path", "N/A"))

        stage1_tsv = df_to_tsv(group_df)
        if len(stage1_tsv) > 100000:
            stage1_tsv = stage1_tsv[:50000] + "\n...TRUNCATED...\n" + stage1_tsv[-50000:]

        custom_id = make_postprocess_custom_id(excel_file, excel_sheet, block_id, block_csv_path)
        prompt = build_second_pass_prompt(
            excel_file=excel_file,
            excel_sheet=excel_sheet,
            block_id=block_id,
            block_csv_path=block_csv_path,
            stage1_tsv=stage1_tsv,
            dynamic_schema=dynamic_schema,
            request_id=custom_id,
        )
        metadata = build_batch_request_metadata(
            task_name="postprocess_gemini",
            model_name=model_name,
            custom_id=custom_id,
            extra_metadata={"excel_file": excel_file, "excel_sheet": excel_sheet, "block_id": block_id, "block_csv_path": block_csv_path},
        )
        request_body = build_generate_content_batch_request(
            model_name=model_name,
            contents=shared_pdf_parts,
            prompt_text=prompt,
            response_mime_type="application/json",
        )
        append_batch_request(request_file, custom_id, request_body, metadata)

    local_job_id = create_batch_job_record(
        paper_folder=root_folder,
        task_name="postprocess_gemini",
        model_name=model_name,
        request_file=request_file,
        metadata={
            "request_count": count_requests_in_jsonl(request_file),
            "gcs_input_uri": f"{DEFAULT_GCS_BATCH_BUCKET}/batch/{request_file.name}",
            "gcs_output_uri_prefix": f"{DEFAULT_GCS_BATCH_BUCKET}/batch_output/{request_file.stem}",
        },
    )
    batch_job = submit_batch_job(client, root_folder, local_job_id, display_name=f"postprocess-{root_folder.name}{task_suffix}")
    print(f"  ✅ Batch 제출 완료: {batch_job.name}")
    finished_job = poll_batch_job(client, root_folder, local_job_id, poll_interval_seconds=30)
    state_name = getattr(getattr(finished_job, "state", None), "name", None) or str(getattr(finished_job, "state", "UNKNOWN"))
    if state_name != "JOB_STATE_SUCCEEDED":
        raise RuntimeError(f"postprocess_gemini batch 실패: {state_name}")
    result_file = download_batch_results(client, root_folder, local_job_id)
    return load_batch_results_as_map(result_file)


def consume_postprocess_results(groups, group_cols, batch_results_map, model_name: str):
    all_frames = []
    usage_rows = []
    failed_groups = []

    for group_key, group_df in groups:
        if not isinstance(group_key, tuple):
            group_key = (group_key,)
        key_map = dict(zip(group_cols, group_key))
        excel_file = safe_text(key_map.get("Excel_File_Name", "N/A"))
        excel_sheet = safe_text(key_map.get("Excel_Sheet_Name", "N/A"))
        block_id = safe_text(key_map.get("Block_ID", "N/A"))
        block_csv_path = safe_text(key_map.get("Block_CSV_Path", "N/A"))
        custom_id = make_postprocess_custom_id(excel_file, excel_sheet, block_id, block_csv_path)

        row = batch_results_map.get(custom_id)
        if not row or not row.get("success") or not str(row.get("response_text", "")).strip():
            failed_groups.append((group_key, group_df))
            continue

        cost_info = row.get("cost_info") or {}
        usage_rows.append({
            "Excel_File_Name": excel_file,
            "Excel_Sheet_Name": excel_sheet,
            "Block_ID": block_id,
            "task_name": "postprocess_gemini",
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
            validate_postprocess_results(results)
            out_df = normalize_result_rows(results, group_df)
            if out_df.empty:
                raise ValueError("empty_normalized_df")
            all_frames.append(out_df)
        except Exception as e:
            print(f"⚠️ Postprocess 검증 실패 ({excel_file} [{excel_sheet}] [{block_id}]): {e}")
            failed_groups.append((group_key, group_df))

    return all_frames, usage_rows, failed_groups


def process_second_pass(stage1_excel_path: Path, root_folder: Optional[Path], output_path: Optional[Path], db_path: Optional[Path], model_name: str = MODEL_NAME, api_json_name: str = "vertex.json"):
    if not stage1_excel_path.exists():
        raise FileNotFoundError(f"입력 파일이 없습니다: {stage1_excel_path}")

    df = pd.read_excel(stage1_excel_path)
    required = {"Excel_File_Name", "Excel_Sheet_Name", "Item_ID"}
    if required - set(df.columns):
        raise ValueError("입력 시트에 필수 컬럼이 없습니다.")

    api_key_path = find_api_key_file(api_json_name)
    with open(api_key_path, "r", encoding="utf-8") as f:
        cred_data = json.load(f)

    project_id = cred_data.get("project_id")
    client = get_vertexai_client(api_key_path, project=project_id)
    dynamic_schema = load_dynamic_schema(db_path, TARGET_COLS)

    group_cols = [c for c in ["Excel_File_Name", "Excel_Sheet_Name", "Block_ID", "Block_CSV_Path"] if c in df.columns]
    groups = list(df.groupby(group_cols, dropna=False))

    print(f"📦 2차 BATCH 후처리 시작: 총 {len(groups)}개 그룹")
    batch_results_map = run_postprocess_batch(
        root_folder=root_folder,
        client=client,
        model_name=model_name,
        groups=groups,
        group_cols=group_cols,
        dynamic_schema=dynamic_schema,
    )

    all_frames, usage_rows, failed_groups = consume_postprocess_results(
        groups=groups,
        group_cols=group_cols,
        batch_results_map=batch_results_map,
        model_name=model_name,
    )

    if failed_groups:
        print(f"🔁 실패한 {len(failed_groups)}개 group만 batch 재시도합니다..")
        retry_results_map = run_postprocess_batch(
            root_folder=root_folder,
            client=client,
            model_name=model_name,
            groups=failed_groups,
            group_cols=group_cols,
            dynamic_schema=dynamic_schema,
            task_suffix="_retry",
        )
        retry_frames, retry_usage_rows, retry_failed_groups = consume_postprocess_results(
            groups=failed_groups,
            group_cols=group_cols,
            batch_results_map=retry_results_map,
            model_name=model_name,
        )
        all_frames.extend(retry_frames)
        usage_rows.extend(retry_usage_rows)
        for _, group_df in retry_failed_groups:
            all_frames.append(fallback_split_without_gemini(group_df))
    if not failed_groups:
        pass

    final_df = pd.concat(all_frames, ignore_index=True) if all_frames else pd.DataFrame(columns=["Excel_File_Name", "Excel_Sheet_Name", "Block_ID", "Block_CSV_Path", "Item_ID", "source_item_id", "figure_item_id", "figure_label", "split_reason", "source_row_count", "Reasoning", "Original_Text_Source", *TARGET_COLS])

    preferred_order = ["Excel_File_Name", "Excel_Sheet_Name", "Block_ID", "Block_CSV_Path", "Item_ID", "source_item_id", "figure_item_id", "figure_label", "split_reason", "source_row_count", "Reasoning", "Original_Text_Source", *TARGET_COLS]
    final_df = final_df[[c for c in preferred_order if c in final_df.columns] + [c for c in final_df.columns if c not in preferred_order]]
    final_df = final_df.drop_duplicates().reset_index(drop=True)

    if output_path is None:
        output_path = stage1_excel_path.with_name(stage1_excel_path.stem + "_postprocessed_gemini.xlsx")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
        final_df.to_excel(writer, index=False, sheet_name="Postprocessed")
        ws = writer.sheets["Postprocessed"]
        bold = Font(bold=True)
        basic = {"Excel_File_Name", "Excel_Sheet_Name", "Block_ID", "Block_CSV_Path", "Item_ID", "source_item_id", "figure_item_id", "figure_label", "split_reason", "source_row_count", "Reasoning", "Original_Text_Source"}
        for col_idx, col_name in enumerate(final_df.columns, start=1):
            if col_name not in basic:
                for r in range(2, len(final_df) + 2):
                    ws.cell(row=r, column=col_idx).font = bold

    print(f"\n출력 완료: {output_path}")

    if usage_rows:
        usage_csv_path = root_folder / "11_postprocess_usage_inventory.csv"
        pd.DataFrame(usage_rows).to_csv(usage_csv_path, index=False, encoding="utf-8-sig")

        total_in = sum(int(r.get("input_tokens") or 0) for r in usage_rows)
        total_out = sum(int(r.get("output_tokens") or 0) for r in usage_rows)
        total_cost = sum(float(r.get("total_cost_usd") or 0.0) for r in usage_rows)

        print("\n=== BATCH TOKEN / COST SUMMARY (11_Postprocess) ===")
        print(f"total_input_tokens: {total_in:,}")
        print(f"total_output_tokens: {total_out:,}")
        print(f"total_cost_usd: {total_cost:.10f}")
        print(f"🧾 사용량 CSV 저장 완료: {usage_csv_path.name}")

    return output_path


if __name__ == "__main__":
    STAGE1_EXCEL = Path(r"C:\Users\kogun\PycharmProjects\LNPDB_Articles_Extraction\Extraction_Examples\excel_o\1_excel_o_multimodal_extracted.xlsx")
    ROOT_FOLDER = Path(r"C:\Users\kogun\PycharmProjects\LNPDB_Articles_Extraction\Extraction_Examples\excel_o")
    DB_PATH = Path(r"F:\드라이브\LNPDB (1).csv")
    API_JSON_NAME = "vertex.json"

    process_second_pass(
        stage1_excel_path=STAGE1_EXCEL,
        root_folder=ROOT_FOLDER,
        output_path=None,
        db_path=DB_PATH,
        model_name=MODEL_NAME,
        api_json_name=API_JSON_NAME,
    )
