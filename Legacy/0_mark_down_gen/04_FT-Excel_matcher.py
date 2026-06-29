import hashlib
import json
import re
import sys
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

DEFAULT_GCS_BATCH_BUCKET = "gs://lnpdb-articles-extraction-batch-results-geon"
API_JSON_NAME = "vertex.json"
MODEL_NAME = "gemini-3.1-pro-preview"


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


def list_pdf_paths(folder: Path) -> list[Path]:
    return sorted([f for f in folder.rglob("*.pdf") if f.is_file() and "Exp_Excel" not in f.parts])


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


def make_request_id(block_info: dict) -> str:
    seed = "::".join([block_info.get("excel_file", ""), block_info.get("excel_sheet", ""), block_info.get("block_id", ""), block_info.get("block_csv_path", "")])
    return "excel_block_match__" + hashlib.sha1(seed.encode("utf-8")).hexdigest()[:16]


def usage_from_batch_row(row: dict, task_name: str, model_name: str) -> dict:
    cost_info = row.get("cost_info") or {}
    usage = {"task_name": task_name, "model_name": model_name, "input_tokens": row.get("input_tokens"), "output_tokens": row.get("output_tokens"), "total_tokens": row.get("total_tokens"), "billed_output_tokens": row.get("billed_output_tokens")}
    if cost_info:
        usage["total_cost_usd"] = cost_info.get("total_cost_usd")
    return usage


def load_excel_blocks(folder: Path) -> dict[str, dict]:
    inventory_path = folder / "excel_block_inventory.csv"
    if not inventory_path.exists():
        return {}
    inv_df = pd.read_csv(inventory_path, dtype=str).fillna("")
    out = {}
    for _, row in inv_df.iterrows():
        csv_path = folder / str(row.get("block_csv_path", "")).strip()
        if not csv_path.exists():
            continue
        df = pd.read_csv(csv_path, dtype=str).fillna("")
        key = f'{row.get("excel_file","")} | {row.get("excel_sheet","")} | {row.get("block_id","")}'
        out[key] = {
            "block_key": key,
            "excel_file": str(row.get("excel_file", "")).strip(),
            "excel_sheet": str(row.get("excel_sheet", "")).strip(),
            "block_id": str(row.get("block_id", "")).strip(),
            "block_csv_path": str(row.get("block_csv_path", "")).strip(),
            "block_csv_abs_path": str(csv_path),
            "block_title_guess": str(row.get("block_title_guess", "")).strip(),
            "block_type": str(row.get("block_type", "")).strip(),
            "save_mode": str(row.get("save_mode", "")).strip(),
            "bbox": {"r1": str(row.get("bbox_r1", "")).strip(), "r2": str(row.get("bbox_r2", "")).strip(), "c1": str(row.get("bbox_c1", "")).strip(), "c2": str(row.get("bbox_c2", "")).strip()},
            "candidate_ids": str(row.get("figure_table_candidates", "")).strip(),
            "matched_ids_hint": str(row.get("matched_item_ids", "")).strip(),
            "normalized_sheet_item_hint": normalize_ft_item_id(row.get("excel_sheet", "")),
            "csv_text": df.to_csv(index=False),
        }
    return out


def parse_match_json(text: str, block_info: dict, request_id: str) -> list[dict]:
    cleaned = str(text).replace("```json", "").replace("```", "").strip()
    payload = json.loads(cleaned)
    if str(payload.get("request_id", "")).strip() != request_id:
        raise ValueError("request_id mismatch")
    matches = []
    for row in payload.get("matches", []):
        if not isinstance(row, dict):
            continue
        pdf_item_id = normalize_ft_item_id(row.get("pdf_item_id", ""))
        if not pdf_item_id:
            continue
        matches.append({
            "pdf_item_id": pdf_item_id,
            "excel_item_id": str(row.get("excel_item_id", "")).strip(),
            "excel_file": block_info["excel_file"],
            "excel_sheet": block_info["excel_sheet"],
            "block_id": block_info["block_id"],
            "block_csv_path": block_info["block_csv_path"],
            "reason": str(row.get("reason", "")).strip(),
        })
    return matches


def build_block_match_prompt(inventory_items: list[str], block_info: dict, request_id: str) -> str:
    inventory_text = "\n".join(f"- {x}" for x in inventory_items[:400]) if inventory_items else "- none"
    return f"""
Match one final Excel block to paper fig/table inventory.

request_id: {request_id}
excel_file: {block_info["excel_file"]}
excel_sheet: {block_info["excel_sheet"]}
block_id: {block_info["block_id"]}
block_csv_path: {block_info["block_csv_path"]}
block_title_guess: {block_info.get("block_title_guess", "")}
block_type: {block_info.get("block_type", "")}
save_mode: {block_info.get("save_mode", "")}
bbox: {json.dumps(block_info.get("bbox", {}), ensure_ascii=False)}
candidate_ids_hint: {block_info.get("candidate_ids", "")}
matched_ids_hint: {block_info.get("matched_ids_hint", "")}
normalized_sheet_item_hint: {block_info.get("normalized_sheet_item_hint", "")}

Important:
- This block inventory is already grouped in step 03.
- Do not try to merge blocks again.
- Just decide which inventory item(s) this block matches.
- Body-only, title-only, and already-combined body/title blocks are all valid inputs.
- Extended Data Fig. 1, Extended Data Figure 1, and extended data figure 1 are the same item. Do not confuse them with ordinary figure 1 or supplementary figure 1.

Inventory:
{inventory_text}

Block CSV:
{block_info["csv_text"]}

Return JSON only:
{{
  "request_id": "{request_id}",
  "matches": [
    {{
      "pdf_item_id": "figure 2a",
      "excel_item_id": "figure 2a",
      "reason": "why"
    }}
  ]
}}
"""


