from __future__ import annotations

import re
from pathlib import Path

import pandas as pd

from Legacy.active_legacy_utils import normalize_text, truncate_csv_text


def safe_path_name(name: str) -> str:
    text = str(name or "").strip() or "unnamed_sheet"
    text = re.sub(r'[\\/*?:"<>|]', "_", text)
    return re.sub(r"\s+", " ", text).strip()


def load_sheet_df(excel_path: str | Path, sheet_name: str | None = None) -> pd.DataFrame:
    path = Path(excel_path)
    if path.suffix.lower() in {".csv", ".tsv"}:
        sep = "\t" if path.suffix.lower() == ".tsv" else ","
        return pd.read_csv(path, dtype=str, sep=sep).fillna("")
    if sheet_name is None:
        sheet_name = 0
    return pd.read_excel(path, sheet_name=sheet_name, dtype=str).fillna("")


def list_sheet_specs(file_path: str | Path) -> list[dict]:
    path = Path(file_path)
    suffix = path.suffix.lower()
    if suffix in {".csv", ".tsv"}:
        return [{"excel_file": path.name, "excel_sheet": "single_sheet", "source_path": path}]
    if suffix in {".xlsx", ".xlsm"}:
        xls = pd.ExcelFile(path)
        return [{"excel_file": path.name, "excel_sheet": sheet, "source_path": path} for sheet in xls.sheet_names]
    return []


def load_markdown_text(folder: str | Path, limit: int = 120000) -> str:
    root = Path(folder)
    texts: list[str] = []
    for md_path in sorted(root.rglob("*.md")):
        if any(part in {"agent_workspace", "legacy_reference", "active_legacy_utils", "__pycache__"} for part in md_path.parts):
            continue
        try:
            texts.append(md_path.read_text(encoding="utf-8"))
        except UnicodeDecodeError:
            texts.append(md_path.read_text(encoding="utf-8", errors="replace"))
    return normalize_text("\n\n".join(texts), limit=limit)


__all__ = [
    "safe_path_name",
    "load_sheet_df",
    "list_sheet_specs",
    "load_markdown_text",
    "truncate_csv_text",
]

