import csv
import io
import json
import math
import re
import sys
import time
from pathlib import Path

import pandas as pd
from PIL import Image, ImageDraw, ImageFont
from google.genai import types

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

API_JSON_NAME = "vertex.json"
PRIMARY_MODEL = "gemini-3.1-pro-preview"
FALLBACK_MODEL = "gemini-3-flash-preview"
MATCHING_CSV_NAME = "fig_table_lnpdb_classified.csv"
MAPPING_JSON_NAME = "excel_mapping.json"
OUTPUT_CSV_NAME = "exp_vals_from_excels_direct_llm.csv"
LNPDB_CSV_PATH = Path("/Users/kogeon/Library/CloudStorage/GoogleDrive-geon@molcube.com/LNPDB (1).csv")
TEMP_CAPTURE_DIRNAME = "_sheet_captures_direct_llm"
DEFAULT_GCS_BATCH_BUCKET = "gs://lnpdb-articles-extraction-batch-results-geon"
SOFT_TOKEN_LIMIT = 120000
MAX_ROWS_FOR_CAPTURE = 80
MAX_COLS_FOR_CAPTURE = 20
MAX_CELL_TEXT_LEN = 30
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


def ensure_output_schema(df: pd.DataFrame, item_ids=None, item_metadata=None, block_metadata=None, matched_sheet_file: str = "") -> pd.DataFrame:
    if df is None or not isinstance(df, pd.DataFrame):
        df = pd.DataFrame(columns=REQUIRED_COLS)
    out = df.copy()
    for col in REQUIRED_COLS:
        if col not in out.columns:
            out[col] = ""
    if item_ids:
        out.loc[out["Item_ID"].astype(str).str.strip().eq(""), "Item_ID"] = ", ".join(map(str, item_ids))
    if matched_sheet_file:
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


def format_figure_evidence_block(block_metadata=None) -> str:
    block_metadata = block_metadata or {}
    evidence_type = safe_str(block_metadata.get("figure_evidence_type")) or "none"
    actual_file_note = ""
    if evidence_type == "pdf" and not safe_str(block_metadata.get("figure_pdf_path")):
        actual_file_note = "PDF fallback was selected but actual file part is unavailable."
    return "\n".join(
        [
            "Figure evidence:",
            f"- evidence_type: {evidence_type}",
            f"- mapping_status: {safe_str(block_metadata.get('figure_mapping_status'))}",
            f"- panel_image_path: {safe_str(block_metadata.get('figure_panel_image_path'))}",
            f"- pdf_path: {safe_str(block_metadata.get('figure_pdf_path'))}",
            f"- panel_image_found: {safe_str(block_metadata.get('panel_image_found'))}",
            f"- used_pdf_fallback: {safe_str(block_metadata.get('used_pdf_fallback'))}",
            f"- pdf_candidate_count: {safe_str(block_metadata.get('pdf_candidate_count'))}",
            f"- actual_file_note: {actual_file_note}",
            "",
            "Figure evidence rules:",
            "- Use the Excel CSV as the authoritative numeric source.",
            "- Use figure/PDF evidence only to interpret axes, labels, groups, legends, panel identity, and metric meaning.",
            "- Do not estimate numeric values from image/PDF when Excel CSV provides numeric values.",
            "- If evidence_type == panel_image, a cropped panel image corresponding exactly to this item is provided; use it to interpret the requested panel.",
            "- If evidence_type == pdf, no exact panel crop was found; full-image fallback was intentionally not used because it may contain unrelated panels. The PDF is fallback context.",
            "- If evidence_type == none, use only Excel CSV, mapping_reason, classified_reason, and metadata.",
        ]
    )


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
    return {"char_count": char_count, "word_count": word_count, "approx_tokens": approx_tokens}


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
            writer.writerow(["" if is_numeric_like(cell) else cell for cell in row])
        cleaned_text = output_io.getvalue().strip()
        return cleaned_text if cleaned_text else csv_text
    except Exception:
        return csv_text


def prepare_csv_for_prompt(client, model_name, csv_text: str, stage_name: str, soft_token_limit: int = SOFT_TOKEN_LIMIT):
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


def safe_str(x) -> str:
    if pd.isna(x):
        return ""
    return str(x).strip()


