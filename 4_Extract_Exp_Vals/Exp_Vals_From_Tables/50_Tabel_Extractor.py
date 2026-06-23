import csv
import io
import json
import math
import re
import sys
import time
from pathlib import Path

import pandas as pd
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
    upload_file_to_gcs,
)

API_JSON_NAME = "vertex.json"
PRIMARY_MODEL = "gemini-3.1-pro-preview"
FALLBACK_MODEL = "gemini-3-flash-preview"
SELECTOR_CSV_NAME = "fig_table_lnpdb_classified.csv"
OUTPUT_CSV_NAME = "exp_vals_from_tables.csv"
DEFAULT_GCS_BATCH_BUCKET = "gs://lnpdb-articles-extraction-batch-results-geon"
REQUIRED_COLS = [
    "Matched_Sheet_File",
    "Item_ID",
    "formulation_id",
    "metric_type",
    "original_values",
    "aggregated_value",
]


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


def prepare_text_for_prompt(client, model_name, text: str, stage_name: str, soft_token_limit: int = 120000):
    if text is None:
        text = ""
    estimated = estimate_text_size_for_gemini(text)
    counted_tokens = maybe_count_tokens_with_client(client, model_name, text)
    token_basis = counted_tokens if counted_tokens is not None else estimated["approx_tokens"]
    print(
        f"      [size:{stage_name}] chars={estimated['char_count']:,}, "
        f"words={estimated['word_count']:,}, approx_tokens={estimated['approx_tokens']:,}"
        + (f" counted_tokens={counted_tokens:,}" if counted_tokens is not None else "")
    )
    if token_basis <= soft_token_limit:
        return text, False
    stripped_text = strip_numeric_cells_from_csv(text)
    stripped_estimated = estimate_text_size_for_gemini(stripped_text)
    stripped_counted_tokens = maybe_count_tokens_with_client(client, model_name, stripped_text)
    stripped_basis = stripped_counted_tokens if stripped_counted_tokens is not None else stripped_estimated["approx_tokens"]
    print(
        f"      [size:{stage_name}:stripped] chars={stripped_estimated['char_count']:,}, "
        f"words={stripped_estimated['word_count']:,}, approx_tokens={stripped_estimated['approx_tokens']:,}"
        + (f" counted_tokens={stripped_counted_tokens:,}" if stripped_counted_tokens is not None else "")
    )
    if stripped_basis < token_basis:
        return stripped_text, True
    return text, False


def get_document_part(file_path: Path):
    mime_map = {".pdf": "application/pdf", ".md": "text/plain", ".txt": "text/plain"}
    with open(file_path, "rb") as f:
        return types.Part.from_bytes(data=f.read(), mime_type=mime_map.get(file_path.suffix.lower(), "text/plain"))

def upload_pdfs_to_gcs(folder: Path, gcs_batch_bucket: str) -> list[dict]:
    uploaded = []
    for pdf_path in find_pdf_files(folder):
        gcs_uri = f"{gcs_batch_bucket}/papers/{folder.name}/{pdf_path.name}"
        upload_file_to_gcs(pdf_path, gcs_uri)
        uploaded.append(
            {
                "local_path": str(pdf_path),
                "gcs_uri": gcs_uri,
                "mime_type": "application/pdf",
                "name": pdf_path.name,
            }
        )
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

def find_selector_csv(folder: Path, classified_csv_path=None) -> Path:
    if classified_csv_path is not None:
        csv_path = Path(classified_csv_path)
        if not csv_path.exists():
            raise FileNotFoundError(f"selector CSV not found: {csv_path}")
        return csv_path

    csv_path = folder / SELECTOR_CSV_NAME
    if not csv_path.exists():
        raise FileNotFoundError(f"selector CSV not found: {csv_path}")
    return csv_path


EMPTY_MANUAL_VALUES = {"", "nan", "none", "null", "[]", "{}"}

def is_meaningful_manual_value(value) -> bool:
    if value is None:
        return False
    try:
        if pd.isna(value):
            return False
    except (TypeError, ValueError):
        pass
    return str(value).strip().lower() not in EMPTY_MANUAL_VALUES


def get_selector_value(row, manual_col: str | None, need_col: str) -> str:
    manual = str(row.get(manual_col, "")).strip().lower() if manual_col else ""
    if is_meaningful_manual_value(manual):
        if manual in {"yes", "y", "1", "true"}:
            return "yes"
        if manual in {"no", "n", "0", "false"}:
            return "no"
        if manual == "maybe":
            return "maybe"
        return "no"

    return str(row.get(need_col, "")).strip().lower()