def run_block_match_batch(folder: Path, client, model_name: str, inventory_items: list[str], blocks_data: dict, uploaded_pdfs: list[dict], gcs_bucket: str = DEFAULT_GCS_BATCH_BUCKET):
    request_file = create_batch_request_file(folder, f"excel_block_match_{folder.name}")
    shared_contents = build_pdf_file_parts(uploaded_pdfs)
    for block_key, block_info in blocks_data.items():
        request_id = make_request_id(block_info)
        prompt = build_block_match_prompt(inventory_items, block_info, request_id)
        metadata = build_batch_request_metadata(task_name="excel_block_match", model_name=model_name, custom_id=request_id, stage_name="excel_block_match", item_id=block_key, paper_folder=str(folder), extra_metadata={"request_id": request_id, "excel_file": block_info.get("excel_file", ""), "excel_sheet": block_info.get("excel_sheet", ""), "block_id": block_info.get("block_id", "")})
        request_body = build_generate_content_batch_request(model_name=model_name, contents=list(shared_contents), prompt_text=prompt, response_mime_type="application/json")
        append_batch_request(request_file=request_file, custom_id=request_id, request_body=request_body, metadata=metadata)
    local_job_id = create_batch_job_record(paper_folder=folder, task_name="excel_block_match", model_name=model_name, request_file=request_file, metadata={"request_count": count_requests_in_jsonl(request_file), "gcs_input_uri": f"{gcs_bucket}/batch/{request_file.name}", "gcs_output_uri_prefix": f"{gcs_bucket}/batch_output/{request_file.stem}"})
    batch_job = submit_batch_job(client=client, paper_folder=folder, local_job_id=local_job_id, display_name=f"excel-block-match-{folder.name}")
    print(f"  * submitted matcher batch: {batch_job.name}")
    finished_job = poll_batch_job(client=client, paper_folder=folder, local_job_id=local_job_id, poll_interval_seconds=30)
    state_name = getattr(getattr(finished_job, "state", None), "name", None) or str(getattr(finished_job, "state", "UNKNOWN"))
    if state_name != "JOB_STATE_SUCCEEDED":
        raise RuntimeError(f"excel_block_match batch failed: {state_name}")
    return load_batch_results_as_map(download_batch_results(client=client, paper_folder=folder, local_job_id=local_job_id))


def call_block_match_sync(client, model_name: str, inventory_items: list[str], block_info: dict, shared_contents=None):
    request_id = make_request_id(block_info)
    prompt = build_block_match_prompt(inventory_items, block_info, request_id)
    call_result = generate_content_with_guard(client=client, model_name=model_name, contents=list(shared_contents or []), prompt_text=prompt, task_name="excel_block_match_retry", response_mime_type="application/json", max_retries=1)
    return parse_match_json(call_result.response_text, block_info, request_id)


