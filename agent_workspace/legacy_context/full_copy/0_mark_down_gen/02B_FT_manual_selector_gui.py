# Run:
# streamlit run 0_mark_down_gen/02B_FT_manual_selector_gui.py

from __future__ import annotations

import argparse
import json
import math
import re
from datetime import datetime
from io import StringIO
from pathlib import Path

import pandas as pd
import streamlit as st


def parse_cli_args():
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--paper-folder", default=".")
    args, _ = parser.parse_known_args()
    return args


CLI_ARGS = parse_cli_args()
DEFAULT_PAPER_FOLDER = CLI_ARGS.paper_folder
CSV_NAME = "fig_table_lnpdb_classified.csv"
REVIEWED_COPY_NAME = "fig_table_lnpdb_classified_manual_reviewed.csv"
ROW_ID_COL = "__row_id__"
MANUAL_REVIEW_MARKER_FILENAME = ".manual_select_review_done"


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

EXCEL_MATCH_COLUMNS = [
    "excel_item_id",
    "matched_blocks",
    "matched_block_ids",
    "matched_block_csv",
    "matched_sheet",
    "matched_sheet_file",
    "excel_block_id",
    "excel_block_file",
    "excel_sheet",
]

SEARCH_COLUMNS = [
    "item_id",
    "base_id",
    "reason",
    "visual_type",
    "excel_item_id",
    "matched_blocks",
]

PREVIEW_COLUMNS = [
    "item_id",
    "manual_select",
    "need_for_lnpdb",
    "visual_type",
    "priority",
    "excel_item_id",
    "matched_blocks",
]

EMPTY_VALUES = {"", "nan", "none", "null", "[]", "{}"}
INCLUDE_MANUAL_VALUES = {"yes", "y", "1", "true", "maybe"}
EXCLUDE_MANUAL_VALUES = {"no", "n", "0", "false"}


def is_meaningful_value(value) -> bool:
    if value is None:
        return False
    try:
        if pd.isna(value):
            return False
    except (TypeError, ValueError):
        pass
    return str(value).strip().lower() not in EMPTY_VALUES


def row_has_excel_match(row, excel_cols) -> bool:
    return any(is_meaningful_value(row.get(col, "")) for col in excel_cols)


def normalize_manual_select(value) -> str:
    text = str(value).strip().lower()
    if text in EMPTY_VALUES:
        return ""
    if text in INCLUDE_MANUAL_VALUES:
        return "yes"
    if text in EXCLUDE_MANUAL_VALUES:
        return "no"
    return ""


def initial_select_for_row(row) -> bool:
    manual = normalize_manual_select(row.get("manual_select", ""))
    if manual == "yes":
        return True
    if manual == "no":
        return False
    need = str(row.get("need_for_lnpdb", "")).strip().lower()
    return need in {"yes", "maybe"}


def normalize_manual_select_from_row(row) -> str:
    return "yes" if initial_select_for_row(row) else "no"


def normalize_all_manual_select(df: pd.DataFrame) -> pd.DataFrame:
    normalized = df.copy()
    normalized["manual_select"] = normalized.apply(normalize_manual_select_from_row, axis=1)
    return normalized


def dataframe_to_csv_bytes(df: pd.DataFrame) -> bytes:
    buffer = StringIO()
    df.drop(columns=[ROW_ID_COL], errors="ignore").to_csv(buffer, index=False, encoding="utf-8-sig")
    return buffer.getvalue().encode("utf-8-sig")


def load_classified_csv(csv_path: Path) -> pd.DataFrame:
    df = pd.read_csv(csv_path, dtype=str).fillna("")
    if "manual_select" not in df.columns:
        df["manual_select"] = ""
    df[ROW_ID_COL] = range(len(df))
    return df


def build_selector_view_df(df: pd.DataFrame) -> pd.DataFrame:
    selector_df = pd.DataFrame(
        {
            ROW_ID_COL: df[ROW_ID_COL].astype(int).tolist(),
            "item_id": df["item_id"].astype(str).tolist() if "item_id" in df.columns else [""] * len(df),
            "base_id": df["base_id"].astype(str).tolist() if "base_id" in df.columns else [""] * len(df),
        }
    )
    selector_df["select"] = df.apply(initial_select_for_row, axis=1).astype(bool).tolist()
    return selector_df