def is_valid_block_csv_path(value) -> bool:
    if value is None:
        return False
    text = str(value).strip()
    if not text:
        return False
    if text.lower() in {"nan", "none", "null", "n/a"}:
        return False
    return True


def get_fig_selection_value(row) -> str:
    manual = safe_str(row.get("manual_select")).lower()
    if manual in {"yes", "y", "1", "true", "o"}:
        return "yes"
    if manual in {"no", "n", "0", "false", "x"}:
        return "no"
    return safe_str(row.get("need_for_lnpdb")).lower()


def find_matching_csv(folder: Path) -> Path:
    path = folder / MATCHING_CSV_NAME
    if not path.exists():
        raise FileNotFoundError(f"matching CSV not found: {path}")
    return path


def load_matched_block_groups(folder: Path) -> dict:
    csv_path = find_matching_csv(folder)
    df = pd.read_csv(csv_path)
    item_metadata_map = {}
    if "item_id" in df.columns:
        for _, row in df.fillna("").iterrows():
            item_id = normalize_item_id(row.get("item_id", ""))
            if not item_id:
                continue
            visual_type = safe_str(row.get("visual_type", "")).lower()
            if visual_type == "raw_data_table":
                visual_type = "table"
            item_metadata_map[item_id] = {
                "item_id": item_id,
                "visual_type": visual_type or "unknown",
                "estimated_data_count": safe_str(row.get("estimated_data_count", "")),
                "reason": safe_str(row.get("reason", "")),
            }
    map_path = folder / MAPPING_JSON_NAME
    excel_mapping = {}
    if map_path.exists():
        with open(map_path, "r", encoding="utf-8") as f:
            excel_mapping = json.load(f)

    cols_lower = {c.lower(): c for c in df.columns}
    item_col = cols_lower.get("item_id")
    matched_block_col = cols_lower.get("matched_block_csv_path")
    visual_type_col = cols_lower.get("visual_type")
    if item_col is None:
        raise ValueError("item_id column missing")

    allowed_visual_types = {"table", "barplot", "heatmap", "chemical_structure"}

    grouped = {}
    if matched_block_col is not None:
        for _, row in df.iterrows():
            item_id = safe_str(row[item_col]).lower().strip()
            raw_paths = safe_str(row[matched_block_col])
            if not raw_paths:
                continue

            selection_val = get_fig_selection_value(row)
            if selection_val not in {"yes", "maybe"}:
                continue

            if visual_type_col is not None:
                visual_type_val = safe_str(row[visual_type_col]).lower()
                if visual_type_val == "raw_data_table":
                    visual_type_val = "table"
                if visual_type_val not in allowed_visual_types:
                    continue

            for p in [x.strip() for x in raw_paths.split(" | ") if is_valid_block_csv_path(x)]:
                grouped.setdefault(
                    p,
                    {
                        "excel_file": "",
                        "excel_sheet": "",
                        "block_id": Path(p).stem,
                        "block_csv_path": p,
                        "item_ids": [],
                    },
                )
                if item_id not in grouped[p]["item_ids"]:
                    grouped[p]["item_ids"].append(item_id)

    for item_id, mappings in excel_mapping.items():
        clean_item_id = safe_str(item_id).lower().strip()
        for m in mappings:
            block_csv_path = safe_str(m.get("block_csv_path"))
            if not is_valid_block_csv_path(block_csv_path):
                continue
            grouped.setdefault(
                block_csv_path,
                {
                    "excel_file": safe_str(m.get("excel_file")),
                    "excel_sheet": safe_str(m.get("excel_sheet")),
                    "block_id": safe_str(m.get("block_id")) or Path(block_csv_path).stem,
                    "block_csv_path": block_csv_path,
                    "item_ids": [],
                },
            )
            if clean_item_id and clean_item_id not in grouped[block_csv_path]["item_ids"]:
                grouped[block_csv_path]["item_ids"].append(clean_item_id)

    valid_grouped = {}
    for block_csv_path, meta in grouped.items():
        if not is_valid_block_csv_path(block_csv_path):
            continue
        item_ids = [safe_str(x).lower() for x in meta.get("item_ids", []) if safe_str(x)]
        item_ids = sorted(list(set(item_ids)))
        if not item_ids:
            continue
        meta["item_ids"] = item_ids
        meta["item_metadata"] = metadata_for_items(item_ids, item_metadata_map)
        valid_grouped[block_csv_path] = meta
    grouped = valid_grouped

    print(f"  - 실제 유효 direct llm block 개수: {len(grouped)}")
    if grouped:
        print("  - 실제 유효 direct llm block 목록:")
        for p in sorted(grouped.keys()):
            print(f"    * {p}")

    return grouped


