import io
import json
import re
import sys
import time
import traceback
from pathlib import Path

import pandas as pd

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent.parent

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from find_api import find_api_key_file, get_vertexai_client

API_JSON_NAME = "vertex.json"
PRIMARY_MODEL = "gemini-3.1-pro-preview"
FALLBACK_MODEL = "gemini-3.1-pro-preview"
MATCHING_CSV_NAME = "fig_table_lnpdb_classified.csv"
MAPPING_JSON_NAME = "excel_mapping.json"
ROUTING_LOG_CSV_NAME = "exp_vals_routing_log.csv"
FINAL_OUTPUT_CSV_NAME = "exp_vals_final.csv"
INDIVIDUAL_OUTPUT_DIRNAME = "exp_vals_individual_sheets"
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
VALIDATION_SUMMARY_CSV_NAME = "exp_vals_extraction_validation_summary.csv"
FAILURE_LOG_CSV_NAME = "exp_vals_extraction_failure_log.csv"
CLASSIFICATION_CSV_CANDIDATES = [
    "fig_table_lnpdb_classified.csv",
    "fig_table_inventory.csv",
    "selected_item_routes.csv",
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
    text = re.sub(r"\bsupplementary\s+figure\s*([0-9]+[a-z]?)\b", r"supplementary figure \1", text)
    text = re.sub(r"\bsupplementary\s+table\s*([0-9]+[a-z]?)\b", r"supplementary table \1", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def normalize_block_key(value) -> str:
    text = safe_str(value).replace("\\", "/").lower().strip()
    if text.startswith("./"):
        text = text[2:]
    return re.sub(r"/+", "/", text)


def block_key_candidates(value) -> list[str]:
    norm = normalize_block_key(value)
    if not norm:
        return []
    path = Path(norm)
    candidates = [
        norm,
        path.name,
        path.stem,
    ]
    if norm.endswith(".csv"):
        candidates.append(norm[:-4])
    return list(dict.fromkeys([x for x in candidates if x]))


def load_total_figure_mapping(folder: Path) -> dict:
    for path in [folder / "total_figure_mapping.json", folder.parent / "total_figure_mapping.json"]:
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                return data if isinstance(data, dict) else {}
            except Exception as exc:
                print(f"  ! total_figure_mapping load failed: {path} | {exc}")
                return {}
    return {}


def find_pdf_candidates(folder: Path) -> list[str]:
    candidates = []
    for base in [folder, folder.parent]:
        if not base.exists():
            continue
        try:
            if base == folder:
                found = base.rglob("*.pdf")
            else:
                found = list(base.glob("*.pdf"))
                found.extend(p for child in base.iterdir() if child.is_dir() for p in child.glob("*.pdf"))
            for path in found:
                if path.is_file() and path.exists():
                    candidates.append(str(path.resolve()))
        except Exception:
            continue
    return list(dict.fromkeys(candidates))


def extract_panel_suffix(item_id: str) -> str:
    text = normalize_item_id(item_id)
    match = re.search(r"\b(?:supplementary\s+)?(?:figure|table)\s+\d+([a-z])\b$", text)
    return match.group(1) if match else ""


def strip_panel_suffix(item_id: str) -> str:
    text = normalize_item_id(item_id)
    return re.sub(r"\b((?:supplementary\s+)?(?:figure|table)\s+\d+)[a-z]\b$", r"\1", text).strip()


def select_pdf_for_item(item_id: str, block_entry: dict, pdf_candidates: list[str]) -> str:
    existing = [p for p in pdf_candidates if Path(p).exists()]
    if not existing:
        return ""
    item_norm = normalize_item_id(item_id)
    supp_keywords = ("moesm", "esm", "supp", "supplementary")
    main_keywords = ("main", "article", "paper")
    if item_norm.startswith("supplementary "):
        for path in existing:
            if any(k in Path(path).name.lower() for k in supp_keywords):
                return path
    else:
        non_supp = [p for p in existing if not any(k in Path(p).name.lower() for k in supp_keywords)]
        for path in non_supp:
            name = Path(path).stem.lower()
            if any(k in name for k in main_keywords):
                return path
        if non_supp:
            return non_supp[0]
    return existing[0]


def resolve_path_maybe_relative(path_value: str, folder: Path) -> str:
    text = safe_str(path_value)
    if not text:
        return ""
    path = Path(text)
    if path.exists():
        return str(path.resolve())
    candidate = folder / text
    if candidate.exists():
        return str(candidate.resolve())
    parent_candidate = folder.parent / text
    if parent_candidate.exists():
        return str(parent_candidate.resolve())
    return text


def iter_figure_mapping_candidates(total_figure_mapping: dict):
    if not isinstance(total_figure_mapping, dict):
        return
    for key, value in total_figure_mapping.items():
        if isinstance(value, dict) and ("full_image" in value or "panels" in value):
            yield key, value
        elif isinstance(value, dict):
            for sub_key, sub_value in value.items():
                yield sub_key, sub_value


def resolve_figure_evidence(item_id: str, block_entry: dict, total_figure_mapping: dict, pdf_candidates: list[str], folder: Path) -> dict:
    item_norm = normalize_item_id(item_id)
    item_base_norm = strip_panel_suffix(item_norm)
    suffix = extract_panel_suffix(item_norm)
    selected_pdf = select_pdf_for_item(item_norm, block_entry, pdf_candidates)
    best = {
        "figure_evidence_type": "none",
        "figure_mapping_status": "mapping_missing_no_pdf",
        "figure_panel_image_path": "",
        "figure_pdf_path": "",
        "figure_full_image_path": "",
        "panel_image_found": False,
        "used_pdf_fallback": False,
        "figure_image_found": False,
        "pdf_candidate_count": len(pdf_candidates),
        "pdf_candidates": " | ".join(pdf_candidates),
    }

    mapping_found = False
    full_image_path = ""
    for map_item_id, item_map in iter_figure_mapping_candidates(total_figure_mapping):
        map_norm = normalize_item_id(map_item_id)
        if map_norm not in {item_norm, item_base_norm}:
            continue
        mapping_found = True
        if not isinstance(item_map, dict):
            continue
        full_image_path = full_image_path or resolve_path_maybe_relative(item_map.get("full_image", ""), folder)
        panels = item_map.get("panels", {})
        if isinstance(panels, dict) and suffix:
            for panel_key, panel_path in panels.items():
                if safe_str(panel_key).lower() == suffix:
                    panel_resolved = resolve_path_maybe_relative(panel_path, folder)
                    if panel_resolved and Path(panel_resolved).exists():
                        return {
                            **best,
                            "figure_evidence_type": "panel_image",
                            "figure_mapping_status": "panel_found",
                            "figure_panel_image_path": panel_resolved,
                            "figure_full_image_path": full_image_path,
                            "panel_image_found": True,
                            "used_pdf_fallback": False,
                            "figure_image_found": True,
                        }

    if selected_pdf:
        status = "panel_missing_pdf_fallback" if mapping_found else "mapping_missing_pdf_fallback"
        return {
            **best,
            "figure_evidence_type": "pdf",
            "figure_mapping_status": status,
            "figure_pdf_path": selected_pdf,
            "figure_full_image_path": full_image_path,
            "panel_image_found": False,
            "used_pdf_fallback": True,
            "figure_image_found": False,
        }

    return {
        **best,
        "figure_mapping_status": "panel_missing_no_pdf" if mapping_found else "mapping_missing_no_pdf",
        "figure_full_image_path": full_image_path,
    }


def print_figure_evidence(entry: dict, prefix: str = "      "):
    item_display = ", ".join(entry.get("item_ids", []))
    evidence_type = safe_str(entry.get("figure_evidence_type"))
    status = safe_str(entry.get("figure_mapping_status"))
    if evidence_type == "panel_image":
        print(f"{prefix}[evidence] item={item_display} type=panel_image status={status} panel={entry.get('figure_panel_image_path')}")
    elif evidence_type == "pdf":
        extra = f" full_image_not_used={entry.get('figure_full_image_path')}" if safe_str(entry.get("figure_full_image_path")) else ""
        print(f"{prefix}[evidence] item={item_display} type=pdf status={status} pdf={entry.get('figure_pdf_path')}{extra}")
    else:
        print(f"{prefix}[evidence] item={item_display} type=none status={status}")


def extract_item_id_candidates_from_text(value) -> list[str]:
    text = safe_str(value)
    if not text:
        return []
    normalized_space = re.sub(r"[._]+", " ", text)
    patterns = [
        r"\b(?:supp(?:lementary)?\.?\s*)?(?:fig(?:ure)?|table)\.?\s*[0-9]+[a-z]?\b",
        r"\b(?:fig(?:ure)?|table)[0-9]+[a-z]?\b",
    ]
    candidates = []
    for pattern in patterns:
        for match in re.findall(pattern, text, flags=re.IGNORECASE):
            candidates.append(normalize_item_id(match))
        for match in re.findall(pattern, normalized_space, flags=re.IGNORECASE):
            candidates.append(normalize_item_id(match))
    return list(dict.fromkeys([x for x in candidates if x]))


def append_unique(values: list, value):
    if value is None:
        return
    if isinstance(value, dict):
        key = json.dumps(value, sort_keys=True, ensure_ascii=False)
        existing = {json.dumps(v, sort_keys=True, ensure_ascii=False) for v in values if isinstance(v, dict)}
        if key not in existing:
            values.append(value)
        return
    text = safe_str(value)
    if text and text not in values:
        values.append(text)


def parse_estimated_data_count(value):
    text = safe_str(value).replace(",", "")
    if not text or text.lower() in {"unknown", "nan", "none", "null", "n/a"}:
        return None
    try:
        return int(float(text))
    except Exception:
        return None


def semicolon_value_count(value) -> int:
    text = safe_str(value)
    if not text:
        return 0
    return len([x for x in text.split(";") if safe_str(x)])


def build_count_diagnostics(result_df: pd.DataFrame, item_metadata: list[dict] | None = None, block_metadata: dict | None = None) -> dict:
    original_values_column_present = isinstance(result_df, pd.DataFrame) and "original_values" in result_df.columns
    result_df = ensure_output_schema(result_df)
    meta = dominant_metadata(item_metadata or [])
    block_metadata = block_metadata or {}
    expected_count = parse_estimated_data_count(block_metadata.get("estimated_data_count") or meta.get("estimated_data_count"))
    actual_rows = len(result_df)
    if original_values_column_present and not result_df.empty:
        original_counts = result_df["original_values"].map(semicolon_value_count)
    else:
        original_counts = pd.Series([1] * actual_rows, dtype=int)
    max_original_values_count = int(original_counts.max()) if len(original_counts) else 0
    expanded_original_values_count = int(original_counts.sum()) if len(original_counts) else actual_rows
    semicolon_packed_rows_count = int((original_counts >= 2).sum()) if len(original_counts) else 0
    has_semicolon_packed_values = semicolon_packed_rows_count > 0

    count_validation_status = "not_checked_no_expected_count"
    validation_warning = ""
    if expected_count is not None:
        tolerance = max(1, (expected_count + 9) // 10)
        lower = expected_count - tolerance
        upper = expected_count + tolerance
        actual_matches = lower <= actual_rows <= upper
        expanded_matches = lower <= expanded_original_values_count <= upper
        if actual_matches:
            count_validation_status = "match_actual_rows"
        elif expanded_matches:
            count_validation_status = "match_expanded_values"
            validation_warning = (
                "values_are_semicolon_packed_but_count_matches_expected "
                f"max_original_values_count={max_original_values_count} "
                f"expanded_original_values_count={expanded_original_values_count}"
            )
        else:
            count_validation_status = "mismatch"
    elif has_semicolon_packed_values:
        validation_warning = (
            "semicolon_packed_values_detected "
            f"max_original_values_count={max_original_values_count} "
            f"expanded_original_values_count={expanded_original_values_count}"
        )

    return {
        "expected_data_count": expected_count if expected_count is not None else "",
        "actual_row_count": actual_rows,
        "expanded_original_values_count": expanded_original_values_count,
        "max_original_values_count": max_original_values_count,
        "semicolon_packed_rows_count": semicolon_packed_rows_count,
        "has_semicolon_packed_values": has_semicolon_packed_values,
        "count_validation_status": count_validation_status,
        "validation_warning": validation_warning,
    }


def ensure_output_schema(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or not isinstance(df, pd.DataFrame):
        df = pd.DataFrame(columns=REQUIRED_COLS)
    out = df.copy()
    for col in REQUIRED_COLS:
        if col not in out.columns:
            out[col] = ""
    out = out[REQUIRED_COLS + [col for col in out.columns if col not in REQUIRED_COLS]]
    for col in REQUIRED_COLS:
        out[col] = out[col].fillna("").astype(str).str.strip()
    return out


def find_classification_csv(folder: Path, classification_csv_path=None) -> Path | None:
    if classification_csv_path:
        path = Path(classification_csv_path)
        return path if path.exists() else None
    for name in CLASSIFICATION_CSV_CANDIDATES:
        path = folder / name
        if path.exists():
            return path
    return None


def load_item_metadata(folder: Path, classification_csv_path=None) -> dict:
    csv_path = find_classification_csv(folder, classification_csv_path=classification_csv_path)
    if not csv_path:
        return {"item_metadata_by_item_key": {}, "item_metadata_by_block_key": {}}
    try:
        df = pd.read_csv(csv_path).fillna("")
    except Exception as exc:
        print(f"  ! classification metadata load failed: {csv_path} | {exc}")
        return {"item_metadata_by_item_key": {}, "item_metadata_by_block_key": {}}

    cols_lower = {c.lower(): c for c in df.columns}
    item_col = cols_lower.get("item_id") or cols_lower.get("item_id".lower()) or cols_lower.get("item_id")
    if item_col is None and "Item_ID" in df.columns:
        item_col = "Item_ID"
    if item_col is None:
        return {"item_metadata_by_item_key": {}, "item_metadata_by_block_key": {}}

    item_metadata_by_item_key = {}
    item_metadata_by_block_key = {}

    def row_value(row, name):
        col = cols_lower.get(name.lower())
        return safe_str(row.get(col, "")) if col else ""

    for _, row in df.iterrows():
        item_id = normalize_item_id(row.get(item_col, ""))
        if not item_id:
            continue
        visual_type = row_value(row, "visual_type").lower()
        if visual_type == "raw_data_table":
            visual_type = "table"
        metadata = {
            "item_id": item_id,
            "item_type": row_value(row, "item_type"),
            "base_id": normalize_item_id(row_value(row, "base_id")),
            "is_supplementary": row_value(row, "is_supplementary"),
            "visual_type": visual_type or "unknown",
            "need_for_lnpdb": row_value(row, "need_for_lnpdb"),
            "priority": row_value(row, "priority"),
            "estimated_data_count": row_value(row, "estimated_data_count"),
            "classified_reason": row_value(row, "reason"),
            "reason": row_value(row, "reason"),
            "confidence": row_value(row, "confidence"),
            "excel_item_id": normalize_item_id(row_value(row, "excel_item_id")),
            "matched_blocks": row_value(row, "matched_blocks"),
            "matched_block_csv_path": row_value(row, "matched_block_csv_path"),
            "manual_select": row_value(row, "manual_select"),
        }

        for key_source in [metadata["item_id"], metadata["excel_item_id"], metadata["base_id"]]:
            key = normalize_item_id(key_source)
            if key:
                item_metadata_by_item_key.setdefault(key, metadata)

        for raw_path in [x.strip() for x in metadata["matched_block_csv_path"].split(" | ") if x.strip()]:
            for key in block_key_candidates(raw_path):
                item_metadata_by_block_key.setdefault(key, metadata)

        matched_blocks = metadata["matched_blocks"]
        for key in block_key_candidates(matched_blocks):
            item_metadata_by_block_key.setdefault(key, metadata)
        for block_id_like in re.findall(r"[A-Za-z0-9][A-Za-z0-9_.-]*__(?:Fig|Figure|Table|Supp)[A-Za-z0-9_.-]*__[A-Za-z0-9_.-]+", matched_blocks, flags=re.IGNORECASE):
            for key in block_key_candidates(block_id_like):
                item_metadata_by_block_key.setdefault(key, metadata)

    return {
        "item_metadata_by_item_key": item_metadata_by_item_key,
        "item_metadata_by_block_key": item_metadata_by_block_key,
    }


def metadata_for_items(item_ids, item_metadata_map: dict) -> list[dict]:
    out = []
    for item_id in item_ids or []:
        clean = normalize_item_id(item_id)
        meta = dict(item_metadata_map.get(clean, {}))
        if not meta:
            meta = {"item_id": clean, "visual_type": "unknown", "estimated_data_count": "", "classified_reason": "", "reason": ""}
        out.append(meta)
    return out


def dominant_metadata(item_metadata: list[dict]) -> dict:
    if item_metadata:
        return item_metadata[0]
    return {"item_id": "", "visual_type": "unknown", "estimated_data_count": "", "classified_reason": "", "reason": ""}


def empty_block_metadata() -> dict:
    return {
        "visual_type": "unknown",
        "estimated_data_count": "",
        "mapping_reason": "",
        "classified_reason": "",
        "metadata_found": False,
        "metadata_matched_by": "not_found",
        "metadata_candidates": [],
        "excel_file": "",
        "excel_sheet": "",
        "block_id": "",
        "block_csv_path": "",
        "figure_evidence_type": "none",
        "figure_mapping_status": "",
        "figure_panel_image_path": "",
        "figure_full_image_path": "",
        "figure_pdf_path": "",
        "panel_image_found": False,
        "used_pdf_fallback": False,
        "figure_image_found": False,
        "pdf_candidate_count": 0,
        "pdf_candidates": "",
    }


def validate_extraction_df(df: pd.DataFrame, item_metadata: list[dict] | None = None, block_metadata: dict | None = None) -> tuple[bool, str, pd.DataFrame]:
    result_df = ensure_output_schema(df)
    if result_df.empty:
        return False, "empty_result", result_df

    core_cols = ["formulation_id", "metric_type", "original_values", "aggregated_value"]
    nonempty_mask = ~(
        result_df[core_cols].fillna("").astype(str).apply(lambda s: s.str.strip().eq("")).all(axis=1)
    )
    if not bool(nonempty_mask.any()):
        return False, "core_columns_all_empty", result_df

    meta = dominant_metadata(item_metadata or [])
    block_metadata = block_metadata or {}
    visual_type = safe_str(block_metadata.get("visual_type")).lower() or safe_str(meta.get("visual_type")).lower()
    estimated_count = parse_estimated_data_count(block_metadata.get("estimated_data_count") or meta.get("estimated_data_count"))
    if not visual_type or visual_type == "unknown":
        visual_values = result_df["visual_type"].astype(str).str.lower().replace("", pd.NA).dropna().unique().tolist()
        visual_type = visual_values[0] if visual_values else ""
    if visual_type and "visual_type" in result_df.columns:
        result_df.loc[result_df["visual_type"].astype(str).str.strip().eq(""), "visual_type"] = visual_type

    diagnostics = build_count_diagnostics(result_df, item_metadata=item_metadata, block_metadata=block_metadata)
    if estimated_count is None and result_df["original_values"].astype(str).str.strip().eq("").all():
        return False, "original_values_all_empty", result_df
    if estimated_count is not None and diagnostics["count_validation_status"] == "mismatch":
        tolerance = max(1, (estimated_count + 9) // 10)
        return (
            False,
            (
                f"count_mismatch expected={estimated_count} "
                f"actual_rows={diagnostics['actual_row_count']} "
                f"expanded_values={diagnostics['expanded_original_values_count']} "
                f"tolerance={tolerance}"
            ),
            result_df,
        )

    return True, "ok", result_df


def is_usable_result_df(df: pd.DataFrame) -> bool:
    if df is None or not isinstance(df, pd.DataFrame):
        return False
    result_df = ensure_output_schema(df)
    if result_df.empty:
        return False
    core_cols = ["formulation_id", "metric_type", "original_values", "aggregated_value"]
    nonempty_core = ~(
        result_df[core_cols].fillna("").astype(str).apply(lambda s: s.str.strip().eq("")).all(axis=1)
    )
    return bool(nonempty_core.any())


def build_validation_summary_row(result_df: pd.DataFrame, item_metadata: list[dict], validation_status: str, validation_reason: str, used_route: str, block_metadata: dict | None = None, matched_sheet_file: str = "", pipeline_status: str | None = None) -> dict:
    result_df = ensure_output_schema(result_df)
    meta = dominant_metadata(item_metadata)
    block_metadata = block_metadata or {}
    original_counts = result_df["original_values"].map(semicolon_value_count) if not result_df.empty else pd.Series(dtype=int)
    diagnostics = build_count_diagnostics(result_df, item_metadata=item_metadata, block_metadata=block_metadata)
    pipeline_status = pipeline_status or validation_status
    return {
        "item_id": safe_str(meta.get("item_id")) or safe_str(result_df["Item_ID"].iloc[0] if not result_df.empty else ""),
        "matched_sheet_file": matched_sheet_file or safe_str(result_df["Matched_Sheet_File"].iloc[0] if not result_df.empty else ""),
        "visual_type": safe_str(block_metadata.get("visual_type")) or safe_str(meta.get("visual_type")) or safe_str(result_df["visual_type"].iloc[0] if not result_df.empty else ""),
        "estimated_data_count": safe_str(block_metadata.get("estimated_data_count")) or safe_str(meta.get("estimated_data_count")),
        "output_rows": len(result_df),
        "unique_formulation_id_count": int(result_df["formulation_id"].astype(str).str.strip().replace("", pd.NA).dropna().nunique()) if not result_df.empty else 0,
        "max_original_values_count": int(original_counts.max()) if len(original_counts) else 0,
        "semicolon_row_count": int((original_counts >= 2).sum()) if len(original_counts) else 0,
        "expected_data_count": diagnostics["expected_data_count"],
        "actual_row_count": diagnostics["actual_row_count"],
        "expanded_original_values_count": diagnostics["expanded_original_values_count"],
        "semicolon_packed_rows_count": diagnostics["semicolon_packed_rows_count"],
        "has_semicolon_packed_values": diagnostics["has_semicolon_packed_values"],
        "count_validation_status": diagnostics["count_validation_status"],
        "validation_warning": diagnostics["validation_warning"],
        "validation_status": validation_status,
        "validation_reason": validation_reason,
        "used_route": used_route,
        "route_used": used_route,
        "status": pipeline_status,
        "metadata_found": bool(block_metadata.get("metadata_found", False)),
        "metadata_matched_by": safe_str(block_metadata.get("metadata_matched_by")),
        "mapping_reason": safe_str(block_metadata.get("mapping_reason")),
        "classified_reason": safe_str(block_metadata.get("classified_reason")) or safe_str(meta.get("classified_reason")) or safe_str(meta.get("reason")),
        "excel_file": safe_str(block_metadata.get("excel_file")),
        "excel_sheet": safe_str(block_metadata.get("excel_sheet")),
        "block_id": safe_str(block_metadata.get("block_id")),
        "block_csv_path": safe_str(block_metadata.get("block_csv_path")),
        "figure_evidence_type": safe_str(block_metadata.get("figure_evidence_type")),
        "figure_mapping_status": safe_str(block_metadata.get("figure_mapping_status")),
        "panel_image_found": bool(block_metadata.get("panel_image_found", False)),
        "used_pdf_fallback": bool(block_metadata.get("used_pdf_fallback", False)),
        "figure_panel_image_path": safe_str(block_metadata.get("figure_panel_image_path")),
        "figure_full_image_path": safe_str(block_metadata.get("figure_full_image_path")),
        "figure_pdf_path": safe_str(block_metadata.get("figure_pdf_path")),
        "pdf_candidate_count": safe_str(block_metadata.get("pdf_candidate_count")),
        "pdf_candidates": safe_str(block_metadata.get("pdf_candidates")),
    }


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


def resolve_mapping_metadata(mapping_item_key: str, mapping: dict, metadata_maps: dict) -> tuple[dict, str, list[str]]:
    item_map = metadata_maps.get("item_metadata_by_item_key", {})
    block_map = metadata_maps.get("item_metadata_by_block_key", {})
    candidates = []

    item_sources = [
        ("item_id", mapping_item_key),
        ("pdf_item_id", mapping.get("pdf_item_id", "")),
        ("excel_item_id", mapping.get("excel_item_id", "")),
        ("excel_sheet", mapping.get("excel_sheet", "")),
    ]
    for source, value in item_sources:
        for candidate in [normalize_item_id(value), *extract_item_id_candidates_from_text(value)]:
            if candidate:
                candidates.append(f"{source}:{candidate}")
                if candidate in item_map:
                    return item_map[candidate], source, candidates

    for source, value in [("block_id", mapping.get("block_id", "")), ("block_csv_path", mapping.get("block_csv_path", ""))]:
        for item_candidate in extract_item_id_candidates_from_text(value):
            candidates.append(f"{source}:{item_candidate}")
            if item_candidate in item_map:
                return item_map[item_candidate], source, candidates
        for block_candidate in block_key_candidates(value):
            candidates.append(f"{source}:{block_candidate}")
            if block_candidate in block_map:
                return block_map[block_candidate], source, candidates

    return {}, "not_found", candidates


def merge_block_metadata(entry: dict):
    item_metadata = entry.get("item_metadata", [])
    found_meta = next((m for m in item_metadata if m), {})
    entry["visual_type"] = safe_str(entry.get("visual_type")) or safe_str(found_meta.get("visual_type")) or "unknown"
    entry["estimated_data_count"] = safe_str(entry.get("estimated_data_count")) or safe_str(found_meta.get("estimated_data_count"))
    entry["classified_reason"] = safe_str(entry.get("classified_reason")) or safe_str(found_meta.get("classified_reason")) or safe_str(found_meta.get("reason"))
    entry["metadata_found"] = bool(entry.get("metadata_found"))
    entry["metadata_matched_by"] = safe_str(entry.get("metadata_matched_by")) or ("item_id" if entry["metadata_found"] else "not_found")
    return entry


def print_block_metadata(entry: dict):
    item_display = ", ".join(entry.get("item_ids", []))
    if entry.get("metadata_found"):
        print(
            f"[metadata] block={entry.get('block_id')} item={item_display} "
            f"visual_type={entry.get('visual_type')} estimated_data_count={entry.get('estimated_data_count')} "
            f"matched_by={entry.get('metadata_matched_by')}"
        )
        if safe_str(entry.get("mapping_reason")):
            print(f"[metadata] mapping_reason={safe_str(entry.get('mapping_reason'))[:300]}")
        if safe_str(entry.get("classified_reason")):
            print(f"[metadata] classified_reason={safe_str(entry.get('classified_reason'))[:300]}")
    else:
        print(f"[metadata] NOT FOUND block={entry.get('block_id')} candidates={entry.get('metadata_candidates', [])[:20]}")


def upsert_group_entry(grouped: dict, block_csv_path: str, mapping_item_key: str, mapping: dict, metadata_maps: dict, use_mapping_metadata: bool = True):
    block_csv_path = safe_str(block_csv_path)
    if not is_valid_block_csv_path(block_csv_path):
        return

    default_entry = {
        **empty_block_metadata(),
        "excel_file": safe_str(mapping.get("excel_file")),
        "excel_sheet": safe_str(mapping.get("excel_sheet")),
        "block_id": safe_str(mapping.get("block_id")) or Path(block_csv_path).stem,
        "block_csv_path": block_csv_path,
        "item_ids": [],
        "item_metadata": [],
        "mapping_reason": safe_str(mapping.get("reason")),
    }
    entry = grouped.setdefault(block_csv_path, default_entry)
    for key in ["excel_file", "excel_sheet", "block_id", "block_csv_path", "mapping_reason"]:
        if not safe_str(entry.get(key)):
            entry[key] = safe_str(default_entry.get(key))

    item_candidates = [
        normalize_item_id(mapping_item_key),
        normalize_item_id(mapping.get("pdf_item_id", "")),
        normalize_item_id(mapping.get("excel_item_id", "")),
    ]
    for candidate in item_candidates:
        append_unique(entry["item_ids"], candidate)

    if use_mapping_metadata:
        metadata, matched_by, candidates = resolve_mapping_metadata(mapping_item_key, mapping, metadata_maps)
    else:
        item_map = metadata_maps.get("item_metadata_by_item_key", {})
        metadata = item_map.get(normalize_item_id(mapping_item_key), {})
        matched_by = "item_id" if metadata else "not_found"
        candidates = [normalize_item_id(mapping_item_key)]

    entry["metadata_candidates"] = list(dict.fromkeys(entry.get("metadata_candidates", []) + candidates))
    if metadata:
        append_unique(entry["item_metadata"], metadata)
        entry["metadata_found"] = True
        if safe_str(entry.get("metadata_matched_by")) in {"", "not_found"}:
            entry["metadata_matched_by"] = matched_by
        if not safe_str(entry.get("visual_type")) or entry.get("visual_type") == "unknown":
            entry["visual_type"] = safe_str(metadata.get("visual_type")) or "unknown"
        if not safe_str(entry.get("estimated_data_count")):
            entry["estimated_data_count"] = safe_str(metadata.get("estimated_data_count"))
        if not safe_str(entry.get("classified_reason")):
            entry["classified_reason"] = safe_str(metadata.get("classified_reason")) or safe_str(metadata.get("reason"))
    else:
        entry["metadata_matched_by"] = entry.get("metadata_matched_by") or "not_found"

    merge_block_metadata(entry)


def load_matched_block_groups(folder: Path, metadata_maps: dict | None = None) -> dict:
    metadata_maps = metadata_maps or {"item_metadata_by_item_key": {}, "item_metadata_by_block_key": {}}
    total_figure_mapping = load_total_figure_mapping(folder)
    pdf_candidates = find_pdf_candidates(folder)
    csv_path = find_matching_csv(folder)
    df = pd.read_csv(csv_path)
    map_path = folder / MAPPING_JSON_NAME
    excel_mapping = {}
    if map_path.exists():
        with open(map_path, "r", encoding="utf-8") as f:
            excel_mapping = json.load(f)

    grouped = {}
    if excel_mapping:
        for top_item_id, mappings in excel_mapping.items():
            mapping_list = mappings if isinstance(mappings, list) else [mappings] if isinstance(mappings, dict) else []
            for mapping in mapping_list:
                block_csv_path = safe_str(mapping.get("block_csv_path"))
                upsert_group_entry(grouped, block_csv_path, top_item_id, mapping, metadata_maps, use_mapping_metadata=True)
    else:
        cols_lower = {c.lower(): c for c in df.columns}
        item_col = cols_lower.get("item_id")
        matched_block_col = cols_lower.get("matched_block_csv_path")
        visual_type_col = cols_lower.get("visual_type")
        if item_col is None:
            raise ValueError("item_id column missing")
        if matched_block_col is None:
            print("  ! matched_block_csv_path column missing and excel_mapping.json unavailable.")
            return {}

        allowed_visual_types = {"table", "barplot", "heatmap", "chemical_structure"}
        for _, row in df.iterrows():
            item_id = normalize_item_id(row[item_col])
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
                upsert_group_entry(
                    grouped,
                    p,
                    item_id,
                    {"block_csv_path": p, "block_id": Path(p).stem, "reason": ""},
                    metadata_maps,
                    use_mapping_metadata=False,
                )

    valid_grouped = {}
    for block_csv_path, meta in grouped.items():
        if not is_valid_block_csv_path(block_csv_path):
            continue
        item_ids = [normalize_item_id(x) for x in meta.get("item_ids", []) if safe_str(x)]
        item_ids = sorted(list(set(item_ids)))
        if not item_ids:
            continue
        meta["item_ids"] = item_ids
        merge_block_metadata(meta)
        primary_item_id = item_ids[0] if item_ids else ""
        meta.update(resolve_figure_evidence(primary_item_id, meta, total_figure_mapping, pdf_candidates, folder))
        print_block_metadata(meta)
        valid_grouped[block_csv_path] = meta
    grouped = valid_grouped

    print(f"  - 실제 유효 router block 개수: {len(grouped)}")
    if grouped:
        print("  - 실제 유효 router block 목록:")
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


def build_vertex_client(api_json_name: str = API_JSON_NAME):
    api_key_path = find_api_key_file(api_json_name)
    with open(api_key_path, "r", encoding="utf-8") as f:
        cred_data = json.load(f)
    project_id = cred_data.get("project_id")
    if not project_id:
        raise ValueError(f"project_id missing: {api_key_path}")
    return get_vertexai_client(api_key_path, project=project_id)


def validate_result_df(df: pd.DataFrame, item_metadata: list[dict] | None = None, block_metadata: dict | None = None) -> bool:
    ok, _, _ = validate_extraction_df(df, item_metadata=item_metadata, block_metadata=block_metadata)
    return ok


def safe_import(module_name: str):
    __import__(module_name)
    return sys.modules[module_name]


def run_via_40(module40, df: pd.DataFrame, excel_file: str, excel_sheet: str, block_id: str, block_csv_path: str, item_ids, api_json_name: str, item_metadata=None, block_metadata=None, validation_failure_reason: str = ""):
    client = build_vertex_client(api_json_name)
    request_id = module40.make_norm_request_id(excel_file, excel_sheet, block_id, block_csv_path)
    return module40.generate_and_execute_norm_code(
        client=client,
        primary_model=PRIMARY_MODEL,
        fallback_model=FALLBACK_MODEL,
        max_retries=5,
        switch_model_at=2,
        raw_df=df.copy(),
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


def run_via_41(module41, folder: Path, df: pd.DataFrame, excel_file: str, excel_sheet: str, block_id: str, block_csv_path: str, item_ids, api_json_name: str, item_metadata=None, block_metadata=None, validation_failure_reason: str = ""):
    client = build_vertex_client(api_json_name)
    schema_dict = module41.get_dynamic_schema_from_db(Path(module41.LNPDB_CSV_PATH), ["metric_type", "formulation_id"])
    schema_json_str = json.dumps(schema_dict, indent=2, ensure_ascii=False)
    csv_text_prepared, numeric_cells_stripped = module41.prepare_csv_for_prompt(
        client, PRIMARY_MODEL, df.to_csv(index=False), stage_name=f"route41::{block_id}"
    )
    capture_dir = folder / module41.TEMP_CAPTURE_DIRNAME
    capture_dir.mkdir(parents=True, exist_ok=True)
    capture_path = capture_dir / f"{Path(excel_file).stem}__{excel_sheet}__{block_id}.png"
    module41.dataframe_to_sheet_capture(df, capture_path, title=f"{excel_file} [{excel_sheet}] [{block_id}]")
    image_part = module41.get_image_part(capture_path)
    evidence_part = None
    evidence_type = safe_str((block_metadata or {}).get("figure_evidence_type"))
    if evidence_type == "panel_image":
        panel_path = safe_str((block_metadata or {}).get("figure_panel_image_path"))
        if panel_path and Path(panel_path).exists():
            evidence_part = module41.get_file_part(Path(panel_path))
    elif evidence_type == "pdf":
        pdf_path = safe_str((block_metadata or {}).get("figure_pdf_path"))
        if pdf_path and Path(pdf_path).exists() and hasattr(module41, "get_file_part"):
            evidence_part = module41.get_file_part(Path(pdf_path))
    request_id = module41.make_direct_block_request_id(excel_file, excel_sheet, block_id, block_csv_path)
    response_text = module41.call_direct_llm_for_block(
        client=client,
        primary_model=PRIMARY_MODEL,
        fallback_model=FALLBACK_MODEL,
        image_part=image_part,
        evidence_part=evidence_part,
        excel_file=excel_file,
        excel_sheet=excel_sheet,
        block_id=block_id,
        block_csv_path=block_csv_path,
        item_ids=item_ids,
        csv_text=csv_text_prepared,
        numeric_cells_stripped=numeric_cells_stripped,
        schema_json_str=schema_json_str,
        request_id=request_id,
        item_metadata=item_metadata or [],
        block_metadata=block_metadata or {},
        validation_failure_reason=validation_failure_reason,
    )
    return module41.parse_direct_llm_payload(
        response_text,
        request_id,
        item_metadata=item_metadata or [],
        block_metadata=block_metadata or {},
        item_ids=item_ids,
        matched_sheet_file=f"{excel_file} [{excel_sheet}] [{block_id}]",
    )


def save_outputs(folder: Path, result_df: pd.DataFrame, routing_log_df: pd.DataFrame):
    final_csv_path = folder / FINAL_OUTPUT_CSV_NAME
    final_xlsx_path = folder / FINAL_OUTPUT_CSV_NAME.replace(".csv", ".xlsx")
    routing_csv_path = folder / ROUTING_LOG_CSV_NAME
    result_df = ensure_output_schema(result_df)
    result_df.to_csv(final_csv_path, index=False, encoding="utf-8-sig")
    result_df.to_excel(final_xlsx_path, index=False)
    routing_log_df.to_csv(routing_csv_path, index=False, encoding="utf-8-sig")
    print(f"[router] saved final: {final_csv_path}")
    print(f"[router] saved final xlsx: {final_xlsx_path}")
    print(f"[router] saved log: {routing_csv_path}")


def safe_filename_part(value) -> str:
    text = safe_str(value) or "unknown"
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", text).strip("_") or "unknown"


def save_invalid_result_debug(
    folder: Path,
    result_df: pd.DataFrame,
    block_metadata: dict,
    item_ids,
    route: str,
    attempt,
    validation_reason: str,
) -> str:
    result_df = ensure_output_schema(result_df)
    diagnostics = build_count_diagnostics(result_df, item_metadata=block_metadata.get("item_metadata", []), block_metadata=block_metadata)
    debug_dir = folder / "Exp_Val" / "_debug_invalid_results"
    debug_dir.mkdir(parents=True, exist_ok=True)
    block_id = safe_str(block_metadata.get("block_id")) or "block"
    attempt_suffix = f"_{safe_filename_part(f'attempt{attempt}')}" if attempt not in {"", None} else ""
    out_path = debug_dir / f"invalid__{safe_filename_part(block_id)}__{safe_filename_part(route)}{attempt_suffix}.csv"
    debug_df = result_df.copy()
    debug_columns = {
        "debug_block_id": block_id,
        "debug_item_ids": ", ".join(item_ids or []),
        "debug_route": route,
        "debug_attempt": attempt,
        "debug_validation_reason": validation_reason,
        "debug_validation_warning": diagnostics["validation_warning"],
        "debug_expected_data_count": diagnostics["expected_data_count"],
        "debug_actual_row_count": diagnostics["actual_row_count"],
        "debug_expanded_original_values_count": diagnostics["expanded_original_values_count"],
        "debug_max_original_values_count": diagnostics["max_original_values_count"],
        "debug_semicolon_packed_rows_count": diagnostics["semicolon_packed_rows_count"],
        "debug_figure_evidence_type": safe_str(block_metadata.get("figure_evidence_type")),
        "debug_figure_mapping_status": safe_str(block_metadata.get("figure_mapping_status")),
    }
    for col, value in reversed(list(debug_columns.items())):
        debug_df.insert(0, col, value)
    debug_df.to_csv(out_path, index=False, encoding="utf-8-sig")
    return str(out_path)


def run_router_sync_mode(
    folder: Path,
    block_groups: dict,
    module40,
    module41,
    skip_large_sheets: bool,
    api_json_name: str,
):
    individual_out_dir = folder / INDIVIDUAL_OUTPUT_DIRNAME
    individual_out_dir.mkdir(parents=True, exist_ok=True)

    all_frames = []
    routing_logs = []
    validation_summary_rows = []
    failure_rows = []

    for idx, (block_csv_path, meta) in enumerate(block_groups.items(), 1):
        excel_file = safe_str(meta.get("excel_file"))
        excel_sheet = safe_str(meta.get("excel_sheet"))
        block_id = safe_str(meta.get("block_id")) or Path(block_csv_path).stem
        item_ids = meta.get("item_ids", [])
        item_metadata = meta.get("item_metadata", [])
        block_metadata = {
            **empty_block_metadata(),
            **{k: v for k, v in meta.items() if k not in {"item_ids", "item_metadata"}},
        }
        dominant_meta = dominant_metadata(item_metadata)
        matched_sheet_file = f"{excel_file} [{excel_sheet}] [{block_id}]"
        item_ids_str = ", ".join(item_ids)
        norm_request_id = module40.make_norm_request_id(excel_file, excel_sheet, block_id, block_csv_path)
        direct_request_id = module41.make_direct_block_request_id(excel_file, excel_sheet, block_id, block_csv_path)

        used_route = ""
        status = "failed"
        error_msg = ""
        validation_failure_reason = ""
        validation_warning = ""
        invalid_result_debug_path = ""
        last_validation_diagnostics = {}
        last_invalid_result_df = pd.DataFrame(columns=REQUIRED_COLS)
        route40_failure = ""
        route41_failure = ""
        fallback_used = False
        route_reason = "40 first, then 41 fallback for the same block only"
        route_confidence = "high"

        print(f"[{idx}/{len(block_groups)}] {matched_sheet_file}")
        print_figure_evidence(meta)

        try:
            df = load_block_df(folder, block_csv_path, excel_file, excel_sheet)
            if skip_large_sheets and len(df) > 5000:
                status = "skipped"
                error_msg = "too large"
                raise RuntimeError("too large")

            last_exception = None
            for attempt_40 in range(1, 6):
                try:
                    success, result_df, err, _ = run_via_40(
                        module40,
                        df,
                        excel_file,
                        excel_sheet,
                        block_id,
                        block_csv_path,
                        item_ids,
                        api_json_name,
                        item_metadata=item_metadata,
                        block_metadata=block_metadata,
                        validation_failure_reason=validation_failure_reason,
                    )
                    ok, reason, result_df = validate_extraction_df(result_df, item_metadata=item_metadata, block_metadata=block_metadata)
                    diagnostics = build_count_diagnostics(result_df, item_metadata=item_metadata, block_metadata=block_metadata)
                    last_validation_diagnostics = diagnostics
                    validation_warning = diagnostics["validation_warning"]
                    if success and ok:
                        used_route = "40"
                        status = "success"
                        fallback_used = attempt_40 > 1
                        all_frames.append(result_df)
                        validation_failure_reason = ""
                        if validation_warning:
                            print(f"  ! route40 valid with warning: {validation_warning}")
                        validation_summary_rows.append(
                            build_validation_summary_row(result_df, item_metadata, "success", "ok", "40", block_metadata=block_metadata, matched_sheet_file=matched_sheet_file, pipeline_status=status)
                        )
                        break
                    if success and is_usable_result_df(result_df):
                        used_route = "40"
                        status = "warning_success"
                        fallback_used = attempt_40 > 1
                        validation_failure_reason = ""
                        all_frames.append(result_df)
                        print(f"  [validation warning] route40 result accepted: {reason}")
                        if validation_warning:
                            print(f"  ! route40 diagnostic warning: {validation_warning}")
                        validation_summary_rows.append(
                            build_validation_summary_row(result_df, item_metadata, "warning", reason, "40", block_metadata=block_metadata, matched_sheet_file=matched_sheet_file, pipeline_status=status)
                        )
                        break
                    validation_failure_reason = reason
                    last_invalid_result_df = result_df.copy()
                    invalid_result_debug_path = save_invalid_result_debug(
                        folder,
                        result_df,
                        block_metadata,
                        item_ids,
                        "route40",
                        attempt_40,
                        reason,
                    )
                    raise RuntimeError(err or reason or "empty result")
                except Exception as route_exc:
                    last_exception = route_exc
                    route40_failure = str(route_exc)
                    print(f"  ! route40 failed ({attempt_40}/5): {route_exc}")

            if status not in {"success", "warning_success"}:
                try:
                    result_df = run_via_41(
                        module41,
                        folder,
                        df,
                        excel_file,
                        excel_sheet,
                        block_id,
                        block_csv_path,
                        item_ids,
                        api_json_name,
                        item_metadata=item_metadata,
                        block_metadata=block_metadata,
                        validation_failure_reason=validation_failure_reason,
                    )
                except Exception as route41_exc:
                    route41_failure = str(route41_exc)
                    raise
                ok, reason, result_df = validate_extraction_df(result_df, item_metadata=item_metadata, block_metadata=block_metadata)
                diagnostics = build_count_diagnostics(result_df, item_metadata=item_metadata, block_metadata=block_metadata)
                last_validation_diagnostics = diagnostics
                validation_warning = diagnostics["validation_warning"]
                if ok:
                    used_route = "41"
                    status = "success"
                    fallback_used = True
                    all_frames.append(result_df)
                    if validation_warning:
                        print(f"  ! route41 valid with warning: {validation_warning}")
                    validation_summary_rows.append(
                        build_validation_summary_row(result_df, item_metadata, "success", "ok", "41", block_metadata=block_metadata, matched_sheet_file=matched_sheet_file, pipeline_status=status)
                    )
                elif is_usable_result_df(result_df):
                    used_route = "41"
                    status = "warning_success"
                    fallback_used = True
                    validation_failure_reason = reason
                    all_frames.append(result_df)
                    print(f"  [validation warning] route41 result accepted: {reason}")
                    if validation_warning:
                        print(f"  ! route41 diagnostic warning: {validation_warning}")
                    validation_summary_rows.append(
                        build_validation_summary_row(result_df, item_metadata, "warning", reason, "41", block_metadata=block_metadata, matched_sheet_file=matched_sheet_file, pipeline_status=status)
                    )
                else:
                    validation_failure_reason = reason
                    route41_failure = reason
                    last_invalid_result_df = result_df.copy()
                    invalid_result_debug_path = save_invalid_result_debug(
                        folder,
                        result_df,
                        block_metadata,
                        item_ids,
                        "route41",
                        "",
                        reason,
                    )
                    raise RuntimeError(f"route41 invalid result after route40 failure: {reason}; route40={last_exception}")

            if status in {"success", "warning_success"}:
                safe_excel_name = Path(excel_file).stem
                safe_sheet_name = "".join(c for c in excel_sheet if c.isalnum() or c in (" ", "_", "-")).strip()
                safe_block_id = "".join(c for c in block_id if c.isalnum() or c in (" ", "_", "-")).strip()
                individual_csv_name = f"{safe_excel_name}__{safe_sheet_name}__{safe_block_id}.csv"
                all_frames[-1].to_csv(individual_out_dir / individual_csv_name, index=False, encoding="utf-8-sig")

        except Exception as e:
            if status != "skipped":
                error_msg = str(e)
                validation_failure_reason = validation_failure_reason or error_msg
            print(f"  ! final failure: {e}")
            traceback.print_exc()
            failure_diagnostics = last_validation_diagnostics or build_count_diagnostics(pd.DataFrame(columns=REQUIRED_COLS), item_metadata=item_metadata, block_metadata=block_metadata)
            failure_rows.append(
                {
                    "item_id": safe_str(dominant_meta.get("item_id")) or item_ids_str,
                    "excel_file": excel_file,
                    "excel_sheet": excel_sheet,
                    "block_id": block_id,
                    "block_csv_path": block_csv_path,
                    "visual_type": safe_str(block_metadata.get("visual_type")) or safe_str(dominant_meta.get("visual_type")),
                    "estimated_data_count": safe_str(block_metadata.get("estimated_data_count")) or safe_str(dominant_meta.get("estimated_data_count")),
                    "metadata_found": bool(block_metadata.get("metadata_found", False)),
                    "metadata_matched_by": safe_str(block_metadata.get("metadata_matched_by")),
                    "mapping_reason": safe_str(block_metadata.get("mapping_reason")),
                    "classified_reason": safe_str(block_metadata.get("classified_reason")) or safe_str(dominant_meta.get("classified_reason")) or safe_str(dominant_meta.get("reason")),
                    "figure_evidence_type": safe_str(block_metadata.get("figure_evidence_type")),
                    "figure_mapping_status": safe_str(block_metadata.get("figure_mapping_status")),
                    "panel_image_found": bool(block_metadata.get("panel_image_found", False)),
                    "used_pdf_fallback": bool(block_metadata.get("used_pdf_fallback", False)),
                    "figure_panel_image_path": safe_str(block_metadata.get("figure_panel_image_path")),
                    "figure_full_image_path": safe_str(block_metadata.get("figure_full_image_path")),
                    "figure_pdf_path": safe_str(block_metadata.get("figure_pdf_path")),
                    "pdf_candidate_count": safe_str(block_metadata.get("pdf_candidate_count")),
                    "pdf_candidates": safe_str(block_metadata.get("pdf_candidates")),
                    "route40_failure": route40_failure,
                    "route41_failure": route41_failure,
                    "final_failure_reason": validation_failure_reason or error_msg,
                    "validation_status": "failed" if status != "skipped" else "skipped",
                    "validation_reason": validation_failure_reason or error_msg,
                    "route_used": used_route or "40_then_41",
                    "status": status,
                    "expected_data_count": failure_diagnostics["expected_data_count"],
                    "actual_row_count": failure_diagnostics["actual_row_count"],
                    "expanded_original_values_count": failure_diagnostics["expanded_original_values_count"],
                    "max_original_values_count": failure_diagnostics["max_original_values_count"],
                    "semicolon_packed_rows_count": failure_diagnostics["semicolon_packed_rows_count"],
                    "has_semicolon_packed_values": failure_diagnostics["has_semicolon_packed_values"],
                    "count_validation_status": failure_diagnostics["count_validation_status"],
                    "validation_warning": validation_warning or failure_diagnostics["validation_warning"],
                    "invalid_result_debug_path": invalid_result_debug_path,
                }
            )
            validation_summary_rows.append(
                build_validation_summary_row(
                    last_invalid_result_df,
                    item_metadata,
                    "failed" if status != "skipped" else "skipped",
                    validation_failure_reason or error_msg,
                    used_route or "40_then_41",
                    block_metadata=block_metadata,
                    matched_sheet_file=matched_sheet_file,
                )
            )

        routing_logs.append(
            {
                "Matched_Sheet_File": matched_sheet_file,
                "Item_IDs": item_ids_str,
                "Norm_Request_ID": norm_request_id,
                "Direct_Request_ID": direct_request_id,
                "Recommended_Route": "40_then_41",
                "Used_Route": used_route,
                "Fallback_Used": fallback_used,
                "Route_Reason": route_reason,
                "Route_Confidence": route_confidence,
                "Status": status,
                "status": status,
                "Error": error_msg,
                "validation_status": "warning" if status == "warning_success" else "success" if status == "success" else status,
                "validation_reason": validation_failure_reason or ("ok" if status == "success" else error_msg),
                "route_used": used_route,
                "visual_type": safe_str(block_metadata.get("visual_type")) or safe_str(dominant_meta.get("visual_type")),
                "estimated_data_count": safe_str(block_metadata.get("estimated_data_count")) or safe_str(dominant_meta.get("estimated_data_count")),
                "classification_reason": safe_str(dominant_meta.get("reason")),
                "Validation_Failure_Reason": validation_failure_reason,
                "metadata_found": bool(block_metadata.get("metadata_found", False)),
                "metadata_matched_by": safe_str(block_metadata.get("metadata_matched_by")),
                "mapping_reason": safe_str(block_metadata.get("mapping_reason")),
                "classified_reason": safe_str(block_metadata.get("classified_reason")),
                "figure_evidence_type": safe_str(block_metadata.get("figure_evidence_type")),
                "figure_mapping_status": safe_str(block_metadata.get("figure_mapping_status")),
                "panel_image_found": bool(block_metadata.get("panel_image_found", False)),
                "used_pdf_fallback": bool(block_metadata.get("used_pdf_fallback", False)),
                "figure_panel_image_path": safe_str(block_metadata.get("figure_panel_image_path")),
                "figure_full_image_path": safe_str(block_metadata.get("figure_full_image_path")),
                "figure_pdf_path": safe_str(block_metadata.get("figure_pdf_path")),
                "pdf_candidate_count": safe_str(block_metadata.get("pdf_candidate_count")),
                "pdf_candidates": safe_str(block_metadata.get("pdf_candidates")),
            }
        )
        time.sleep(2)

    result_df = ensure_output_schema(pd.concat(all_frames, ignore_index=True) if all_frames else pd.DataFrame(columns=REQUIRED_COLS))
    summary_df = pd.DataFrame(validation_summary_rows)
    failure_df = pd.DataFrame(failure_rows)
    summary_df.to_csv(folder / VALIDATION_SUMMARY_CSV_NAME, index=False, encoding="utf-8-sig")
    failure_df.to_csv(folder / FAILURE_LOG_CSV_NAME, index=False, encoding="utf-8-sig")
    return result_df, pd.DataFrame(routing_logs)


def run_router_batch_mode(
    folder: Path,
    module40,
    api_json_name: str,
):
    # Module 40 performs request_id-based results_map matching, so batch response order is irrelevant.
    print("[router] batch mode: delegate primary execution to 40 batch pipeline")
    print("[router] batch mode: request_id-based matching keeps batch input/output order-independent")
    module40.extract_exp_vals_main(
        paper_folder_str=str(folder),
        primary_model=PRIMARY_MODEL,
        fallback_model=FALLBACK_MODEL,
        max_retries=3,
        switch_model_at=2,
        api_json_name=api_json_name,
        execution_mode="batch",
    )

    output_xlsx = folder / f"4_{folder.name}_standardized_exp_data.xlsx"
    if output_xlsx.exists():
        try:
            result_df = ensure_output_schema(pd.read_excel(output_xlsx).fillna(""))
        except Exception:
            result_df = pd.DataFrame(columns=REQUIRED_COLS)
    else:
        result_df = pd.DataFrame(columns=REQUIRED_COLS)

    summary_row = build_validation_summary_row(
        result_df,
        [],
        "success" if not result_df.empty else "empty",
        "batch_delegated_to_module40",
        "40_batch",
    )
    pd.DataFrame([summary_row]).to_csv(folder / VALIDATION_SUMMARY_CSV_NAME, index=False, encoding="utf-8-sig")
    pd.DataFrame().to_csv(folder / FAILURE_LOG_CSV_NAME, index=False, encoding="utf-8-sig")

    routing_log_df = pd.DataFrame([
        {
            "Matched_Sheet_File": "",
            "Item_IDs": "",
            "Norm_Request_ID": "",
            "Direct_Request_ID": "",
            "Recommended_Route": "40_batch_only",
            "Used_Route": "40_batch",
            "Fallback_Used": False,
            "Route_Reason": "execution_mode=batch -> delegated to module40 batch entry with request_id-based matching",
            "Route_Confidence": "high",
            "Status": "success" if not result_df.empty else "empty",
            "Error": "",
        }
    ])

    return result_df, routing_log_df


def extract_exp_vals_with_router(
        folder_path: str,
        skip_large_sheets:
        bool = True,
        api_json_name:
        str = API_JSON_NAME,
        execution_mode: str = "sync",
        classification_csv_path=None,
    ):

    execution_mode = str(execution_mode).strip().lower()
    if execution_mode not in {"sync", "batch"}:
        raise ValueError(f"invalid execution_mode: {execution_mode}")

    folder = Path(folder_path)
    if not folder.exists():
        raise FileNotFoundError(f"folder not found: {folder}")

    module40 = safe_import("40_Extract_Exp_Vals_Norm")
    module41 = safe_import("41_Extract_Exp_Vals_DirectLLM")
    metadata_maps = load_item_metadata(folder, classification_csv_path=classification_csv_path)
    block_groups = load_matched_block_groups(folder, metadata_maps=metadata_maps)
    if not block_groups:
        save_outputs(folder, pd.DataFrame(columns=REQUIRED_COLS), pd.DataFrame())
        pd.DataFrame().to_csv(folder / VALIDATION_SUMMARY_CSV_NAME, index=False, encoding="utf-8-sig")
        pd.DataFrame().to_csv(folder / FAILURE_LOG_CSV_NAME, index=False, encoding="utf-8-sig")
        return

    individual_out_dir = folder / INDIVIDUAL_OUTPUT_DIRNAME
    individual_out_dir.mkdir(parents=True, exist_ok=True)

    if execution_mode == "sync":
        result_df, routing_log_df = run_router_sync_mode(
            folder=folder,
            block_groups=block_groups,
            module40=module40,
            module41=module41,
            skip_large_sheets=skip_large_sheets,
            api_json_name=api_json_name,
        )
    else:
        print("[router] execution_mode=batch requested, but enhanced validation/fallback requires per-block routing; using validated sync routing.")
        result_df, routing_log_df = run_router_sync_mode(
            folder=folder,
            block_groups=block_groups,
            module40=module40,
            module41=module41,
            skip_large_sheets=skip_large_sheets,
            api_json_name=api_json_name,
        )

    save_outputs(folder, result_df, routing_log_df)


def main(api_json_name: str = API_JSON_NAME):
    target_folder = r"/Users/kogeon/Google Drive/내 드라이브/LNPDB_new/ZT_2026"
    execution_mode = "batch"
    extract_exp_vals_with_router(
        target_folder,
        api_json_name=api_json_name,
        execution_mode=execution_mode,
    )


if __name__ == "__main__":
    main(API_JSON_NAME)