def get_unique_options(df: pd.DataFrame, column: str) -> list[str]:
    if column not in df.columns:
        return []
    values = sorted({str(v).strip() for v in df[column].fillna("").tolist() if str(v).strip()})
    return values


def apply_filters(df: pd.DataFrame, filters: dict) -> pd.DataFrame:
    visible = df.copy()

    for column in ["need_for_lnpdb", "priority", "visual_type", "item_type", "is_supplementary", "confidence"]:
        selected = filters.get(column, [])
        if selected and column in visible.columns:
            visible = visible[visible[column].astype(str).str.strip().isin(selected)]

    excel_cols = [col for col in EXCEL_MATCH_COLUMNS if col in visible.columns]
    if excel_cols:
        excel_match = visible.apply(row_has_excel_match, axis=1, excel_cols=excel_cols)
    else:
        excel_match = pd.Series(False, index=visible.index)

    excel_status = filters.get("excel_status", "all")
    if excel_status == "Excel matched only":
        visible = visible[excel_match]
    elif excel_status == "Excel missing only":
        visible = visible[~excel_match]

    search = str(filters.get("search", "")).strip().lower()
    if search:
        existing_search_cols = [col for col in SEARCH_COLUMNS if col in visible.columns]
        if existing_search_cols:
            haystack = visible[existing_search_cols].astype(str).agg(" ".join, axis=1).str.lower()
            normalized_cells = visible[existing_search_cols].astype(str).apply(
                lambda col: col.map(normalize_ft_item_id)
            )
            normalized_haystack = normalized_cells.agg(" ".join, axis=1)
            haystack = haystack + " " + normalized_haystack
            visible = visible[haystack.str.contains(search, regex=False, na=False)]

    return visible


def set_visible_selection(value: bool, visible_row_ids: list[int]) -> None:
    selector_view_df = st.session_state["selector_view_df"].copy()
    mask = selector_view_df[ROW_ID_COL].astype(int).isin([int(row_id) for row_id in visible_row_ids])
    selector_view_df.loc[mask, "select"] = value
    st.session_state["selector_view_df"] = selector_view_df
    st.session_state["selector_widget_version"] = st.session_state.get("selector_widget_version", 0) + 1


def build_visible_selector_df(visible_df: pd.DataFrame, selector_view_df: pd.DataFrame) -> pd.DataFrame:
    visible_row_ids = visible_df[ROW_ID_COL].astype(int).tolist()
    visible_selector_df = selector_view_df[
        selector_view_df[ROW_ID_COL].astype(int).isin(visible_row_ids)
    ].copy()
    order_map = {row_id: idx for idx, row_id in enumerate(visible_row_ids)}
    visible_selector_df["_order"] = visible_selector_df[ROW_ID_COL].map(order_map)
    visible_selector_df = visible_selector_df.sort_values("_order").drop(columns=["_order"])
    visible_selector_df = visible_selector_df[[ROW_ID_COL, "item_id", "base_id", "select"]]
    if "item_id" in visible_selector_df.columns and visible_selector_df["item_id"].astype(str).str.strip().any():
        visible_selector_df = visible_selector_df.sort_values(
            by="item_id",
            key=lambda s: s.astype(str).str.lower(),
            kind="stable",
        )
    elif "base_id" in visible_selector_df.columns and visible_selector_df["base_id"].astype(str).str.strip().any():
        visible_selector_df = visible_selector_df.sort_values(
            by="base_id",
            key=lambda s: s.astype(str).str.lower(),
            kind="stable",
        )
    return visible_selector_df[[ROW_ID_COL, "item_id", "select"]]


def sort_preview_for_display(preview_df: pd.DataFrame) -> pd.DataFrame:
    sorted_preview = preview_df.copy()
    if "item_id" in sorted_preview.columns:
        return sorted_preview.sort_values(
            by="item_id",
            key=lambda s: s.astype(str).str.lower(),
            kind="stable",
        )
    if "base_id" in sorted_preview.columns:
        return sorted_preview.sort_values(
            by="base_id",
            key=lambda s: s.astype(str).str.lower(),
            kind="stable",
        )
    return sorted_preview


