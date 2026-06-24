from __future__ import annotations

import argparse
import csv
import json
import math
import os
import re
import subprocess
import sys
import tempfile
import traceback
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib import request, error


try:
    import pandas as pd
except Exception as exc:  # pragma: no cover - dependency check at runtime
    pd = None
    PANDAS_IMPORT_ERROR = str(exc)
else:
    PANDAS_IMPORT_ERROR = None


PROJECT_ROOT = Path(__file__).resolve().parent
WORKSPACE = PROJECT_ROOT / "expval_merge_workspace"
DEFAULT_CONFIG = WORKSPACE / "merge_manifest.json"
STATE_PATH = WORKSPACE / "merge_state.json"
LOG_DIR = WORKSPACE / "logs"

SUPPORTED_EXTENSIONS = {".csv", ".xlsx", ".xlsm", ".xls"}
EXCEL_EXTENSIONS = {".xlsx", ".xlsm", ".xls"}

STAGE_ORDER = [
    "00_observe_inputs",
    "01_build_figure_table_key_map",
    "02_normalize_expvals",
    "03_normalize_lnpdb",
    "04_build_match_candidates",
    "05_merge_values",
    "06_validate_merge",
]

EXPVAL_COLUMNS = [
    "expval_id",
    "source_file",
    "source_sheet",
    "paper_key",
    "figure_key",
    "partition_key",
    "source_row",
    "source_table_type",
    "figure_name",
    "item_id",
    "panel_id",
    "box_id",
    "x_label",
    "group_label",
    "row_label",
    "col_label",
    "metric_type",
    "value",
    "value_text",
    "unit",
    "x_pixel",
    "y_pixel",
    "x_center",
    "y_center",
    "cell_rgb",
    "cell_hex",
    "color_distance",
    "raw_columns_json",
    "manual_required",
    "normalization_warning",
]

LNPDB_CANONICAL_COLUMNS = [
    "lnpdb_row_id",
    "source_file",
    "source_sheet",
    "paper_key",
    "figure_key",
    "partition_key",
    "source_row",
    "paper_id",
    "doi",
    "item_id",
    "figure_name",
    "panel_id",
    "metric_type",
    "formulation_id",
    "formulation_name",
    "group_label",
    "condition_text",
    "existing_value_text",
    "existing_unit",
    "raw_columns_json",
]

MERGE_PROVENANCE_COLUMNS = [
    "lnpdb_row_id",
    "merged_experimental_value",
    "expval_source_file",
    "expval_source_sheet",
    "expval_source_row",
    "expval_source_table_type",
    "expval_value_column",
    "expval_value_text",
    "expval_x_pixel",
    "expval_y_pixel",
    "expval_x_center",
    "expval_y_center",
    "expval_match_score",
    "expval_match_confidence",
    "expval_match_reason",
    "expval_manual_required",
]

EXPERIMENTAL_VALUE_COLUMN = "experimental_value"
EXPVAL_VALUE_COLUMNS = ["Value", "value", "extracted_value", "matched_value"]
UNIT_COLUMNS = ["unit", "Unit", "units", "Units"]
FIGURE_TABLE_KEY_MAP_COLUMNS = [
    "role",
    "source_file",
    "source_sheet",
    "row_count",
    "inferred_key",
    "confidence",
    "method",
    "evidence",
    "raw_llm_response",
    "prompt_json",
    "needs_review",
    "review_reason",
]


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def require_pandas() -> None:
    if pd is None:
        raise RuntimeError(f"pandas is required for this runner: {PANDAS_IMPORT_ERROR}")


def load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2, default=str)
        f.write("\n")


def append_log(event: dict[str, Any]) -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_path = LOG_DIR / "expval_merge.jsonl"
    record = {"timestamp": utc_now(), **event}
    with log_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")


def update_state(stage: str | None, status: str, detail: dict[str, Any] | None = None) -> None:
    state = load_json(
        STATE_PATH,
        {
            "schema_version": 1,
            "project": "LNPDB_expval_lnpdb_like_merge",
            "mode": "local_cli_with_optional_llm_key_map",
            "stage_status": {},
        },
    )
    state["last_updated"] = utc_now()
    if stage:
        state.setdefault("stage_status", {})[stage] = {
            "status": status,
            "updated": utc_now(),
            "detail": detail or {},
        }
    state["last_event"] = {"stage": stage, "status": status, "detail": detail or {}}
    write_json(STATE_PATH, state)


def load_config(path: str | Path | None = None) -> dict[str, Any]:
    config_path = Path(path) if path else DEFAULT_CONFIG
    config = load_json(config_path, {})
    if not config:
        raise FileNotFoundError(f"Config not found or empty: {config_path}")
    config["_config_path"] = str(config_path)
    return config


def resolve_roots(values: list[str] | None, config_values: Any) -> list[Path]:
    roots = values if values else config_values
    if isinstance(roots, str):
        roots = [roots]
    return [Path(x) for x in (roots or [])]


def output_root_from_args(args: argparse.Namespace, config: dict[str, Any]) -> Path:
    return Path(args.output_root or config.get("default_output_root") or (WORKSPACE / "outputs"))


def llm_provider_from_args(args: argparse.Namespace, config: dict[str, Any]) -> str:
    value = getattr(args, "llm_provider", None) or config.get("llm_provider") or os.environ.get("EXPVAL_MERGE_LLM_PROVIDER") or "none"
    return normalize_text(value) or "none"


def llm_model_from_args(args: argparse.Namespace, config: dict[str, Any]) -> str:
    return (
        getattr(args, "llm_model", None)
        or config.get("llm_model")
        or os.environ.get("EXPVAL_MERGE_LLM_MODEL")
        or ""
    )