def find_excel_file(folder: Path, excel_filename: str) -> Path:
    candidates = list(folder.rglob(excel_filename))
    if candidates:
        return candidates[0]
    raise FileNotFoundError(f"excel file not found: {excel_filename}")


def load_block_df(folder: Path, block_csv_path: str, excel_file: str = "", excel_sheet: str = "") -> pd.DataFrame:
    block_csv_path = safe_str(block_csv_path)
    if block_csv_path:
        csv_path = folder / block_csv_path
        if csv_path.exists():
            return pd.read_csv(csv_path, dtype=str).fillna("")
    if excel_file:
        excel_path = find_excel_file(folder, excel_file)
        if excel_path.suffix.lower() == ".csv":
            return pd.read_csv(excel_path, dtype=str).fillna("")
        return pd.read_excel(excel_path, sheet_name=excel_sheet, dtype=str).fillna("")
    raise FileNotFoundError(f"block source not found: {block_csv_path}")


def get_dynamic_schema_from_db(db_path: Path, target_cols):
    if not db_path.exists():
        return {col: [] for col in target_cols}
    try:
        df = pd.read_csv(db_path, low_memory=False)
    except Exception:
        return {col: [] for col in target_cols}
    schema_dict = {}
    for col in target_cols:
        if col in df.columns:
            schema_dict[col] = (
                df[col].dropna().astype(str).str.strip().replace("", pd.NA).dropna().unique().tolist()[:10]
            )
        else:
            schema_dict[col] = []
    return schema_dict


def truncate_text(text: str, max_len: int = MAX_CELL_TEXT_LEN) -> str:
    s = safe_str(text).replace("\n", " ").replace("\r", " ")
    return s if len(s) <= max_len else s[: max_len - 3] + "..."


def dataframe_to_sheet_capture(df: pd.DataFrame, out_path: Path, title: str = ""):
    show_df = df.copy()
    if len(show_df) > MAX_ROWS_FOR_CAPTURE:
        show_df = show_df.iloc[:MAX_ROWS_FOR_CAPTURE].copy()
    if show_df.shape[1] > MAX_COLS_FOR_CAPTURE:
        show_df = show_df.iloc[:, :MAX_COLS_FOR_CAPTURE].copy()
    show_df.columns = [truncate_text(c, 25) for c in show_df.columns]
    for col in show_df.columns:
        show_df[col] = show_df[col].map(lambda x: truncate_text(x, MAX_CELL_TEXT_LEN))
    rows = show_df.shape[0] + 1
    cols = show_df.shape[1]
    cell_w = 180
    cell_h = 28
    margin = 20
    title_h = 40 if title else 10
    width = margin * 2 + cols * cell_w
    height = margin * 2 + title_h + rows * cell_h
    img = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype("/System/Library/Fonts/Supplemental/Courier New.ttf", 14)
    except Exception:
        font = ImageFont.load_default()
    y0 = margin
    if title:
        draw.text((margin, y0), title, fill="black", font=font)
        y0 += title_h
    for c, col_name in enumerate(show_df.columns):
        x = margin + c * cell_w
        draw.rectangle([x, y0, x + cell_w, y0 + cell_h], outline="black", fill="#d9eaf7")
        draw.text((x + 5, y0 + 6), safe_str(col_name), fill="black", font=font)
    for r in range(show_df.shape[0]):
        for c in range(cols):
            x = margin + c * cell_w
            y = y0 + (r + 1) * cell_h
            draw.rectangle([x, y, x + cell_w, y + cell_h], outline="gray", fill="white")
            draw.text((x + 5, y + 6), safe_str(show_df.iat[r, c]), fill="black", font=font)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(out_path)