def split_selector_targets(folder: Path, classified_csv_path=None):
    csv_path = find_selector_csv(folder, classified_csv_path=classified_csv_path)
    df = pd.read_csv(csv_path)
    cols_lower = {c.lower(): c for c in df.columns}
    item_col = cols_lower.get("item_id")
    type_col = cols_lower.get("item_type")
    manual_col = cols_lower.get("manual_select")
    need_col = cols_lower.get("need_for_lnpdb") or cols_lower.get("extractable")
    visual_col = cols_lower.get("visual_type")
    reason_col = cols_lower.get("reason")
    confidence_col = cols_lower.get("confidence")
    if item_col is None or need_col is None or visual_col is None:
        raise ValueError("selector CSV missing required columns")
    df[item_col] = df[item_col].astype(str).str.strip().str.lower()
    df[type_col] = df[type_col].astype(str).str.strip().str.lower()
    df[visual_col] = df[visual_col].astype(str).str.strip().str.lower()
    df[need_col] = df[need_col].astype(str).str.strip().str.lower()
    df["_selector_value"] = df.apply(get_selector_value, axis=1, manual_col=manual_col, need_col=need_col)
    keep_values = {"yes", "maybe", "o", "true", "1", "y"}
    if manual_col:
        manual_mask = df[manual_col].apply(is_meaningful_manual_value)
    else:
        manual_mask = pd.Series(False, index=df.index)
    selected_mask = df["_selector_value"].isin(keep_values)
    table_mask = df[visual_col] == "table"
    target_mask = (manual_mask & selected_mask) | (~manual_mask & table_mask & selected_mask)
    table_df = df[target_mask | (~manual_mask & table_mask)].copy()
    target_df = table_df[table_df["_selector_value"].isin(keep_values)].copy()
    non_target_df = table_df[~table_df["_selector_value"].isin(keep_values)].copy()
    print(f"  - rows selected by manual_select override: {int((manual_mask & selected_mask).sum())}")
    print(f"  - rows selected by automatic criteria: {int((~manual_mask & table_mask & selected_mask).sum())}")
    print(f"  - rows excluded by manual_select=no/invalid: {int((manual_mask & ~selected_mask).sum())}")
    target_df = target_df.drop_duplicates(subset=[item_col]).reset_index(drop=True)
    non_target_df = non_target_df.drop_duplicates(subset=[item_col]).reset_index(drop=True)

    def _normalize_output(sub_df: pd.DataFrame, is_target: bool) -> pd.DataFrame:
        out = pd.DataFrame()
        out["Item_ID"] = sub_df[item_col].astype(str).str.strip() if item_col in sub_df.columns else ""
        out["Item_Type"] = sub_df[type_col].astype(str).str.strip() if type_col and type_col in sub_df.columns else ""
        out["Selector_Value"] = sub_df["_selector_value"].astype(str).str.strip() if "_selector_value" in sub_df.columns else ""
        out["Is_Target"] = is_target
        out["Visual_Type"] = sub_df[visual_col].astype(str).str.strip() if visual_col and visual_col in sub_df.columns else ""
        out["Reason"] = sub_df[reason_col].astype(str).str.strip() if reason_col and reason_col in sub_df.columns else ""
        out["Confidence"] = sub_df[confidence_col].astype(str).str.strip() if confidence_col and confidence_col in sub_df.columns else ""
        return out.reset_index(drop=True)

    return _normalize_output(target_df, True), _normalize_output(non_target_df, False)


def find_md_files(folder: Path):
    md_files = sorted([p for p in folder.rglob("*.md") if p.is_file()])
    print(f"  found {len(md_files)} markdown files")
    return md_files


def find_pdf_files(folder: Path):
    pdf_files = sorted([p for p in folder.rglob("*.pdf") if p.is_file()])
    print(f"  found {len(pdf_files)} pdf files")
    return pdf_files


def load_markdown_text(folder: Path, max_chars: int = 120000) -> str:
    texts = []
    for md_path in find_md_files(folder):
        try:
            texts.append(md_path.read_text(encoding="utf-8", errors="ignore"))
        except Exception:
            continue
    return "\n\n".join(texts)[:max_chars]