def normalize_text(value: Any) -> str:
    if value is None:
        return ""
    try:
        if pd is not None and pd.isna(value):
            return ""
    except Exception:
        pass
    text = str(value).strip().lower()
    text = text.replace("\u2212", "-").replace("\u00d7", "x")
    text = re.sub(r"\bsuppl(?:ementary)?\.?\s*(?:fig\.?|figure)\b", "supplementary figure", text)
    text = re.sub(r"\bsuppl(?:ementary)?\.?\s*(?:tbl\.?|table)\b", "supplementary table", text)
    text = re.sub(r"\bfig\.", "figure", text)
    text = re.sub(r"[_\-]+", " ", text)
    text = re.sub(r"[^\w\s.+/%()^-]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def compact_key(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "", normalize_text(value))


def infer_item_id(*values: Any) -> str:
    joined = " ".join(str(v) for v in values if v is not None)
    text = normalize_text(joined)
    match = re.search(r"(supplementary figure|supplementary table|figure|table)\s*([s]?[0-9]{1,3}[a-z]?)\b", text)
    if match:
        raw_prefix = match.group(1)
        if raw_prefix.startswith("supplementary"):
            prefix = "supplementary table" if "table" in raw_prefix else "supplementary figure"
        else:
            prefix = "table" if raw_prefix == "table" else "figure"
        return format_item_key(prefix, match.group(2))
    match = re.search(r"\b(fig(?:ure)?|table)\s*([s]?[0-9]{1,3}[a-z]?)\b", text)
    if match:
        prefix = "table" if match.group(1) == "table" else "figure"
        return format_item_key(prefix, match.group(2))
    match = re.search(r"\bsupp(?:lementary)?\s*(?:fig(?:ure)?|table)?\s*([s]?[0-9]{1,3}[a-z]?)\b", text)
    if match:
        return format_item_key("supplementary figure", match.group(1))
    match = re.search(r"\b(?:fg|fig|figure)?\s*s\s*([0-9]{1,3})([a-z]?)(?![0-9])", text)
    if match:
        return format_item_key("supplementary figure", f"{match.group(1)}{match.group(2) or ''}")
    match = re.search(r"\b(?:tbl|table)\s*s?\s*([0-9]{1,3})([a-z]?)(?![0-9])", text)
    if match:
        return format_item_key("supplementary table", f"{match.group(1)}{match.group(2) or ''}")
    return ""


def infer_panel_id(*values: Any) -> str:
    item = infer_item_id(*values)
    match = re.search(r"([0-9]+)([a-z])$", item)
    return match.group(2) if match else ""


def format_item_key(prefix: str, raw_id: str) -> str:
    item_id = normalize_text(raw_id).replace(" ", "")
    is_supplementary = prefix.startswith("supplementary") or item_id.startswith("s")
    if item_id.startswith("s"):
        item_id = item_id[1:]
    kind = "table" if "table" in prefix else "figure"
    label = f"supplementary {kind}" if is_supplementary else kind
    return f"{label} {item_id}".strip()


def infer_figure_key(*values: Any) -> str:
    return infer_item_id(*values)


def make_partition_key(figure_key: str) -> str:
    return figure_key or "unknown_figure_table"


def safe_path_component(value: Any) -> str:
    text = normalize_text(value) or "unknown"
    text = re.sub(r"[^a-z0-9]+", "_", text).strip("_")
    return text[:120] or "unknown"


def find_column(columns: list[str], candidates: list[str]) -> str | None:
    by_compact = {compact_key(c): c for c in columns}
    for candidate in candidates:
        hit = by_compact.get(compact_key(candidate))
        if hit:
            return hit
    for col in columns:
        col_key = compact_key(col)
        for candidate in candidates:
            if compact_key(candidate) and compact_key(candidate) in col_key:
                return col
    return None


def find_exact_column(columns: list[str], column_name: str) -> str | None:
    target = compact_key(column_name)
    for col in columns:
        if compact_key(col) == target:
            return col
    return None


def text_from_row(row: dict[str, Any], columns: list[str]) -> str:
    values = []
    for col in columns:
        if col in row and str(row.get(col, "")).strip():
            values.append(str(row.get(col)))
    return " | ".join(values)


def text_from_columns(columns: list[str]) -> str:
    return " | ".join(str(col) for col in columns if str(col).strip())


def text_from_row_except(row: dict[str, Any], columns: list[str], excluded_columns: set[str] | None = None) -> str:
    excluded = {compact_key(c) for c in (excluded_columns or set())}
    values = []
    for col in columns:
        if compact_key(col) in excluded:
            continue
        value = safe_cell(row.get(col))
        if value.strip():
            values.append(value)
    return " | ".join(values)


def raw_json_context(row: dict[str, Any], excluded_columns: set[str] | None = None) -> str:
    raw_text = row.get("raw_columns_json", "")
    if not raw_text:
        return ""
    try:
        raw = json.loads(raw_text)
    except Exception:
        return safe_cell(raw_text)
    return text_from_row_except(raw, list(raw.keys()), excluded_columns)


def meaningful_match_text(value: Any) -> str:
    text = normalize_text(value)
    if not text:
        return ""
    if len(compact_key(text)) < 2:
        return ""
    return text


def safe_cell(value: Any) -> str:
    if value is None:
        return ""
    try:
        if pd is not None and pd.isna(value):
            return ""
    except Exception:
        pass
    return str(value)


def to_number_or_blank(value: Any) -> Any:
    text = safe_cell(value).strip()
    if not text:
        return ""
    text2 = text.replace(",", "").replace("\u2212", "-")
    try:
        num = float(text2)
    except Exception:
        return ""
    if math.isfinite(num):
        return num
    return ""


def numbers_equivalent(a: Any, b: Any, tolerance: float = 1e-9) -> bool:
    ta = safe_cell(a).strip()
    tb = safe_cell(b).strip()
    if not ta and not tb:
        return True
    if ta == tb:
        return True
    na = to_number_or_blank(ta)
    nb = to_number_or_blank(tb)
    if na == "" or nb == "":
        return False
    return abs(float(na) - float(nb)) <= tolerance


def iter_candidate_files(roots: list[Path], exclude_roots: list[Path] | None = None) -> list[Path]:
    exclude_resolved = []
    for root in exclude_roots or []:
        try:
            exclude_resolved.append(root.resolve())
        except Exception:
            pass
    files: list[Path] = []
    seen: set[str] = set()
    for root in roots:
        if root.is_file() and root.suffix.lower() in SUPPORTED_EXTENSIONS:
            candidates = [root]
        elif root.is_dir():
            candidates = [p for p in root.rglob("*") if p.is_file() and p.suffix.lower() in SUPPORTED_EXTENSIONS]
        else:
            candidates = []
        for path in candidates:
            try:
                resolved = path.resolve()
            except Exception:
                resolved = path.absolute()
            if any(str(resolved).lower().startswith(str(ex).lower()) for ex in exclude_resolved):
                continue
            key = str(resolved).lower()
            if key in seen:
                continue
            seen.add(key)
            files.append(path)
    return sorted(files, key=lambda p: str(p).lower())


def read_csv_flexible(path: Path) -> Any:
    require_pandas()
    try:
        return pd.read_csv(path, dtype=str, encoding="utf-8-sig")
    except pd.errors.EmptyDataError:
        return pd.DataFrame()
    except UnicodeDecodeError:
        try:
            return pd.read_csv(path, dtype=str, encoding="cp949")
        except pd.errors.EmptyDataError:
            return pd.DataFrame()


def read_table_file(path: Path) -> list[tuple[str, Any]]:
    require_pandas()
    if path.suffix.lower() == ".csv":
        return [("csv", read_csv_flexible(path))]
    xls = pd.ExcelFile(path)
    return [(sheet, pd.read_excel(path, sheet_name=sheet, dtype=str)) for sheet in xls.sheet_names]


def write_csv(path: Path, rows: list[dict[str, Any]], columns: list[str] | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if columns is None:
        columns = []
        seen = set()
        for row in rows:
            for key in row.keys():
                if key not in seen:
                    columns.append(key)
                    seen.add(key)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def dataframe_to_records(df: Any) -> list[dict[str, Any]]:
    df = df.fillna("")
    return [{str(k): safe_cell(v) for k, v in row.items()} for row in df.to_dict(orient="records")]


def compact_sample_value(value: Any, max_len: int = 160) -> str:
    text = safe_cell(value).replace("\r", " ").replace("\n", " ")
    text = re.sub(r"\s+", " ", text).strip()
    return text[:max_len]


def sample_unique_values(records: list[dict[str, Any]], columns: list[str], limit_per_column: int = 8) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for col in columns:
        seen: list[str] = []
        seen_keys: set[str] = set()
        for row in records:
            value = compact_sample_value(row.get(col))
            key = normalize_text(value)
            if not key or key in seen_keys:
                continue
            seen.append(value)
            seen_keys.add(key)
            if len(seen) >= limit_per_column:
                break
        if seen:
            out[col] = seen
    return out


def build_sheet_context(role: str, source_file: Path, source_sheet: str, df: Any, sample_rows: int = 8) -> dict[str, Any]:
    records = dataframe_to_records(df)
    columns = list(records[0].keys()) if records else [str(c) for c in getattr(df, "columns", [])]
    sample = []
    for row in records[:sample_rows]:
        sample.append({col: compact_sample_value(row.get(col)) for col in columns[:40]})
    context_text = " ".join(
        [
            str(source_file),
            source_file.name,
            source_file.stem,
            source_sheet,
            text_from_columns(columns),
            text_from_row(records[0], columns) if records else "",
        ]
    )
    heuristic_key = infer_figure_key(context_text)
    return {
        "role": role,
        "source_file": str(source_file),
        "source_sheet": source_sheet,
        "row_count": len(records),
        "columns": columns,
        "sample_rows": sample,
        "unique_values": sample_unique_values(records[:200], columns[:40]),
        "heuristic_key": heuristic_key,
    }


def figure_table_prompt(context: dict[str, Any]) -> dict[str, Any]:
    return {
        "task": "Infer the single figure/table key for this extracted-value or LNPDB-like table block.",
        "rules": [
            "Return one canonical key such as 'figure 2b', 'supplementary figure 12a', 'table 1', or 'supplementary table 3'.",
            "Use file path, file name, sheet name, column names, sample rows, and unique values.",
            "If there are multiple figures/tables or there is no reliable evidence, set inferred_key to an empty string and needs_review to true.",
            "Do not use paper title, DOI, or author names as the key.",
            "Output JSON only.",
        ],
        "output_schema": {
            "inferred_key": "string",
            "confidence": "high|medium|low|none",
            "evidence": "short reason",
            "needs_review": "boolean",
            "review_reason": "string",
        },
        "context": context,
    }


def parse_llm_key_response(text: str) -> dict[str, Any]:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?", "", cleaned).strip()
        cleaned = re.sub(r"```$", "", cleaned).strip()
    try:
        payload = json.loads(cleaned)
    except Exception:
        match = re.search(r"\{.*\}", cleaned, flags=re.DOTALL)
        if not match:
            raise
        payload = json.loads(match.group(0))
    return {
        "inferred_key": safe_cell(payload.get("inferred_key", "")),
        "confidence": safe_cell(payload.get("confidence", "none")),
        "evidence": safe_cell(payload.get("evidence", "")),
        "needs_review": bool(payload.get("needs_review", False)),
        "review_reason": safe_cell(payload.get("review_reason", "")),
    }


def call_openai_key_classifier(prompt: dict[str, Any], model: str) -> tuple[dict[str, Any], str]:
    api_key = os.environ.get("OPENAI_API_KEY", "")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is not set")
    body = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": "You classify scientific table blocks into canonical figure/table keys. Return JSON only.",
            },
            {"role": "user", "content": json.dumps(prompt, ensure_ascii=False)},
        ],
        "temperature": 0,
    }
    req = request.Request(
        "https://api.openai.com/v1/chat/completions",
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"OpenAI API error {exc.code}: {detail}") from exc
    text = data["choices"][0]["message"]["content"]
    return parse_llm_key_response(text), text


