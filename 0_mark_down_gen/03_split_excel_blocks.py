import json
import re
import hashlib
import traceback
from pathlib import Path
from typing import Any
import pandas as pd
import sys

# --- [경로 설정] 프로젝트 최상위 경로를 sys.path에 추가 ---
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from LLM_API import prepare_text_for_prompt

PROMPT_TOKEN_LIMIT = 160000
EXTENDED_DATA_PROMPT_NOTE = (
    "Extended Data figures/tables are valid figure/table identifiers. "
    "Keep them distinct from ordinary figures and supplementary figures."
)


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


def infer_candidates(text: str) -> list[str]:
    text = str(text or "")
    patterns = [
        r"(extended\s+data\s+(?:fig\.?|figure)\s+\d+[a-z]?)",
        r"(extended\s+data\s+table\s+\d+[a-z]?)",
        r"(supplementary\s+figure\s+\d+[a-z]?)",
        r"(supplementary\s+table\s+\d+[a-z]?)",
        r"(figure\s+\d+[a-z]?)",
        r"(fig\.?\s*\d+[a-z]?)",
        r"(table\s+\d+[a-z]?)",
    ]
    out = []
    for pattern in patterns:
        for match in re.findall(pattern, text, flags=re.I):
            value = normalize_ft_item_id(match)
            if value and value not in out:
                out.append(value)
    return out


def prepare_stage_text_with_token_limit(
    client,
    model_name: str,
    text: str,
    stage_name: str,
    allow_numeric_strip: bool = False,
) -> str:
    prep = prepare_text_for_prompt(
        client=client,
        model_name=model_name,
        text=str(text or ""),
        stage_name=stage_name,
        soft_token_limit=PROMPT_TOKEN_LIMIT,
        hard_token_limit=PROMPT_TOKEN_LIMIT,
        allow_numeric_strip=allow_numeric_strip,
        allow_truncate=True,
    )
    if prep.over_hard_limit:
        raise ValueError(
            f"[{stage_name}] prepared text is still over token hard limit {PROMPT_TOKEN_LIMIT:,}"
        )
    return prep.prepared_text

# =========================
# minimal helpers
# =========================
def safe_path_name(name: str) -> str:
    name = str(name or "").strip()
    if not name:
        return "unnamed_sheet"
    # 윈도우 금지문자 치환
    name = re.sub(r'[\\/*?:"<>|]', "_", name)
    # 너무 긴 공백 정리
    name = re.sub(r"\s+", " ", name).strip()
    return name

def try_read_json(text: str) -> dict:
    if not text:
        raise ValueError("빈 응답입니다.")

    cleaned = text.strip()
    cleaned = re.sub(r"^```json", "", cleaned, flags=re.I).strip()
    cleaned = re.sub(r"^```", "", cleaned).strip()
    cleaned = re.sub(r"```$", "", cleaned).strip()

    try:
        return json.loads(cleaned)
    except Exception:
        pass

    match = re.search(r"\{.*\}", cleaned, flags=re.S)
    if match:
        return json.loads(match.group(0))

    raise ValueError(f"JSON 파싱 실패: {cleaned[:500]}")



def normalize_text(text: str, limit: int = 120000) -> str:
    return str(text or "")[:limit]



def prepare_csv_for_prompt(csv_text: str, hard_char_limit: int = 120000) -> str:
    csv_text = str(csv_text or "")
    if len(csv_text) <= hard_char_limit:
        return csv_text

    lines = csv_text.splitlines()
    if not lines:
        return csv_text[:hard_char_limit]

    header = lines[0]
    trimmed = [header]
    current_len = len(header)
    for line in lines[1:]:
        if current_len + len(line) + 1 > hard_char_limit:
            break
        trimmed.append(line)
        current_len += len(line) + 1
    return "\n".join(trimmed)