def build_item_search_patterns(item_id: str) -> list[str]:
    item = re.sub(r"\s+", " ", str(item_id or "").strip().lower())
    m = re.match(r"^(supplementary\s+)?(figure|fig|table)\s+([a-z]?\d+|\d+[a-z]?)([a-z])?$", item)
    if not m:
        return [re.escape(item)] if item else []

    supp_prefix = m.group(1) or ""
    kind = m.group(2)
    number_token = m.group(3)
    trailing_panel = m.group(4) or ""

    panel = trailing_panel
    base_number = number_token
    m2 = re.match(r"^([a-z]?)(\d+)([a-z]?)$", number_token)
    if m2:
        leading_letter, digits, trailing_letter = m2.groups()
        if digits:
            base_number = digits
        if not panel and trailing_letter:
            panel = trailing_letter

    kind_variants = []
    if kind in {"figure", "fig"}:
        kind_variants = [r"figure", r"fig\\.?"]
    elif kind == "table":
        kind_variants = [r"table", r"tab\\.?"]

    prefix_variants = [""]
    if supp_prefix:
        prefix_variants = [r"supplementary\s+", r"supp\\.?\s+", r""]

    number_variants = [re.escape(base_number)]
    if supp_prefix:
        number_variants.append(rf"s\s*{re.escape(base_number)}")

    panel_variants = [""]
    if panel:
        panel_variants = [
            rf"\s*{re.escape(panel)}",
            rf"\s*\(\s*{re.escape(panel)}\s*\)",
            rf"\s*[.\-:]\s*\(\s*{re.escape(panel)}\s*\)",
            rf"\s*[.\-:]\s*{re.escape(panel)}",
        ]

    patterns = []
    for prefix in prefix_variants:
        for kind_pat in kind_variants:
            for num_pat in number_variants:
                for panel_pat in panel_variants:
                    patterns.append(rf"{prefix}{kind_pat}\s+{num_pat}{panel_pat}")

    unique_patterns = []
    seen = set()
    for pat in patterns:
        if pat not in seen:
            seen.add(pat)
            unique_patterns.append(pat)
    return unique_patterns


def find_item_id_match(md_text: str, item_id: str):
    if not md_text.strip():
        return None
    for pat in build_item_search_patterns(item_id):
        match = re.search(pat, md_text, flags=re.IGNORECASE)
        if match:
            return match
    return None


def is_caption_start_line(line: str) -> bool:
    text = str(line or "").strip()
    if not text:
        return False
    text = re.sub(r"^#{1,6}\s+", "", text)
    return bool(
        re.match(
            r"^(?:supplementary\s+|supp\.?\s+)?(?:table|tab\.?|figure|fig\.?)\s+"
            r"(?:s\s*)?(?:[a-z]?\d+|\d+[a-z]?)(?:\s*[a-z]|\s*\([a-z]\))?"
            r"(?:[\s.:;\-–—]|$)",
            text,
            flags=re.IGNORECASE,
        )
    )


def is_heading_line(line: str) -> bool:
    return bool(re.match(r"^\s{0,3}#{1,6}\s+\S", str(line or "")))


def is_table_like_line(line: str) -> bool:
    text = str(line or "").rstrip()
    stripped = text.strip()
    if not stripped:
        return False
    if stripped.count("|") >= 2:
        return True
    if "\t" in stripped and len([part for part in stripped.split("\t") if part.strip()]) >= 2:
        return True
    column_like = bool(re.search(r"\S+\s{2,}\S+(?:\s{2,}\S+)+", stripped))
    row_tokens = bool(
        re.search(
            r"(?:\d+(?:\.\d+)?(?:e[+-]?\d+)?|%|±|\+/-|\b[A-Z]{1,4}\d+[A-Za-z]?\b|"
            r"\b(?:DOTAP|DOPE|DSPC|cholesterol|PEG|MC3|DLin|lipid|LNP|RNA|mRNA|siRNA)\b)",
            stripped,
            flags=re.IGNORECASE,
        )
    )
    return column_like and row_tokens


def line_offsets(text: str) -> list[tuple[int, int, str]]:
    offsets = []
    pos = 0
    for line in text.splitlines(keepends=True):
        start = pos
        end = pos + len(line)
        offsets.append((start, end, line.rstrip("\n\r")))
        pos = end
    if text and (not offsets or offsets[-1][1] < len(text)):
        offsets.append((pos, len(text), text[pos:]))
    return offsets