def call_codex_key_classifier(prompt: dict[str, Any], model: str) -> tuple[dict[str, Any], str]:
    schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "properties": {
            "inferred_key": {"type": "string"},
            "confidence": {"type": "string", "enum": ["high", "medium", "low", "none"]},
            "evidence": {"type": "string"},
            "needs_review": {"type": "boolean"},
            "review_reason": {"type": "string"},
        },
        "required": ["inferred_key", "confidence", "evidence", "needs_review", "review_reason"],
        "additionalProperties": False,
    }
    prompt_text = (
        "Classify the supplied scientific table context. Do not inspect files, run commands, or modify anything. "
        "Use only the JSON context below and return the requested JSON object.\n\n"
        + json.dumps(prompt, ensure_ascii=False)
    )
    with tempfile.TemporaryDirectory(prefix="expval_merge_codex_") as temp_dir:
        temp_root = Path(temp_dir)
        schema_path = temp_root / "response_schema.json"
        response_path = temp_root / "response.json"
        schema_path.write_text(json.dumps(schema, ensure_ascii=False, indent=2), encoding="utf-8")
        command = [
            "codex",
            "exec",
            "--cd",
            str(PROJECT_ROOT),
            "--sandbox",
            "read-only",
            "--ephemeral",
            "--color",
            "never",
            "--output-schema",
            str(schema_path),
            "--output-last-message",
            str(response_path),
        ]
        if model:
            command.extend(["--model", model])
        command.append("-")
        try:
            completed = subprocess.run(
                command,
                cwd=PROJECT_ROOT,
                input=prompt_text,
                text=True,
                encoding="utf-8",
                errors="replace",
                capture_output=True,
                timeout=300,
            )
        except FileNotFoundError as exc:
            raise RuntimeError("Codex CLI is not installed or is not available on PATH") from exc
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError("Codex CLI classification timed out after 300 seconds") from exc
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout or "").strip()
            raise RuntimeError(f"Codex CLI failed with exit code {completed.returncode}: {detail[-2000:]}")
        if not response_path.exists():
            raise RuntimeError("Codex CLI completed without producing a final response")
        text = response_path.read_text(encoding="utf-8")
        return parse_llm_key_response(text), text


def load_figure_table_key_map(output_root: Path, role: str) -> dict[tuple[str, str], dict[str, Any]]:
    path = output_root / "figure_table_key_map.csv"
    if not path.exists():
        return {}
    rows = dataframe_to_records(read_csv_flexible(path))
    out = {}
    for row in rows:
        if row.get("role") != role:
            continue
        key = (safe_cell(row.get("source_file")), safe_cell(row.get("source_sheet")))
        out[key] = row
    return out


def map_key_for_sheet(
    key_map: dict[tuple[str, str], dict[str, Any]],
    source_file: Path,
    source_sheet: str,
) -> str:
    row = key_map.get((str(source_file), source_sheet), {})
    key = safe_cell(row.get("inferred_key", "")).strip()
    return key if key and normalize_text(key) != "unknown" else ""


def observe_inputs(
    expval_roots: list[Path],
    lnpdb_roots: list[Path],
    output_root: Path,
) -> dict[str, Any]:
    require_pandas()
    expval_files = iter_candidate_files(expval_roots)
    lnpdb_files = iter_candidate_files(lnpdb_roots, exclude_roots=expval_roots + [output_root])
    inventory = []

    for role, files in [("expval", expval_files), ("lnpdb_like", lnpdb_files)]:
        for path in files:
            row = {
                "file_role": role,
                "source_file": str(path),
                "extension": path.suffix.lower(),
                "file_size_bytes": path.stat().st_size if path.exists() else "",
                "sheet_count": "",
                "readable": False,
                "error": "",
            }
            try:
                if path.suffix.lower() == ".csv":
                    _ = read_csv_flexible(path).head(1)
                    row["sheet_count"] = 1
                else:
                    xls = pd.ExcelFile(path)
                    row["sheet_count"] = len(xls.sheet_names)
                row["readable"] = True
            except Exception as exc:
                row["error"] = str(exc)
            inventory.append(row)

    output_root.mkdir(parents=True, exist_ok=True)
    write_csv(output_root / "input_inventory.csv", inventory)
    report = {
        "schema_version": 1,
        "created_at": utc_now(),
        "expval_roots": [str(p) for p in expval_roots],
        "lnpdb_roots": [str(p) for p in lnpdb_roots],
        "output_root": str(output_root),
        "expval_files_seen": len(expval_files),
        "lnpdb_files_seen": len(lnpdb_files),
        "readable_files": sum(1 for row in inventory if row["readable"]),
        "unreadable_files": sum(1 for row in inventory if not row["readable"]),
    }
    write_json(output_root / "observe_report.json", report)
    return report


def read_inventory(output_root: Path, role: str) -> list[Path]:
    path = output_root / "input_inventory.csv"
    if not path.exists():
        raise FileNotFoundError(f"Missing input inventory: {path}. Run observe first.")
    df = read_csv_flexible(path).fillna("")
    rows = []
    for row in df.to_dict(orient="records"):
        if row.get("file_role") == role and str(row.get("readable", "")).lower() in {"true", "1"}:
            rows.append(Path(str(row.get("source_file"))))
    return rows