def update_selector_view_rows(selector_rows: list[tuple[int, bool]]) -> None:
    selector_view_df = st.session_state["selector_view_df"].copy()
    selector_view_df[ROW_ID_COL] = selector_view_df[ROW_ID_COL].astype(int)
    selector_index = selector_view_df.set_index(ROW_ID_COL)
    for row_id, checked in selector_rows:
        if int(row_id) in selector_index.index:
            selector_index.at[int(row_id), "select"] = bool(checked)
    st.session_state["selector_view_df"] = selector_index.reset_index()


def selector_rows_for_ids(selector_view_df: pd.DataFrame, row_ids: list[int]) -> pd.DataFrame:
    row_id_set = {int(row_id) for row_id in row_ids}
    return selector_view_df[
        selector_view_df[ROW_ID_COL].astype(int).isin(row_id_set)
    ].copy()


def apply_selection_rows_to_full_df(df: pd.DataFrame, selector_rows_df: pd.DataFrame) -> pd.DataFrame:
    applied = df.copy()
    if selector_rows_df.empty or ROW_ID_COL not in selector_rows_df.columns or "select" not in selector_rows_df.columns:
        return applied
    applied[ROW_ID_COL] = applied[ROW_ID_COL].astype(int)
    applied_index = applied.set_index(ROW_ID_COL)
    for _, row in selector_rows_df.iterrows():
        row_id = int(row[ROW_ID_COL])
        if row_id in applied_index.index:
            applied_index.at[row_id, "manual_select"] = "yes" if bool(row["select"]) else "no"
    applied = applied_index.reset_index()
    return applied


def preview_columns(df: pd.DataFrame) -> list[str]:
    return [col for col in PREVIEW_COLUMNS if col in df.columns]


def save_with_backup(csv_path: Path, df: pd.DataFrame) -> Path:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = csv_path.with_name(f"{csv_path.stem}.before_manual_review_{timestamp}{csv_path.suffix}")
    if csv_path.exists():
        original_df = pd.read_csv(csv_path, dtype=str).fillna("")
        original_df.to_csv(backup_path, index=False, encoding="utf-8-sig")
    df.drop(columns=[ROW_ID_COL], errors="ignore").to_csv(csv_path, index=False, encoding="utf-8-sig")
    return backup_path


def create_marker_file(marker_path: Path, csv_path: Path, df_to_save: pd.DataFrame) -> None:
    manual_norm = df_to_save["manual_select"].astype(str).str.strip().str.lower()
    marker_payload = {
        "saved_at": datetime.now().isoformat(timespec="seconds"),
        "csv_path": str(csv_path),
        "row_count": int(len(df_to_save)),
        "selected_yes_count": int((manual_norm == "yes").sum()),
        "selected_no_count": int((manual_norm == "no").sum()),
    }
    with open(marker_path, "w", encoding="utf-8") as f:
        json.dump(marker_payload, f, indent=2, ensure_ascii=False)


st.set_page_config(page_title="02B FT Manual Selector", layout="wide")
st.title("02B FT Manual Selector")
st.caption("Check = include this item in downstream figure pipeline")
st.caption("Unchecked = exclude this item from downstream figure pipeline")
st.caption("After Apply, review the preview table, then Save.")

with st.sidebar:
    st.header("Input")
    paper_folder_text = st.text_input("Paper folder path", value=DEFAULT_PAPER_FOLDER)
    paper_folder = Path(paper_folder_text).expanduser().resolve()
    csv_path = paper_folder / CSV_NAME
    marker_path = paper_folder / MANUAL_REVIEW_MARKER_FILENAME
    st.caption(f"Loaded CSV path:\n{csv_path}")
    if marker_path.exists():
        st.success(f"Manual review marker exists: {marker_path}")
    else:
        st.warning(f"Manual review marker not found yet: {marker_path}")
    st.caption(f'To review again, delete marker:\nrm "{marker_path}"')

    reload_clicked = st.button("Reload CSV")