def render_sheet_ascii_preview(df, max_rows: int = 40, max_cols: int = 20, max_cell_len: int = 20) -> str:
    if df is None or getattr(df, "empty", False):
        return "<empty sheet>"

    clipped = df.iloc[:max_rows, :max_cols].copy().fillna("")
    clipped.columns = [str(c) for c in clipped.columns]

    def _fmt(v: Any) -> str:
        s = str(v or "").replace("\n", " ").strip()
        if len(s) > max_cell_len:
            s = s[: max_cell_len - 3] + "..."
        return s

    header = [f"C{idx+1}:{_fmt(col)}" for idx, col in enumerate(clipped.columns)]
    rows = ["\t".join(header)]
    for ridx, (_, row) in enumerate(clipped.iterrows(), 1):
        rows.append("\t".join([f"R{ridx}"] + [_fmt(v) for v in row.tolist()]))
    if df.shape[0] > max_rows or df.shape[1] > max_cols:
        rows.append(f"... truncated preview rows={df.shape[0]} cols={df.shape[1]}")
    return "\n".join(rows)



def summarize_element_types(element_blocks: list[dict]) -> list[dict]:
    rows = []
    for blk in element_blocks:
        eid = str(blk.get("element_id", "")).strip()
        title_guess = str(blk.get("title_guess", "")).strip()
        features = blk.get("features", {}) or {}
        has_numeric_body = bool(features.get("has_numeric_body"))
        title_like_top_row = bool(features.get("title_like_top_row"))
        header_like_rows = int(features.get("header_like_rows", 0) or 0)

        if has_numeric_body and (title_like_top_row or (title_guess and header_like_rows >= 1)):
            predicted_type = "title_and_table"
        elif has_numeric_body:
            predicted_type = "table_body"
        elif title_like_top_row or title_guess:
            predicted_type = "table_title"
        else:
            predicted_type = "multi_table_or_other"

        rows.append({
            "element_id": eid,
            "predicted_type": predicted_type,
            "title_guess": title_guess,
            "bbox": blk.get("bbox", {}) or {},
            "has_numeric_body": has_numeric_body,
            "title_like_top_row": title_like_top_row,
            "header_like_rows": header_like_rows,
            "n_rows": int(features.get("n_rows", 0) or 0),
            "n_cols": int(features.get("n_cols", 0) or 0),
        })
    return rows



def stringify_classification_payload(element_blocks: list[dict]) -> str:
    payload_rows = []
    for blk in element_blocks:
        payload_rows.append({
            "element_id": str(blk.get("element_id", "")).strip(),
            "title_guess": str(blk.get("title_guess", "")).strip(),
            "bbox": blk.get("bbox"),
            "features": blk.get("features", {}) or {},
        })
    return json.dumps(payload_rows, ensure_ascii=False, indent=2)



def attach_element_types_to_blocks(element_blocks: list[dict], element_classification: list[dict]) -> list[dict]:
    type_map = {}
    for item in element_classification or []:
        if not isinstance(item, dict):
            continue
        eid = str(item.get("element_id", "")).strip()
        etype = str(item.get("type", "")).strip()
        if eid:
            type_map[eid] = etype

    for blk in element_blocks:
        eid = str(blk.get("element_id", "")).strip()
        blk["element_type"] = type_map.get(eid, "")
    return element_blocks



def load_markdown_text(folder: Path) -> str:
    md_files = sorted(folder.rglob("*.md"))
    texts = []
    for md in md_files:
        try:
            texts.append(md.read_text(encoding="utf-8"))
        except UnicodeDecodeError:
            texts.append(md.read_text(encoding="utf-8", errors="replace"))
    return normalize_text("\n\n".join(texts), limit=120000)



def load_pdf_text(folder: Path, limit: int = 120000) -> str:
    pdf_files = sorted(folder.rglob("*.pdf"))
    texts = []

    for pdf_path in pdf_files:
        try:
            try:
                from pypdf import PdfReader
                reader = PdfReader(str(pdf_path))
                one_pdf_text = []
                for page in reader.pages:
                    one_pdf_text.append(page.extract_text() or "")
                texts.append(f"\n\n[PDF: {pdf_path.name}]\n" + "\n".join(one_pdf_text))
            except Exception:
                import fitz
                doc = fitz.open(str(pdf_path))
                one_pdf_text = []
                for page in doc:
                    one_pdf_text.append(page.get_text("text"))
                texts.append(f"\n\n[PDF: {pdf_path.name}]\n" + "\n".join(one_pdf_text))
        except Exception:
            continue

    return normalize_text("\n\n".join(texts), limit=limit)