def build_figure_table_key_map(output_root: Path, provider: str = "none", model: str = "") -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    flags: list[dict[str, Any]] = []
    llm_attempted = 0
    llm_succeeded = 0
    for role in ["expval", "lnpdb_like"]:
        files = read_inventory(output_root, role)
        for path in files:
            try:
                tables = read_table_file(path)
            except Exception as exc:
                rows.append(
                    {
                        "role": role,
                        "source_file": str(path),
                        "source_sheet": "",
                        "row_count": "",
                        "inferred_key": "",
                        "confidence": "none",
                        "method": "read_failed",
                        "evidence": "",
                        "raw_llm_response": "",
                        "prompt_json": "",
                        "needs_review": "true",
                        "review_reason": str(exc),
                    }
                )
                continue
            for sheet, df in tables:
                context = build_sheet_context(role, path, sheet, df)
                prompt = figure_table_prompt(context)
                heuristic_key = context.get("heuristic_key", "")
                result = {
                    "inferred_key": heuristic_key,
                    "confidence": "medium" if heuristic_key else "none",
                    "evidence": "heuristic from path/sheet/columns/sample values" if heuristic_key else "",
                    "needs_review": not bool(heuristic_key),
                    "review_reason": "" if heuristic_key else "no reliable figure/table key found",
                }
                method = "heuristic"
                raw_response = ""
                if provider in {"codex", "openai"}:
                    llm_attempted += 1
                    try:
                        if provider == "codex":
                            llm_result, raw_response = call_codex_key_classifier(prompt, model)
                        else:
                            llm_result, raw_response = call_openai_key_classifier(prompt, model or "gpt-4.1-mini")
                        llm_key = infer_figure_key(llm_result.get("inferred_key", ""))
                        if llm_key:
                            llm_result["inferred_key"] = llm_key
                        result = llm_result
                        method = f"{provider}:{model or 'login-default-model'}"
                        llm_succeeded += 1
                    except Exception as exc:
                        method = "heuristic_after_llm_failed"
                        result["needs_review"] = True
                        result["review_reason"] = f"LLM failed; fallback used. {exc}"
                elif provider not in {"none", "heuristic", ""}:
                    result["needs_review"] = True
                    result["review_reason"] = f"unsupported llm provider: {provider}"

                inferred_key = safe_cell(result.get("inferred_key", "")).strip()
                needs_review = bool(result.get("needs_review", False)) or not inferred_key
                row = {
                    "role": role,
                    "source_file": str(path),
                    "source_sheet": sheet,
                    "row_count": context.get("row_count", ""),
                    "inferred_key": inferred_key,
                    "confidence": result.get("confidence", "none"),
                    "method": method,
                    "evidence": result.get("evidence", ""),
                    "raw_llm_response": raw_response,
                    "prompt_json": json.dumps(prompt, ensure_ascii=False),
                    "needs_review": str(needs_review).lower(),
                    "review_reason": result.get("review_reason", "") if needs_review else "",
                }
                rows.append(row)
                if needs_review:
                    flags.append(
                        {
                            "role": role,
                            "source_file": str(path),
                            "source_sheet": sheet,
                            "issue": "figure_table_key_needs_review",
                            "reason": row["review_reason"] or "missing inferred_key",
                            "evidence": row["evidence"],
                        }
                    )

    write_csv(output_root / "figure_table_key_map.csv", rows, FIGURE_TABLE_KEY_MAP_COLUMNS)
    write_csv(
        output_root / "figure_table_key_map_review_flags.csv",
        flags,
        ["role", "source_file", "source_sheet", "issue", "reason", "evidence"],
    )
    return {
        "rows": len(rows),
        "review_flags": len(flags),
        "provider": provider,
        "model": model if provider in {"codex", "openai"} else "",
        "llm_attempted": llm_attempted,
        "llm_succeeded": llm_succeeded,
        "output": str(output_root / "figure_table_key_map.csv"),
    }


def detect_expval_table_type(columns: list[str]) -> str:
    keys = {compact_key(c) for c in columns}
    if {"xlabel", "value", "xpixel", "ypixel"} & keys and "xlabel" in keys:
        return "barplot"
    if "extractedvalue" in keys or "matchedvalue" in keys:
        return "heatmap_long"
    if {"rowindex", "colindex", "rowlabel", "collabel"} <= keys:
        return "heatmap_long"
    return "heatmap_matrix" if len(columns) > 2 else "unknown"


def normalize_expval_row(
    row: dict[str, Any],
    source_file: Path,
    source_sheet: str,
    source_row: int,
    table_type: str,
    value_col: str,
    seq: int,
    mapped_figure_key: str = "",
) -> dict[str, Any]:
    columns = list(row.keys())
    figure_name = safe_cell(row.get(find_column(columns, ["figure_name", "Figure", "Item_ID", "Item"])))
    row_context = text_from_row(row, columns)
    column_context = text_from_columns(columns)
    item_id = infer_item_id(figure_name, row_context, column_context, str(source_file), source_sheet)
    heuristic_figure_key = infer_figure_key(item_id, figure_name, row_context, column_context, str(source_file), source_sheet)
    figure_key = mapped_figure_key or heuristic_figure_key
    paper_key = ""
    partition_key = make_partition_key(figure_key)
    value_text = safe_cell(row.get(value_col))
    return {
        "expval_id": f"EV{seq:08d}",
        "source_file": str(source_file),
        "source_sheet": source_sheet,
        "paper_key": paper_key,
        "figure_key": figure_key,
        "partition_key": partition_key,
        "source_row": source_row,
        "source_table_type": table_type,
        "figure_name": figure_name,
        "item_id": item_id,
        "panel_id": infer_panel_id(figure_name, source_file.stem, source_sheet),
        "box_id": safe_cell(row.get(find_column(columns, ["box_id", "box"]))),
        "x_label": safe_cell(row.get(find_column(columns, ["X_Label", "x_label", "xlabel"]))),
        "group_label": safe_cell(row.get(find_column(columns, ["Group", "group", "matched_class_label"]))),
        "row_label": safe_cell(row.get(find_column(columns, ["row_label", "rowlabel"]))),
        "col_label": safe_cell(row.get(find_column(columns, ["col_label", "collabel"]))),
        "metric_type": safe_cell(row.get(find_column(columns, ["metric_type", "metric", "Type", "type"]))),
        "value": to_number_or_blank(value_text),
        "value_text": value_text,
        "unit": safe_cell(row.get(find_column(columns, UNIT_COLUMNS))),
        "x_pixel": safe_cell(row.get(find_column(columns, ["x_pixel", "xpixel"]))),
        "y_pixel": safe_cell(row.get(find_column(columns, ["y_pixel", "ypixel"]))),
        "x_center": safe_cell(row.get(find_column(columns, ["x_center", "xcenter"]))),
        "y_center": safe_cell(row.get(find_column(columns, ["y_center", "ycenter"]))),
        "cell_rgb": safe_cell(row.get(find_column(columns, ["cell_rgb", "rgb"]))),
        "cell_hex": safe_cell(row.get(find_column(columns, ["cell_hex", "hex"]))),
        "color_distance": safe_cell(row.get(find_column(columns, ["color_distance", "colordistance"]))),
        "raw_columns_json": json.dumps(row, ensure_ascii=False),
        "manual_required": "false" if value_text else "true",
        "normalization_warning": "" if value_text else "missing value",
    }


def normalize_matrix_table(
    df: Any,
    source_file: Path,
    source_sheet: str,
    start_seq: int,
    mapped_figure_key: str = "",
) -> tuple[list[dict[str, Any]], int]:
    records = dataframe_to_records(df)
    if not records:
        return [], start_seq
    columns = list(records[0].keys())
    first_col = columns[0]
    value_columns = [c for c in columns[1:] if safe_cell(c).strip()]
    out = []
    seq = start_seq
    row_context = text_from_row(records[0], columns)
    column_context = text_from_columns(columns)
    item_id = infer_item_id(str(source_file), source_sheet, column_context, row_context)
    heuristic_figure_key = infer_figure_key(item_id, str(source_file), source_sheet, column_context, row_context)
    figure_key = mapped_figure_key or heuristic_figure_key
    paper_key = ""
    partition_key = make_partition_key(figure_key)
    for ridx, row in enumerate(records, start=2):
        row_label = safe_cell(row.get(first_col)) or str(ridx - 1)
        for col_label in value_columns:
            value_text = safe_cell(row.get(col_label))
            if not value_text:
                continue
            seq += 1
            raw = {"row_label": row_label, "col_label": col_label, "value": value_text}
            out.append(
                {
                    "expval_id": f"EV{seq:08d}",
                    "source_file": str(source_file),
                    "source_sheet": source_sheet,
                    "paper_key": paper_key,
                    "figure_key": figure_key,
                    "partition_key": partition_key,
                    "source_row": ridx,
                    "source_table_type": "heatmap_matrix",
                    "figure_name": "",
                    "item_id": item_id,
                    "panel_id": infer_panel_id(source_file.stem, source_sheet),
                    "box_id": "",
                    "x_label": "",
                    "group_label": "",
                    "row_label": row_label,
                    "col_label": col_label,
                    "metric_type": "",
                    "value": to_number_or_blank(value_text),
                    "value_text": value_text,
                    "unit": "",
                    "x_pixel": "",
                    "y_pixel": "",
                    "x_center": "",
                    "y_center": "",
                    "cell_rgb": "",
                    "cell_hex": "",
                    "color_distance": "",
                    "raw_columns_json": json.dumps(raw, ensure_ascii=False),
                    "manual_required": "false",
                    "normalization_warning": "",
                }
            )
    return out, seq