def get_image_part(image_path: Path):
    with open(image_path, "rb") as f:
        img_bytes = f.read()
    return types.Part.from_bytes(data=img_bytes, mime_type="image/png")


def get_file_part(file_path: Path):
    suffix = file_path.suffix.lower()
    if suffix == ".pdf":
        mime_type = "application/pdf"
    elif suffix in {".jpg", ".jpeg"}:
        mime_type = "image/jpeg"
    elif suffix == ".png":
        mime_type = "image/png"
    else:
        mime_type = "application/octet-stream"
    with open(file_path, "rb") as f:
        data = f.read()
    return types.Part.from_bytes(data=data, mime_type=mime_type)


def make_direct_block_request_id(excel_file: str, excel_sheet: str, block_id: str, block_csv_path: str) -> str:
    seed = block_csv_path or f"{excel_file}|{excel_sheet}|{block_id}"
    safe_seed = re.sub(r"[^a-z0-9]+", "_", str(seed).lower()).strip("_")
    return f"exp_vals_direct__{safe_seed or 'unknown'}"


def build_direct_llm_prompt(
    excel_file: str,
    excel_sheet: str,
    block_id: str,
    block_csv_path: str,
    item_ids,
    csv_text: str,
    numeric_cells_stripped: bool,
    schema_json_str: str,
    request_id: str,
    previous_response_text: str = "",
    previous_error: str = "",
    is_retry: bool = False,
    item_metadata=None,
    block_metadata=None,
    validation_failure_reason: str = "",
):
    item_ids_str = ", ".join(item_ids)
    retry_context = ""
    if is_retry:
        retry_context = f"""
Previous attempt failed.
Fix the JSON structure based on the previous response and error.
Return valid JSON only.
request_id must match exactly.

previous_response_text:
{previous_response_text or "<empty>"}

previous_error:
{previous_error or "<empty>"}

validation_failure_reason:
{validation_failure_reason or "<empty>"}
""".strip()
        retry_context = f"{retry_context}\n\n"

    return f"""
request_id: {request_id}

{retry_context}You are extracting formulation-level experimental values from one Excel block.
- excel_file: {excel_file}
- excel_sheet: {excel_sheet}
- block_id: {block_id}
- block_csv_path: {block_csv_path}
- item_ids: {item_ids_str}
- numeric_cells_stripped: {numeric_cells_stripped}

{format_metadata_block(item_metadata, block_metadata=block_metadata)}

{format_figure_evidence_block(block_metadata=block_metadata)}

{VISUAL_EXTRACTION_RULES}

Validation failure to correct, if any:
{validation_failure_reason or "<none>"}

Expected heatmap examples:
- figure 2b: rows=B1~B7 bromide tails, columns=1A1~2A13 amine heads. formulation_id=<amine_head><bromide_tail>, condition_1_name=amine_head, condition_2_name=bromide_tail, one numeric cell per row.
- figure 2c: rows=B1~B7 tails, subrows=Li/Sp/Lu organ, columns=1A1~2A13 amine heads. formulation_id=<amine_head><bromide_tail>, condition_3_name=organ, metric_type=selectivity, one numeric cell per row.

Use the block screenshot and CSV text together.
Return valid JSON only.
Schema hints:
{schema_json_str}

Block CSV:
{csv_text}

Return JSON only:
{{
  "request_id": "{request_id}",
  "rows": [
    {{
      "Matched_Sheet_File": "{excel_file} [{excel_sheet}] [{block_id}]",
      "Item_ID": "{item_ids_str}",
      "visual_type": "heatmap",
      "formulation_id": "MC3",
      "condition_1_name": "",
      "condition_1_value": "",
      "condition_2_name": "",
      "condition_2_value": "",
      "condition_3_name": "",
      "condition_3_value": "",
      "condition_4_name": "",
      "condition_4_value": "",
      "metric_type": "Size",
      "original_values": "",
      "aggregated_value": "72.5"
    }}
  ]
}}
""".strip()


