import csv
import io
import json
import math
import numpy as np
import re
import sys
import time
from pathlib import Path

import pandas as pd

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent.parent

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

DEFAULT_GCS_BATCH_BUCKET = "gs://lnpdb-articles-extraction-batch-results-geon"
REQUIRED_COLS = [
    "Matched_Sheet_File",
    "Item_ID",
    "visual_type",
    "formulation_id",
    "condition_1_name",
    "condition_1_value",
    "condition_2_name",
    "condition_2_value",
    "condition_3_name",
    "condition_3_value",
    "condition_4_name",
    "condition_4_value",
    "metric_type",
    "original_values",
    "aggregated_value",
]


def safe_str(x) -> str:
    if pd.isna(x):
        return ""
    return str(x).strip()


def normalize_item_id(value) -> str:
    text = safe_str(value).lower()
    text = text.replace("–", "-").replace("—", "-")
    text = re.sub(r"[._]+", " ", text)
    text = re.sub(r"\bfig(?=\d)", "figure", text)
    text = re.sub(r"\btab(?=\d)", "table", text)
    text = re.sub(r"\bsupplemental\b", "supplementary", text)
    text = re.sub(r"\bsupp(?:lementary)?\b", "supplementary", text)
    text = re.sub(r"\bfig(?:ure)?\b", "figure", text)
    text = re.sub(r"\btab(?:le)?\b", "table", text)
    text = re.sub(r"\bfigure\s*([0-9]+[a-z]?)\b", r"figure \1", text)
    text = re.sub(r"\btable\s*([0-9]+[a-z]?)\b", r"table \1", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def ensure_output_schema(df: pd.DataFrame, item_ids=None, item_metadata=None, block_metadata=None, matched_sheet_file: str = "") -> pd.DataFrame:
    if df is None or not isinstance(df, pd.DataFrame):
        df = pd.DataFrame(columns=REQUIRED_COLS)
    out = df.copy()
    for col in REQUIRED_COLS:
        if col not in out.columns:
            out[col] = ""
    if "Item_ID" in out.columns and item_ids:
        out.loc[out["Item_ID"].astype(str).str.strip().eq(""), "Item_ID"] = ", ".join(map(str, item_ids))
    if "Matched_Sheet_File" in out.columns and matched_sheet_file:
        out.loc[out["Matched_Sheet_File"].astype(str).str.strip().eq(""), "Matched_Sheet_File"] = matched_sheet_file
    visual_type = ""
    if block_metadata:
        visual_type = safe_str(block_metadata.get("visual_type", ""))
    if item_metadata:
        visual_type = visual_type or safe_str(item_metadata[0].get("visual_type", ""))
    if visual_type:
        out.loc[out["visual_type"].astype(str).str.strip().eq(""), "visual_type"] = visual_type
    out = out[REQUIRED_COLS + [col for col in out.columns if col not in REQUIRED_COLS]]
    for col in REQUIRED_COLS:
        out[col] = out[col].fillna("").astype(str).str.strip()
    return out


def build_item_metadata_map(df: pd.DataFrame) -> dict:
    if df is None or df.empty or "item_id" not in df.columns:
        return {}
    metadata = {}
    for _, row in df.fillna("").iterrows():
        item_id = normalize_item_id(row.get("item_id", ""))
        if not item_id:
            continue
        visual_type = safe_str(row.get("visual_type", "")).lower()
        if visual_type == "raw_data_table":
            visual_type = "table"
        metadata[item_id] = {
            "item_id": item_id,
            "visual_type": visual_type or "unknown",
            "estimated_data_count": safe_str(row.get("estimated_data_count", "")),
            "reason": safe_str(row.get("reason", "")),
        }
    return metadata


def metadata_for_items(item_ids, item_metadata_map: dict) -> list[dict]:
    out = []
    for item_id in item_ids or []:
        clean = normalize_item_id(item_id)
        out.append(item_metadata_map.get(clean, {"item_id": clean, "visual_type": "unknown", "estimated_data_count": "", "reason": ""}))
    return out


def format_metadata_block(item_metadata, block_metadata=None) -> str:
    block_metadata = block_metadata or {}
    if block_metadata:
        item_id = safe_str(block_metadata.get("item_id")) or ", ".join([safe_str(m.get("item_id")) for m in item_metadata or [] if safe_str(m.get("item_id"))])
        return "\n".join(
            [
                "Figure/Table metadata:",
                f"- item_id: {item_id}",
                f"- visual_type: {safe_str(block_metadata.get('visual_type')) or 'unknown'}",
                f"- estimated_data_count: {safe_str(block_metadata.get('estimated_data_count'))}",
                f"- mapping_reason: {safe_str(block_metadata.get('mapping_reason'))}",
                f"- classified_reason: {safe_str(block_metadata.get('classified_reason'))}",
                f"- excel_file: {safe_str(block_metadata.get('excel_file'))}",
                f"- excel_sheet: {safe_str(block_metadata.get('excel_sheet'))}",
                f"- block_id: {safe_str(block_metadata.get('block_id'))}",
                f"- block_csv_path: {safe_str(block_metadata.get('block_csv_path'))}",
                f"- metadata_found: {safe_str(block_metadata.get('metadata_found'))}",
                f"- metadata_matched_by: {safe_str(block_metadata.get('metadata_matched_by'))}",
                f"- figure_evidence_type: {safe_str(block_metadata.get('figure_evidence_type'))}",
                f"- figure_mapping_status: {safe_str(block_metadata.get('figure_mapping_status'))}",
                f"- figure_panel_image_path: {safe_str(block_metadata.get('figure_panel_image_path'))}",
                f"- figure_pdf_path: {safe_str(block_metadata.get('figure_pdf_path'))}",
                f"- panel_image_found: {safe_str(block_metadata.get('panel_image_found'))}",
                f"- used_pdf_fallback: {safe_str(block_metadata.get('used_pdf_fallback'))}",
            ]
        )
    if not item_metadata:
        return "Figure/Table metadata:\n- item_id: \n- visual_type: unknown\n- estimated_data_count: \n- mapping_reason: \n- classified_reason: \n- excel_file: \n- excel_sheet: \n- block_id: \n- block_csv_path: \n- metadata_found: False\n- metadata_matched_by: not_found"
    lines = ["Figure/Table metadata:"]
    for meta in item_metadata:
        lines.extend(
            [
                f"- item_id: {safe_str(meta.get('item_id'))}",
                f"  visual_type: {safe_str(meta.get('visual_type')) or 'unknown'}",
                f"  estimated_data_count: {safe_str(meta.get('estimated_data_count'))}",
                f"  classified_reason: {safe_str(meta.get('classified_reason')) or safe_str(meta.get('reason'))}",
            ]
        )
    return "\n".join(lines)


VISUAL_EXTRACTION_RULES = """
Visual-type extraction rules:
If visual_type == heatmap:
1. Do NOT average across rows or columns.
2. Each numeric heatmap cell must become one output row.
3. Row labels, column labels, and subrow labels are conditions, not replicates.
4. If row label + column label together define a formulation, combine them into formulation_id.
5. Preserve row/column/subrow labels in condition_1~condition_4.
6. original_values should normally contain one numeric value.
7. Only use semicolon-separated original_values for explicit replicate labels.
8. If there are organ subrows such as Li, Sp, Lu, preserve them as condition_3_name=organ and metric_type like selectivity.

If visual_type == barplot:
1. Each plotted bar should become one output row.
2. If explicit replicate values are present for the same bar, join them with semicolon in original_values and put the mean in aggregated_value.
3. Do not treat different x-axis groups, organs, doses, time points, formulations, or cell types as replicates.

If visual_type == table:
1. Preserve table rows as much as possible.
2. If multiple metric columns exist, melt them into long format.
3. Do not average different metric columns unless they are explicitly replicate columns.
""".strip()


def estimate_text_size_for_gemini(text: str) -> dict:
    if text is None:
        text = ""
    char_count = len(text)
    word_count = len(text.split()) if text else 0
    approx_tokens_from_chars = math.ceil(char_count / 4) if char_count else 0
    approx_tokens_from_words = math.ceil(word_count * 1.3) if word_count else 0
    approx_tokens = max(approx_tokens_from_chars, approx_tokens_from_words)
    return {
        "char_count": char_count,
        "word_count": word_count,
        "approx_tokens": approx_tokens,
    }


def is_numeric_like(value: str) -> bool:
    if value is None:
        return False
    s = str(value).strip()
    if s == "":
        return False
    s_lower = s.lower()
    if s_lower in {"nan", "na", "n/a", "none", "null", "inf", "-inf"}:
        return True
    s_clean = s.replace(",", "")
    percent_clean = s_clean[:-1] if s_clean.endswith("%") else s_clean
    sci_pattern = r"^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$"
    frac_pattern = r"^[+-]?\d+\s*/\s*[+-]?\d+$"
    return bool(re.fullmatch(sci_pattern, percent_clean) or re.fullmatch(frac_pattern, s_clean))


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
            cleaned_row = ["" if is_numeric_like(cell) else cell for cell in row]
            writer.writerow(cleaned_row)
        cleaned_text = output_io.getvalue().strip()
        return cleaned_text if cleaned_text else csv_text
    except Exception:
        return csv_text


def maybe_count_tokens_with_client(client, model_name, text: str):
    try:
        if hasattr(client, "models") and hasattr(client.models, "count_tokens"):
            result = client.models.count_tokens(model=model_name, contents=[text])
            total_tokens = getattr(result, "total_tokens", None)
            if total_tokens is not None:
                return int(total_tokens)
    except Exception:
        pass
    return None


def prepare_csv_for_prompt(client, model_name, csv_text: str, stage_name: str, soft_token_limit: int = 120000):
    if csv_text is None:
        csv_text = ""
    estimated = estimate_text_size_for_gemini(csv_text)
    counted_tokens = maybe_count_tokens_with_client(client, model_name, csv_text)
    token_basis = counted_tokens if counted_tokens is not None else estimated["approx_tokens"]
    print(
        f"      [size:{stage_name}] chars={estimated['char_count']:,}, "
        f"words={estimated['word_count']:,}, approx_tokens={estimated['approx_tokens']:,}"
        + (f" counted_tokens={counted_tokens:,}" if counted_tokens is not None else "")
    )
    if token_basis <= soft_token_limit:
        return csv_text, False
    stripped_csv = strip_numeric_cells_from_csv(csv_text)
    stripped_estimated = estimate_text_size_for_gemini(stripped_csv)
    stripped_counted_tokens = maybe_count_tokens_with_client(client, model_name, stripped_csv)
    stripped_basis = stripped_counted_tokens if stripped_counted_tokens is not None else stripped_estimated["approx_tokens"]
    print(
        f"      [size:{stage_name}:stripped] chars={stripped_estimated['char_count']:,}, "
        f"words={stripped_estimated['word_count']:,}, approx_tokens={stripped_estimated['approx_tokens']:,}"
        + (f" counted_tokens={stripped_counted_tokens:,}" if stripped_counted_tokens is not None else "")
    )
    if stripped_basis < token_basis:
        return stripped_csv, True
    return csv_text, False


def get_block_df(folder: Path, block_csv_path: str, excel_file: str = "", excel_sheet: str = ""):
    block_csv_path = str(block_csv_path or "").strip()
    if block_csv_path:
        csv_path = folder / block_csv_path
        if csv_path.exists():
            try:
                return pd.read_csv(csv_path, dtype=str).fillna("")
            except Exception as e:
                print(f"  ! block csv load failed ({block_csv_path}): {e}")
    exp_folder = folder / "Exp_Excel"
    file_path = exp_folder / excel_file
    if not file_path.exists():
        return None
    try:
        if file_path.suffix.lower() == ".csv":
            return pd.read_csv(file_path, dtype=str).fillna("")
        xls = pd.ExcelFile(file_path)
        return pd.read_excel(xls, sheet_name=excel_sheet, dtype=str).fillna("")
    except Exception as e:
        print(f"  ! sheet load failed ({excel_file}[{excel_sheet}]): {e}")
        return None


def extract_python_code(text):
    cleaned = str(text or "").strip()
    if not cleaned:
        return ""
    cleaned = re.sub(r"^\s*```(?:python)?\s*", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s*```\s*$", "", cleaned)
    cleaned = cleaned.replace("```python", "").replace("```", "").strip()
    return cleaned


def make_norm_request_id(excel_file: str, excel_sheet: str, block_id: str, block_csv_path: str) -> str:
    seed = block_csv_path or f"{excel_file}|{excel_sheet}|{block_id}"
    safe_seed = re.sub(r"[^a-z0-9]+", "_", str(seed).lower()).strip("_")
    return f"exp_vals_norm__{safe_seed or 'unknown'}"


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


def build_norm_code_prompt(
    client,
    primary_model,
    raw_df,
    excel_file,
    excel_sheet,
    block_id,
    block_csv_path,
    item_ids,
    request_id: str,
    previous_response_text: str = "",
    previous_code: str = "",
    previous_error: str = "",
    is_retry: bool = False,
    item_metadata=None,
    block_metadata=None,
    validation_failure_reason: str = "",
):
    csv_sample, numeric_cells_stripped = prepare_csv_for_prompt(
        client, primary_model, raw_df.to_csv(index=False), stage_name=f"exp_vals_norm::{block_id}"
    )
    item_ids_str = ", ".join(item_ids)
    retry_context = ""
    if is_retry:
        retry_context = f"""
Previous attempt failed.
Fix the code based on the previous code and error.
If validation failed, fix the extraction logic rather than only changing column names.
Do not reuse undefined variables.
Always use quoted string literals for metric names when needed.

previous_response_text:
{previous_response_text or "<empty>"}

previous_code:
{previous_code or "<empty>"}

previous_error:
{previous_error or "<empty>"}

validation_failure_reason:
{validation_failure_reason or "<empty>"}
""".strip()
        retry_context = f"{retry_context}\n\n"

    prompt_text = f"""
request_id: {request_id}

{retry_context}You are generating executable Python code that transforms a pandas DataFrame named `raw_df`.
The source block is:
- excel_file: {excel_file}
- excel_sheet: {excel_sheet}
- block_id: {block_id}
- block_csv_path: {block_csv_path}
- item_ids: {item_ids_str}
- numeric_cells_stripped: {numeric_cells_stripped}

{format_metadata_block(item_metadata, block_metadata=block_metadata)}

{VISUAL_EXTRACTION_RULES}

Validation failure to correct, if any:
{validation_failure_reason or "<none>"}

Expected heatmap examples:
- figure 2b: rows=B1~B7 bromide tails, columns=1A1~2A13 amine heads. formulation_id=<amine_head><bromide_tail>, condition_1_name=amine_head, condition_2_name=bromide_tail, one numeric cell per row.
- figure 2c: rows=B1~B7 tails, subrows=Li/Sp/Lu organ, columns=1A1~2A13 amine heads. formulation_id=<amine_head><bromide_tail>, condition_3_name=organ, metric_type=selectivity, one numeric cell per row.

The code must:
1. Use the already-loaded `raw_df` variable directly.
2. Produce a pandas DataFrame named `result_df`.
3. Return valid executable Python only.
4. Do not include markdown fences inside python_code.
4a. The only input dataframe is raw_df.
4b. Do not reference undefined variables.
4c. Define every helper function before use.
4d. Do not use variables such as row, val_cols, value_cols, or to_f unless they are explicitly defined.
4e. The generated code must be self-contained.
4f. The final object must be result_df.
5. Output exactly these columns in this order:
   {REQUIRED_COLS}
6. Fill Matched_Sheet_File with "{excel_file} [{excel_sheet}] [{block_id}]".
7. Fill Item_ID with "{item_ids_str}".
8. Fill visual_type from the metadata.
9. Preserve the current business logic only for true replicate measurements:
   - if multiple metric types exist in one table, melt them into long format
   - if repeated measurements exist for the same exact bar/condition, join repeated values with ';' in 'original_values' and put their arithmetic mean in 'aggregated_value'
   - never average different row labels, column labels, subrow labels, organs, timepoints, doses, cell types, formulation ids, lipids, proteins, or groups
10. For heatmap/wide-format data, each numeric cell is one output row. original_values should normally be a single numeric string.

CSV sample:
{csv_sample}

Return JSON only:
{{
  "request_id": "{request_id}",
  "python_code": "import pandas as pd\\nimport numpy as np\\nresult_df = raw_df.copy()"
}}
""".strip()
    return prompt_text


def parse_norm_code_payload(payload_text: str, expected_request_id: str) -> str:
    cleaned = str(payload_text or "").replace("```json", "").replace("```", "").strip()
    if not cleaned:
        raise ValueError("empty response")
    payload = json.loads(cleaned)
    response_request_id = str(payload.get("request_id", "")).strip()
    if not response_request_id:
        raise ValueError("missing request_id")
    if response_request_id != expected_request_id:
        raise ValueError(f"request_id mismatch: expected={expected_request_id} | got={response_request_id}")
    python_code = str(payload.get("python_code", "")).strip()
    if not python_code:
        raise ValueError("missing python_code")
    return extract_python_code(python_code)


def execute_norm_code(ai_code: str, raw_df):
    local_vars = {"raw_df": raw_df.copy(), "pd": pd, "np": np}
    exec(ai_code, globals(), local_vars)
    result_df = local_vars.get("result_df")
    if result_df is None or result_df.empty:
        raise ValueError("result_df missing or empty")
    return result_df


def generate_and_execute_norm_code(
    client,
    primary_model,
    fallback_model,
    max_retries,
    switch_model_at,
    raw_df,
    excel_file,
    excel_sheet,
    block_id,
    block_csv_path,
    item_ids,
    request_id=None,
    item_metadata=None,
    block_metadata=None,
    validation_failure_reason: str = "",
):
    request_id = request_id or make_norm_request_id(excel_file, excel_sheet, block_id, block_csv_path)
    base_prompt = build_norm_code_prompt(
        client=client,
        primary_model=primary_model,
        raw_df=raw_df,
        excel_file=excel_file,
        excel_sheet=excel_sheet,
        block_id=block_id,
        block_csv_path=block_csv_path,
        item_ids=item_ids,
        request_id=request_id,
        item_metadata=item_metadata or [],
        block_metadata=block_metadata or {},
        validation_failure_reason=validation_failure_reason,
    )
    previous_code = ""
    error_msg = ""

    for attempt in range(1, max_retries + 1):
        current_model = primary_model if attempt < switch_model_at else fallback_model
        prompt_text = base_prompt
        if attempt > 1:
            prompt_text = (
                f"Previous attempt failed.\nrequest_id: {request_id}\n"
                f"previous_code:\n```python\n{previous_code}\n```\n"
                f"error:\n{error_msg}\n\n"
                f"{base_prompt}"
            )

        ai_code = None
        for api_attempt in range(4):
            try:
                call_result = generate_content_with_guard(
                    client=client,
                    model_name=current_model,
                    contents=[],
                    prompt_text=prompt_text,
                    task_name="exp_vals_norm_code_generation",
                    response_mime_type="application/json",
                    max_retries=1,
                )
                ai_code = parse_norm_code_payload(call_result.response_text, request_id)
                break
            except Exception as e:
                error_msg = str(e)
                error_msg_api = error_msg.lower()
                if "429" in error_msg_api or "resource_exhausted" in error_msg_api:
                    if "per_day" in error_msg_api or "per day" in error_msg_api:
                        raise
                    time.sleep(10 * (2 ** api_attempt) + (10 if "tokens" in error_msg_api else 0))
                    continue
                if "400" in error_msg_api or "invalid_argument" in error_msg_api:
                    prompt_text = prompt_text[: max(1000, len(prompt_text) // 2)]
                    continue
                break

        if ai_code is None:
            previous_code = "API response failed"
            continue

        try:
            result_df = execute_norm_code(ai_code, raw_df)
            result_df = ensure_output_schema(
                result_df,
                item_ids=item_ids,
                item_metadata=item_metadata or [],
                block_metadata=block_metadata or {},
                matched_sheet_file=f"{excel_file} [{excel_sheet}] [{block_id}]",
            )
            return True, result_df, None, attempt
        except Exception as exec_e:
            previous_code = ai_code
            error_msg = str(exec_e)
            print(f"    retry {attempt} failed ({current_model}): {error_msg.splitlines()[-1][:80]}...")
            time.sleep(2.5)

    return False, None, error_msg, max_retries


def load_norm_block_tasks(df: pd.DataFrame, excel_mapping: dict, paper_folder: Path):
    target_visual_types = ["barplot", "table", "chemical_structure", "heatmap"]
    item_metadata_map = build_item_metadata_map(df)

    df["_fig_select"] = df.apply(get_fig_selection_value, axis=1)
    df["_visual_type_norm"] = (
        df["visual_type"]
        .astype(str)
        .str.strip()
        .str.lower()
        .replace({"raw_data_table": "table"})
    )

    valid_items = set(
        df[
            df["_fig_select"].isin(["yes", "maybe"])
            & df["_visual_type_norm"].isin(target_visual_types)
        ]["item_id"].astype(str).str.lower().str.strip().tolist()
    )

    print(f"  - valid_items 개수: {len(valid_items)}")
    if valid_items:
        print("  - valid_items 예시:")
        for x in list(sorted(valid_items))[:30]:
            print(f"    * {x}")

    classified_block_map = {}
    if "matched_block_csv_path" in df.columns:
        for _, row in df.iterrows():
            item_id = str(row.get("item_id", "")).lower().strip()
            if item_id not in valid_items:
                continue
            raw_paths = str(row.get("matched_block_csv_path", "")).strip()
            if not raw_paths:
                continue
            for p in [x.strip() for x in raw_paths.split(" | ") if is_valid_block_csv_path(x)]:
                classified_block_map.setdefault(p, [])
                if item_id not in classified_block_map[p]:
                    classified_block_map[p].append(item_id)

    block_to_items = {}
    block_to_meta = {}
    for item_id, mappings in excel_mapping.items():
        clean_item_id = item_id.lower().strip()
        if clean_item_id not in valid_items:
            continue
        for m in mappings:
            block_csv_path = str(m.get("block_csv_path", "")).strip()
            if not is_valid_block_csv_path(block_csv_path):
                continue
            excel_file = str(m.get("excel_file", "")).strip()
            excel_sheet = str(m.get("excel_sheet", "")).strip()
            block_id = str(m.get("block_id", "")).strip()
            block_to_items.setdefault(block_csv_path, [])
            if clean_item_id not in block_to_items[block_csv_path]:
                block_to_items[block_csv_path].append(clean_item_id)
            block_to_meta.setdefault(
                block_csv_path,
                {
                    "excel_file": excel_file,
                    "excel_sheet": excel_sheet,
                    "block_id": block_id,
                    "block_csv_path": block_csv_path,
                },
            )

    for block_csv_path, items in classified_block_map.items():
        block_to_items.setdefault(block_csv_path, [])
        for item in items:
            if item not in block_to_items[block_csv_path]:
                block_to_items[block_csv_path].append(item)
        if block_csv_path not in block_to_meta:
            guessed_file = ""
            guessed_sheet = ""
            guessed_block_id = Path(block_csv_path).stem
            parts = Path(block_csv_path).parts
            if len(parts) >= 3:
                guessed_sheet = parts[-2]
                guessed_file = f"{parts[-3]}.xlsx"
            block_to_meta[block_csv_path] = {
                "excel_file": guessed_file,
                "excel_sheet": guessed_sheet,
                "block_id": guessed_block_id,
                "block_csv_path": block_csv_path,
            }

    valid_block_to_items = {}
    valid_block_to_meta = {}

    for block_csv_path, items in block_to_items.items():
        if not is_valid_block_csv_path(block_csv_path):
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

    print(f"  - 실제 유효 norm block CSV 개수: {len(block_to_items)}")
    if block_to_items:
        print("  - 실제 유효 norm block CSV 목록:")
        for p in sorted(block_to_items.keys()):
            print(f"    * {p}")

    tasks = []
    for block_csv_path, items in block_to_items.items():
        if not is_valid_block_csv_path(block_csv_path):
            continue
        meta = block_to_meta.get(block_csv_path, {})
        raw_df = get_block_df(
            paper_folder,
            block_csv_path,
            meta.get("excel_file", ""),
            meta.get("excel_sheet", ""),
        )
        if raw_df is None or raw_df.empty:
            continue
        request_id = make_norm_request_id(
            meta.get("excel_file", ""),
            meta.get("excel_sheet", ""),
            meta.get("block_id", Path(block_csv_path).stem),
            block_csv_path,
        )
        task_item_metadata = metadata_for_items(items, item_metadata_map)
        dominant_meta = task_item_metadata[0] if task_item_metadata else {}
        tasks.append(
            {
                "request_id": request_id,
                "block_csv_path": block_csv_path,
                "item_ids": items,
                "item_metadata": task_item_metadata,
                "block_metadata": {
                    "visual_type": safe_str(dominant_meta.get("visual_type")) or "unknown",
                    "estimated_data_count": safe_str(dominant_meta.get("estimated_data_count")),
                    "mapping_reason": "",
                    "classified_reason": safe_str(dominant_meta.get("classified_reason")) or safe_str(dominant_meta.get("reason")),
                    "metadata_found": bool(dominant_meta),
                    "metadata_matched_by": "item_id" if dominant_meta else "not_found",
                    "excel_file": meta.get("excel_file", ""),
                    "excel_sheet": meta.get("excel_sheet", ""),
                    "block_id": meta.get("block_id", Path(block_csv_path).stem),
                    "block_csv_path": block_csv_path,
                },
                "meta": meta,
                "raw_df": raw_df,
                "previous_response_text": "",
                "previous_code": "",
                "previous_error": "",
            }
        )
    return tasks


def run_norm_batch_for_tasks(
    client,
    paper_folder: Path,
    tasks: list,
    model_name: str,
    batch_tag: str,
):
    if not tasks:
        return {}

    request_file = create_batch_request_file(paper_folder, f"exp_vals_norm_{paper_folder.name}_{batch_tag}")

    for task in tasks:
        meta = task["meta"]
        prompt_text = build_norm_code_prompt(
            client=client,
            primary_model=model_name,
            raw_df=task["raw_df"],
            excel_file=meta.get("excel_file", ""),
            excel_sheet=meta.get("excel_sheet", ""),
            block_id=meta.get("block_id", ""),
            block_csv_path=task["block_csv_path"],
            item_ids=task["item_ids"],
            request_id=task["request_id"],
            item_metadata=task.get("item_metadata", []),
            block_metadata=task.get("block_metadata", {}),
            validation_failure_reason=task.get("previous_error", ""),
            previous_response_text=task.get("previous_response_text", ""),
            previous_code=task.get("previous_code", ""),
            previous_error=task.get("previous_error", ""),
            is_retry=batch_tag.startswith("retry"),
        )
        metadata = build_batch_request_metadata(
            task_name="exp_vals_norm_code_generation",
            model_name=model_name,
            custom_id=task["request_id"],
            stage_name=f"exp_vals_norm_{batch_tag}",
            item_id=task["block_csv_path"],
            paper_folder=str(paper_folder),
        )
        request_body = build_generate_content_batch_request(
            model_name=model_name,
            contents=[],
            prompt_text=prompt_text,
            response_mime_type="application/json",
        )
        append_batch_request(request_file, task["request_id"], request_body, metadata)

    local_job_id = create_batch_job_record(
        paper_folder=paper_folder,
        task_name="exp_vals_norm_code_generation",
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
        display_name=f"exp-vals-norm-{paper_folder.name}-{batch_tag}",
    )
    print(f"  batch submitted ({batch_tag}): {batch_job.name}")

    finished_job = poll_batch_job(
        client=client,
        paper_folder=paper_folder,
        local_job_id=local_job_id,
        poll_interval_seconds=30,
    )
    state_name = getattr(getattr(finished_job, "state", None), "name", None) or str(getattr(finished_job, "state", "UNKNOWN"))
    if state_name != "JOB_STATE_SUCCEEDED":
        raise RuntimeError(f"batch failed ({batch_tag}): {state_name}")

    result_file = download_batch_results(client=client, paper_folder=paper_folder, local_job_id=local_job_id)
    return load_batch_results_as_map(result_file)


def collect_norm_results_for_tasks(tasks: list, results_map: dict, pass_label: str):
    all_results = []
    failed_tasks = []

    for task in tasks:
        meta = task["meta"]
        row = results_map.get(task["request_id"])
        if not row:
            task["previous_response_text"] = ""
            task["previous_code"] = ""
            task["previous_error"] = "request_id missing from batch results map"
            print(f"  ! {pass_label} missing result: {task['request_id']}")
            failed_tasks.append(task)
            continue

        response_text = str(row.get("response_text", "")).strip()
        if not row.get("success") or not response_text:
            task["previous_response_text"] = response_text
            task["previous_code"] = ""
            task["previous_error"] = str(row.get("error") or "batch response missing or unsuccessful")
            print(f"  ! {pass_label} unsuccessful: {task['request_id']} | {task['previous_error']}")
            failed_tasks.append(task)
            continue

        try:
            ai_code = ""
            ai_code = parse_norm_code_payload(response_text, task["request_id"])
            result_df = execute_norm_code(ai_code, task["raw_df"])
            result_df = ensure_output_schema(
                result_df,
                item_ids=task["item_ids"],
                item_metadata=task.get("item_metadata", []),
                block_metadata=task.get("block_metadata", {}),
                matched_sheet_file=f"{meta.get('excel_file', '')} [{meta.get('excel_sheet', '')}] [{meta.get('block_id', '')}]",
            )
            all_results.append(result_df)
            print(f"  {pass_label}: {meta.get('excel_file', '')} [{meta.get('excel_sheet', '')}] [{meta.get('block_id', '')}]")
        except Exception as e:
            task["previous_response_text"] = response_text
            task["previous_code"] = ai_code
            task["previous_error"] = str(e)
            print(f"  ! {pass_label} parse/exec failed: {task['request_id']} | {e}")
            failed_tasks.append(task)

    return all_results, failed_tasks


def extract_exp_vals_main(
    paper_folder_str,
    primary_model,
    fallback_model,
    max_retries,
    switch_model_at,
    api_json_name="vertex.json",
    execution_mode="batch",
):
    paper_folder = Path(paper_folder_str)
    execution_mode = str(execution_mode).strip().lower()
    if execution_mode not in {"sync", "batch"}:
        raise ValueError(f"invalid execution_mode: {execution_mode}")
    print(f"[exp_vals_norm] start: {paper_folder.name}")

    csv_path = paper_folder / "fig_table_lnpdb_classified.csv"
    map_path = paper_folder / "excel_mapping.json"
    if not csv_path.exists() or not map_path.exists():
        print("  ! classified CSV or mapping JSON missing.")
        return

    df = pd.read_csv(csv_path)
    with open(map_path, "r", encoding="utf-8") as f:
        excel_mapping = json.load(f)

    api_key_path = find_api_key_file(api_json_name)
    with open(api_key_path, "r", encoding="utf-8") as f:
        cred_data = json.load(f)
    project_id = cred_data.get("project_id")
    if not project_id:
        raise ValueError(f"project_id missing: {api_key_path}")
    client = get_vertexai_client(api_key_path, project=project_id)

    tasks = load_norm_block_tasks(df, excel_mapping, paper_folder)
    if not tasks:
        print("  ! no block tasks.")
        return

    all_results = []
    remaining_tasks = list(tasks)

    try:
        first_pass_results = run_norm_batch_for_tasks(
            client=client,
            paper_folder=paper_folder,
            tasks=remaining_tasks,
            model_name=primary_model,
            batch_tag="pass1",
        )
    except Exception as e:
        print(f"  ! batch first pass failed: {e}")
        first_pass_results = {}

    first_pass_frames, remaining_tasks = collect_norm_results_for_tasks(
        tasks=remaining_tasks,
        results_map=first_pass_results,
        pass_label="batch first pass success",
    )
    all_results.extend(first_pass_frames)

    if remaining_tasks:
        try:
            retry_results = run_norm_batch_for_tasks(
                client=client,
                paper_folder=paper_folder,
                tasks=remaining_tasks,
                model_name=primary_model,
                batch_tag="retry1",
            )
        except Exception as e:
            print(f"  ! batch retry failed: {e}")
            retry_results = {}

        retry_frames, remaining_tasks = collect_norm_results_for_tasks(
            tasks=remaining_tasks,
            results_map=retry_results,
            pass_label="batch retry success",
        )
        all_results.extend(retry_frames)

    if execution_mode == "sync":
        for task in remaining_tasks:
            meta = task["meta"]
            success, result_df, err, _ = generate_and_execute_norm_code(
                client=client,
                primary_model=primary_model,
                fallback_model=fallback_model,
                max_retries=max_retries,
                switch_model_at=switch_model_at,
                raw_df=task["raw_df"],
                excel_file=meta.get("excel_file", ""),
                excel_sheet=meta.get("excel_sheet", ""),
                block_id=meta.get("block_id", ""),
                block_csv_path=task["block_csv_path"],
                item_ids=task["item_ids"],
                request_id=task["request_id"],
                item_metadata=task.get("item_metadata", []),
                block_metadata=task.get("block_metadata", {}),
                validation_failure_reason=task.get("previous_error", ""),
            )
            if success:
                all_results.append(result_df)
                print(f"  sync retry success: {meta.get('excel_file', '')} [{meta.get('excel_sheet', '')}] [{meta.get('block_id', '')}]")
            else:
                print(f"    ! final failure: {task['request_id']} | {err}")
    else:
        for task in remaining_tasks:
            print(f"    ! final failure (batch only): {task['request_id']}")

    if all_results:
        final_df = ensure_output_schema(pd.concat(all_results, ignore_index=True))
        output_xlsx = paper_folder / f"4_{paper_folder.name}_standardized_exp_data.xlsx"
        output_csv = paper_folder / f"4_{paper_folder.name}_standardized_exp_data.csv"
        final_df.to_excel(output_xlsx, index=False)
        final_df.to_csv(output_csv, index=False, encoding="utf-8-sig")
        print(f"[exp_vals_norm] saved: {output_xlsx}")
        print(f"[exp_vals_norm] saved: {output_csv}")
    else:
        print("[exp_vals_norm] no successful results.")


if __name__ == "__main__":
    TEST_DIR = r"/Users/kogeon/Library/CloudStorage/GoogleDrive-geon@molcube.com/EXTRACT-TEST/38-test-2"
    API_JSON_NAME = "vertex.json"
    PRIMARY_MODEL = "gemini-3-flash-preview"
    FALLBACK_MODEL = "gemini-3.1-pro-preview"
    MAX_RETRIES = 3
    SWITCH_MODEL_AT = 2

    extract_exp_vals_main(TEST_DIR, PRIMARY_MODEL, FALLBACK_MODEL, MAX_RETRIES, SWITCH_MODEL_AT, API_JSON_NAME)