def normalize_expvals(output_root: Path) -> dict[str, Any]:
    files = read_inventory(output_root, "expval")
    key_map = load_figure_table_key_map(output_root, "expval")
    rows: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    seq = 0
    for path in files:
        try:
            tables = read_table_file(path)
        except Exception as exc:
            warnings.append({"source_file": str(path), "source_sheet": "", "issue": "read_failed", "reason": str(exc)})
            continue
        for sheet, df in tables:
            try:
                mapped_key = map_key_for_sheet(key_map, path, sheet)
                records = dataframe_to_records(df)
                if not records:
                    continue
                columns = list(records[0].keys())
                table_type = detect_expval_table_type(columns)
                value_col = find_column(columns, EXPVAL_VALUE_COLUMNS)
                if value_col:
                    for idx, row in enumerate(records, start=2):
                        seq += 1
                        rows.append(normalize_expval_row(row, path, sheet, idx, table_type, value_col, seq, mapped_key))
                else:
                    matrix_rows, seq = normalize_matrix_table(df, path, sheet, seq, mapped_key)
                    rows.extend(matrix_rows)
                    if not matrix_rows:
                        warnings.append(
                            {
                                "source_file": str(path),
                                "source_sheet": sheet,
                                "issue": "value_column_not_detected",
                                "reason": ", ".join(columns),
                            }
                        )
            except Exception as exc:
                warnings.append({"source_file": str(path), "source_sheet": sheet, "issue": "normalize_failed", "reason": str(exc)})
    write_csv(output_root / "normalized_expvals.csv", rows, EXPVAL_COLUMNS)
    write_csv(output_root / "normalized_expvals_warnings.csv", warnings)
    return {"rows": len(rows), "warnings": len(warnings), "output": str(output_root / "normalized_expvals.csv")}


def source_value(row: dict[str, Any], columns: list[str], candidates: list[str]) -> str:
    col = find_column(columns, candidates)
    return safe_cell(row.get(col)) if col else ""


def normalize_lnpdb(output_root: Path) -> dict[str, Any]:
    files = read_inventory(output_root, "lnpdb_like")
    key_map = load_figure_table_key_map(output_root, "lnpdb_like")
    rows: list[dict[str, Any]] = []
    file_inventory: list[dict[str, Any]] = []
    seq = 0
    for path in files:
        try:
            tables = read_table_file(path)
        except Exception as exc:
            file_inventory.append({"source_file": str(path), "readable": False, "error": str(exc)})
            continue
        file_inventory.append({"source_file": str(path), "readable": True, "sheet_count": len(tables), "error": ""})
        for sheet, df in tables:
            mapped_key = map_key_for_sheet(key_map, path, sheet)
            records = dataframe_to_records(df)
            if not records:
                continue
            columns = list(records[0].keys())
            for idx, row in enumerate(records, start=2):
                seq += 1
                figure_name = source_value(row, columns, ["figure_name", "Figure", "Fig", "Item_ID", "Item_ID", "Item"])
                existing_value_col = find_exact_column(columns, EXPERIMENTAL_VALUE_COLUMN)
                existing_value = safe_cell(row.get(existing_value_col)) if existing_value_col else ""
                full_row_context = text_from_row_except(row, columns, {EXPERIMENTAL_VALUE_COLUMN})
                column_context = text_from_columns(columns)
                paper_id = source_value(row, columns, ["Paper_ID", "paper_id", "paper", "article_id", "article"])
                doi = source_value(row, columns, ["DOI", "doi"])
                item_id = source_value(row, columns, ["Item_ID", "item_id"]) or infer_item_id(
                    figure_name,
                    full_row_context,
                    column_context,
                    str(path),
                    sheet,
                )
                heuristic_figure_key = infer_figure_key(item_id, figure_name, full_row_context, column_context, str(path), sheet)
                figure_key = heuristic_figure_key or mapped_key
                paper_key = ""
                partition_key = make_partition_key(figure_key)
                rows.append(
                    {
                        "lnpdb_row_id": f"LN{seq:08d}",
                        "source_file": str(path),
                        "source_sheet": sheet,
                        "paper_key": paper_key,
                        "figure_key": figure_key,
                        "partition_key": partition_key,
                        "source_row": idx,
                        "paper_id": paper_id,
                        "doi": doi,
                        "item_id": item_id,
                        "figure_name": figure_name,
                        "panel_id": infer_panel_id(item_id, figure_name),
                        "metric_type": source_value(row, columns, ["metric_type", "metric", "Experiment_method"]),
                        "formulation_id": source_value(row, columns, ["formulation_id", "Formulation_ID"]),
                        "formulation_name": source_value(row, columns, ["Formulation_Name", "formulation_name", "formulation"]),
                        "group_label": source_value(row, columns, ["Group", "group"]),
                        "condition_text": full_row_context,
                        "existing_value_text": existing_value,
                        "existing_unit": source_value(row, columns, UNIT_COLUMNS),
                        "raw_columns_json": json.dumps(row, ensure_ascii=False),
                    }
                )
    write_csv(output_root / "normalized_lnpdb_rows.csv", rows, LNPDB_CANONICAL_COLUMNS)
    write_csv(output_root / "lnpdb_file_inventory.csv", file_inventory)
    return {"rows": len(rows), "files": len(files), "output": str(output_root / "normalized_lnpdb_rows.csv")}


def label_values_for_expval(row: dict[str, Any]) -> list[str]:
    return [
        row.get("x_label", ""),
        row.get("group_label", ""),
        row.get("row_label", ""),
        row.get("col_label", ""),
        row.get("metric_type", ""),
    ]