def extract_matched_table_span(md_text: str, match, item_id=None, max_chars: int | None = 12000) -> str | None:
    if not md_text or not md_text.strip() or match is None:
        return None

    offsets = line_offsets(md_text)
    if not offsets:
        return None

    match_start = match.start()
    start_idx = 0
    for i, (line_start, line_end, _) in enumerate(offsets):
        if line_start <= match_start < line_end:
            start_idx = i
            break

    start_char = offsets[start_idx][0]
    end_idx = len(offsets)
    table_like_count = 0
    seen_table_like = False
    blank_run_after_rows = 0
    non_table_after_blank = 0
    non_table_after_pipe_rows = 0
    previous_line_was_pipe = False

    for i in range(start_idx + 1, len(offsets)):
        _, _, line = offsets[i]
        stripped = line.strip()
        table_like = is_table_like_line(line)

        if stripped and (is_heading_line(line) or is_caption_start_line(line)):
            end_idx = i
            break

        if table_like:
            table_like_count += 1
            seen_table_like = True
            blank_run_after_rows = 0
            non_table_after_blank = 0
            non_table_after_pipe_rows = 0
            previous_line_was_pipe = stripped.count("|") >= 2
            continue

        if not stripped:
            if seen_table_like:
                blank_run_after_rows += 1
                previous_line_was_pipe = False
            continue

        if seen_table_like and blank_run_after_rows >= 1:
            non_table_after_blank += 1
            if non_table_after_blank >= 1:
                end_idx = i
                break

        if seen_table_like and previous_line_was_pipe:
            non_table_after_pipe_rows += 1
            if non_table_after_pipe_rows >= 2:
                end_idx = i
                break

    end_char = offsets[end_idx][0] if end_idx < len(offsets) else len(md_text)
    span = md_text[start_char:end_char].strip()
    if not span:
        return None

    if table_like_count < 2 and len(span) < 500:
        return None

    original_chars = len(span)
    if max_chars and original_chars > max_chars:
        span = span[:max_chars].rstrip()
        print(f"[snippet] matched table span truncated: item_id={item_id}, original_chars={original_chars}, kept_chars={len(span)}")

    return span if span else None