def process_excel_matcher(folder: Path, client, model_name: str):
    folder = Path(folder)
    classified_input_csv = folder / "fig_table_lnpdb_classified.csv"
    inventory_csv = folder / "fig_table_inventory.csv"
    if classified_input_csv.exists():
        input_csv = classified_input_csv
    elif inventory_csv.exists():
        input_csv = inventory_csv
    else:
        raise FileNotFoundError(
            f"matcher input not found: {classified_input_csv} or {inventory_csv}"
        )
    inv_df = pd.read_csv(input_csv).fillna("")
    print(f"  - matcher input csv: {input_csv}")
    print(f"  - matcher input row 개수: {len(inv_df)}")
    print(f"  - matcher input columns: {list(inv_df.columns)}")
    inventory_items = [normalize_ft_item_id(x) for x in inv_df["item_id"].tolist()]
    uploaded_pdfs = upload_pdfs_to_gcs(folder, DEFAULT_GCS_BATCH_BUCKET)
    blocks_data = load_excel_blocks(folder)
    print(f"  - 로드된 Excel block 개수: {len(blocks_data)}")
    if blocks_data:
        print("  - 추출 대상 block CSV 목록:")
        for block_key, block_info in blocks_data.items():
            print(f"    * {block_info.get('block_csv_abs_path', block_info.get('block_csv_path', ''))}")
            
    if not blocks_data:
        raise FileNotFoundError("excel_block_inventory.csv has no readable blocks")

    print(f"  - batch 요청 block 개수: {len(blocks_data)}")
    batch_results_map = run_block_match_batch(folder, client, model_name, inventory_items, blocks_data, uploaded_pdfs, gcs_bucket=DEFAULT_GCS_BATCH_BUCKET)
    usage_rows, match_rows, matched_item_data = [], [], {}
    failed = []

    def apply_matches(matches: list[dict]):
        for m in matches:
            pdf_item_id = normalize_ft_item_id(m["pdf_item_id"])
            m["pdf_item_id"] = pdf_item_id
            match_rows.append(m)
            matched_item_data.setdefault(pdf_item_id, {"excel_item_id": m.get("excel_item_id", ""), "matched_blocks": [], "matched_block_paths": []})
            matched_item_data[pdf_item_id]["matched_blocks"].append(f'{m["excel_file"]} [{m["excel_sheet"]}] [{m["block_id"]}]')
            matched_item_data[pdf_item_id]["matched_block_paths"].append(m["block_csv_path"])
            if not matched_item_data[pdf_item_id]["excel_item_id"] and m.get("excel_item_id"):
                matched_item_data[pdf_item_id]["excel_item_id"] = m["excel_item_id"]

    for block_key, block_info in blocks_data.items():
        request_id = make_request_id(block_info)
        row = batch_results_map.get(request_id)
        if not row or not row.get("success") or not str(row.get("response_text", "")).strip():
            failed.append(block_key)
            continue
        usage_rows.append({"excel_file": block_info["excel_file"], "excel_sheet": block_info["excel_sheet"], "block_id": block_info["block_id"], **usage_from_batch_row(row, "excel_block_match", model_name)})
        try:
            apply_matches(parse_match_json(row["response_text"], block_info, request_id))
        except Exception:
            failed.append(block_key)

    if failed:
        shared_retry_contents = build_pdf_file_parts(uploaded_pdfs)
        for block_key in failed:
            block_info = blocks_data.get(block_key)
            if not block_info:
                continue
            try:
                apply_matches(call_block_match_sync(client, model_name, inventory_items, block_info, shared_contents=shared_retry_contents))
            except Exception:
                pass

    if "excel_item_id" not in inv_df.columns:
        inv_df["excel_item_id"] = ""
    if "matched_blocks" not in inv_df.columns:
        inv_df["matched_blocks"] = ""
    if "matched_block_csv_path" not in inv_df.columns:
        inv_df["matched_block_csv_path"] = ""

    for idx, row in inv_df.iterrows():
        item_id = normalize_ft_item_id(row.get("item_id", ""))
        if item_id not in matched_item_data:
            continue
        match = matched_item_data[item_id]
        inv_df.at[idx, "excel_item_id"] = match.get("excel_item_id", "")
        inv_df.at[idx, "matched_blocks"] = " | ".join(match.get("matched_blocks", []))
        inv_df.at[idx, "matched_block_csv_path"] = " | ".join(match.get("matched_block_paths", []))

    matched_block_paths = sorted(
        {
            path
            for match in matched_item_data.values()
            for path in match.get("matched_block_paths", [])
            if path
        }
    )
    print("  - 실제 매칭된 block CSV 목록:")
    for path in matched_block_paths:
        print(f"    * {path}")

    if "manual_select" not in inv_df.columns:
        inv_df["manual_select"] = ""
    moved = inv_df.pop("manual_select")
    inv_df["manual_select"] = moved

    classified_csv_path = folder / "fig_table_lnpdb_classified.csv"
    inv_df.to_csv(classified_csv_path, index=False, encoding="utf-8-sig")

    excel_mapping = {}
    for row in match_rows:
        item_id = normalize_ft_item_id(row.get("pdf_item_id", ""))
        if not item_id:
            continue
        excel_mapping.setdefault(item_id, []).append(
            {
                "pdf_item_id": item_id,
                "excel_item_id": str(row.get("excel_item_id", "")).strip(),
                "excel_file": str(row.get("excel_file", "")).strip(),
                "excel_sheet": str(row.get("excel_sheet", "")).strip(),
                "block_id": str(row.get("block_id", "")).strip(),
                "block_csv_path": str(row.get("block_csv_path", "")).strip(),
                "reason": str(row.get("reason", "")).strip(),
            }
        )

    (folder / "excel_mapping.json").write_text(
        json.dumps(excel_mapping, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    pd.DataFrame(match_rows).to_csv(
        folder / "excel_mapping_rows.csv",
        index=False,
        encoding="utf-8-sig",
    )

    if usage_rows:
        pd.DataFrame(usage_rows).to_csv(folder / "04_excel_match_batch_usage.csv", index=False, encoding="utf-8-sig")
    print(f"saved: {classified_csv_path}")


if __name__ == "__main__":
    TEST_FOLDER = Path(r"/Users/kogeon/Google Drive/내 드라이브/LNPDB_new/FG_2026")
    api_key_path = find_api_key_file(API_JSON_NAME)
    with open(api_key_path, "r", encoding="utf-8") as f:
        cred_data = json.load(f)
    project_id = cred_data.get("project_id")
    if not project_id:
        raise ValueError(f"project_id missing in credentials: {api_key_path}")
    client = get_vertexai_client(api_key_path, project=project_id)
    process_excel_matcher(TEST_FOLDER, client, MODEL_NAME)