def load_inventory_items(folder: Path) -> list[str]:
    inventory_csv = folder / "fig_table_inventory.csv"
    if not inventory_csv.exists():
        return []

    try:
        df_inv = pd.read_csv(inventory_csv)
    except Exception:
        return []

    possible_cols = [
        c for c in df_inv.columns
        if str(c).strip().lower() in {"item_id", "pdf_item_id", "item"}
    ]
    if not possible_cols:
        return []

    col = possible_cols[0]
    items = []
    for v in df_inv[col].fillna("").astype(str):
        s = normalize_ft_item_id(v)
        if s:
            items.append(s)
    return sorted(set(items))



def load_sheet_df(excel_path: Path, sheet_name: str) -> pd.DataFrame:
    if excel_path.suffix.lower() == ".csv":
        return pd.read_csv(excel_path, dtype=str).fillna("")
    return pd.read_excel(excel_path, sheet_name=sheet_name, dtype=str).fillna("")



def list_sheet_specs(file_path: Path) -> list[dict]:
    suffix = file_path.suffix.lower()

    if suffix == ".csv":
        return [{
            "excel_file": file_path.name,
            "excel_sheet": "단일시트",
            "source_path": file_path,
        }]

    if suffix == ".xlsx":
        xls = pd.ExcelFile(file_path)
        return [{
            "excel_file": file_path.name,
            "excel_sheet": sheet_name,
            "source_path": file_path,
        } for sheet_name in xls.sheet_names]

    return []



def block_df_to_text(block_df, max_rows: int = 20, max_cols: int = 12, max_cell_len: int = 60) -> str:
    if block_df is None or getattr(block_df, "empty", False):
        return "<empty block>"

    clipped = block_df.iloc[:max_rows, :max_cols].copy().fillna("")
    clipped.columns = [str(c) for c in clipped.columns]

    def _fmt(v):
        s = str(v or "").replace("\n", " ").strip()
        if len(s) > max_cell_len:
            s = s[: max_cell_len - 3] + "..."
        return s

    lines = []
    header = [_fmt(c) for c in clipped.columns]
    lines.append(",".join(header))

    for _, row in clipped.iterrows():
        lines.append(",".join(_fmt(v) for v in row.tolist()))

    if block_df.shape[0] > max_rows or block_df.shape[1] > max_cols:
        lines.append(f"... truncated rows={block_df.shape[0]} cols={block_df.shape[1]}")

    return "\n".join(lines)



def build_element_alias_map(element_blocks: list[dict], excel_file: str, excel_sheet: str) -> tuple[dict, dict]:
    orig_to_alias = {}
    alias_to_orig = {}

    for blk in element_blocks:
        orig_id = str(blk.get("element_id", "")).strip()
        if not orig_id:
            continue

        seed = f"{excel_file}::{excel_sheet}::{orig_id}"
        alias = "EL_" + hashlib.sha1(seed.encode("utf-8")).hexdigest()[:10].upper()

        orig_to_alias[orig_id] = alias
        alias_to_orig[alias] = orig_id

    return orig_to_alias, alias_to_orig

def build_element_cards_text(
    element_blocks: list[dict],
    element_classification: list[dict],
    orig_to_alias: dict,
) -> str:
    class_map = {}
    for item in element_classification or []:
        if not isinstance(item, dict):
            continue
        orig_id = str(item.get("element_id", "")).strip()
        class_map[orig_id] = {
            "type": str(item.get("type", "")).strip(),
            "reason": str(item.get("reason", "")).strip(),
        }

    lines = []
    for blk in element_blocks:
        orig_id = str(blk.get("element_id", "")).strip()
        alias = orig_to_alias.get(orig_id, orig_id)
        cls = class_map.get(orig_id, {})
        block_df = blk.get("df", None)

        lines.append(f"[{alias}]")
        lines.append(f"type: {cls.get('type', '')}")
        lines.append(f"classification_reason: {cls.get('reason', '')}")
        lines.append(f"title_guess: {str(blk.get('title_guess', '')).strip()}")
        lines.append("[content]")
        lines.append(block_df_to_text(block_df))
        lines.append("")

    return "\n".join(lines).strip()


def make_sheet_stage_custom_id(stage_name: str, excel_file: str, excel_sheet: str) -> str:
    seed = f"{stage_name}::{excel_file}::{excel_sheet}"
    return f"{stage_name}__" + hashlib.sha1(seed.encode("utf-8")).hexdigest()[:12]