def score_candidate(lnpdb: dict[str, Any], expval: dict[str, Any]) -> tuple[int, list[str], str]:
    score = 0
    fields = []
    reasons = []
    l_figure = compact_key(lnpdb.get("figure_key") or lnpdb.get("item_id") or lnpdb.get("figure_name"))
    e_figure = compact_key(expval.get("figure_key") or expval.get("item_id") or expval.get("figure_name"))
    if l_figure and e_figure and l_figure == e_figure:
        score += 55
        fields.append("figure_key")
        reasons.append("same normalized figure/table key")

    l_item = compact_key(lnpdb.get("item_id") or lnpdb.get("figure_name"))
    e_item = compact_key(expval.get("item_id") or expval.get("figure_name"))
    if l_item and e_item and l_item == e_item:
        score += 35 if "figure_key" in fields else 55
        fields.append("item_id")
        reasons.append("same normalized item/figure id")
    elif l_item and e_item and (l_item in e_item or e_item in l_item):
        score += 35
        fields.append("item_id_partial")
        reasons.append("partial item/figure id overlap")

    if compact_key(lnpdb.get("panel_id")) and compact_key(lnpdb.get("panel_id")) == compact_key(expval.get("panel_id")):
        score += 8
        fields.append("panel_id")

    l_context = normalize_text(
        " ".join(
            [
                lnpdb.get("formulation_name", ""),
                lnpdb.get("formulation_id", ""),
                lnpdb.get("group_label", ""),
                lnpdb.get("condition_text", ""),
                lnpdb.get("metric_type", ""),
                raw_json_context(lnpdb, {EXPERIMENTAL_VALUE_COLUMN}),
            ]
        )
    )
    e_context = normalize_text(
        " ".join(
            [
                expval.get("figure_name", ""),
                expval.get("item_id", ""),
                expval.get("x_label", ""),
                expval.get("group_label", ""),
                expval.get("row_label", ""),
                expval.get("col_label", ""),
                expval.get("metric_type", ""),
                raw_json_context(expval),
                expval.get("source_file", ""),
                expval.get("source_sheet", ""),
            ]
        )
    )
    for value in label_values_for_expval(expval):
        key = meaningful_match_text(value)
        if key and key in l_context:
            score += 15
            fields.append(f"label:{value}")
            reasons.append(f"label present in target context: {value}")
        elif key and compact_key(key) and compact_key(key) in compact_key(l_context):
            score += 10
            fields.append(f"label_compact:{value}")
            reasons.append(f"compact label present in target context: {value}")

    for value in [
        lnpdb.get("formulation_name", ""),
        lnpdb.get("formulation_id", ""),
        lnpdb.get("group_label", ""),
        lnpdb.get("metric_type", ""),
    ]:
        key = meaningful_match_text(value)
        if key and key in e_context:
            score += 8
            fields.append(f"target_label:{value}")
            reasons.append(f"target context present in extracted row: {value}")

    if compact_key(lnpdb.get("metric_type")) and compact_key(lnpdb.get("metric_type")) == compact_key(expval.get("metric_type")):
        score += 15
        fields.append("metric_type")

    if compact_key(lnpdb.get("existing_unit")) and compact_key(lnpdb.get("existing_unit")) == compact_key(expval.get("unit")):
        score += 5
        fields.append("unit")

    if not fields:
        return 0, [], "no identifier or label evidence"
    return score, fields, "; ".join(dict.fromkeys(reasons)) or "deterministic field match"


def confidence_from_score(score: int) -> str:
    if score >= 75:
        return "high"
    if score >= 60:
        return "medium"
    if score >= 45:
        return "low"
    return "conflict"