def parse_direct_llm_payload(payload_text: str, expected_request_id: str, item_metadata=None, block_metadata=None, item_ids=None, matched_sheet_file: str = "") -> pd.DataFrame:
    cleaned = str(payload_text or "").replace("```json", "").replace("```", "").strip()
    if not cleaned:
        raise ValueError("empty response")
    payload = json.loads(cleaned)
    if isinstance(payload, list):
        rows = payload
        response_request_id = ""
    elif isinstance(payload, dict):
        response_request_id = str(payload.get("request_id", "")).strip()
        if response_request_id and response_request_id != expected_request_id:
            raise ValueError(f"request_id mismatch: expected={expected_request_id} | got={response_request_id}")
        rows = payload.get("rows") or payload.get("data") or payload.get("result") or []
    else:
        raise ValueError(f"payload must be dict or list, got {type(payload).__name__}")
    if not isinstance(rows, list):
        raise ValueError("rows must be a list")
    if rows and not all(isinstance(row, dict) for row in rows):
        raise ValueError("rows must be a list of objects")
    df = pd.DataFrame(rows)
    if df.empty:
        raise ValueError("rows empty")
    return ensure_output_schema(df, item_ids=item_ids, item_metadata=item_metadata or [], block_metadata=block_metadata or {}, matched_sheet_file=matched_sheet_file)


def parse_csv_text_to_df(csv_text: str) -> pd.DataFrame:
    if not csv_text or not csv_text.strip():
        return pd.DataFrame(columns=REQUIRED_COLS)
    try:
        df = pd.read_csv(io.StringIO(csv_text))
    except Exception:
        return pd.DataFrame(columns=REQUIRED_COLS)
    for col in REQUIRED_COLS:
        if col not in df.columns:
            df[col] = ""
    return ensure_output_schema(df)