if not csv_path.exists():
    st.error(f"fig_table_lnpdb_classified.csv not found in selected paper folder:\n{csv_path}")
    st.stop()

session_key = str(csv_path)
if reload_clicked or st.session_state.get("csv_path") != session_key or "classified_df" not in st.session_state:
    st.session_state["csv_path"] = session_key
    st.session_state["classified_df"] = load_classified_csv(csv_path)
    st.session_state["selector_view_df"] = build_selector_view_df(st.session_state["classified_df"])
    st.session_state["applied_df"] = None
    st.session_state["selection_applied"] = False
    st.session_state["selector_widget_version"] = 0

df_full = st.session_state["classified_df"].copy()
if "selector_view_df" not in st.session_state:
    st.session_state["selector_view_df"] = build_selector_view_df(df_full)
selector_view_df = st.session_state["selector_view_df"].copy()
excel_cols_full = [col for col in EXCEL_MATCH_COLUMNS if col in df_full.columns]
excel_match_full = (
    df_full.apply(row_has_excel_match, axis=1, excel_cols=excel_cols_full)
    if excel_cols_full
    else pd.Series(False, index=df_full.index)
)

with st.sidebar:
    st.header("Filters")
    filters = {}
    for filter_col in ["need_for_lnpdb", "priority", "visual_type", "item_type", "is_supplementary", "confidence"]:
        options = get_unique_options(df_full, filter_col)
        filters[filter_col] = st.multiselect(filter_col, options=options, default=[])

    filters["excel_status"] = st.radio(
        "Excel matched status",
        ["all", "Excel matched only", "Excel missing only"],
        index=0,
    )
    filters["search"] = st.text_input("Row search")

visible_df = apply_filters(df_full, filters)
visible_row_ids = visible_df[ROW_ID_COL].astype(int).tolist()
selector_view_df = st.session_state["selector_view_df"].copy()
visible_selector_df = build_visible_selector_df(visible_df, selector_view_df)

with st.sidebar:
    st.header("Pagination")
    rows_per_page = st.selectbox("Rows per page", [25, 50, 100, 200], index=1)
    total_pages = max(1, math.ceil(len(visible_selector_df) / rows_per_page))
    page = st.number_input("Page", min_value=1, max_value=total_pages, value=1, step=1)

start = (int(page) - 1) * rows_per_page
end = start + rows_per_page
page_df = visible_selector_df.iloc[start:end].copy()
page_row_ids = page_df[ROW_ID_COL].astype(int).tolist()

normalized_for_metrics = normalize_all_manual_select(df_full)
manual_norm = normalized_for_metrics["manual_select"].astype(str).str.strip().str.lower()
metric_cols = st.columns(6)
metric_cols[0].metric("total rows", len(df_full))
metric_cols[1].metric("visible rows", len(visible_df))
metric_cols[2].metric("selected yes", int((manual_norm == "yes").sum()))
metric_cols[3].metric("selected no", int((manual_norm == "no").sum()))
metric_cols[4].metric("Excel matched", int(excel_match_full.sum()))
metric_cols[5].metric("Excel missing", int((~excel_match_full).sum()))

st.subheader("Visible Rows")
st.caption(f"Showing page {int(page)} of {total_pages} ({len(page_df)} rows on this page).")
action_cols = st.columns(4)
if action_cols[0].button("Check all rows on current page", disabled=not page_row_ids):
    set_visible_selection(True, page_row_ids)
if action_cols[1].button("Uncheck all rows on current page", disabled=not page_row_ids):
    set_visible_selection(False, page_row_ids)
if action_cols[2].button("Check all visible rows", disabled=not visible_row_ids):
    set_visible_selection(True, visible_row_ids)
if action_cols[3].button("Uncheck all visible rows", disabled=not visible_row_ids):
    set_visible_selection(False, visible_row_ids)

selector_view_df = st.session_state["selector_view_df"].copy()
visible_selector_df = build_visible_selector_df(visible_df, selector_view_df)
page_df = visible_selector_df.iloc[start:end].copy()
page_row_ids = page_df[ROW_ID_COL].astype(int).tolist()