def write_partition_outputs(
    output_root: Path,
    expvals: list[dict[str, Any]],
    lnpdb_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    inventory: list[dict[str, Any]] = []
    for role, rows, id_col, columns in [
        ("expvals", expvals, "expval_id", EXPVAL_COLUMNS),
        ("lnpdb_like", lnpdb_rows, "lnpdb_row_id", LNPDB_CANONICAL_COLUMNS),
    ]:
        grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in rows:
            partition = row.get("partition_key") or make_partition_key(row.get("figure_key", ""))
            grouped[partition].append(row)
        for partition, group_rows in sorted(grouped.items(), key=lambda item: item[0]):
            paper_key = group_rows[0].get("paper_key", "")
            figure_key = group_rows[0].get("figure_key", "")
            partition_dir = output_root / "partitioned" / role
            partition_path = partition_dir / f"{safe_path_component(figure_key or 'unknown_figure_table')}.csv"
            write_csv(partition_path, group_rows, columns)
            inventory.append(
                {
                    "role": role,
                    "partition_key": partition,
                    "paper_key": paper_key,
                    "figure_key": figure_key,
                    "row_count": len(group_rows),
                    "id_column": id_col,
                    "partition_file": str(partition_path),
                }
            )
    write_csv(
        output_root / "partition_inventory.csv",
        inventory,
        ["role", "partition_key", "paper_key", "figure_key", "row_count", "id_column", "partition_file"],
    )
    return {
        "partitions": len(inventory),
        "expval_partitions": sum(1 for row in inventory if row["role"] == "expvals"),
        "lnpdb_partitions": sum(1 for row in inventory if row["role"] == "lnpdb_like"),
        "output": str(output_root / "partition_inventory.csv"),
    }


def build_match_candidates(output_root: Path) -> dict[str, Any]:
    expvals = dataframe_to_records(read_csv_flexible(output_root / "normalized_expvals.csv"))
    lnpdb_rows = dataframe_to_records(read_csv_flexible(output_root / "normalized_lnpdb_rows.csv"))
    partition_report = write_partition_outputs(output_root, expvals, lnpdb_rows)
    exp_by_item: dict[str, list[dict[str, Any]]] = defaultdict(list)
    exp_by_figure: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in expvals:
        key = compact_key(row.get("item_id") or row.get("figure_name"))
        if key:
            exp_by_item[key].append(row)
        figure_key = compact_key(row.get("figure_key") or row.get("item_id") or row.get("figure_name"))
        if figure_key:
            exp_by_figure[figure_key].append(row)

    candidates: list[dict[str, Any]] = []
    conflicts: list[dict[str, Any]] = []
    accepted_expvals: set[str] = set()
    accepted_lnpdb: set[str] = set()
    candidate_seq = 0
    conflict_seq = 0

    for lrow in lnpdb_rows:
        lkey = compact_key(lrow.get("item_id") or lrow.get("figure_name"))
        lfigure = compact_key(lrow.get("figure_key") or lrow.get("item_id") or lrow.get("figure_name"))
        tier_pools: list[tuple[str, list[dict[str, Any]]]] = []
        if lfigure:
            tier_pools.append(("figure_partition", exp_by_figure.get(lfigure, [])))
        if lkey and exp_by_item.get(lkey):
            tier_pools.append(("item_id", exp_by_item.get(lkey, [])))
        if lkey:
            partial_pool = [
                row
                for ekey, item_rows in exp_by_item.items()
                if ekey and (lkey in ekey or ekey in lkey)
                for row in item_rows
            ]
            if partial_pool:
                tier_pools.append(("item_id_partial", partial_pool))
        tier_pools.append(("remaining_global", expvals))

        scored = []
        selected_tier = "remaining_global"
        seen_pool_ids: set[str] = set()
        for tier, pool in tier_pools:
            if not pool:
                continue
            tier_scored = []
            for erow in pool:
                expval_id = erow.get("expval_id", "")
                if expval_id in seen_pool_ids:
                    continue
                seen_pool_ids.add(expval_id)
                score, fields, reason = score_candidate(lrow, erow)
                if score <= 0:
                    continue
                tier_scored.append((score, fields, reason, erow))
            if tier_scored:
                scored = tier_scored
                selected_tier = tier
                break
        scored.sort(key=lambda x: x[0], reverse=True)
        top_score = scored[0][0] if scored else 0
        top = [x for x in scored if x[0] == top_score and top_score >= 45]

        for score, fields, reason, erow in scored[:10]:
            candidate_seq += 1
            existing = lrow.get("existing_value_text", "")
            extracted = erow.get("value_text", "")
            accepted = False
            manual_required = score < 75
            conflict_reason = ""
            if score < 60:
                conflict_reason = "score below automatic acceptance threshold"
            elif len(top) > 1 and score == top_score:
                conflict_reason = "multiple top extracted-value candidates"
            elif existing:
                conflict_reason = "target experimental_value already filled"
            elif not extracted:
                conflict_reason = "missing extracted value"
            elif score == top_score:
                accepted = True
                manual_required = confidence_from_score(score) != "high"

            candidate = {
                "candidate_id": f"MC{candidate_seq:08d}",
                "lnpdb_row_id": lrow.get("lnpdb_row_id", ""),
                "expval_id": erow.get("expval_id", ""),
                "match_tier": selected_tier,
                "lnpdb_partition_key": lrow.get("partition_key", ""),
                "expval_partition_key": erow.get("partition_key", ""),
                "match_score": score,
                "match_confidence": confidence_from_score(score),
                "matched_fields": "|".join(fields),
                "match_reason": reason,
                "accepted": str(accepted).lower(),
                "manual_required": str(manual_required).lower(),
                "conflict_reason": conflict_reason,
            }
            candidates.append(candidate)
            if accepted:
                accepted_expvals.add(erow.get("expval_id", ""))
                accepted_lnpdb.add(lrow.get("lnpdb_row_id", ""))
            elif conflict_reason and score >= 60:
                conflict_seq += 1
                conflicts.append(
                    {
                        "conflict_id": f"CF{conflict_seq:08d}",
                        "lnpdb_row_id": lrow.get("lnpdb_row_id", ""),
                        "expval_id": erow.get("expval_id", ""),
                        "conflict_type": "candidate_conflict",
                        "conflict_reason": conflict_reason,
                        "candidate_ids": candidate["candidate_id"],
                        "existing_value_text": lrow.get("existing_value_text", ""),
                        "extracted_value_text": erow.get("value_text", ""),
                        "existing_unit": lrow.get("existing_unit", ""),
                        "extracted_unit": erow.get("unit", ""),
                        "review_action": "manual review required",
                    }
                )

    unmatched_expvals = [
        {
            "expval_id": row.get("expval_id", ""),
            "source_file": row.get("source_file", ""),
            "source_sheet": row.get("source_sheet", ""),
            "source_row": row.get("source_row", ""),
            "partition_key": row.get("partition_key", ""),
            "figure_name": row.get("figure_name", ""),
            "item_id": row.get("item_id", ""),
            "label_summary": " | ".join([x for x in label_values_for_expval(row) if x]),
            "value_text": row.get("value_text", ""),
            "reason": "no accepted LNPDB-like target row",
        }
        for row in expvals
        if row.get("expval_id") not in accepted_expvals
    ]
    unmatched_lnpdb = [
        {
            "lnpdb_row_id": row.get("lnpdb_row_id", ""),
            "source_file": row.get("source_file", ""),
            "source_sheet": row.get("source_sheet", ""),
            "source_row": row.get("source_row", ""),
            "partition_key": row.get("partition_key", ""),
            "item_id": row.get("item_id", ""),
            "figure_name": row.get("figure_name", ""),
            "label_summary": " | ".join([row.get("formulation_name", ""), row.get("group_label", ""), row.get("condition_text", "")]).strip(" |"),
            "existing_value_text": row.get("existing_value_text", ""),
            "reason": "no accepted extracted-value row",
        }
        for row in lnpdb_rows
        if row.get("lnpdb_row_id") not in accepted_lnpdb
    ]

    write_csv(
        output_root / "merge_candidates.csv",
        candidates,
        [
            "candidate_id",
            "lnpdb_row_id",
            "expval_id",
            "match_tier",
            "lnpdb_partition_key",
            "expval_partition_key",
            "match_score",
            "match_confidence",
            "matched_fields",
            "match_reason",
            "accepted",
            "manual_required",
            "conflict_reason",
        ],
    )
    write_csv(
        output_root / "merge_conflicts.csv",
        conflicts,
        [
            "conflict_id",
            "lnpdb_row_id",
            "expval_id",
            "conflict_type",
            "conflict_reason",
            "candidate_ids",
            "existing_value_text",
            "extracted_value_text",
            "existing_unit",
            "extracted_unit",
            "review_action",
        ],
    )
    write_csv(
        output_root / "merge_unmatched_expvals.csv",
        unmatched_expvals,
        [
            "expval_id",
            "source_file",
            "source_sheet",
            "source_row",
            "partition_key",
            "figure_name",
            "item_id",
            "label_summary",
            "value_text",
            "reason",
        ],
    )
    write_csv(
        output_root / "merge_unmatched_lnpdb_rows.csv",
        unmatched_lnpdb,
        [
            "lnpdb_row_id",
            "source_file",
            "source_sheet",
            "source_row",
            "partition_key",
            "item_id",
            "figure_name",
            "label_summary",
            "existing_value_text",
            "reason",
        ],
    )
    return {
        "candidates": len(candidates),
        "accepted": sum(1 for row in candidates if row.get("accepted") == "true"),
        "conflicts": len(conflicts),
        "unmatched_expvals": len(unmatched_expvals),
        "unmatched_lnpdb_rows": len(unmatched_lnpdb),
        "partition_report": partition_report,
    }


def merge_values(output_root: Path, mode: str = "fill_existing") -> dict[str, Any]:
    if mode not in {"fill_existing", "long_expand"}:
        raise ValueError(f"Unsupported merge mode: {mode}")
    lnpdb_rows = dataframe_to_records(read_csv_flexible(output_root / "normalized_lnpdb_rows.csv"))
    expvals = {row["expval_id"]: row for row in dataframe_to_records(read_csv_flexible(output_root / "normalized_expvals.csv"))}
    candidates = dataframe_to_records(read_csv_flexible(output_root / "merge_candidates.csv"))
    accepted_by_lnpdb: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in candidates:
        if str(row.get("accepted", "")).lower() == "true":
            accepted_by_lnpdb[row.get("lnpdb_row_id", "")].append(row)

    out_rows: list[dict[str, Any]] = []
    for lrow in lnpdb_rows:
        raw = json.loads(lrow.get("raw_columns_json") or "{}")
        matches = accepted_by_lnpdb.get(lrow.get("lnpdb_row_id", ""), [])
        if mode == "fill_existing" and len(matches) > 1:
            matches = []
        if not matches:
            merged = dict(raw)
            for col in MERGE_PROVENANCE_COLUMNS:
                merged.setdefault(col, "")
            merged.setdefault(EXPERIMENTAL_VALUE_COLUMN, "")
            merged["lnpdb_row_id"] = lrow.get("lnpdb_row_id", "")
            out_rows.append(merged)
            continue
        for match in matches:
            erow = expvals.get(match.get("expval_id", ""), {})
            merged = dict(raw)
            extracted_value = erow.get("value_text", "")
            target_col = find_exact_column(list(merged.keys()), EXPERIMENTAL_VALUE_COLUMN)
            if target_col is None:
                target_col = EXPERIMENTAL_VALUE_COLUMN
                merged[target_col] = ""
            inserted = False
            if not safe_cell(merged.get(target_col)).strip():
                merged[target_col] = extracted_value
                inserted = True
            merged["lnpdb_row_id"] = lrow.get("lnpdb_row_id", "")
            merged["merged_experimental_value"] = extracted_value if inserted else ""
            merged["expval_source_file"] = erow.get("source_file", "") if inserted else ""
            merged["expval_source_sheet"] = erow.get("source_sheet", "") if inserted else ""
            merged["expval_source_row"] = erow.get("source_row", "") if inserted else ""
            merged["expval_source_table_type"] = erow.get("source_table_type", "") if inserted else ""
            merged["expval_value_column"] = "value_text" if inserted else ""
            merged["expval_value_text"] = extracted_value if inserted else ""
            merged["expval_x_pixel"] = erow.get("x_pixel", "") if inserted else ""
            merged["expval_y_pixel"] = erow.get("y_pixel", "") if inserted else ""
            merged["expval_x_center"] = erow.get("x_center", "") if inserted else ""
            merged["expval_y_center"] = erow.get("y_center", "") if inserted else ""
            merged["expval_match_score"] = match.get("match_score", "") if inserted else ""
            merged["expval_match_confidence"] = match.get("match_confidence", "") if inserted else ""
            merged["expval_match_reason"] = match.get("match_reason", "") if inserted else ""
            merged["expval_manual_required"] = match.get("manual_required", "") if inserted else ""
            out_rows.append(merged)

    write_csv(output_root / "merged_lnpdb_like.csv", out_rows)
    return {"merged_rows": len(out_rows), "output": str(output_root / "merged_lnpdb_like.csv"), "merge_mode": mode}


def validate_outputs(output_root: Path, merge_mode: str = "fill_existing") -> tuple[bool, list[str], dict[str, Any]]:
    messages: list[str] = []
    required = [
        "input_inventory.csv",
        "figure_table_key_map.csv",
        "normalized_expvals.csv",
        "normalized_lnpdb_rows.csv",
        "partition_inventory.csv",
        "merge_candidates.csv",
        "merged_lnpdb_like.csv",
    ]
    ok = True
    counts: dict[str, int] = {}
    for name in required:
        path = output_root / name
        if not path.exists():
            ok = False
            messages.append(f"missing {name}")
            continue
        try:
            counts[name] = len(read_csv_flexible(path))
            messages.append(f"{name}: rows={counts[name]}")
        except Exception as exc:
            ok = False
            messages.append(f"{name}: parse failed: {exc}")

    candidates = []
    if (output_root / "merge_candidates.csv").exists():
        candidates = dataframe_to_records(read_csv_flexible(output_root / "merge_candidates.csv"))
    accepted = [row for row in candidates if str(row.get("accepted", "")).lower() == "true"]
    conflicts_count = len(read_csv_flexible(output_root / "merge_conflicts.csv")) if (output_root / "merge_conflicts.csv").exists() else 0
    unmatched_expvals = len(read_csv_flexible(output_root / "merge_unmatched_expvals.csv")) if (output_root / "merge_unmatched_expvals.csv").exists() else 0
    unmatched_lnpdb = len(read_csv_flexible(output_root / "merge_unmatched_lnpdb_rows.csv")) if (output_root / "merge_unmatched_lnpdb_rows.csv").exists() else 0

    flags = []
    flag_seq = 0
    for row in candidates:
        if row.get("conflict_reason"):
            flag_seq += 1
            flags.append(
                {
                    "flag_id": f"FL{flag_seq:08d}",
                    "severity": "high" if row.get("match_score", "0").isdigit() and int(row.get("match_score", "0")) >= 60 else "medium",
                    "lnpdb_row_id": row.get("lnpdb_row_id", ""),
                    "expval_id": row.get("expval_id", ""),
                    "field": "match",
                    "issue": row.get("conflict_reason", ""),
                    "reason": row.get("match_reason", ""),
                    "recommended_action": "manual review",
                }
            )
    write_csv(
        output_root / "merge_review_flags.csv",
        flags,
        ["flag_id", "severity", "lnpdb_row_id", "expval_id", "field", "issue", "reason", "recommended_action"],
    )
    report = {
        "schema_version": 1,
        "created_at": utc_now(),
        "merge_mode": merge_mode,
        "expval_files_seen": "",
        "lnpdb_files_seen": "",
        "normalized_expval_rows": counts.get("normalized_expvals.csv", 0),
        "normalized_lnpdb_rows": counts.get("normalized_lnpdb_rows.csv", 0),
        "accepted_matches": len(accepted),
        "merged_rows": counts.get("merged_lnpdb_like.csv", 0),
        "conflict_rows": conflicts_count,
        "unmatched_expval_rows": unmatched_expvals,
        "unmatched_lnpdb_rows": unmatched_lnpdb,
        "manual_required_rows": len(flags),
        "output_files": [str(p) for p in output_root.rglob("*") if p.is_file()],
        "warnings": [m for m in messages if "missing" in m or "failed" in m],
    }
    write_json(output_root / "merge_qc_report.json", report)
    return ok, messages, report


def run_stage(stage: str, args: argparse.Namespace, config: dict[str, Any]) -> dict[str, Any]:
    output_root = output_root_from_args(args, config)
    expval_roots = resolve_roots(getattr(args, "expval_root", None), config.get("default_expval_root"))
    lnpdb_roots = resolve_roots(getattr(args, "lnpdb_root", None), config.get("default_lnpdb_roots"))
    append_log({"action": "stage_start", "stage": stage, "output_root": str(output_root)})
    update_state(stage, "running", {"output_root": str(output_root)})
    try:
        if stage == "00_observe_inputs":
            result = observe_inputs(expval_roots, lnpdb_roots, output_root)
        elif stage == "01_build_figure_table_key_map":
            result = build_figure_table_key_map(
                output_root,
                llm_provider_from_args(args, config),
                llm_model_from_args(args, config),
            )
        elif stage == "02_normalize_expvals":
            result = normalize_expvals(output_root)
        elif stage == "03_normalize_lnpdb":
            result = normalize_lnpdb(output_root)
        elif stage == "04_build_match_candidates":
            result = build_match_candidates(output_root)
        elif stage == "05_merge_values":
            result = merge_values(output_root, getattr(args, "mode", "fill_existing"))
        elif stage == "06_validate_merge":
            ok, messages, report = validate_outputs(output_root, getattr(args, "mode", "fill_existing"))
            result = {"ok": ok, "messages": messages, "report": report}
        else:
            raise ValueError(f"Unknown stage: {stage}")
        status = "validated" if result.get("ok") is True else "success"
        append_log({"action": "stage_complete", "stage": stage, "result": result})
        update_state(stage, status, result)
        return result
    except Exception as exc:
        result = {"status": "failed", "error": str(exc), "traceback": traceback.format_exc()}
        append_log({"action": "stage_failed", "stage": stage, **result})
        update_state(stage, "failed", result)
        raise


def run_all(args: argparse.Namespace, config: dict[str, Any]) -> dict[str, Any]:
    summary = {"status": "completed", "stages": []}
    for stage in STAGE_ORDER:
        try:
            result = run_stage(stage, args, config)
            summary["stages"].append({"stage": stage, "result": result})
            if stage == "06_validate_merge" and not result.get("ok", False):
                summary["status"] = "validation_failed"
                break
        except Exception as exc:
            summary["status"] = "failed"
            summary["stages"].append({"stage": stage, "error": str(exc)})
            break
    append_log({"action": "run_all_complete", **summary})
    return summary


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Local merge runner with optional LLM-based figure/table key classification.")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG), help="Path to merge_manifest.json.")
    sub = parser.add_subparsers(dest="command", required=True)

    def add_common(p: argparse.ArgumentParser) -> None:
        p.add_argument("--config", default=argparse.SUPPRESS, help="Path to merge_manifest.json.")
        p.add_argument("--expval-root", action="append", help="Extracted-value file or folder. Can be repeated.")
        p.add_argument("--lnpdb-root", action="append", help="LNPDB-like file or folder. Can be repeated.")
        p.add_argument("--output-root", help="Output folder. Defaults to manifest default_output_root.")
        p.add_argument("--llm-provider", choices=["none", "heuristic", "codex", "openai"], default=argparse.SUPPRESS)
        p.add_argument("--llm-model", default=argparse.SUPPRESS)

    for command in ["observe", "build-key-map", "normalize-expvals", "normalize-lnpdb", "build-candidates", "validate", "run-all"]:
        p = sub.add_parser(command)
        add_common(p)
        if command in {"validate", "run-all"}:
            p.add_argument("--mode", choices=["fill_existing", "long_expand"], default="fill_existing")

    p_merge = sub.add_parser("merge")
    add_common(p_merge)
    p_merge.add_argument("--mode", choices=["fill_existing", "long_expand"], default="fill_existing")

    return parser


def main() -> int:
    args = build_parser().parse_args()
    config = load_config(args.config)
    command_to_stage = {
        "observe": "00_observe_inputs",
        "build-key-map": "01_build_figure_table_key_map",
        "normalize-expvals": "02_normalize_expvals",
        "normalize-lnpdb": "03_normalize_lnpdb",
        "build-candidates": "04_build_match_candidates",
        "merge": "05_merge_values",
        "validate": "06_validate_merge",
    }
    try:
        if args.command == "run-all":
            result = run_all(args, config)
            print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
            return 0 if result.get("status") == "completed" else 2
        stage = command_to_stage[args.command]
        result = run_stage(stage, args, config)
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
        if args.command == "validate":
            return 0 if result.get("ok") else 2
        return 0
    except Exception as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}, ensure_ascii=False, indent=2), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