def call_direct_llm_for_block(
    client,
    primary_model: str,
    fallback_model: str,
    image_part,
    excel_file: str,
    excel_sheet: str,
    block_id: str,
    block_csv_path: str,
    item_ids,
    csv_text: str,
    numeric_cells_stripped: bool,
    schema_json_str: str,
    request_id: str,
    evidence_part=None,
    item_metadata=None,
    block_metadata=None,
    validation_failure_reason: str = "",
    max_retries: int = 4,
):
    prompt_input = build_direct_llm_prompt(
        excel_file=excel_file,
        excel_sheet=excel_sheet,
        block_id=block_id,
        block_csv_path=block_csv_path,
        item_ids=item_ids,
        csv_text=csv_text,
        numeric_cells_stripped=numeric_cells_stripped,
        schema_json_str=schema_json_str,
        request_id=request_id,
        item_metadata=item_metadata or [],
        block_metadata=block_metadata or {},
        validation_failure_reason=validation_failure_reason,
    )
    models_to_try = [primary_model, fallback_model]
    last_error = None
    for model_name in models_to_try:
        for attempt in range(max_retries):
            try:
                call_result = generate_content_with_guard(
                    client=client,
                    model_name=model_name,
                    contents=[part for part in [image_part, evidence_part] if part is not None],
                    prompt_text=prompt_input,
                    task_name="exp_vals_direct_llm_block",
                    response_mime_type="application/json",
                    max_retries=1,
                )
                return call_result.response_text
            except Exception as e:
                last_error = e
                error_msg = str(e).lower()
                if "429" in error_msg or "resource_exhausted" in error_msg:
                    time.sleep(10 * (2 ** attempt))
                    continue
                if "400" in error_msg or "invalid_argument" in error_msg:
                    csv_text = csv_text[: max(1000, len(csv_text) // 2)]
                    prompt_input = build_direct_llm_prompt(
                        excel_file=excel_file,
                        excel_sheet=excel_sheet,
                        block_id=block_id,
                        block_csv_path=block_csv_path,
                        item_ids=item_ids,
                        csv_text=csv_text,
                        numeric_cells_stripped=numeric_cells_stripped,
                        schema_json_str=schema_json_str,
                        request_id=request_id,
                        item_metadata=item_metadata or [],
                        block_metadata=block_metadata or {},
                        validation_failure_reason=validation_failure_reason,
                    )
                    continue
                break
    raise RuntimeError(f"Direct LLM block extraction failed: {excel_file} [{excel_sheet}] [{block_id}] | {last_error}")


def save_outputs(folder: Path, result_df: pd.DataFrame):
    out_path = folder / OUTPUT_CSV_NAME
    xlsx_path = folder / OUTPUT_CSV_NAME.replace(".csv", ".xlsx")
    result_df = ensure_output_schema(result_df)
    result_df.to_csv(out_path, index=False, encoding="utf-8-sig")
    result_df.to_excel(xlsx_path, index=False)
    print(f"[direct_llm] saved: {out_path}")
    print(f"[direct_llm] saved: {xlsx_path}")


def load_direct_llm_tasks(folder: Path, client, schema_json_str: str):
    block_groups = load_matched_block_groups(folder)
    if not block_groups:
        return []

    capture_dir = folder / TEMP_CAPTURE_DIRNAME
    capture_dir.mkdir(parents=True, exist_ok=True)

    tasks = []
    for block_csv_path, meta in block_groups.items():
        if not is_valid_block_csv_path(block_csv_path):
            continue
        excel_file = safe_str(meta.get("excel_file"))
        excel_sheet = safe_str(meta.get("excel_sheet"))
        block_id = safe_str(meta.get("block_id")) or Path(block_csv_path).stem
        item_ids = meta.get("item_ids", [])
        try:
            df = load_block_df(folder, block_csv_path, excel_file, excel_sheet)
        except Exception as e:
            print(f"  ! block load failed: {block_csv_path} | {e}")
            continue
        csv_text_prepared, numeric_cells_stripped = prepare_csv_for_prompt(
            client, PRIMARY_MODEL, df.to_csv(index=False), stage_name=f"direct_block::{block_id}"
        )
        capture_path = capture_dir / f"{Path(excel_file).stem}__{excel_sheet}__{block_id}.png"
        dataframe_to_sheet_capture(df, capture_path, title=f"{excel_file} [{excel_sheet}] [{block_id}]")
        image_part = get_image_part(capture_path)
        request_id = make_direct_block_request_id(excel_file, excel_sheet, block_id, block_csv_path)
        task_item_metadata = meta.get("item_metadata", [])
        dominant_meta = task_item_metadata[0] if task_item_metadata else {}
        tasks.append(
            {
                "request_id": request_id,
                "block_csv_path": block_csv_path,
                "excel_file": excel_file,
                "excel_sheet": excel_sheet,
                "block_id": block_id,
                "item_ids": item_ids,
                "item_metadata": task_item_metadata,
                "block_metadata": {
                    "visual_type": safe_str(meta.get("visual_type")) or safe_str(dominant_meta.get("visual_type")) or "unknown",
                    "estimated_data_count": safe_str(meta.get("estimated_data_count")) or safe_str(dominant_meta.get("estimated_data_count")),
                    "mapping_reason": safe_str(meta.get("mapping_reason")),
                    "classified_reason": safe_str(meta.get("classified_reason")) or safe_str(dominant_meta.get("classified_reason")) or safe_str(dominant_meta.get("reason")),
                    "metadata_found": bool(meta.get("metadata_found", bool(dominant_meta))),
                    "metadata_matched_by": safe_str(meta.get("metadata_matched_by")) or ("item_id" if dominant_meta else "not_found"),
                    "excel_file": excel_file,
                    "excel_sheet": excel_sheet,
                    "block_id": block_id,
                    "block_csv_path": block_csv_path,
                },
                "csv_text": csv_text_prepared,
                "numeric_cells_stripped": numeric_cells_stripped,
                "image_part": image_part,
                "schema_json_str": schema_json_str,
                "previous_response_text": "",
                "previous_error": "",
            }
        )
    return tasks


def run_direct_llm_batch_for_tasks(
    client,
    folder: Path,
    tasks: list,
    model_name: str,
    batch_tag: str,
):
    if not tasks:
        return {}

    request_file = create_batch_request_file(folder, f"exp_vals_direct_{folder.name}_{batch_tag}")
    for task in tasks:
        prompt_input = build_direct_llm_prompt(
            excel_file=task["excel_file"],
            excel_sheet=task["excel_sheet"],
            block_id=task["block_id"],
            block_csv_path=task["block_csv_path"],
            item_ids=task["item_ids"],
            csv_text=task["csv_text"],
            numeric_cells_stripped=task["numeric_cells_stripped"],
            schema_json_str=task["schema_json_str"],
            request_id=task["request_id"],
            item_metadata=task.get("item_metadata", []),
            block_metadata=task.get("block_metadata", {}),
            validation_failure_reason=task.get("previous_error", ""),
            previous_response_text=task.get("previous_response_text", ""),
            previous_error=task.get("previous_error", ""),
            is_retry=batch_tag.startswith("retry"),
        )
        metadata = build_batch_request_metadata(
            task_name="exp_vals_direct_llm_block",
            model_name=model_name,
            custom_id=task["request_id"],
            stage_name=f"exp_vals_direct_llm_{batch_tag}",
            item_id=task["block_csv_path"],
            paper_folder=str(folder),
        )
        request_body = build_generate_content_batch_request(
            model_name=model_name,
            contents=[task["image_part"]],
            prompt_text=prompt_input,
            response_mime_type="application/json",
        )
        append_batch_request(request_file, task["request_id"], request_body, metadata)

    local_job_id = create_batch_job_record(
        paper_folder=folder,
        task_name="exp_vals_direct_llm_block",
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
        paper_folder=folder,
        local_job_id=local_job_id,
        display_name=f"exp-vals-direct-{folder.name}-{batch_tag}",
    )
    print(f"  batch submitted ({batch_tag}): {batch_job.name}")
    finished_job = poll_batch_job(client=client, paper_folder=folder, local_job_id=local_job_id, poll_interval_seconds=30)
    state_name = getattr(getattr(finished_job, "state", None), "name", None) or str(getattr(finished_job, "state", "UNKNOWN"))
    if state_name != "JOB_STATE_SUCCEEDED":
        raise RuntimeError(f"batch failed ({batch_tag}): {state_name}")
    result_file = download_batch_results(client=client, paper_folder=folder, local_job_id=local_job_id)
    return load_batch_results_as_map(result_file)


def collect_direct_llm_results(tasks: list, results_map: dict, pass_label: str):
    all_frames = []
    failed_tasks = []
    for task in tasks:
        row = results_map.get(task["request_id"])
        if not row:
            task["previous_response_text"] = ""
            task["previous_error"] = "request_id missing from batch results map"
            print(f"  ! {pass_label} missing result: {task['request_id']}")
            failed_tasks.append(task)
            continue

        response_text = str(row.get("response_text", "")).strip()
        if not row.get("success") or not response_text:
            task["previous_response_text"] = response_text
            task["previous_error"] = str(row.get("error") or "batch response missing or unsuccessful")
            print(f"  ! {pass_label} unsuccessful: {task['request_id']} | {task['previous_error']}")
            failed_tasks.append(task)
            continue

        try:
            df_one = parse_direct_llm_payload(
                response_text,
                task["request_id"],
                item_metadata=task.get("item_metadata", []),
                block_metadata=task.get("block_metadata", {}),
                item_ids=task.get("item_ids", []),
                matched_sheet_file=f"{task['excel_file']} [{task['excel_sheet']}] [{task['block_id']}]",
            )
            all_frames.append(df_one)
            print(f"  {pass_label}: {task['excel_file']} [{task['excel_sheet']}] [{task['block_id']}]")
        except Exception as e:
            task["previous_response_text"] = response_text
            task["previous_error"] = str(e)
            print(f"  ! {pass_label} parse failed: {task['request_id']} | {e}")
            failed_tasks.append(task)
    return all_frames, failed_tasks


def extract_exp_vals_direct_llm(
    folder_path: str,
    api_json_name: str = API_JSON_NAME,
    execution_mode: str = "batch",
):
    execution_mode = str(execution_mode).strip().lower()
    if execution_mode not in {"sync", "batch"}:
        raise ValueError(f"invalid execution_mode: {execution_mode}")

    folder = Path(folder_path)
    if not folder.exists():
        raise FileNotFoundError(f"folder not found: {folder}")

    key_path = find_api_key_file(api_json_name)
    with open(key_path, "r", encoding="utf-8") as f:
        cred_data = json.load(f)
    project_id = cred_data.get("project_id")
    if not project_id:
        raise ValueError(f"project_id missing: {key_path}")
    client = get_vertexai_client(key_path, project=project_id)

    schema_cols = ["metric_type", "formulation_id"]
    schema_dict = get_dynamic_schema_from_db(LNPDB_CSV_PATH, schema_cols)
    schema_json_str = json.dumps(schema_dict, indent=2, ensure_ascii=False)

    tasks = load_direct_llm_tasks(folder, client, schema_json_str)
    if not tasks:
        save_outputs(folder, pd.DataFrame(columns=REQUIRED_COLS))
        return

    all_frames = []
    remaining_tasks = list(tasks)

    try:
        first_pass_results = run_direct_llm_batch_for_tasks(
            client=client,
            folder=folder,
            tasks=remaining_tasks,
            model_name=PRIMARY_MODEL,
            batch_tag="pass1",
        )
    except Exception as e:
        print(f"  ! batch first pass failed: {e}")
        first_pass_results = {}

    first_pass_frames, remaining_tasks = collect_direct_llm_results(
        tasks=remaining_tasks,
        results_map=first_pass_results,
        pass_label="batch first pass success",
    )
    all_frames.extend(first_pass_frames)

    if remaining_tasks:
        try:
            retry_results = run_direct_llm_batch_for_tasks(
                client=client,
                folder=folder,
                tasks=remaining_tasks,
                model_name=PRIMARY_MODEL,
                batch_tag="retry1",
            )
        except Exception as e:
            print(f"  ! batch retry failed: {e}")
            retry_results = {}

        retry_frames, remaining_tasks = collect_direct_llm_results(
            tasks=remaining_tasks,
            results_map=retry_results,
            pass_label="batch retry success",
        )
        all_frames.extend(retry_frames)

    if execution_mode == "sync":
        for task in remaining_tasks:
            try:
                response_text = call_direct_llm_for_block(
                    client=client,
                    primary_model=PRIMARY_MODEL,
                    fallback_model=FALLBACK_MODEL,
                    image_part=task["image_part"],
                    excel_file=task["excel_file"],
                    excel_sheet=task["excel_sheet"],
                    block_id=task["block_id"],
                    block_csv_path=task["block_csv_path"],
                    item_ids=task["item_ids"],
                    csv_text=task["csv_text"],
                    numeric_cells_stripped=task["numeric_cells_stripped"],
                    schema_json_str=task["schema_json_str"],
                    request_id=task["request_id"],
                    item_metadata=task.get("item_metadata", []),
                    block_metadata=task.get("block_metadata", {}),
                    validation_failure_reason=task.get("previous_error", ""),
                )
                df_one = parse_direct_llm_payload(
                    response_text,
                    task["request_id"],
                    item_metadata=task.get("item_metadata", []),
                    block_metadata=task.get("block_metadata", {}),
                    item_ids=task.get("item_ids", []),
                    matched_sheet_file=f"{task['excel_file']} [{task['excel_sheet']}] [{task['block_id']}]",
                )
                all_frames.append(df_one)
                print(f"  sync retry success: {task['excel_file']} [{task['excel_sheet']}] [{task['block_id']}]")
            except Exception as e:
                print(f"    ! final failure: {task['request_id']} | {e}")
    else:
        for task in remaining_tasks:
            print(f"    ! final failure (batch only): {task['request_id']}")

    result_df = ensure_output_schema(pd.concat(all_frames, ignore_index=True) if all_frames else pd.DataFrame(columns=REQUIRED_COLS))
    if not result_df.empty:
        result_df = result_df[
            ~(
                result_df["formulation_id"].astype(str).str.strip().eq("")
                & result_df["metric_type"].astype(str).str.strip().eq("")
                & result_df["original_values"].astype(str).str.strip().eq("")
                & result_df["aggregated_value"].astype(str).str.strip().eq("")
            )
        ].reset_index(drop=True)
    save_outputs(folder, result_df)


def main(api_json_name: str = API_JSON_NAME):
    target_folder = r"/Users/kogeon/Library/CloudStorage/GoogleDrive-geon@molcube.com/ATLAS_only_DOIs/38. Payload distribution and capacity of mRNA lipid nanoparticles"
    extract_exp_vals_direct_llm(target_folder, api_json_name)


if __name__ == "__main__":
    main(API_JSON_NAME)
