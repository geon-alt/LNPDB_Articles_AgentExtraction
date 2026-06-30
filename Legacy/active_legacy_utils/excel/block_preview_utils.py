from __future__ import annotations

import re
from typing import Any

import pandas as pd


def normalize_text(text: str, limit: int = 120000) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()[:limit]


def truncate_csv_text(csv_text: str, hard_char_limit: int = 120000) -> str:
    csv_text = str(csv_text or "")
    if len(csv_text) <= hard_char_limit:
        return csv_text
    lines = csv_text.splitlines()
    if not lines:
        return csv_text[:hard_char_limit]
    kept = [lines[0]]
    current_len = len(lines[0])
    for line in lines[1:]:
        if current_len + len(line) + 1 > hard_char_limit:
            break
        kept.append(line)
        current_len += len(line) + 1
    return "\n".join(kept)


def _fmt_cell(value: Any, max_len: int) -> str:
    text = str(value or "").replace("\n", " ").strip()
    if len(text) > max_len:
        return text[: max_len - 3] + "..."
    return text


def render_sheet_ascii_preview(df: pd.DataFrame, max_rows: int = 40, max_cols: int = 20, max_cell_len: int = 20) -> str:
    if df is None or getattr(df, "empty", False):
        return "<empty sheet>"
    clipped = df.iloc[:max_rows, :max_cols].copy().fillna("")
    clipped.columns = [str(c) for c in clipped.columns]
    rows = ["\t".join(f"C{idx + 1}:{_fmt_cell(col, max_cell_len)}" for idx, col in enumerate(clipped.columns))]
    for row_index, (_, row) in enumerate(clipped.iterrows(), 1):
        rows.append("\t".join([f"R{row_index}"] + [_fmt_cell(value, max_cell_len) for value in row.tolist()]))
    if df.shape[0] > max_rows or df.shape[1] > max_cols:
        rows.append(f"... truncated preview rows={df.shape[0]} cols={df.shape[1]}")
    return "\n".join(rows)


def block_df_to_text(block_df: pd.DataFrame, max_rows: int = 20, max_cols: int = 12, max_cell_len: int = 60) -> str:
    if block_df is None or getattr(block_df, "empty", False):
        return "<empty block>"
    clipped = block_df.iloc[:max_rows, :max_cols].copy().fillna("")
    clipped.columns = [str(c) for c in clipped.columns]
    lines = [",".join(_fmt_cell(col, max_cell_len) for col in clipped.columns)]
    for _, row in clipped.iterrows():
        lines.append(",".join(_fmt_cell(value, max_cell_len) for value in row.tolist()))
    if block_df.shape[0] > max_rows or block_df.shape[1] > max_cols:
        lines.append(f"... truncated rows={block_df.shape[0]} cols={block_df.shape[1]}")
    return "\n".join(lines)


def block_preview(df: pd.DataFrame, max_rows: int = 10, max_cols: int = 10, max_len: int = 40) -> str:
    return block_df_to_text(df, max_rows=max_rows, max_cols=max_cols, max_cell_len=max_len)