edited_rows = []
with st.form("manual_selector_form"):
    st.caption("Check = include, unchecked = exclude")
    header_cols = st.columns([4, 1])
    header_cols[0].markdown("**item_id**")
    header_cols[1].markdown("**select**")

    widget_version = st.session_state.get("selector_widget_version", 0)
    for _, row in page_df.iterrows():
        row_id = int(row[ROW_ID_COL])
        item_id = str(row.get("item_id", ""))
        current_value = bool(row.get("select", False))

        cols = st.columns([4, 1])
        cols[0].write(item_id)
        with cols[1]:
            checked = st.checkbox(
                "select",
                value=current_value,
                key=f"select_row_{row_id}_{widget_version}",
                label_visibility="collapsed",
            )
        edited_rows.append((row_id, checked))

    submitted = st.form_submit_button("Apply current page selection")

if submitted:
    update_selector_view_rows(edited_rows)
    selector_view_df = st.session_state["selector_view_df"].copy()
    selector_rows_df = selector_rows_for_ids(selector_view_df, [row_id for row_id, _ in edited_rows])
    base_df = st.session_state["applied_df"] if st.session_state.get("selection_applied", False) and st.session_state.get("applied_df") is not None else df_full
    applied_df = apply_selection_rows_to_full_df(base_df, selector_rows_df)
    st.session_state["applied_df"] = applied_df
    st.session_state["selection_applied"] = True
    st.success(f"Applied selection to {len(edited_rows)} rows on this page.")

if st.button("Apply all visible rows from current selector buffer", disabled=not visible_row_ids):
    selector_view_df = st.session_state["selector_view_df"].copy()
    selector_rows_df = selector_rows_for_ids(selector_view_df, visible_row_ids)
    applied_df = apply_selection_rows_to_full_df(df_full, selector_rows_df)
    st.session_state["applied_df"] = applied_df
    st.session_state["selection_applied"] = True
    st.success(f"Applied selection to {len(visible_row_ids)} visible rows.")

applied_df = st.session_state.get("applied_df")
if applied_df is not None and st.session_state.get("selection_applied", False):
    st.subheader("Applied Preview")
    preview_df = applied_df[preview_columns(applied_df)].copy()
    preview_df = sort_preview_for_display(preview_df)
    st.dataframe(preview_df, use_container_width=True, hide_index=True)
else:
    st.info("Apply selection to preview manual_select changes before saving.")

st.subheader("Save")
save_cols = st.columns(3)

if save_cols[0].button("Save applied selection to CSV", type="primary"):
    if applied_df is None or not st.session_state.get("selection_applied", False):
        st.warning("Apply selection before saving.")
        st.stop()
    else:
        df_to_save = normalize_all_manual_select(applied_df)
        backup_path = save_with_backup(csv_path, df_to_save)
        create_marker_file(marker_path, csv_path, df_to_save)
        st.session_state["classified_df"] = df_to_save
        st.session_state["selector_view_df"] = build_selector_view_df(df_to_save)
        st.session_state["applied_df"] = df_to_save
        st.success(f"Saved: {csv_path}")
        st.info(f"Backup created: {backup_path}")
        st.success(f"Manual review marker created: {marker_path}")

if save_cols[1].button("Save as reviewed copy"):
    df_for_copy = applied_df if applied_df is not None else df_full
    df_for_copy = normalize_all_manual_select(df_for_copy)
    reviewed_path = paper_folder / REVIEWED_COPY_NAME
    df_for_copy.drop(columns=[ROW_ID_COL], errors="ignore").to_csv(reviewed_path, index=False, encoding="utf-8-sig")
    st.success(f"Saved reviewed copy: {reviewed_path}")

download_df = applied_df if applied_df is not None else df_full
download_df = normalize_all_manual_select(download_df)
save_cols[2].download_button(
    "Download applied full CSV",
    data=dataframe_to_csv_bytes(download_df),
    file_name=CSV_NAME,
    mime="text/csv",
)