def extract_local_table_snippet(md_text: str, item_id: str, window_chars: int = 12000) -> str:
    if not md_text.strip():
        return ""

    best_match = find_item_id_match(md_text, item_id)

    if best_match is None:
        return md_text

    idx = best_match.start()
    start = max(0, idx - window_chars // 3)
    end = min(len(md_text), idx + (window_chars * 2 // 3))
    snippet = md_text[start:end].strip()
    return snippet if snippet else md_text


def make_table_request_id(item_id: str) -> str:
    safe_item = re.sub(r"[^a-z0-9]+", "_", str(item_id).lower()).strip("_")
    return f"table_extract__{safe_item or 'unknown'}"


def build_table_extraction_prompt(item_id: str, md_snippet: str, numeric_cells_stripped: bool, request_id: str) -> str:
    return f"""
request_id: {request_id}
item_id: {item_id}

Extract formulation-level experimental values for this table only.
If repeated measurements exist, join them with ';' in '?ㅽ뿕?섏튂??' and put the arithmetic mean in '?ㅽ뿕?섏튂1'.

Markdown snippet:
{md_snippet}

numeric_cells_stripped: {numeric_cells_stripped}

Return JSON only:
{{
  "request_id": "{request_id}",
  "rows": [
    {{
      "Matched_Sheet_File": "TABLE::{item_id}",
      "Item_ID": "{item_id}",
      "formulation_id": "MC3",
      "metric_type": "Size",
      "original_values": "",
      "aggregated_value": "72.5"
    }}
  ]
}}
""".strip()


def parse_table_batch_payload(payload_text: str, expected_request_id: str) -> pd.DataFrame:
    cleaned = str(payload_text or "").replace("```json", "").replace("```", "").strip()
    if not cleaned:
        raise ValueError("empty response")
    payload = json.loads(cleaned)
    response_request_id = str(payload.get("request_id", "")).strip()
    if not response_request_id:
        raise ValueError("missing request_id")
    if response_request_id != expected_request_id:
        raise ValueError(f"request_id mismatch: expected={expected_request_id} | got={response_request_id}")
    rows = payload.get("rows")
    if not isinstance(rows, list):
        raise ValueError("rows must be a list")
    df = pd.DataFrame(rows)
    if df.empty:
        raise ValueError("rows empty")
    for col in REQUIRED_COLS:
        if col not in df.columns:
            raise ValueError(f"missing required column: {col}")
    return df[REQUIRED_COLS].copy()


def call_gemini_for_table(client, primary_model: str, fallback_model: str, document_parts, item_id: str, md_snippet: str, max_retries: int = 4):
    request_id = make_table_request_id(item_id)
    prompt_input, numeric_cells_stripped = prepare_text_for_prompt(client, primary_model, md_snippet, stage_name=f"table::{item_id}")
    prompt = build_table_extraction_prompt(item_id=item_id, md_snippet=prompt_input, numeric_cells_stripped=numeric_cells_stripped, request_id=request_id)
    for model_name in [primary_model, fallback_model]:
        for attempt in range(max_retries):
            try:
                call_result = generate_content_with_guard(
                    client=client,
                    model_name=model_name,
                    contents=document_parts,
                    prompt_text=prompt,
                    task_name="table_extraction",
                    response_mime_type="application/json",
                    max_retries=1,
                )
                return call_result.response_text
            except Exception as e:
                error_msg = str(e).lower()
                if "429" in error_msg or "resource_exhausted" in error_msg:
                    time.sleep(10 * (2 ** attempt))
                    continue
                if "400" in error_msg or "invalid_argument" in error_msg:
                    prompt_input = prompt_input[: max(1000, len(prompt_input) // 2)]
                    prompt = build_table_extraction_prompt(item_id=item_id, md_snippet=prompt_input, numeric_cells_stripped=numeric_cells_stripped, request_id=request_id)
                    continue
                break
    raise RuntimeError(f"Gemini table extraction failed: {item_id}")


def save_outputs(folder: Path, result_df: pd.DataFrame, output_csv_path=None):
    csv_path = Path(output_csv_path) if output_csv_path is not None else folder / OUTPUT_CSV_NAME
    result_df.to_csv(csv_path, index=False, encoding="utf-8-sig")
    print(f"[table_extract] saved: {csv_path}")


def extract_exp_vals_from_tables(folder_path: str, api_json_name: str = API_JSON_NAME, model_name: str = None, fallback_model: str = None, classified_csv_path=None, output_csv_path=None):
    folder = Path(folder_path)
    active_primary_model = model_name or PRIMARY_MODEL
    active_fallback_model = fallback_model or FALLBACK_MODEL
    if not folder.exists():
        raise FileNotFoundError(f"folder not found: {folder}")

    key_path = find_api_key_file(api_json_name)
    with open(key_path, "r", encoding="utf-8") as f:
        cred_data = json.load(f)
    project_id = cred_data.get("project_id")
    if not project_id:
        raise ValueError(f"project_id missing: {key_path}")
    client = get_vertexai_client(key_path, project=project_id)

    target_df, _ = split_selector_targets(folder, classified_csv_path=classified_csv_path)
    selector_df = target_df.copy().reset_index(drop=True)
    if selector_df.empty:
        save_outputs(folder, pd.DataFrame(columns=REQUIRED_COLS), output_csv_path=output_csv_path)
        return

    md_text = load_markdown_text(folder)
    
    # sync fallback용
    document_parts = []
    for pdf_path in find_pdf_files(folder):
        try:
            document_parts.append(get_document_part(pdf_path))
        except Exception:
            pass
    for md_path in find_md_files(folder):
        try:
            document_parts.append(get_document_part(md_path))
        except Exception:
            pass
        
    # batch용 (JSON serializable)
    uploaded_pdfs = upload_pdfs_to_gcs(folder, DEFAULT_GCS_BATCH_BUCKET)
    batch_document_contents = build_pdf_file_parts(uploaded_pdfs)
    if md_text.strip():
        batch_document_contents.append(md_text)

    request_file = create_batch_request_file(folder, f"table_extract_{folder.name}")
    item_payloads = []
    for _, row in selector_df.iterrows():
        item_id = str(row["Item_ID"]).strip()
        request_id = make_table_request_id(item_id)
        item_match = find_item_id_match(md_text, item_id)
        md_snippet = extract_matched_table_span(md_text, item_match, item_id=item_id, max_chars=12000)
        if md_snippet:
            print(f"[snippet] extracted matched table span: item_id={item_id}, chars={len(md_snippet)}")
        else:
            print(f"[snippet] matched table span failed; fallback to local context window: item_id={item_id}")
            md_snippet = extract_local_table_snippet(md_text, item_id)
        prompt_input, numeric_cells_stripped = prepare_text_for_prompt(client, active_primary_model, md_snippet, stage_name=f"table::{item_id}")
        prompt = build_table_extraction_prompt(item_id=item_id, md_snippet=prompt_input, numeric_cells_stripped=numeric_cells_stripped, request_id=request_id)
        metadata = build_batch_request_metadata(
            task_name="table_extraction",
            model_name=active_primary_model,
            custom_id=request_id,
            stage_name="table_extraction",
            item_id=item_id,
            paper_folder=str(folder),
        )
        request_body = build_generate_content_batch_request(
            model_name=active_primary_model,
            contents=batch_document_contents,
            prompt_text=prompt,
            response_mime_type="application/json",
        )
        append_batch_request(request_file=request_file, custom_id=request_id, request_body=request_body, metadata=metadata)
        item_payloads.append({"item_id": item_id, "request_id": request_id, "md_snippet": md_snippet})

    local_job_id = create_batch_job_record(
        paper_folder=folder,
        task_name="table_extraction",
        model_name=active_primary_model,
        request_file=request_file,
        metadata={
            "request_count": count_requests_in_jsonl(request_file),
            "gcs_input_uri": f"{DEFAULT_GCS_BATCH_BUCKET}/batch/{request_file.name}",
            "gcs_output_uri_prefix": f"{DEFAULT_GCS_BATCH_BUCKET}/batch_output/{request_file.stem}",
        },
    )

    results_map = {}
    try:
        batch_job = submit_batch_job(client=client, paper_folder=folder, local_job_id=local_job_id, display_name=f"table-extract-{folder.name}")
        print(f"  batch submitted: {batch_job.name}")
        finished_job = poll_batch_job(client=client, paper_folder=folder, local_job_id=local_job_id, poll_interval_seconds=30)
        state_name = getattr(getattr(finished_job, "state", None), "name", None) or str(getattr(finished_job, "state", "UNKNOWN"))
        if state_name != "JOB_STATE_SUCCEEDED":
            raise RuntimeError(f"batch failed: {state_name}")
        result_file = download_batch_results(client=client, paper_folder=folder, local_job_id=local_job_id)
        results_map = load_batch_results_as_map(result_file)
    except Exception as e:
        print(f"  ! batch stage failed, falling back to sync retry for all tables: {e}")

    all_frames = []
    failed_items = []
    for item in item_payloads:
        row = results_map.get(item["request_id"])
        if not row or row.get("success") is not True or not str(row.get("response_text", "")).strip():
            failed_items.append(item)
            continue
        try:
            df_one = parse_table_batch_payload(row.get("response_text", ""), item["request_id"])
            all_frames.append(df_one)
        except Exception:
            failed_items.append(item)

    if failed_items:
        print(f"  sync retry for failed tables: {len(failed_items)}")
        for item in failed_items:
            try:
                response_text = call_gemini_for_table(
                    client=client,
                    primary_model=active_primary_model,
                    fallback_model=active_fallback_model,
                    document_parts=document_parts,
                    item_id=item["item_id"],
                    md_snippet=item["md_snippet"],
                )
                df_one = parse_table_batch_payload(response_text, item["request_id"])
                all_frames.append(df_one)
            except Exception as e:
                print(f"    ! final failure: {item['item_id']} | {e}")

    result_df = pd.concat(all_frames, ignore_index=True) if all_frames else pd.DataFrame(columns=REQUIRED_COLS)
    if not result_df.empty:
        result_df = result_df[
            ~(
                    result_df["formulation_id"].astype(str).str.strip().eq("")
                    & result_df["metric_type"].astype(str).str.strip().eq("")
                    & result_df["original_values"].astype(str).str.strip().eq("")
                    & result_df["aggregated_value"].astype(str).str.strip().eq("")
            )
        ].reset_index(drop=True)
    save_outputs(folder, result_df, output_csv_path=output_csv_path)


def main(api_json_name: str = API_JSON_NAME, model_name: str = PRIMARY_MODEL, fallback_model: str = FALLBACK_MODEL):
    target_folder = r"/Users/kogeon/Library/CloudStorage/GoogleDrive-geon@molcube.com/내 드라이브/ATLAS_only_DOIs/14. Engineered ionizable lipid nanoparticles for targeted delivery"
    extract_exp_vals_from_tables(target_folder, api_json_name=api_json_name, model_name=model_name, fallback_model=fallback_model)


if __name__ == "__main__":
    main(API_JSON_NAME, PRIMARY_MODEL, FALLBACK_MODEL)
