import hashlib
import importlib.util
import json
import re
import sys
import traceback
from pathlib import Path

import pandas as pd

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

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
from find_api import find_api_key_file, get_vertexai_client
from sheet_block_splitter import extract_block_df_from_ws, load_sheet_df_and_ws, split_sheet_into_blocks

DEFAULT_GCS_BATCH_BUCKET = "gs://lnpdb-articles-extraction-batch-results-geon"
API_JSON_NAME = "vertex.json"
MODEL_NAME = "gemini-3.1-pro-preview"


def _load_base_module():
    base_path = SCRIPT_DIR / "03_split_excel_blocks.py"
    spec = importlib.util.spec_from_file_location("split_excel_blocks_base", base_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"failed to load base module: {base_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


base = _load_base_module()
prepare_stage_text_with_token_limit = base.prepare_stage_text_with_token_limit
safe_path_name = base.safe_path_name
try_read_json = base.try_read_json
prepare_csv_for_prompt = base.prepare_csv_for_prompt
summarize_element_types = base.summarize_element_types
load_markdown_text = base.load_markdown_text
load_inventory_items = base.load_inventory_items
load_sheet_df = base.load_sheet_df
list_sheet_specs = base.list_sheet_specs
normalize_ft_item_id = base.normalize_ft_item_id
infer_candidates = base.infer_candidates
EXTENDED_DATA_PROMPT_NOTE = base.EXTENDED_DATA_PROMPT_NOTE


def list_pdf_paths(folder: Path) -> list[Path]:
    return sorted(folder.rglob("*.pdf"))


def upload_pdfs_to_gcs(folder: Path, bucket: str) -> list[dict]:
    uploaded = []
    for pdf_path in list_pdf_paths(folder):
        gcs_uri = f"{bucket}/papers/{folder.name}/{pdf_path.name}"
        upload_file_to_gcs(pdf_path, gcs_uri)
        uploaded.append({"gcs_uri": gcs_uri, "mime_type": "application/pdf"})
    return uploaded


def build_pdf_file_parts(uploaded_pdfs: list[dict]) -> list[dict]:
    return [
        {"fileData": {"fileUri": x["gcs_uri"], "mimeType": x.get("mime_type", "application/pdf")}}
        for x in uploaded_pdfs
        if x.get("gcs_uri")
    ]


def make_request_id(stage: str, *parts: str) -> str:
    seed = "::".join([stage, *[str(x) for x in parts]])
    return f"{stage}__{hashlib.sha1(seed.encode('utf-8')).hexdigest()[:16]}"


def normalize_list(value) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        value = [value]
    out = []
    for item in value:
        text = normalize_ft_item_id(item)
        if text and text not in out:
            out.append(text)
    return out


def usage_from_batch_row(row: dict, task_name: str, model_name: str) -> dict:
    cost_info = row.get("cost_info") or {}
    usage = {
        "task_name": task_name,
        "model_name": model_name,
        "input_tokens": row.get("input_tokens"),
        "output_tokens": row.get("output_tokens"),
        "total_tokens": row.get("total_tokens"),
        "billed_output_tokens": row.get("billed_output_tokens"),
    }
    if cost_info:
        usage["total_cost_usd"] = cost_info.get("total_cost_usd")
    return usage


def build_sync_usage_row(call_result) -> dict:
    usage = call_result.to_usage_dict() if hasattr(call_result, "to_usage_dict") else {}
    return {"success": True, "response_text": getattr(call_result, "response_text", "") or "", **usage}


def normalize_bbox(bbox: dict | None, fallback: dict | None = None) -> dict:
    bbox = bbox or {}
    fallback = fallback or {"r1": 1, "r2": 1, "c1": 1, "c2": 1}

    def _get(key: str) -> int:
        try:
            return int(bbox.get(key, fallback[key]))
        except Exception:
            return int(fallback[key])

    r1, r2 = sorted([_get("r1"), _get("r2")])
    c1, c2 = sorted([_get("c1"), _get("c2")])
    return {"r1": r1, "r2": r2, "c1": c1, "c2": c2}


def abs_bbox_from_rel(rel_bbox: dict, parent_bbox: dict) -> dict:
    rel = normalize_bbox(rel_bbox)
    parent = normalize_bbox(parent_bbox)
    return {
        "r1": parent["r1"] + rel["r1"] - 1,
        "r2": parent["r1"] + rel["r2"] - 1,
        "c1": parent["c1"] + rel["c1"] - 1,
        "c2": parent["c1"] + rel["c2"] - 1,
    }


def block_preview(df: pd.DataFrame, max_rows: int = 10, max_cols: int = 10, max_len: int = 40) -> str:
    if df is None or getattr(df, "empty", False):
        return "<empty>"
    clipped = df.iloc[:max_rows, :max_cols].fillna("").copy()
    clipped.columns = [str(x) for x in clipped.columns]

    def _fmt(v):
        s = str(v or "").replace("\n", " ").strip()
        return s[: max_len - 3] + "..." if len(s) > max_len else s

    lines = [",".join(_fmt(x) for x in clipped.columns)]
    for _, row in clipped.iterrows():
        lines.append(",".join(_fmt(x) for x in row.tolist()))
    return "\n".join(lines)

def make_json_safe(obj):
    if isinstance(obj, pd.DataFrame):
        return {
            "_type": "DataFrame",
            "shape": list(obj.shape),
            "preview": block_preview(obj),
        }
    if isinstance(obj, dict):
        return {k: make_json_safe(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [make_json_safe(v) for v in obj]
    return obj

def heuristic_type(block: dict) -> str:
    f = block.get("features", {}) or {}
    tg = str(block.get("title_guess", "")).strip()
    if f.get("has_numeric_body") and (f.get("title_like_top_row") or (tg and int(f.get("header_like_rows", 0) or 0) >= 1)):
        return "title_and_table"
    if f.get("has_numeric_body"):
        return "table_body"
    if f.get("title_like_top_row") or tg:
        return "table_title"
    if int(f.get("n_rows", 0) or 0) >= 4 and int(f.get("n_cols", 0) or 0) >= 4:
        return "multi_table"
    return "other"


def parse_stage_payload(row: dict | None, request_id: str, required_keys: list[str]) -> dict:
    if not row or not row.get("success"):
        raise ValueError(f"missing or failed batch row: {request_id}")

    payload = try_read_json(str(row.get("response_text", "")).strip())

    if isinstance(payload, list):
        # 1) 리스트 안에 request_id가 있는 dict wrapper가 있으면 그걸 우선 사용
        for item in payload:
            if isinstance(item, dict) and str(item.get("request_id", "")).strip() == request_id:
                payload = item
                break
        else:
            # 2) classify처럼 element list만 바로 온 경우 자동 wrapper
            if required_keys == ["element_classification"]:
                payload = {
                    "request_id": request_id,
                    "element_classification": payload,
                    "reason": "auto-wrapped from top-level list response",
                    "confidence": "low",
                }
            else:
                raise ValueError(f"top-level list payload is not supported for this stage: {request_id}")

    if not isinstance(payload, dict):
        raise ValueError(f"payload must be dict: {type(payload).__name__}")

    if str(payload.get("request_id", "")).strip() != request_id:
        raise ValueError(f"request_id mismatch: {request_id}")

    for key in required_keys:
        if key not in payload:
            raise ValueError(f"missing key: {key}")

    return payload


def call_stage_sync_retry(client, model_name: str, stage_name: str, rec: dict, prompt_builder, shared_contents=None) -> dict:
    prompt = prompt_builder(rec)
    call_result = generate_content_with_guard(
        client=client,
        model_name=model_name,
        contents=list(shared_contents or []),
        prompt_text=prompt,
        task_name=f"{stage_name}_retry",
        response_mime_type="application/json",
        max_retries=1,
    )
    return build_sync_usage_row(call_result)


def run_batch_stage(folder: Path, client, model_name: str, stage_name: str, records: list[dict], prompt_builder, request_id_getter, shared_contents=None, gcs_bucket: str = DEFAULT_GCS_BATCH_BUCKET) -> dict[str, dict]:
    if not records:
        return {}
    request_file = create_batch_request_file(folder, f"{stage_name}_{folder.name}")
    for rec in records:
        request_id = request_id_getter(rec)
        prompt = prompt_builder(rec)
        metadata = build_batch_request_metadata(
            task_name=stage_name,
            model_name=model_name,
            custom_id=request_id,
            stage_name=stage_name,
            item_id=rec.get("item_key") or request_id,
            paper_folder=str(folder),
            extra_metadata={"request_id": request_id, "excel_file": rec.get("excel_file", ""), "excel_sheet": rec.get("excel_sheet", "")},
        )
        request_body = build_generate_content_batch_request(model_name=model_name, contents=list(shared_contents or []), prompt_text=prompt, response_mime_type="application/json")
        append_batch_request(request_file=request_file, custom_id=request_id, request_body=request_body, metadata=metadata)

    local_job_id = create_batch_job_record(
        paper_folder=folder,
        task_name=stage_name,
        model_name=model_name,
        request_file=request_file,
        metadata={"request_count": count_requests_in_jsonl(request_file), "gcs_input_uri": f"{gcs_bucket}/batch/{request_file.name}", "gcs_output_uri_prefix": f"{gcs_bucket}/batch_output/{request_file.stem}"},
    )
    batch_job = submit_batch_job(client=client, paper_folder=folder, local_job_id=local_job_id, display_name=f"{stage_name}-{folder.name}")
    print(f"      * submitted {stage_name}: {batch_job.name}")
    finished_job = poll_batch_job(client=client, paper_folder=folder, local_job_id=local_job_id, poll_interval_seconds=30)
    state_name = getattr(getattr(finished_job, "state", None), "name", None) or str(getattr(finished_job, "state", "UNKNOWN"))
    if state_name != "JOB_STATE_SUCCEEDED":
        raise RuntimeError(f"{stage_name} batch failed: {state_name}")
    return load_batch_results_as_map(download_batch_results(client=client, paper_folder=folder, local_job_id=local_job_id))


def resolve_stage_results(client, model_name: str, stage_name: str, records: list[dict], results_map: dict[str, dict], prompt_builder, request_id_getter, required_keys: list[str], validator, shared_contents=None) -> dict[str, dict]:
    resolved = {}
    for rec in records:
        request_id = request_id_getter(rec)
        row = results_map.get(request_id)
        try:
            payload = validator(parse_stage_payload(row, request_id, required_keys), rec)
            resolved[request_id] = {"row": row, "payload": payload}
        except Exception:
            retry_row = call_stage_sync_retry(client, model_name, stage_name, rec, prompt_builder, shared_contents=shared_contents)
            payload = validator(parse_stage_payload(retry_row, request_id, required_keys), rec)
            resolved[request_id] = {"row": retry_row, "payload": payload}
    return resolved


def classification_rows(element_blocks: list[dict]) -> list[dict]:
    predicted_map = {x["element_id"]: x["predicted_type"] for x in summarize_element_types(element_blocks)}
    rows = []
    for blk in element_blocks:
        eid = str(blk.get("element_id", "")).strip()
        rows.append(
            {
                "element_id": eid,
                "predicted_type": predicted_map.get(eid) or heuristic_type(blk),
                "title_guess": str(blk.get("title_guess", "")).strip(),
                "bbox": blk.get("bbox", {}),
                "reading_order_index": blk.get("reading_order_index"),
                "gap_rows_from_prev": blk.get("gap_rows_from_prev"),
                "gap_cols_from_prev": blk.get("gap_cols_from_prev"),
                "features": {k: blk.get("features", {}).get(k) for k in ["n_rows", "n_cols", "nonempty_ratio", "numeric_ratio", "header_like_rows", "title_like_top_row", "has_numeric_body"]},
                "figure_table_candidates": infer_candidates(" ".join([str(blk.get("title_guess", "")), block_preview(blk.get("df"))[:300]])),
                "csv_preview": block_preview(blk.get("df")),
            }
        )
    return rows


def validate_route_payload(payload: dict, rec: dict) -> dict:
    route = str(payload.get("route", "")).strip()
    if route not in {"single_sheet_table", "split_blocks"}:
        route = "split_blocks"
    return {"request_id": payload["request_id"], "route": route, "reason": str(payload.get("reason", "")).strip(), "matched_item_ids": normalize_list(payload.get("matched_item_ids")), "confidence": str(payload.get("confidence", "medium")).strip() or "medium"}


def validate_classification_payload(payload: dict, rec: dict) -> dict:
    element_map = {str(x.get("element_id", "")).strip(): x for x in rec["element_blocks"]}
    normalized = []
    seen = set()
    for item in payload.get("element_classification", []):
        if not isinstance(item, dict):
            continue
        eid = str(item.get("element_id", "")).strip()
        blk = element_map.get(eid)
        if not blk:
            continue
        item_type = str(item.get("type", "")).strip().lower()
        if item_type not in {"table_body", "table_title", "title_and_table", "multi_table", "other"}:
            item_type = heuristic_type(blk)
        guessed = normalize_list(item.get("guessed_item_ids"))
        matched = normalize_list(item.get("matched_item_ids"))
        candidates = normalize_list(item.get("figure_table_candidates")) or infer_candidates(" ".join([str(blk.get("title_guess", "")), " ".join(guessed), " ".join(matched), str(item.get("reason", ""))]))
        normalized.append({"element_id": eid, "type": item_type, "matched_item_ids": matched, "guessed_item_ids": guessed, "figure_table_candidates": candidates, "reason": str(item.get("reason", "")).strip(), "confidence": str(item.get("confidence", "medium")).strip() or "medium"})
        seen.add(eid)
    for eid, blk in element_map.items():
        if eid in seen:
            continue
        normalized.append({"element_id": eid, "type": heuristic_type(blk), "matched_item_ids": [], "guessed_item_ids": [], "figure_table_candidates": infer_candidates(str(blk.get("title_guess", ""))), "reason": "heuristic fallback", "confidence": "low"})
    return {"request_id": payload["request_id"], "element_classification": normalized, "reason": str(payload.get("reason", "")).strip(), "confidence": str(payload.get("confidence", "medium")).strip() or "medium"}


def sanitize_code(code: str) -> str:
    code = str(code or "").strip()
    code = re.sub(r"^```python\s*", "", code, flags=re.I)
    code = re.sub(r"^```\s*", "", code)
    code = re.sub(r"\s*```$", "", code)
    return code.strip()

def sanitize_executable_split_code(code: str) -> str:
    code = sanitize_code(code)
    cleaned_lines = []
    for line in code.splitlines():
        stripped = line.strip()
        if stripped.startswith("import ") or stripped.startswith("from "):
            continue
        cleaned_lines.append(line)
    return "\n".join(cleaned_lines).strip()

ALLOWED_IMPORTS = {"re", "math", "json", "numpy", "pandas"}

def restricted_import(name, globals=None, locals=None, fromlist=(), level=0):
    root_name = str(name).split(".")[0]
    if root_name not in ALLOWED_IMPORTS:
        raise ImportError(f"Import not allowed: {name}")
    return __import__(name, globals, locals, fromlist, level)

def validate_split_code_payload(payload: dict, rec: dict) -> dict:
    code = sanitize_code(payload.get("code", ""))
    if not code:
        raise ValueError("empty split code")
    return {"request_id": payload["request_id"], "code": code, "reason": str(payload.get("reason", "")).strip(), "confidence": str(payload.get("confidence", "medium")).strip() or "medium"}


def validate_split_validation_payload(payload: dict, rec: dict) -> dict:
    split_map = {x["sub_element_id"]: x for x in rec["split_results"]}
    validated = []
    seen = set()
    for item in payload.get("validated_splits", []):
        if not isinstance(item, dict):
            continue
        sub_id = str(item.get("sub_element_id", "")).strip()
        if sub_id not in split_map:
            continue
        item_type = str(item.get("type", "")).strip().lower()
        if item_type not in {"table_body", "table_title", "title_and_table", "other"}:
            item_type = "other"
        guessed = normalize_list(item.get("guessed_item_ids")) or split_map[sub_id].get("guessed_item_ids", [])
        matched = normalize_list(item.get("matched_item_ids")) or split_map[sub_id].get("matched_item_ids", [])
        candidates = normalize_list(item.get("figure_table_candidates")) or split_map[sub_id].get("figure_table_candidates", [])
        validated.append({"sub_element_id": sub_id, "type": item_type, "matched_item_ids": matched, "guessed_item_ids": guessed, "figure_table_candidates": candidates, "reason": str(item.get("reason", "")).strip(), "confidence": str(item.get("confidence", "medium")).strip() or "medium"})
        seen.add(sub_id)
    for sub_id, split in split_map.items():
        if sub_id in seen:
            continue
        validated.append({"sub_element_id": sub_id, "type": "other", "matched_item_ids": split.get("matched_item_ids", []), "guessed_item_ids": split.get("guessed_item_ids", []), "figure_table_candidates": split.get("figure_table_candidates", []), "reason": "validation omitted this split", "confidence": "low"})
    return {"request_id": payload["request_id"], "split_quality": str(payload.get("split_quality", "partial")).strip() or "partial", "validated_splits": validated, "reason": str(payload.get("reason", "")).strip(), "confidence": str(payload.get("confidence", "medium")).strip() or "medium"}


def validate_grouping_payload(payload: dict, rec: dict) -> dict:
    valid_ids = {x["element_id"] for x in rec["effective_elements"]}
    groups, used = [], set()
    for group in payload.get("resolved_groups", []):
        if not isinstance(group, list):
            continue
        clean = []
        for eid in group:
            eid = str(eid).strip()
            if eid and eid in valid_ids and eid not in used and eid not in clean:
                clean.append(eid)
        if clean:
            groups.append(clean)
            used.update(clean)
    for eid in sorted(valid_ids):
        if eid not in used:
            groups.append([eid])
    return {"request_id": payload["request_id"], "resolved_groups": groups, "reason": str(payload.get("reason", "")).strip(), "confidence": str(payload.get("confidence", "medium")).strip() or "medium"}


def build_route_prompt(rec: dict, inventory_items: list[str], client, model_name: str) -> str:
    request_id = make_request_id("route_sheet", rec["excel_file"], rec["excel_sheet"])
    current_csv = prepare_stage_text_with_token_limit(
        client=client,
        model_name=model_name,
        text=prepare_csv_for_prompt(rec["sheet_csv"], hard_char_limit=120000),
        stage_name=f'route::{rec["excel_file"]}::{rec["excel_sheet"]}',
        allow_numeric_strip=True,
    )
    inv = "\n".join(f"- {x}" for x in inventory_items[:300]) if inventory_items else "- none"

    return f"""
You are routing one Excel sheet.

[REQUEST_ID]
{request_id}

[SHEET INFO]
excel_file: {rec["excel_file"]}
excel_sheet: {rec["excel_sheet"]}
normalized_sheet_item_hint: {rec.get("normalized_sheet_item_hint", "")}

[INVENTORY]
{inv}

[IDENTIFIER NOTE]
{EXTENDED_DATA_PROMPT_NOTE}

[SHEET CSV]
{current_csv}

[OUTPUT RULES]
- Return exactly one JSON object.
- Do not return a top-level array.
- The top-level JSON must include request_id.
- request_id must be exactly "{request_id}".

[OUTPUT JSON TEMPLATE]
{{
  "request_id": "{request_id}",
  "route": "single_sheet_table or split_blocks",
  "reason": "...",
  "matched_item_ids": ["..."],
  "confidence": "high"
}}
""".strip()

def build_classify_prompt(rec: dict, inventory_items: list[str], client, model_name: str) -> str:
    request_id = make_request_id("classify_elements", rec["excel_file"], rec["excel_sheet"])
    current_csv = prepare_stage_text_with_token_limit(
        client=client,
        model_name=model_name,
        text=prepare_csv_for_prompt(rec["sheet_csv"], hard_char_limit=120000),
        stage_name=f'classify_csv::{rec["excel_file"]}::{rec["excel_sheet"]}',
        allow_numeric_strip=True,
    )
    payload_text = prepare_stage_text_with_token_limit(
        client=client,
        model_name=model_name,
        text=json.dumps(classification_rows(rec["element_blocks"]), ensure_ascii=False, indent=2),
        stage_name=f'classify_payload::{rec["excel_file"]}::{rec["excel_sheet"]}',
        allow_numeric_strip=False,
    )
    inv = "\n".join(f"- {x}" for x in inventory_items[:300]) if inventory_items else "- none"

    return f"""
You are classifying Excel elements.

[REQUEST_ID]
{request_id}

[SHEET INFO]
excel_file: {rec["excel_file"]}
excel_sheet: {rec["excel_sheet"]}
normalized_sheet_item_hint: {rec.get("normalized_sheet_item_hint", "")}

[TASK]
Classify each element into exactly one of:
- table_body
- table_title
- title_and_table
- multi_table
- other

For each element also output:
- matched_item_ids
- guessed_item_ids
- figure_table_candidates
- reason
- confidence

[INVENTORY]
{inv}

[IDENTIFIER NOTE]
{EXTENDED_DATA_PROMPT_NOTE}

[SHEET CSV]
{current_csv}

[ELEMENTS]
{payload_text}

[OUTPUT RULES]
- Return exactly one JSON object.
- Do not return a top-level array.
- Do not return only the element_classification list.
- The top-level JSON must contain:
  - request_id
  - element_classification
  - reason
  - confidence
- request_id must be exactly "{request_id}".

[OUTPUT JSON TEMPLATE]
{{
  "request_id": "{request_id}",
  "element_classification": [
    {{
      "element_id": "...",
      "type": "multi_table",
      "matched_item_ids": [],
      "guessed_item_ids": [],
      "figure_table_candidates": [],
      "reason": "...",
      "confidence": "high"
    }}
  ],
  "reason": "...",
  "confidence": "high"
}}
""".strip()

def build_split_prompt(rec: dict, inventory_items: list[str], client, model_name: str) -> str:
    csv_text = prepare_stage_text_with_token_limit(
        client=client,
        model_name=model_name,
        text=prepare_csv_for_prompt(rec["csv_text"], hard_char_limit=120000),
        stage_name=f'split_code::{rec["excel_file"]}::{rec["excel_sheet"]}::{rec["element_id"]}',
        allow_numeric_strip=True,
    )
    inv = "\n".join(f"- {x}" for x in inventory_items[:200]) if inventory_items else "- none"

    return f"""
You are splitting one multi_table element.

[REQUEST_ID]
{rec["request_id"]}

[ELEMENT INFO]
excel_file: {rec["excel_file"]}
excel_sheet: {rec["excel_sheet"]}
normalized_sheet_item_hint: {rec.get("normalized_sheet_item_hint", "")}
element_id: {rec["element_id"]}
parent_bbox: {json.dumps(rec["bbox"], ensure_ascii=False)}

[INVENTORY]
{inv}

[IDENTIFIER NOTE]
{EXTENDED_DATA_PROMPT_NOTE}

[CSV]
{csv_text}

[CODE RULES]
- Return exactly one JSON object.
- Do not return a top-level array.
- The top-level JSON must include request_id.
- request_id must be exactly "{rec["request_id"]}".
- Output field name must be "code".
- The code must be executable Python only.
- Do not use markdown fences.
- Do not write any import statements.
- pandas is already available as pd.
- input dataframe name is raw_df.
- output variable name must be split_results.
- split_results must be a list[dict].
- each dict should include:
  - sub_id
  - title_guess
  - either range or bbox or fragments
  - type
  - optional matched_item_ids
  - optional guessed_item_ids
  - optional figure_table_candidates
- fragments is preferred when one logical sub-table is made of detached title/body pieces,
  multiple meaningful pieces, or a non-rectangular structure.
- fragments must be a list of boxes like:
  {{"r1": 1, "r2": 2, "c1": 1, "c2": 6}}
- range/bbox/fragments are relative to raw_df using 1-based inclusive indices.
- Prefer precise fragments over oversized bounding boxes.
- Do not use os, sys, subprocess, pathlib, or file operations.

[EXAMPLE SPLIT RESULT ITEM]
{{
  "sub_id": "sub_001",
  "title_guess": "Table 1",
  "type": "title_and_table",
  "fragments": [
    {{"r1": 1, "r2": 2, "c1": 1, "c2": 6}},
    {{"r1": 4, "r2": 12, "c1": 1, "c2": 10}}
  ],
  "matched_item_ids": [],
  "guessed_item_ids": [],
  "figure_table_candidates": []
}}

[OUTPUT JSON TEMPLATE]
{{
  "request_id": "{rec["request_id"]}",
  "code": "...",
  "reason": "...",
  "confidence": "high"
}}
""".strip()

def build_validation_prompt(rec: dict, inventory_items: list[str], client, model_name: str) -> str:
    parent_csv = prepare_stage_text_with_token_limit(
        client=client,
        model_name=model_name,
        text=prepare_csv_for_prompt(rec["parent_csv_text"], hard_char_limit=120000),
        stage_name=f'validate_parent::{rec["excel_file"]}::{rec["excel_sheet"]}::{rec["parent_element_id"]}',
        allow_numeric_strip=True,
    )
    inv = "\n".join(f"- {x}" for x in inventory_items[:200]) if inventory_items else "- none"
    previews = [
        json.dumps(
            {
                "sub_element_id": x["sub_element_id"],
                "title_guess": x.get("title_guess", ""),
                "bbox": x["bbox"],
                "candidate_item_ids": x.get("candidate_item_ids", []),
                "preview": x["csv_preview"],
            },
            ensure_ascii=False,
        )
        for x in rec["split_results"]
    ]
    split_results_text = "\n".join(previews)

    return f"""
You are validating multi_table split results.

[REQUEST_ID]
{rec["request_id"]}

[PARENT INFO]
excel_file: {rec["excel_file"]}
excel_sheet: {rec["excel_sheet"]}
normalized_sheet_item_hint: {rec.get("normalized_sheet_item_hint", "")}
parent_element_id: {rec["parent_element_id"]}

[INVENTORY]
{inv}

[IDENTIFIER NOTE]
{EXTENDED_DATA_PROMPT_NOTE}

[ORIGINAL CSV]
{parent_csv}

[SPLIT RESULTS]
{split_results_text}

[OUTPUT RULES]
- Return exactly one JSON object.
- Do not return a top-level array.
- The top-level JSON must include request_id.
- request_id must be exactly "{rec["request_id"]}".
- validated_splits must be a list.
- Each validated split must include sub_element_id and type.

[OUTPUT JSON TEMPLATE]
{{
  "request_id": "{rec["request_id"]}",
  "split_quality": "good or partial or bad",
  "validated_splits": [
    {{
      "sub_element_id": "...",
      "type": "table_body",
      "matched_item_ids": [],
      "guessed_item_ids": [],
      "figure_table_candidates": [],
      "reason": "...",
      "confidence": "high"
    }}
  ],
  "reason": "...",
  "confidence": "high"
}}
""".strip()

def build_grouping_prompt(rec: dict, inventory_items: list[str]) -> str:
    inv = "\n".join(f"- {x}" for x in inventory_items[:300]) if inventory_items else "- none"
    cards = [
        json.dumps(
            {
                "element_id": x["element_id"],
                "source_kind": x.get("source_kind"),
                "parent_element_id": x.get("parent_element_id"),
                "type": x.get("type"),
                "title_guess": x.get("title_guess"),
                "bbox": x.get("bbox"),
                "matched_item_ids": x.get("matched_item_ids"),
                "guessed_item_ids": x.get("guessed_item_ids"),
                "figure_table_candidates": x.get("figure_table_candidates"),
                "reading_order_index": x.get("reading_order_index"),
                "csv_preview": x.get("csv_preview"),
            },
            ensure_ascii=False,
        )
        for x in rec["effective_elements"]
    ]
    cards_text = "\n".join(cards)

    return f"""
You are grouping validated elements into final blocks.

[REQUEST_ID]
{rec["request_id"]}

[SHEET INFO]
excel_file: {rec["excel_file"]}
excel_sheet: {rec["excel_sheet"]}
normalized_sheet_item_hint: {rec.get("normalized_sheet_item_hint", "")}

[INVENTORY]
{inv}

[IDENTIFIER NOTE]
{EXTENDED_DATA_PROMPT_NOTE}

[EFFECTIVE ELEMENTS]
{cards_text}

[GROUPING RULES]
- Every element_id must appear exactly once.
- Return exactly one JSON object.
- Do not return a top-level array.
- The top-level JSON must include request_id.
- request_id must be exactly "{rec["request_id"]}".

[OUTPUT JSON TEMPLATE]
{{
  "request_id": "{rec["request_id"]}",
  "resolved_groups": [
    ["a", "b"],
    ["c"]
  ],
  "reason": "...",
  "confidence": "high"
}}
""".strip()

def build_sheet_record(excel_file: str, excel_sheet: str, source_path: Path, df: pd.DataFrame, element_blocks: list[dict]) -> dict:
    return {
        "excel_file": excel_file,
        "excel_sheet": excel_sheet,
        "normalized_sheet_item_hint": normalize_ft_item_id(excel_sheet),
        "source_path": source_path,
        "df": df,
        "sheet_csv": df.to_csv(index=False),
        "element_blocks": element_blocks,
    }


def build_split_task(sheet_rec: dict, blk: dict) -> dict:
    return {"request_id": make_request_id("multi_table_split_code", sheet_rec["excel_file"], sheet_rec["excel_sheet"], blk["element_id"]), "item_key": f'{sheet_rec["excel_file"]}::{sheet_rec["excel_sheet"]}::{blk["element_id"]}', "excel_file": sheet_rec["excel_file"], "excel_sheet": sheet_rec["excel_sheet"], "normalized_sheet_item_hint": sheet_rec.get("normalized_sheet_item_hint", ""), "source_path": sheet_rec["source_path"], "element_id": blk["element_id"], "bbox": blk["bbox"], "title_guess": blk.get("title_guess", ""), "df": blk["df"], "csv_text": blk["csv_text"]}


def normalize_fragment_list(fragments, fallback: dict | None = None) -> list[dict]:
    out = []
    for fragment in fragments or []:
        if not isinstance(fragment, dict):
            continue
        out.append(normalize_bbox(fragment, fallback=fallback))
    return out


def union_optional_bboxes(boxes: list[dict], fallback: dict | None = None) -> dict:
    if not boxes:
        return normalize_bbox(fallback or {})
    return union_bbox(boxes)


def compose_df_from_fragments(raw_df: pd.DataFrame, fragments: list[dict]) -> pd.DataFrame:
    if not fragments:
        return pd.DataFrame()

    union = union_bbox(fragments)
    n_rows = union["r2"] - union["r1"] + 1
    n_cols = union["c2"] - union["c1"] + 1
    canvas = pd.DataFrame("", index=range(n_rows), columns=range(n_cols))

    for frag in fragments:
        rel = normalize_bbox(frag)
        frag_df = raw_df.iloc[rel["r1"] - 1: rel["r2"], rel["c1"] - 1: rel["c2"]].copy().fillna("")
        r0 = rel["r1"] - union["r1"]
        c0 = rel["c1"] - union["c1"]
        for i in range(frag_df.shape[0]):
            for j in range(frag_df.shape[1]):
                canvas.iat[r0 + i, c0 + j] = frag_df.iat[i, j]

    return canvas


def relative_fragments_to_absolute(fragments: list[dict], parent_bbox: dict) -> list[dict]:
    return [abs_bbox_from_rel(fragment, parent_bbox) for fragment in fragments]


def execute_split_code(task: dict, payload: dict) -> dict:
    raw_df = task["df"].copy()

    safe_builtins = {
        "len": len,
        "range": range,
        "min": min,
        "max": max,
        "sum": sum,
        "str": str,
        "int": int,
        "float": float,
        "list": list,
        "dict": dict,
        "enumerate": enumerate,
        "sorted": sorted,
        "set": set,
        "any": any,
        "all": all,
        "zip": zip,
        "hasattr": hasattr,
        "getattr": getattr,
        "isinstance": isinstance,
        "__import__": restricted_import,
    }

    code_to_run = sanitize_executable_split_code(payload["code"])

    local_vars = {"raw_df": raw_df}
    global_vars = {
        "pd": pd,
        "__builtins__": safe_builtins,
    }

    exec(code_to_run, global_vars, local_vars)

    split_results = local_vars.get("split_results")
    if not isinstance(split_results, list):
        raise ValueError("split_results must be list")

    out = []
    parent_bbox = normalize_bbox(task["bbox"])
    full_rel_bbox = {"r1": 1, "r2": max(1, raw_df.shape[0]), "c1": 1, "c2": max(1, raw_df.shape[1])}
    for idx, item in enumerate(split_results, 1):
        if not isinstance(item, dict):
            continue
        raw_sub_id = str(item.get("sub_id", "")).strip() or f"sub_{idx:03d}"
        sub_id = f'{task["element_id"]}__{raw_sub_id}'
        rel_fragments = normalize_fragment_list(item.get("fragments"), fallback=full_rel_bbox)
        if rel_fragments:
            rel_bbox = union_bbox(rel_fragments)
            abs_fragments = relative_fragments_to_absolute(rel_fragments, parent_bbox)
            abs_bbox = union_bbox(abs_fragments)
            df_part = compose_df_from_fragments(raw_df, rel_fragments)
        else:
            rel_bbox = normalize_bbox(item.get("range") or item.get("bbox") or {}, fallback=full_rel_bbox)
            abs_bbox = abs_bbox_from_rel(rel_bbox, parent_bbox)
            abs_fragments = [abs_bbox]
            rel_fragments = [rel_bbox]
            df_part = raw_df.iloc[
                rel_bbox["r1"] - 1: rel_bbox["r2"],
                rel_bbox["c1"] - 1: rel_bbox["c2"]
            ].copy().fillna("")

        matched = normalize_list(item.get("matched_item_ids"))
        guessed = normalize_list(item.get("guessed_item_ids"))
        candidates = normalize_list(item.get("figure_table_candidates"))
        #candidates = normalize_list(item.get("figure_table_candidates")) or infer_candidates(
        #    " ".join([str(item.get("title_guess", "")).strip(), " ".join(matched), " ".join(guessed)])
        #)

        out.append(
            {
                "sub_element_id": sub_id,
                "parent_element_id": task["element_id"],
                "title_guess": str(item.get("title_guess", "")).strip(),
                "bbox": abs_bbox,
                "relative_bbox": rel_bbox,
                "relative_fragments": rel_fragments,
                "fragments": abs_fragments,
                "df": df_part,
                "csv_text": df_part.to_csv(index=False),
                "csv_preview": block_preview(df_part),
                "type": str(item.get("type", "")).strip().lower() or "other",
                "matched_item_ids": matched,
                "guessed_item_ids": guessed,
                "figure_table_candidates": candidates,
                "candidate_item_ids": list(dict.fromkeys(matched + guessed)),
            }
        )

    return {
        "request_id": task["request_id"],
        "parent_element_id": task["element_id"],
        "code": code_to_run,
        "reason": payload.get("reason", ""),
        "confidence": payload.get("confidence", "medium"),
        "split_results": out,
    }

def make_effective_original(blk: dict, cls: dict) -> dict:
    return {"element_id": blk["element_id"], "parent_element_id": blk["element_id"], "source_kind": "original", "type": cls["type"], "title_guess": blk.get("title_guess", ""), "bbox": normalize_bbox(blk["bbox"]), "df": blk["df"].copy(), "csv_preview": block_preview(blk["df"]), "matched_item_ids": cls.get("matched_item_ids", []), "guessed_item_ids": cls.get("guessed_item_ids", []), "figure_table_candidates": cls.get("figure_table_candidates", []), "reading_order_index": blk.get("reading_order_index")}


def union_bbox(boxes: list[dict]) -> dict:
    n = [normalize_bbox(x) for x in boxes]
    return {"r1": min(x["r1"] for x in n), "r2": max(x["r2"] for x in n), "c1": min(x["c1"] for x in n), "c2": max(x["c2"] for x in n)}


def compose_group_df_original_layout(members: list[dict]) -> pd.DataFrame:
    if not members:
        return pd.DataFrame()

    norm_members = []
    for m in members:
        bbox = normalize_bbox(m["bbox"])
        df = m.get("df")
        if df is None:
            df = pd.DataFrame()
        norm_members.append({"bbox": bbox, "df": df.copy().fillna("")})

    union = union_bbox([x["bbox"] for x in norm_members])
    n_rows = union["r2"] - union["r1"] + 1
    n_cols = union["c2"] - union["c1"] + 1

    canvas = pd.DataFrame("", index=range(n_rows), columns=range(n_cols))

    for item in norm_members:
        bbox = item["bbox"]
        df = item["df"]
        r0 = bbox["r1"] - union["r1"]
        c0 = bbox["c1"] - union["c1"]

        rows = min(df.shape[0], bbox["r2"] - bbox["r1"] + 1)
        cols = min(df.shape[1], bbox["c2"] - bbox["c1"] + 1)

        for i in range(rows):
            for j in range(cols):
                canvas.iat[r0 + i, c0 + j] = df.iat[i, j]

    return canvas


def bbox_span(bbox: dict, axis: str) -> int:
    box = normalize_bbox(bbox)
    if axis == "vertical":
        return box["r2"] - box["r1"] + 1
    return box["c2"] - box["c1"] + 1


def interval_overlap(a1: int, a2: int, b1: int, b2: int) -> int:
    return max(0, min(a2, b2) - max(a1, b1) + 1)


def interval_gap(a1: int, a2: int, b1: int, b2: int) -> int:
    if a2 < b1:
        return b1 - a2 - 1
    if b2 < a1:
        return a1 - b2 - 1
    return 0


def member_df(member: dict) -> pd.DataFrame:
    df = member.get("df")
    if df is None:
        return pd.DataFrame()
    return df.copy().fillna("")


def detect_member_relationship(left: dict, right: dict) -> dict:
    a = normalize_bbox(left["bbox"])
    b = normalize_bbox(right["bbox"])
    col_overlap = interval_overlap(a["c1"], a["c2"], b["c1"], b["c2"])
    row_overlap = interval_overlap(a["r1"], a["r2"], b["r1"], b["r2"])
    vertical_gap = interval_gap(a["r1"], a["r2"], b["r1"], b["r2"])
    horizontal_gap = interval_gap(a["c1"], a["c2"], b["c1"], b["c2"])

    vertical_score = 0.0
    horizontal_score = 0.0

    if col_overlap > 0:
        vertical_score += 2.0 + min(1.5, col_overlap / max(1, min(bbox_span(a, "horizontal"), bbox_span(b, "horizontal"))))
    if row_overlap > 0:
        horizontal_score += 2.0 + min(1.5, row_overlap / max(1, min(bbox_span(a, "vertical"), bbox_span(b, "vertical"))))

    vertical_score += max(0.0, 1.5 - min(vertical_gap, 6) * 0.25)
    horizontal_score += max(0.0, 1.5 - min(horizontal_gap, 6) * 0.25)

    left_type = str(left.get("type", "")).strip().lower()
    right_type = str(right.get("type", "")).strip().lower()
    type_pair = {left_type, right_type}
    if "table_title" in type_pair and ("table_body" in type_pair or "title_and_table" in type_pair):
        vertical_score += 3.0
        horizontal_score -= 0.5

    if vertical_score >= horizontal_score + 1.0:
        orientation = "vertical"
        confidence = "high" if vertical_score >= horizontal_score + 2.0 else "medium"
    elif horizontal_score >= vertical_score + 1.0:
        orientation = "horizontal"
        confidence = "high" if horizontal_score >= vertical_score + 2.0 else "medium"
    else:
        orientation = "ambiguous"
        confidence = "low"

    return {
        "orientation": orientation,
        "confidence": confidence,
        "vertical_gap": vertical_gap,
        "horizontal_gap": horizontal_gap,
        "row_overlap": row_overlap,
        "col_overlap": col_overlap,
        "vertical_score": round(vertical_score, 3),
        "horizontal_score": round(horizontal_score, 3),
    }


def detect_group_primary_axis(members: list[dict]) -> dict:
    if len(members) < 2:
        return {"mode": "original-layout", "axis": None, "confidence": "low", "relationships": []}

    ordered = sorted(members, key=lambda x: (normalize_bbox(x["bbox"])["r1"], normalize_bbox(x["bbox"])["c1"], x["element_id"]))
    relationships = []
    vertical_votes = 0
    horizontal_votes = 0
    strong_vertical = 0
    strong_horizontal = 0

    for idx in range(len(ordered) - 1):
        rel = detect_member_relationship(ordered[idx], ordered[idx + 1])
        rel["pair"] = [ordered[idx]["element_id"], ordered[idx + 1]["element_id"]]
        relationships.append(rel)
        if rel["orientation"] == "vertical":
            vertical_votes += 1
            if rel["confidence"] == "high":
                strong_vertical += 1
        elif rel["orientation"] == "horizontal":
            horizontal_votes += 1
            if rel["confidence"] == "high":
                strong_horizontal += 1

    if strong_vertical > strong_horizontal or (vertical_votes > horizontal_votes and strong_vertical >= 1):
        return {"mode": "axis-aware", "axis": "vertical", "confidence": "high", "relationships": relationships}
    if strong_horizontal > strong_vertical or (horizontal_votes > vertical_votes and strong_horizontal >= 1):
        return {"mode": "axis-aware", "axis": "horizontal", "confidence": "high", "relationships": relationships}
    if vertical_votes > horizontal_votes and vertical_votes >= max(2, len(relationships) - 0):
        return {"mode": "axis-aware", "axis": "vertical", "confidence": "medium", "relationships": relationships}
    if horizontal_votes > vertical_votes and horizontal_votes >= max(2, len(relationships) - 0):
        return {"mode": "axis-aware", "axis": "horizontal", "confidence": "medium", "relationships": relationships}
    return {"mode": "original-layout", "axis": None, "confidence": "low", "relationships": relationships}


def compose_group_df_axis_aware(members: list[dict], axis: str) -> pd.DataFrame:
    if not members:
        return pd.DataFrame()

    if axis == "vertical":
        ordered = sorted(members, key=lambda x: (normalize_bbox(x["bbox"])["r1"], normalize_bbox(x["bbox"])["c1"], x["element_id"]))
        gap_size = 1
        total_rows = sum(max(1, member_df(m).shape[0]) for m in ordered) + gap_size * max(0, len(ordered) - 1)
        total_cols = max(max(1, member_df(m).shape[1]) for m in ordered)
        canvas = pd.DataFrame("", index=range(total_rows), columns=range(total_cols))
        r0 = 0
        for member in ordered:
            df = member_df(member)
            for i in range(df.shape[0]):
                for j in range(df.shape[1]):
                    canvas.iat[r0 + i, j] = df.iat[i, j]
            r0 += df.shape[0] + gap_size
        return canvas

    ordered = sorted(members, key=lambda x: (normalize_bbox(x["bbox"])["c1"], normalize_bbox(x["bbox"])["r1"], x["element_id"]))
    gap_size = 1
    total_rows = max(max(1, member_df(m).shape[0]) for m in ordered)
    total_cols = sum(max(1, member_df(m).shape[1]) for m in ordered) + gap_size * max(0, len(ordered) - 1)
    canvas = pd.DataFrame("", index=range(total_rows), columns=range(total_cols))
    c0 = 0
    for member in ordered:
        df = member_df(member)
        for i in range(df.shape[0]):
            for j in range(df.shape[1]):
                canvas.iat[i, c0 + j] = df.iat[i, j]
        c0 += df.shape[1] + gap_size
    return canvas


def compose_group_df_from_members(members: list[dict]) -> tuple[pd.DataFrame, dict]:
    decision = detect_group_primary_axis(members)
    if decision["mode"] == "axis-aware" and decision["axis"] in {"vertical", "horizontal"}:
        return compose_group_df_axis_aware(members, decision["axis"]), decision
    return compose_group_df_original_layout(members), decision

def extract_bbox_df(source_path: Path, sheet_name: str, bbox: dict, fallback_df: pd.DataFrame | None = None) -> pd.DataFrame:
    try:
        _, ws = load_sheet_df_and_ws(source_path, sheet_name)
        if ws is not None:
            return extract_block_df_from_ws(ws, bbox).fillna("")
    except Exception:
        pass
    if fallback_df is not None:
        b = normalize_bbox(bbox)
        return fallback_df.iloc[b["r1"] - 1: b["r2"], b["c1"] - 1: b["c2"]].copy().fillna("")
    return pd.DataFrame()


def materialize_final_blocks(sheet_rec: dict, grouping: dict, effective_elements: list[dict]) -> list[dict]:
    emap = {x["element_id"]: x for x in effective_elements}
    blocks = []
    prefix = f'{Path(sheet_rec["excel_file"]).stem}__{safe_path_name(sheet_rec["excel_sheet"])}'
    for idx, group in enumerate(grouping["resolved_groups"], 1):
        members = [emap[eid] for eid in group if eid in emap]
        if not members:
            continue
        bbox = union_bbox([x["bbox"] for x in members])
        df, composition = compose_group_df_from_members(members)
        types = [x["type"] for x in members]
        if "title_and_table" in types or ("table_body" in types and "table_title" in types):
            block_type = "title_and_table"
        elif "table_body" in types:
            block_type = "table_body"
        elif "table_title" in types:
            block_type = "table_title"
        else:
            block_type = "other"
        matched, guessed, candidates = [], [], []
        for x in members:
            for v in x.get("matched_item_ids", []):
                if v not in matched:
                    matched.append(v)
            for v in x.get("guessed_item_ids", []):
                if v not in guessed:
                    guessed.append(v)
            for v in x.get("figure_table_candidates", []):
                if v not in candidates:
                    candidates.append(v)
        blocks.append({"block_id": f"{prefix}__block_{idx:03d}", "group_id": f"{prefix}__group_{idx:03d}", "element_id": members[0]["element_id"], "title_guess": next((x.get("title_guess", "") for x in members if str(x.get("title_guess", "")).strip()), sheet_rec["excel_sheet"]), "bbox": bbox, "df": df, "block_type": block_type, "source_element_ids": [x["element_id"] for x in members], "source_kinds": [x.get("source_kind", "") for x in members], "matched_item_ids": matched, "guessed_item_ids": guessed, "figure_table_candidates": candidates, "composition_mode": composition["mode"], "composition_axis": composition.get("axis"), "composition_confidence": composition.get("confidence")})
    return blocks


def run_three_steps_batch(folder: Path, client, model_name: str, uploaded_pdfs: list[dict], inventory_items: list[str], sheet_records: list[dict], gcs_bucket: str = DEFAULT_GCS_BATCH_BUCKET) -> list[dict]:
    shared_pdf_parts = build_pdf_file_parts(uploaded_pdfs)
    route_id = lambda rec: make_request_id("route_sheet", rec["excel_file"], rec["excel_sheet"])
    route_prompt = lambda rec: build_route_prompt(rec, inventory_items, client, model_name)
    route_map = run_batch_stage(folder, client, model_name, "route_sheet", sheet_records, route_prompt, route_id, shared_contents=shared_pdf_parts, gcs_bucket=gcs_bucket)
    route_resolved = resolve_stage_results(client, model_name, "route_sheet", sheet_records, route_map, route_prompt, route_id, ["route"], validate_route_payload, shared_contents=shared_pdf_parts)

    results, split_candidate_sheets = [], []
    for rec in sheet_records:
        route = route_resolved[route_id(rec)]
        route_payload = {**route["payload"], "usage": usage_from_batch_row(route["row"], "route_sheet", model_name)}
        if route_payload["route"] == "single_sheet_table":
            results.append({"excel_file": rec["excel_file"], "excel_sheet": rec["excel_sheet"], "source_path": rec["source_path"], "df": rec["df"], "result": {"routing": route_payload, "classification": None, "multi_table_split": [], "multi_table_validation": [], "grouping": None, "effective_elements": [], "final_blocks": [], "usage_records": [route_payload["usage"]]}})
        else:
            split_candidate_sheets.append(rec)
    if not split_candidate_sheets:
        return results

    classify_id = lambda rec: make_request_id("classify_elements", rec["excel_file"], rec["excel_sheet"])
    classify_prompt = lambda rec: build_classify_prompt(rec, inventory_items, client, model_name)
    classify_map = run_batch_stage(folder, client, model_name, "classify_elements", split_candidate_sheets, classify_prompt, classify_id, shared_contents=shared_pdf_parts, gcs_bucket=gcs_bucket)
    classify_resolved = resolve_stage_results(client, model_name, "classify_elements", split_candidate_sheets, classify_map, classify_prompt, classify_id, ["element_classification"], validate_classification_payload, shared_contents=shared_pdf_parts)

    split_tasks, class_by_sheet = [], {}
    for rec in split_candidate_sheets:
        class_row = classify_resolved[classify_id(rec)]
        class_payload = class_row["payload"]
        print(f"\n[DEBUG][CLASSIFICATION] file={rec['excel_file']} sheet={rec['excel_sheet']}")
        for item in class_payload["element_classification"]:
            print(
                f"  - element_id={item['element_id']} "
                f"type={item['type']} "
                f"matched={item.get('matched_item_ids')} "
                f"guessed={item.get('guessed_item_ids')} "
                f"candidates={item.get('figure_table_candidates')}"
            )

        class_by_sheet[(rec["excel_file"], rec["excel_sheet"])] = {"payload": class_payload, "usage": usage_from_batch_row(class_row["row"], "classify_elements", model_name)}
        c_map = {x["element_id"]: x for x in class_payload["element_classification"]}
        for blk in rec["element_blocks"]:
            if c_map.get(blk["element_id"], {}).get("type") == "multi_table":
                split_tasks.append(build_split_task(rec, blk))

    split_exec_map, validation_map = {}, {}
    if split_tasks:
        split_id = lambda rec: rec["request_id"]
        split_prompt = lambda rec: build_split_prompt(rec, inventory_items, client, model_name)
        split_map = run_batch_stage(folder, client, model_name, "multi_table_split_code", split_tasks, split_prompt, split_id, shared_contents=shared_pdf_parts, gcs_bucket=gcs_bucket)
        split_resolved = resolve_stage_results(client, model_name, "multi_table_split_code", split_tasks, split_map, split_prompt, split_id, ["code"], validate_split_code_payload, shared_contents=shared_pdf_parts)
        for task in split_tasks:
            split_exec_map[task["element_id"]] = execute_split_code(task, split_resolved[task["request_id"]]["payload"])

        split_exec = split_exec_map[task["element_id"]]
        print(f"\n[DEBUG][SPLIT EXEC] parent_element={task['element_id']}")
        print("[DEBUG][GENERATED CODE]")
        print(split_exec["code"])

        for sub in split_exec["split_results"]:
            print(
                f"  - sub_element_id={sub['sub_element_id']} "
                f"bbox={sub['bbox']} "
                f"rel_bbox={sub.get('relative_bbox')} "
                f"title_guess={sub.get('title_guess')} "
                f"type={sub.get('type')} "
                f"candidates={sub.get('figure_table_candidates')}"
            )

        validation_tasks = [{"request_id": make_request_id("multi_table_validate", task["excel_file"], task["excel_sheet"], task["element_id"]), "item_key": task["item_key"], "excel_file": task["excel_file"], "excel_sheet": task["excel_sheet"], "normalized_sheet_item_hint": task.get("normalized_sheet_item_hint", ""), "parent_element_id": task["element_id"], "parent_csv_text": task["csv_text"], "split_results": split_exec_map[task["element_id"]]["split_results"]} for task in split_tasks]
        valid_id = lambda rec: rec["request_id"]
        valid_prompt = lambda rec: build_validation_prompt(rec, inventory_items, client, model_name)
        valid_map = run_batch_stage(folder, client, model_name, "multi_table_validate", validation_tasks, valid_prompt, valid_id, shared_contents=shared_pdf_parts, gcs_bucket=gcs_bucket)
        valid_resolved = resolve_stage_results(client, model_name, "multi_table_validate", validation_tasks, valid_map, valid_prompt, valid_id, ["validated_splits"], validate_split_validation_payload, shared_contents=shared_pdf_parts)
        for task in validation_tasks:
            payload = valid_resolved[task["request_id"]]["payload"]
            print(f"\n[DEBUG][VALIDATION] parent_element={task['parent_element_id']}")
            for item in payload["validated_splits"]:
                print(
                    f"  - sub_element_id={item['sub_element_id']} "
                    f"type={item['type']} "
                    f"matched={item.get('matched_item_ids')} "
                    f"guessed={item.get('guessed_item_ids')} "
                    f"candidates={item.get('figure_table_candidates')} "
                    f"reason={item.get('reason')}"
                )

            usage = usage_from_batch_row(valid_resolved[task["request_id"]]["row"], "multi_table_validate", model_name)
            split_map_local = {x["sub_element_id"]: x for x in task["split_results"]}
            validated_elems = []
            for item in payload["validated_splits"]:
                src = split_map_local.get(item["sub_element_id"])
                if not src:
                    continue
                merged = dict(src)
                merged.update({"element_id": src["sub_element_id"], "type": item["type"], "matched_item_ids": item["matched_item_ids"], "guessed_item_ids": item["guessed_item_ids"], "figure_table_candidates": item["figure_table_candidates"], "source_kind": "multi_table_split", "validation_reason": item["reason"], "validation_confidence": item["confidence"]})
                print(
                    f"    -> KEPT sub_element_id={merged['element_id']} "
                    f"type={merged['type']} "
                    f"bbox={merged['bbox']}"
                )
                validated_elems.append(merged)
            validation_map[task["parent_element_id"]] = {"payload": payload, "usage": usage, "validated_elements": validated_elems}

    grouping_tasks, effective_map_by_sheet = [], {}
    for rec in split_candidate_sheets:
        key = (rec["excel_file"], rec["excel_sheet"])
        c_map = {x["element_id"]: x for x in class_by_sheet[key]["payload"]["element_classification"]}
        effective = []
        for blk in rec["element_blocks"]:
            cls = c_map.get(blk["element_id"])
            if not cls:
                continue
            if cls["type"] == "multi_table":
                effective.extend(validation_map.get(blk["element_id"], {}).get("validated_elements", []))
            else:
                effective.append(make_effective_original(blk, cls))
        effective = sorted(effective, key=lambda x: (x["bbox"]["r1"], x["bbox"]["c1"], x["element_id"]))
        print(f"\n[DEBUG][EFFECTIVE ELEMENTS] file={rec['excel_file']} sheet={rec['excel_sheet']}")
        for x in effective:
            print(
                f"  - element_id={x['element_id']} "
                f"source_kind={x.get('source_kind')} "
                f"type={x.get('type')} "
                f"bbox={x.get('bbox')} "
                f"title_guess={x.get('title_guess')} "
                f"candidates={x.get('figure_table_candidates')}"
            )
        effective_map_by_sheet[key] = effective
        grouping_tasks.append({"request_id": make_request_id("resolve_element_groups", rec["excel_file"], rec["excel_sheet"]), "item_key": f'{rec["excel_file"]}::{rec["excel_sheet"]}', "excel_file": rec["excel_file"], "excel_sheet": rec["excel_sheet"], "normalized_sheet_item_hint": rec.get("normalized_sheet_item_hint", ""), "effective_elements": effective})

    group_id = lambda rec: rec["request_id"]
    group_prompt = lambda rec: build_grouping_prompt(rec, inventory_items)
    group_map = run_batch_stage(folder, client, model_name, "resolve_element_groups", grouping_tasks, group_prompt, group_id, shared_contents=shared_pdf_parts, gcs_bucket=gcs_bucket)
    group_resolved = resolve_stage_results(client, model_name, "resolve_element_groups", grouping_tasks, group_map, group_prompt, group_id, ["resolved_groups"], validate_grouping_payload, shared_contents=shared_pdf_parts)

    for rec in split_candidate_sheets:
        key = (rec["excel_file"], rec["excel_sheet"])
        route_row = route_resolved[route_id(rec)]
        group_row = group_resolved[make_request_id("resolve_element_groups", rec["excel_file"], rec["excel_sheet"])]
        route_payload = {**route_row["payload"], "usage": usage_from_batch_row(route_row["row"], "route_sheet", model_name)}
        class_payload = class_by_sheet[key]["payload"]
        group_payload = group_row["payload"]
        print(f"\n[DEBUG][GROUPING RESULT] file={rec['excel_file']} sheet={rec['excel_sheet']}")
        for group in group_payload["resolved_groups"]:
            print(f"  - group={group}")
        effective = effective_map_by_sheet[key]
        final_blocks = materialize_final_blocks(rec, group_payload, effective)
        print(f"\n[DEBUG][FINAL BLOCKS] file={rec['excel_file']} sheet={rec['excel_sheet']}")
        for blk in final_blocks:
            print(
                f"  - block_id={blk['block_id']} "
                f"block_type={blk['block_type']} "
                f"bbox={blk['bbox']} "
                f"source_element_ids={blk['source_element_ids']} "
                f"title_guess={blk['title_guess']} "
                f"candidates={blk['figure_table_candidates']}"
            )
        usage_records = [route_payload["usage"], class_by_sheet[key]["usage"], usage_from_batch_row(group_row["row"], "resolve_element_groups", model_name)]
        mt_split_trace, mt_validation_trace = [], []
        for blk in rec["element_blocks"]:
            if blk["element_id"] in split_exec_map:
                mt_split_trace.append(split_exec_map[blk["element_id"]])
            if blk["element_id"] in validation_map:
                mt_validation_trace.append(validation_map[blk["element_id"]]["payload"])
                usage_records.append(validation_map[blk["element_id"]]["usage"])
        results.append({"excel_file": rec["excel_file"], "excel_sheet": rec["excel_sheet"], "source_path": rec["source_path"], "df": rec["df"], "final_blocks": final_blocks, "result": {"routing": route_payload, "classification": {**class_payload, "usage": class_by_sheet[key]["usage"]}, "multi_table_split": mt_split_trace, "multi_table_validation": mt_validation_trace, "grouping": {**group_payload, "usage_records": [usage_from_batch_row(group_row["row"], "resolve_element_groups", model_name)]}, "effective_elements": [{k: (None if k == "df" else v) for k, v in x.items()} for x in effective], "final_blocks": [{"block_id": x["block_id"], "group_id": x["group_id"], "title_guess": x["title_guess"], "bbox": x["bbox"], "block_type": x["block_type"], "source_element_ids": x["source_element_ids"], "matched_item_ids": x["matched_item_ids"], "guessed_item_ids": x["guessed_item_ids"], "figure_table_candidates": x["figure_table_candidates"], "composition_mode": x.get("composition_mode"), "composition_axis": x.get("composition_axis"), "composition_confidence": x.get("composition_confidence")} for x in final_blocks], "usage_records": [x for x in usage_records if x]}})
    return results


def save_result_artifacts(folder: Path, row_data: dict, inventory_rows: list[dict]):
    excel_file, excel_sheet, result = row_data["excel_file"], row_data["excel_sheet"], row_data["result"]
    safe_sheet = safe_path_name(excel_sheet)
    out_dir = folder / "Exp_Excel_Blocks" / Path(excel_file).stem / safe_sheet
    out_dir.mkdir(parents=True, exist_ok=True)
    if result["routing"]["route"] == "single_sheet_table":
        df = row_data["df"]
        block_id = f"{Path(excel_file).stem}__{safe_sheet}__whole_sheet"
        blocks = [{"block_id": block_id, "group_id": f"{block_id}_group", "element_id": block_id, "title_guess": excel_sheet, "bbox": {"r1": 1, "r2": int(df.shape[0]), "c1": 1, "c2": int(df.shape[1]) if hasattr(df, "shape") else 1}, "df": df, "block_type": "title_and_table", "source_element_ids": [], "matched_item_ids": result["routing"].get("matched_item_ids", []), "guessed_item_ids": [], "figure_table_candidates": [], "source_kinds": []}]
    else:
        blocks = row_data.get("final_blocks", [])
    for block in blocks:
        df_to_save = block.get("df")
        if df_to_save is None or df_to_save.empty:
            continue

        nonempty_mask = df_to_save.astype(str).applymap(lambda x: str(x).strip() != "")
        if not nonempty_mask.any().any():
            continue
        csv_path = out_dir / f'{block["block_id"]}.csv'
        meta_path = out_dir / f'{block["block_id"]}.json'
        block["df"].to_csv(csv_path, index=False, encoding="utf-8-sig")
        meta = {k: v for k, v in block.items() if k != "df"}
        meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
        inventory_rows.append({"excel_file": excel_file, "excel_sheet": excel_sheet, "block_id": block["block_id"], "group_id": block["group_id"], "element_id": block["element_id"], "block_csv_path": csv_path.relative_to(folder).as_posix(), "block_meta_path": meta_path.relative_to(folder).as_posix(), "block_title_guess": block["title_guess"], "block_type": block["block_type"], "save_mode": result["routing"]["route"], "matched_item_ids": json.dumps(block["matched_item_ids"], ensure_ascii=False), "guessed_item_ids": json.dumps(block["guessed_item_ids"], ensure_ascii=False), "figure_table_candidates": json.dumps(block["figure_table_candidates"], ensure_ascii=False), "bbox_r1": block["bbox"]["r1"], "bbox_r2": block["bbox"]["r2"], "bbox_c1": block["bbox"]["c1"], "bbox_c2": block["bbox"]["c2"]})


def process_excel_block_splitter(folder: Path, client, model_name: str, gcs_bucket: str = DEFAULT_GCS_BATCH_BUCKET):
    folder = Path(folder)
    exp_excel_dir = folder / "Exp_Excel"
    if not exp_excel_dir.exists():
        raise FileNotFoundError(f"Exp_Excel not found: {exp_excel_dir}")
    input_files = sorted([p for p in exp_excel_dir.rglob("*") if p.is_file() and p.suffix.lower() in {".xlsx", ".csv"} and not p.name.startswith("~")])
    if not input_files:
        raise FileNotFoundError(f"no xlsx/csv files under {exp_excel_dir}")
    _ = load_markdown_text(folder)
    uploaded_pdfs = upload_pdfs_to_gcs(folder, gcs_bucket)
    inventory_items = load_inventory_items(folder)
    sheet_records = []
    for input_file in input_files:
        print(f"\n=== FILE: {input_file.name} ===")
        try:
            sheet_specs = list_sheet_specs(input_file)
        except Exception as exc:
            print(f"  ! list_sheet_specs failed: {exc}")
            traceback.print_exc()
            continue
        for spec in sheet_specs:
            try:
                df = load_sheet_df(spec["source_path"], spec["excel_sheet"])
                element_blocks = split_sheet_into_blocks(spec["source_path"], spec["excel_sheet"], resolved_groups=None)
                print(f"\n[DEBUG][RAW ELEMENTS] file={spec['excel_file']} sheet={spec['excel_sheet']}")
                # [DEBUG SAVE] first split raw elements as CSV
                debug_dir = folder / "DEBUG_RAW_ELEMENTS" / Path(spec["excel_file"]).stem / safe_path_name(
                    spec["excel_sheet"])
                debug_dir.mkdir(parents=True, exist_ok=True)

                for blk in element_blocks:
                    element_id = str(blk.get("element_id", "unknown"))
                    bbox = blk.get("bbox", {})
                    title_guess = str(blk.get("title_guess", "")).strip()

                    blk_df = blk.get("df")
                    if blk_df is None:
                        continue

                    csv_path = debug_dir / f"{element_id}.csv"
                    meta_path = debug_dir / f"{element_id}.json"

                    blk_df.to_csv(csv_path, index=False, encoding="utf-8-sig")
                    meta_path.write_text(
                        json.dumps(
                            {
                                "element_id": element_id,
                                "excel_file": spec["excel_file"],
                                "excel_sheet": spec["excel_sheet"],
                                "bbox": bbox,
                                "title_guess": title_guess,
                                "reading_order_index": blk.get("reading_order_index"),
                            },
                            ensure_ascii=False,
                            indent=2,
                        ),
                        encoding="utf-8",
                    )

                for blk in element_blocks:
                    print(
                        f"  - element_id={blk.get('element_id')} "
                        f"bbox={blk.get('bbox')} "
                        f"title_guess={blk.get('title_guess')} "
                        f"reading_order_index={blk.get('reading_order_index')}"
                    )
                sheet_records.append(build_sheet_record(spec["excel_file"], spec["excel_sheet"], spec["source_path"], df, element_blocks))
            except Exception as exc:
                print(f"  ! sheet read failed: {exc}")
                traceback.print_exc()
    batch_rows = run_three_steps_batch(folder, client, model_name, uploaded_pdfs, inventory_items, sheet_records, gcs_bucket=gcs_bucket)
    all_results, inventory_rows, usage_rows = [], [], []
    for row in batch_rows:
        save_result_artifacts(folder, row, inventory_rows)
        for usage in row["result"].get("usage_records", []):
            usage_rows.append({"excel_file": row["excel_file"], "excel_sheet": row["excel_sheet"], **usage})
        result_row = {
            "excel_file": row["excel_file"],
            "excel_sheet": row["excel_sheet"],
            "result": row["result"],
        }
        safe_result_row = make_json_safe(result_row)

        all_results.append(safe_result_row)

        out_path = folder / f'three_core_result__{Path(row["excel_file"]).stem}__{safe_path_name(row["excel_sheet"])}.json'
        out_path.write_text(
            json.dumps(safe_result_row, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    (folder / "three_core_result_all.json").write_text(json.dumps(all_results, ensure_ascii=False, indent=2), encoding="utf-8")
    if inventory_rows:
        pd.DataFrame(inventory_rows).to_csv(folder / "excel_block_inventory.csv", index=False, encoding="utf-8-sig")
    if usage_rows:
        pd.DataFrame(usage_rows).to_csv(folder / "excel_block_usage_inventory.csv", index=False, encoding="utf-8-sig")
    return {"summary_path": str(folder / "three_core_result_all.json"), "inventory_path": str(folder / "excel_block_inventory.csv"), "usage_inventory_path": str(folder / "excel_block_usage_inventory.csv"), "block_count": len(inventory_rows)}


if __name__ == "__main__":
    TEST_FOLDER = Path(r"/Users/kogeon/python_projects_path/LNPDB_Articles_Extraction/Extraction_Examples/excel_o")
    api_key_path = find_api_key_file(API_JSON_NAME)
    with open(api_key_path, "r", encoding="utf-8") as f:
        cred_data = json.load(f)
    project_id = cred_data.get("project_id")
    if not project_id:
        raise ValueError(f"project_id missing in credentials: {api_key_path}")
    client = get_vertexai_client(api_key_path, project=project_id)
    process_excel_block_splitter(TEST_FOLDER, client, MODEL_NAME, gcs_bucket=DEFAULT_GCS_BATCH_BUCKET)
